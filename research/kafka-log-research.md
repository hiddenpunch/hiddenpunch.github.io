# Kafka 해체분석기 #1 리서치 노트
# Log의 탄생 - 왜 append-only log가 Kafka의 핵심인가

**작성일**: 2026-02-15
**작성자**: 서브에이전트 (kafka-research)

---

## 1. LinkedIn의 원래 문제 (2010-2011년경)

### 1.1 데이터 폭증 문제
- **규모**: 사용자 활동 데이터가 트랜잭션 데이터 대비 **1000배 이상 증가**
- **데이터 유형**: 프로필 조회, 검색, 연결, 뉴스피드 업데이트 등
- **분산 시스템**: 검색 엔진, 소셜 그래프, Hadoop, Voldemort(key-value store), 추천 엔진 등 수십 개 시스템으로 파편화

### 1.2 기존 메시징 시스템의 한계
```
문제점:
1. JMS/ActiveMQ/RabbitMQ: 단일 노드 아키텍처로 확장성 부족
2. 실시간 처리(보안 시스템)와 배치 처리(Hadoop) 동시 지원 불가
3. 데이터 소스마다 별도 파이프라인 필요 → O(N²) 통합 문제
```

### 1.3 조직적 문제
- **ETL 팀 병목**: 데이터 웨어하우스 팀이 모든 데이터 통합 책임
- **데이터 커버리지 부족**: 조직 전체 데이터의 일부만 접근 가능
- **변경 지연**: 새로운 데이터 소스 추가 시 수동 설정 필요

---

## 2. Jay Kreps의 초기 디자인 결정 (2010-2011)

### 2.1 핵심 디자인 원칙
출처: 2011 Hadoop Summit Talk

1. **Publish-Subscribe 모델**
   - 퍼블리셔와 서브스크라이버 분리
   - 여러 컨슈머 그룹 지원 (그룹 내 1:1, 그룹 간 fan-out)

2. **처음부터 분산 시스템**
   - 머신 장애 대응
   - 랜덤 액세스 없음 → 순차 로그 기반 스토리지

3. **스키마 강제**
   - 하위 호환성 보장
   - Hive/Pig 타입 시스템과 자동 매핑

4. **Pull 기반 고처리량**
   - 퍼블리셔:컨슈머 비율 1:10 지원
   - 간단한 프로토콜로 다국어 클라이언트 지원

5. **실시간 처리**
   - 키 기반 파티셔닝/리파티셔닝
   - 플라이 중 데이터 플로우 지원

### 2.2 "The Log" 개념 (2013년 블로그 글)

**핵심 통찰**:
> "A log is an append-only, totally-ordered sequence of records ordered by time."

#### 왜 로그인가?
1. **State Machine Replication Principle**:
   ```
   동일한 상태의 두 프로세스가 
   동일한 순서로 동일한 입력을 받으면
   → 동일한 출력과 동일한 상태
   ```

2. **로그 = 시간의 추상화**:
   - 물리적 시계와 분리된 논리적 타임스탬프
   - 각 레플리카는 "최대 처리한 로그 엔트리 번호"로 상태 표현

3. **데이터베이스 전통**:
   - RDBMS의 WAL(Write-Ahead Log) 개념
   - 복제(replication)를 위해 이미 로그 사용 중
   - Oracle XStreams, MySQL binlog, PostgreSQL replication

---

## 3. Kafka 첫 커밋 분석 (GitHub)

### 3.1 타임라인
- **2010년 후반**: LinkedIn 내부 개발 및 프로덕션 배포
- **2011년 1월**: 오픈소스화
- **2011년 7월 26일 - 9월 5일**: GitHub kafka-dev/kafka에 초기 커밋
- **2011년 8월**: apache/kafka 공식 레포지토리 첫 커밋
- **2012년 10월 23일**: Apache Incubator 졸업

### 3.2 초기 아키텍처 (추론)
```
핵심 컴포넌트:
1. ZooKeeper 통합: 클러스터 코디네이션
2. Broker: 로그 관리 및 복제
3. 파티션: 수평 확장의 단위
4. 설정 파일: zookeeper.properties, server.properties
```

