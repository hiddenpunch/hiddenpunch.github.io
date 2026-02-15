# Kafka 해체분석기 #1: Log의 탄생

**왜 append-only log가 Kafka의 핵심인가**

---

## 프롤로그: 2010년, LinkedIn의 데이터 지옥

2010년 LinkedIn은 골치 아픈 문제에 직면했다. 사용자가 프로필을 조회하면, 그 단순한 행동 하나가 10개가 넘는 시스템을 건드려야 했다.

```
프로필 조회 1건 → 처리해야 할 시스템:
- Hadoop (오프라인 분석)
- 검색 인덱스 (실시간 업데이트)
- 소셜 그래프 (연결 추천)
- 추천 엔진 (맞춤 추천)
- 보안 시스템 (스크래핑 감지)
- 분석 대시보드 (사용자 통계)
- 데이터 웨어하우스 (리포팅)
- ... (계속)
```

당시 엔지니어 중 한 명이었던 **Jay Kreps**는 이 문제를 "O(N²) 통합 지옥"이라고 불렀다. 시스템이 N개면 N×N개의 파이프라인이 필요했다. 새로운 데이터 소스를 추가할 때마다 모든 시스템에 커스텀 연결을 만들어야 했다.

기존 메시징 시스템(ActiveMQ, RabbitMQ)은? **확장이 안 됐다.** 단일 노드 아키텍처였고, 초당 수만 건의 이벤트를 감당할 수 없었다. LinkedIn이 진짜 필요했던 건 메시지 브로커가 아니라 **"이벤트 히스토리의 영구 저장소"**였다.

---

## 1. 커밋 로그의 재발견

Jay Kreps의 통찰은 단순했다. **데이터베이스를 뜯어보자.**

```sql
-- PostgreSQL WAL (Write-Ahead Log) 구조
LSN (Log Sequence Number): 000000010000000100000042
Offset: 1234567
Transaction: BEGIN
  UPDATE users SET name='Alice' WHERE id=1;
  INSERT INTO events (user_id, action) VALUES (1, 'login');
Transaction: COMMIT
```

RDBMS는 50년간 같은 방식으로 일관성을 유지했다. **모든 변경을 로그에 먼저 쓰고, 나중에 테이블을 업데이트**한다. 크래시가 나면? 로그를 재생하면 된다. 복제가 필요하면? 로그를 보내면 된다.

Kreps는 깨달았다. **"로그가 데이터베이스의 진짜 본체다."** 테이블은 단지 로그의 "materialized view"일 뿐이다.

### State Machine Replication Principle

그의 2013년 블로그 글 ["The Log"](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying)에서 핵심 원리를 제시한다:

> "동일한 상태의 두 프로세스가 동일한 순서로 동일한 입력을 받으면,  
> 동일한 출력과 동일한 상태를 갖는다."

분산 시스템의 일관성 문제는 **"어떻게 모든 노드가 같은 입력을 같은 순서로 받게 하는가?"**로 단순화된다. 그 답이 바로 **분산 로그**다.

---

## 2. 2011년 첫 커밋: append-only의 철학

Kafka는 2011년 7월 말부터 GitHub에 커밋되기 시작했다. 초기 Scala 코드를 보면, 디자인 철학이 명확하다.

### Log 클래스의 본질 (의사 코드)

```scala
class Log(dir: File, maxSize: Long) {
  private val segments = new ConcurrentSkipListMap[Long, LogSegment]
  
  def append(message: Message): Long = {
    val segment = activeSegment
    val offset = nextOffset
    segment.append(offset, message)  // 오직 append만!
    offset
  }
  
  def read(startOffset: Long, maxBytes: Int): MessageSet = {
    val segment = segments.floorEntry(startOffset).getValue
    segment.read(startOffset, maxBytes)
  }
  
  // ❌ 업데이트 없음
  // ❌ 삭제 없음 (나중에 tombstone으로 처리)
  // ❌ 랜덤 쓰기 없음
}
```