**초기 포커스**:
- 분산 커밋 로그 구현
- 파티션 내 순서 보장
- 오프셋 기반 컨슈머 모델
- 내구성과 복제

---

## 4. Append-Only가 분산 시스템에 적합한 이유

### 4.1 성능 최적화

#### 순차 디스크 액세스
```
랜덤 vs 순차 쓰기 (HDD 기준):
- 랜덤: ~100 IOPS
- 순차: ~100 MB/s (~10,000x 빠름)

SSD도 순차 쓰기가 2-3배 더 빠름
```

#### Kafka의 최적화 기법
1. **배치 처리**: 작은 읽기/쓰기를 큰 작업으로 그룹화
2. **Zero-copy**: 메모리-디스크-네트워크 간 동일한 바이너리 포맷
3. **Page cache 활용**: OS 레벨 캐싱으로 메모리 초과 데이터셋 처리

### 4.2 일관성과 복제

#### 간단한 일관성 모델
```
장점:
1. 단일 Writer: 각 파티션 리더만 쓰기
2. 원자적 Append: 락 없이 원자성 보장
3. 검증 가능: 각 엔트리에 고정된 시그니처
4. 결정론적 복제: 순차 재생으로 동일 상태 도달
```

#### WAL 없는 내구성
- 전통 DB: WAL → 데이터 구조 업데이트
- Kafka: 로그 자체가 진리의 원천(source of truth)
- 복구: 로그를 순차적으로 재생

### 4.3 분산 시스템 특성

#### 불변성의 이점
```
1. Snapshot: O(1) (타임스탬프만 저장)
2. Rollback: 특정 오프셋으로 되돌아가기
3. 버전 관리: 톰스톤으로 삭제 표현
4. 다중 컨슈머: 각자 속도로 읽기
```

#### 조정 오버헤드 제거
- 공유 가변 상태 없음
- 멱등성: 재시도 안전
- 락 회피: 조건부 append로 분산 락 구현 가능

### 4.4 LinkedIn의 실제 규모 (블로그 글 기준)
```
2013년 기준:
- 일일 600억 개 이상의 메시지
- 데이터센터 간 미러링 포함 시 수천억 건
- 수평 확장으로 선형 처리량 증가
```

---

## 5. "The Log" 글의 핵심 메시지

### 5.1 로그-중심 아키텍처
```
전통적 접근:
[시스템 A] ↔ [시스템 B]
[시스템 A] ↔ [시스템 C]
[시스템 B] ↔ [시스템 C]
→ O(N²) 통합

로그-중심:
[시스템들] → [중앙 로그] → [시스템들]
→ O(N) 통합
```

### 5.2 Table-Log Duality
```
Table: 현재 상태 (data at rest)
Log: 변경 히스토리 (data in motion)

변환:
- Log → Table: 변경 순차 적용
- Table → Log: 변경을 changelog로 발행
```

### 5.3 ETL의 재정의
```
전통 ETL:
Extract → Transform → Load (배치)

로그-중심 ETL:
1. 프로듀서: 깨끗한 데이터를 로그에 발행
2. 실시간 변환: 로그 → 파생 로그
3. 로딩: 목적지별 최소 변환
```

---

## 6. 인용 및 참조

### 6.1 주요 인용구

Jay Kreps, "The Log" (2013):
> "You can't fully understand databases, NoSQL stores, key value stores, replication, paxos, hadoop, version control, or almost any software system without understanding logs."

> "If two identical, deterministic processes begin in the same state and get the same inputs in the same order, they will produce the same output and end in the same state."

### 6.2 참조 자료
1. **블로그**: https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying
2. **논문**: "Data Infrastructure at LinkedIn" (ICDE 2012)
3. **발표**: Jay Kreps - Hadoop Summit 2011
4. **GitHub**: https://github.com/apache/kafka
5. **관련 시스템**: LinkedIn Databus, Amazon Kinesis

---

## 7. 추가 조사 필요 사항

1. ✅ 2011년 첫 커밋의 실제 코드 구조
   - `kafka-dev/kafka` 레포에서 2011년 7-9월 커밋 확인 필요
   - `git log --reverse --before=2012-01-01` 실행