**핵심 제약**:
1. **Append-only**: 끝에만 추가 가능
2. **Immutable**: 한 번 쓴 데이터는 절대 변경 안 됨
3. **Ordered**: 오프셋으로 전체 순서 보장

이 단순함이 모든 걸 가능하게 한다.

---

## 3. 왜 Append-Only인가? (성능 편)

### 3.1 순차 I/O의 마법

2011년 HDD 성능 (출처: Kafka design doc):
```
랜덤 쓰기: ~100 IOPS (초당 쓰기 횟수)
순차 쓰기: ~100 MB/s

→ 순차가 랜덤보다 약 1000배 빠름!
```

SSD에서도 순차 쓰기가 2-3배 빠르다. Kafka는 이 사실에 모든 걸 걸었다.

### 3.2 Zero-Copy의 비밀

Kafka의 `FileMessageSet` 클래스를 보자:

```java
public long writeTo(GatheringByteChannel channel, 
                    long position, long maxSize) {
    // Java NIO의 transferTo()는 OS sendfile() 사용
    return channel.transferFrom(fileChannel, position, maxSize);
}
```

**전통적 방식** (4번의 복사):
```
디스크 → 커널 버퍼 → 유저 공간 → 소켓 버퍼 → NIC
```

**Zero-Copy** (2번의 복사):
```
디스크 → 커널 버퍼 → NIC
```

파일에서 네트워크로 데이터를 보낼 때, **유저 공간을 전혀 거치지 않는다.** 이게 가능한 이유는? **디스크의 바이너리 포맷과 네트워크 전송 포맷이 동일**하기 때문이다.

### 3.3 배치 처리의 위력

```scala
// Producer API (초기 버전)
producer.send(
  messages = List(msg1, msg2, ..., msg100),  // 배치 전송
  compression = GZIP                          // 압축도 배치 단위
)
```

1개씩 100번 보내는 것보다 100개를 한 번에 보내는 게 **10-100배 빠르다.** 네트워크 왕복 시간(RTT)을 줄이고, 압축률도 높아진다.

**2013년 LinkedIn 규모**:
- 일일 **600억+ 메시지**
- 단일 클러스터에서 처리
- 선형 확장으로 더 추가 가능

---

## 4. 왜 Append-Only인가? (일관성 편)

### 4.1 락 없는 원자성

```scala
// 파티션마다 단일 Leader만 쓰기
class Partition {
  private var leader: Broker
  
  def append(message: Message): Unit = {
    require(isLeader, "Only leader can write")
    log.append(message)  // ← 단순 파일 append (원자적!)
  }
}
```

**전통 DB의 복잡성**:
```
BEGIN TRANSACTION;
  UPDATE table1 ...;  -- 락 획득
  UPDATE index1 ...;  -- 인덱스 업데이트
  UPDATE index2 ...;  -- 또 다른 인덱스
  WRITE WAL;          -- WAL 기록
  COMMIT;             -- 락 해제
```

**Kafka의 단순성**:
```
Append to file;  -- 끝!
(나머지는 follower가 알아서 복제)
```

### 4.2 결정론적 복제

```
Leader (Broker 1):
  Offset 0: {user: 1, action: "login"}
  Offset 1: {user: 1, action: "view_profile"}
  Offset 2: {user: 2, action: "search"}

Follower (Broker 2):
  1. Offset 0 fetch → append
  2. Offset 1 fetch → append
  3. Offset 2 fetch → append
  → Leader와 100% 동일한 상태!
```

**왜 가능한가?**
- 불변성: 한 번 쓴 offset은 절대 안 변함
- 순서 보장: offset으로 전체 순서 명확
- 재생 가능: 크래시 후 마지막 offset부터 다시 fetch

이게 Paxos나 Raft 같은 복잡한 합의 알고리즘 없이 가능한 이유다. (물론 Kafka도 나중에 리더 선출에 ZooKeeper를 쓰긴 한다.)

---

## 5. 파티셔닝: 수평 확장의 비밀

```
Topic: user-events (3 partitions)

Partition 0: [msg0, msg3, msg6, ...] → Broker 1 (Leader)
Partition 1: [msg1, msg4, msg7, ...] → Broker 2 (Leader)
Partition 2: [msg2, msg5, msg8, ...] → Broker 3 (Leader)

Hash(userId) % 3 → Partition 선택
```

**트레이드오프**:
- ✅ 파티션 내 순서 보장
- ✅ 파티션별 병렬 처리
- ❌ 파티션 간 전역 순서 없음

대부분의 애플리케이션은 **"같은 키의 이벤트들만 순서가 보장되면 된다"**. 예를 들어, 같은 사용자의 행동은 순서대로 처리해야 하지만, 서로 다른 사용자 간엔 순서가 중요하지 않다.

---

## 6. Table-Log Duality: 철학적 통찰

Jay Kreps의 가장 아름다운 통찰:

```
Log → Table: 변경을 순차 적용하면 현재 상태
Table → Log: 변경을 발행하면 changelog

예시:
Log: [SET a=1, SET b=2, SET a=3]
   ↓ apply
Table: {a: 3, b: 2}

Table: {name: "Alice", age: 30}
   ↓ CDC (Change Data Capture)
Log: [INSERT name='Alice' age=30, UPDATE age=31]
```

**왜 중요한가?**
- **Event Sourcing**: 현재 상태 대신 이벤트 히스토리 저장
- **CQRS**: Command(Log)와 Query(Table) 분리
- **Time Travel**: 과거 시점의 상태 재구성 (offset으로 돌아가기)

Kafka Streams, ksqlDB, Flink 같은 스트림 프로세싱 프레임워크들이 모두 이 duality에 기반한다.

---

## 7. 미래에서 온 검증

**2013년 Amazon Kinesis 출시**:
- API가 Kafka와 거의 동일
- Partition → Shard (이름만 다름)
- Offset 기반 소비
- 순차 로그 구조

Jay Kreps는 이렇게 말했다:
> "좋은 인프라 추상화를 만들었다는 증거는?  
> AWS가 그걸 서비스로 제공한다는 것이다."

Kafka의 디자인이 **"우연이 아닌 필연"**이었다는 방증이다.

---

## 에필로그: 단순함의 승리

Kafka의 성공 비결은 **"제약을 받아들인 것"**이다.

- ❌ 랜덤 업데이트? → ✅ append-only
- ❌ 전역 순서? → ✅ 파티션 내 순서
- ❌ 복잡한 쿼리? → ✅ offset 기반 순차 읽기

이 제약들이 오히려:
- **성능**: 순차 I/O, zero-copy, batching
- **일관성**: 결정론적 복제, 락 없는 원자성
- **확장성**: 파티션 기반 수평 확장

을 가능하게 했다.

**2011년 첫 커밋부터 2026년 현재까지**, Kafka의 핵심 철학은 변하지 않았다. **"Log is the source of truth."** 이 단순한 진리가, 현대 데이터 아키텍처의 기초가 되었다.

---

## 다음 편 예고

**Kafka 해체분석기 #2: "Zero-Copy의 비밀 - OS 커널과의 춤"**
- `FileChannel.transferTo()`의 내부 동작
- Linux `sendfile()` 시스템 콜 분석
- Page cache 활용 전략
- 실제 벤치마크: random vs sequential I/O

---

**참고 자료**:
- [The Log (Jay Kreps, 2013)](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying)
- [Kafka Design Doc](https://kafka.apache.org/documentation/#design)
- [GitHub: apache/kafka](https://github.com/apache/kafka)
- "Data Infrastructure at LinkedIn" (ICDE 2012)