2. ✅ 초기 Log 클래스 구현
   - `core/src/main/scala/kafka/log/Log.scala`의 초기 버전
   - 세그먼트, 인덱스 구조

3. ✅ ZooKeeper 통합 방식
   - 브로커 메타데이터 관리
   - 파티션 리더 선출

---

## 8. 스토리텔링 포인트

### 8.1 "문제의 진짜 원인"
- LinkedIn 엔지니어들이 마주한 진짜 문제는 "메시징 시스템"이 아니라 "데이터 통합"
- 기존 솔루션은 "메시지 전달"에 집중, Kafka는 "이벤트 히스토리"에 집중

### 8.2 "단순함의 힘"
- append-only라는 가장 단순한 자료구조가 가장 강력한 분산 시스템 추상화
- 제약(순차 쓰기)이 오히려 성능과 일관성을 가능하게 함

### 8.3 "역사는 반복된다"
- 데이터베이스의 WAL → 분산 시스템의 로그
- 버전 관리 시스템(Git)도 사실 로그
- 블록체인도 append-only log

### 8.4 "미래에서 온 디자인"
- 2013년 Amazon Kinesis가 Kafka와 거의 동일한 API로 출시
- "좋은 인프라 추상화는 AWS가 서비스로 제공한다" - Jay Kreps

---

## 9. 다이어그램 아이디어

### 9.1 LinkedIn의 데이터 파이프라인 문제
```
Before Kafka (O(N²)):
DB ──┬──> Search
     ├──> Graph
     ├──> Hadoop
     └──> Cache
App ─┬──> Analytics
     └──> Monitoring

After Kafka (O(N)):
Sources → [Kafka Log] → Consumers
```

### 9.2 Append-Only Log 구조
```
Offset: 0    1    2    3    4    5
        [A] [B] [C] [D] [E] [F] →
        └─────────┘
        Consumer 1 (offset=3)
                      └─────────┘
                      Consumer 2 (offset=5)
```

### 9.3 Partition 기반 수평 확장
```
Topic: user-events
├─ Partition 0 [Leader: Broker 1, Replicas: 2,3]
├─ Partition 1 [Leader: Broker 2, Replicas: 3,1]
└─ Partition 2 [Leader: Broker 3, Replicas: 1,2]
```

---

## 10. 코드 예제 아이디어 (실제 Kafka 코드 분석)

### 10.1 Log Segment 구조 (초기 Scala 코드)
```scala
// 초기 Kafka Log 클래스 (추정)
class Log(dir: File, maxSize: Long) {
  private val segments = new ConcurrentSkipListMap[Long, LogSegment]
  
  def append(message: Message): Long = {
    val segment = activeSegment
    val offset = nextOffset
    segment.append(offset, message)
    offset
  }
  
  def read(offset: Long, maxSize: Int): MessageSet = {
    val segment = segments.floorEntry(offset).getValue
    segment.read(offset, maxSize)
  }
}
```

### 10.2 순차 쓰기의 실제 구현
```java
// FileMessageSet의 writeTo (zero-copy)
@Override
public long writeTo(GatheringByteChannel channel, long position, long maxSize) {
    return channel.transferFrom(fileChannel, position, maxSize);
    // OS sendfile() 시스템 콜 활용
    // 유저 공간 복사 없이 디스크 → 네트워크
}
```

---

## 결론

Kafka의 성공은 **"append-only log"라는 단순한 추상화를 분산 시스템의 핵심으로 만든 것**에 있다. LinkedIn의 실제 문제(데이터 통합)와 데이터베이스/분산 시스템의 오랜 전통(로그)을 결합하여, 성능(순차 I/O), 일관성(결정론적 복제), 확장성(파티셔닝)을 동시에 달성했다.

Jay Kreps의 통찰은 "로그는 시스템의 진리"라는 것이다. 이 철학은 이후 스트림 프로세싱(Kafka Streams), 이벤트 소싱, CQRS 등의 현대 아키텍처 패턴에 큰 영향을 미쳤다.
