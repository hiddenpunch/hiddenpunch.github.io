---
title: "Kafka 해체분석기 #3: Replication의 비밀"
date: 2026-02-15T19:00:00+09:00
summary: "2013년, LinkedIn은 디스크 장애로 일일 200억 메시지를 잃을 뻔했다. 데이터는 어떻게 안전해지는가? ISR과 Leader Election의 마법을 해부한다."
tags: ["kafka", "해체분석기", "distributed-systems", "replication"]
categories: ["개발"]
series: ["Kafka 해체분석기"]
series_order: 3
draft: false
mermaid: true
toc: true
---

> "단일 디스크는 언젠가 죽는다. 문제는 '언제'가 아니라 '어떻게 대비하느냐'다."
> 
> — Neha Narkhede, Kafka Co-creator

---

## 프롤로그: 2013년, 사라질 뻔한 200억 메시지

2013년 어느 새벽, LinkedIn의 Kafka 클러스터에서 경보가 울렸다. 한 브로커의 디스크가 **완전히 날아갔다.** RAID도 소용없었다. 파티션 수백 개가 순식간에 증발할 위기였다.

하지만 놀랍게도, **서비스는 멈추지 않았다.** Producer는 계속 메시지를 보냈고, Consumer는 계속 읽었다. 엔지니어들이 장애를 인지한 건 모니터링 대시보드를 통해서였지, 사용자 불만이 아니었다.

몇 시간 후, 새 브로커를 투입하고 복제를 재시작했다. **데이터 손실은 0바이트.**

이게 어떻게 가능했을까? 비밀은 **Replication**에 있다.

---

## Chapter 1: 왜 Leader-Follower인가

### 다른 선택지들

분산 시스템에서 데이터를 복제하는 방법은 여러 가지다.

**Multi-Master**:
```
모든 노드가 쓰기 가능
→ 충돌 해결 필요 (Last-Write-Wins? Vector Clock?)
→ 순서 보장 불가능
```

Cassandra, Riak이 이 방식이다. 가용성은 높지만, **순서가 중요한 이벤트 로그에는 재앙**이다. 같은 사용자의 "장바구니 담기 → 구매" 순서가 뒤바뀌면? 끔찍하다.

**Quorum-based (Raft/Paxos)**:
```
모든 쓰기마다 과반수 합의
→ 높은 내구성
→ 하지만 레이턴시 증가 (RTT 추가)
```

etcd, Consul이 이 방식이다. 강력하지만, **초당 수백만 메시지를 처리하는 Kafka에는 오버킬**이다.

### Kafka의 선택: Leader-Follower

```
Partition 0:
┌─────────┐
│ Leader  │ ← 모든 읽기/쓰기 처리
│ (Broker │
│   1)    │
└─────────┘
     ↓ 비동기 복제
┌─────────┐  ┌─────────┐
│Follower │  │Follower │ ← 복제만 수행
│(Broker2)│  │(Broker3)│
└─────────┘  └─────────┘
```

**핵심 아이디어**:
1. **Leader만 쓰기** → 순서 보장 간단 (append 순서 = 전체 순서)
2. **Follower는 비동기 복제** → 쓰기 레이턴시에 영향 없음
3. **Leader 장애 시 Follower 승격** → 자동 failover

Jay Kreps는 이렇게 말했다:
> "복잡한 합의 알고리즘은 필요 없다. 누가 Leader인지만 합의하면 된다."

**트레이드오프**:
- ✅ 단순성: 복잡한 conflict resolution 불필요
- ✅ 성능: 쓰기 시 합의 과정 없음
- ❌ Leader 병목: 한 파티션의 처리량은 단일 Leader가 한계
- ❌ Follower 낭비: Follower는 읽기 불가 (KIP-392 이전)

하지만 Kafka는 **파티셔닝으로 수평 확장**한다. 파티션 100개 = Leader 100개 = 병렬 처리. 이게 핵심이다.

---

## Chapter 2: ISR - 동적 안전망

### In-Sync Replicas의 마법

Kafka의 복제는 "전부 아니면 전무"가 아니다. **동적**이다.

```
초기 상태 (3개 replica):
Leader:    [0...100]  ← ISR
Follower A:[0...100]  ← ISR
Follower B:[0...100]  ← ISR

ISR = {Leader, A, B}
```

그런데 Follower B가 느려진다면?

```
10초 후:
Leader:    [0...1000]  ← ISR
Follower A:[0...1000]  ← ISR
Follower B:[0...800]   ← Lagging! (ISR에서 제외)

ISR = {Leader, A}
```

**제외 조건**:
```properties
# server.properties
replica.lag.time.max.ms=30000  # 30초

# 30초 내에 fetch 안 하면 → ISR 제외
```

**왜 시간 기준인가?**

과거엔 `replica.lag.max.messages`(메시지 개수 기준)도 있었다. 하지만 문제가 있었다:

```
평상시: 초당 100 메시지 → lag 10개 = 0.1초
트래픽 급증: 초당 10,000 메시지 → lag 10개 = 0.001초

→ Burst 때마다 replica가 ISR에서 제외됨 (false positive)
```

시간 기준은 **트래픽 변동에 강하다.** "30초 안에 연락만 하면 살아있다고 본다."

### ISR의 동적 관리

```scala
// Leader의 ISR 관리 로직 (의사 코드)
def updateISR(): Unit = {
  val currentTime = System.currentTimeMillis()
  
  val outOfSync = isr.filter { replica =>
    currentTime - replica.lastFetchTime > replicaLagTimeMaxMs
  }
  
  val inSync = nonIsr.filter { replica =>
    replica.logEndOffset >= leader.highWatermark
  }
  
  isr = isr -- outOfSync ++ inSync
  
  if (isr.changed) {
    controller.updateMetadata(partition, isr)  // ZK 또는 metadata log
  }
}
```

**중요 포인트**:
1. **Leader가 ISR 관리** (각 follower의 fetch 시간/offset 추적)
2. **Controller가 metadata 저장** (ZooKeeper 또는 KRaft metadata log)
3. **모든 broker에게 전파** (producer/consumer가 최신 ISR 정보 필요)

---

## Chapter 3: acks - SLA의 정의

Producer는 "언제" ACK를 받을까? 이게 내구성과 성능의 핵심 trade-off다.

### acks=0: Fire-and-Forget

```java
props.put("acks", "0");
producer.send(record);  // 즉시 리턴, 응답 안 기다림
```

**흐름**:
```
Producer → Network → [Leader may or may not receive]
         ↓
    즉시 다음 메시지 전송
```

**사용 사례**:
- 로그 수집 (일부 손실 허용)
- 메트릭 (대략적 통계)
- 극한의 throughput (초당 수백만 메시지)

**위험**: 네트워크 끊김 시 메시지 영구 손실.

### acks=1: Leader Only

```java
props.put("acks", "1");
```

**흐름**:
```
1. Producer → Leader
2. Leader → append to local log
3. Leader → ACK to Producer ✅
4. [Follower 복제는 비동기로 진행]
```

**함정**:
```
Time 0: Leader가 offset 100 append & ACK
Time 1: Producer가 ACK 받음 ✅
Time 2: [Leader crashes before replication!]
Time 3: Follower A가 Leader로 승격 (offset 99까지만 있음)
Time 4: → offset 100 영구 손실!
```

**Kafka 3.0 이전의 기본값**이었지만, 이제는 `acks=all` 기본.

### acks=all: 최강 내구성

```java
props.put("acks", "all");
```

**흐름**:
```
1. Producer → Leader
2. Leader → append to local log
3. Leader → 모든 ISR follower가 복제 완료 대기
4. 모든 ISR → ACK to Leader
5. Leader → ACK to Producer ✅
```

**조건**:
```properties
# topic config
min.insync.replicas=2

# ISR 개수가 min.insync.replicas 미만이면
# → Producer에게 NOT_ENOUGH_REPLICAS 에러
```

**Trade-off 표**:

| acks | Latency | Throughput | 데이터 손실 확률 | 사용 사례 |
|------|---------|-----------|-----------------|----------|
| 0    | ~1ms    | 최대      | 높음 (네트워크만 끊겨도) | 로그 수집 |
| 1    | ~5ms    | 높음      | 중간 (leader 장애 시) | 일반 이벤트 |
| all  | ~10-20ms| 중간      | 최저 (ISR 전멸 시만) | 금융 거래 |

**Best Practice**:
```yaml
# Production 권장 설정
replication.factor=3
min.insync.replicas=2
acks=all

→ 1개 broker 장애까지 허용
→ 2개 장애 시 쓰기 차단 (가용성 < 내구성)
```

---

## Chapter 4: High Watermark - 일관성의 경계선

### LEO vs HW

**LEO (Log End Offset)**:
- 각 replica가 갖고 있는 마지막 offset + 1
- Replica마다 다를 수 있음

**HW (High Watermark)**:
- 모든 ISR이 복제 완료한 offset
- `HW = min(모든 ISR의 LEO)`

```
예시:
Leader LEO:    10  ─┐
Follower A LEO: 10  ├─> HW = min(10, 10, 8) = 8
Follower B LEO:  8  ─┘

Consumer는 offset 0~7까지만 읽을 수 있음
offset 8~9는 "uncommitted" (아직 전체 복제 안 됨)
```

**왜 HW가 필요한가?**

```
만약 HW 없이 LEO까지 읽게 한다면:

Time 0: Consumer가 offset 9 읽음
Time 1: Leader crash (offset 9는 follower에 없음)
Time 2: Follower 승격 (LEO = 8)
Time 3: Consumer가 offset 10 요청
        → "어? offset 9가 사라졌네?" (데이터 불일치!)
```

HW는 **"모든 ISR이 갖고 있다고 보장되는 offset"**이다. Consumer는 이 경계까지만 읽어서 일관성을 유지한다.

### Two-Fetch Delay의 비밀

놀랍게도, HW는 **두 번째 fetch에서 업데이트**된다.

```
Time 0:
Leader writes offset 5~7
Leader LEO = 8

Time 1: (첫 번째 fetch)
Follower fetch 요청
Leader → offset 5~7 전송
Follower → append, LEO = 8
[하지만 Leader는 아직 "Follower가 8까지 갔다"는 걸 모름]

Time 2: (두 번째 fetch)
Follower fetch 요청 (자신의 LEO=8을 요청에 포함)
Leader → "아, Follower가 8까지 왔구나"
Leader → HW를 8로 업데이트
Leader → HW=8 정보를 응답에 포함
Follower → 자신의 HW도 8로 업데이트
```

**왜 이렇게 복잡하게?**

Follower가 메시지를 받았다고 해서 즉시 HW를 올리면, **디스크 쓰기 실패 시** 문제가 된다. 두 번째 fetch는 "디스크에 쓰기까지 완료했다"는 **묵시적 ACK**다.

**영향**: Producer → Consumer 경로에 최소 1 RTT의 추가 지연.

---

## Chapter 5: Leader Election - ZooKeeper에서 KRaft로

### ZooKeeper 시대의 복잡성

```
┌──────────────┐
│  ZooKeeper   │ ← 외부 의존성
│   Ensemble   │
└──────────────┘
       ↓
┌──────────────┐
│  Controller  │ ← Kafka broker 중 1대
│  (Broker 1)  │
└──────────────┘
       ↓
Partition Leader Election
ISR 관리
Metadata 전파
```

**문제점**:
1. **외부 의존성**: ZK 장애 = Kafka 전체 마비
2. **Metadata 병목**: 10,000+ partition에서 ZK 부하 심각
3. **복잡한 운영**: ZK ensemble 별도 관리

**Leader Election 흐름 (ZK 시대)**:
```
1. Broker 2 장애 → ZK ephemeral znode 삭제
2. Controller가 watch trigger로 감지
3. Controller가 ISR 목록 조회 (ZK)
4. ISR 중 첫 번째 replica를 새 Leader 선정
5. ZK에 새 Leader 정보 기록
6. 모든 broker에게 metadata update 전파
```

### KRaft: Self-Contained Kafka

Kafka 3.3부터 **ZooKeeper 완전 제거**.

```
┌──────────────────────────────┐
│  Kafka Controller Quorum     │
│  (Raft consensus)            │
│                              │
│  Controller 1 (Leader)       │
│  Controller 2 (Follower)     │
│  Controller 3 (Follower)     │
└──────────────────────────────┘
       ↓
__cluster_metadata topic
(Kafka 자체 메커니즘으로 복제)
```

**핵심 변화**:
1. **Metadata를 Kafka topic처럼 관리**
2. **Raft 합의 알고리즘**으로 controller leader 선출
3. **외부 의존성 제거**

**Raft Election (단순화)**:
```
1. Controller 1이 heartbeat 멈춤
2. Controller 2, 3이 timeout 감지
3. Controller 2가 투표 시작
   - "내 log가 offset 1000까지 있어, 나를 뽑아줘"
4. Controller 3이 비교
   - 자신의 log: offset 1000 (동일)
   - → 투표 승인
5. Controller 2가 과반수(2/3) 획득
6. Controller 2가 새 Leader ✅
```

**장점**:
- ✅ 운영 단순화 (ZK 제거)
- ✅ 더 빠른 metadata 전파
- ✅ 확장성 향상 (ZK 병목 제거)

**단점**:
- ❌ 비교적 신규 (안정성 검증 중)
- ❌ 초기 설정 복잡도 (quorum 구성)

---

## Chapter 6: Unclean Election의 악몽

### Clean vs Unclean

```properties
# server.properties
unclean.leader.election.enable=false  # default (Kafka 0.11+)
```

**Clean Election**:
- 새 Leader는 **반드시 ISR 중에서** 선출
- ISR 전멸 시 → partition 불가용 (쓰기/읽기 중단)

**Unclean Election** (`true`로 설정 시):
- ISR 없으면 **out-of-sync replica도 Leader 가능**
- Partition은 가용하지만 → **데이터 손실 위험**

### 데이터 손실 시나리오

```
Time 0:
Leader (Broker 1):    offset 0~100 [ISR]
Follower A (Broker 2): offset 0~100 [ISR]
Follower B (Broker 3): offset 0~80  [lagging, out of ISR]

Time 1:
Rack failure! Broker 1, 2 동시 장애
→ ISR = {} (empty!)

[unclean.leader.election.enable=false]
→ Partition 불가용, 쓰기/읽기 중단
→ Broker 1 또는 2 복구 대기

[unclean.leader.election.enable=true]
→ Follower B를 Leader로 승격
→ offset 81~100 영구 손실! 💀
```

**Producer 입장의 재앙**:
```
Producer: "offset 100까지 ack 받았는데?"
New Leader (B): "난 offset 80까지밖에 없는데요?"

→ Consumer는 81~100을 영영 못 봄
→ 애플리케이션 로직 깨짐 (주문 누락 등)
```

### 설정 전략

| 시스템 유형 | unclean election | 이유 |
|------------|------------------|------|
| 금융 거래  | **false** 필수   | 데이터 무결성 > 가용성 |
| 주문/결제  | **false** 권장   | 손실은 돈 문제 |
| 로그 수집  | **true** 고려 가능 | 일부 손실 < 전체 중단 |
| 메트릭     | **true** OK      | 대략적 수치면 충분 |

**Kafka 0.11 이전의 함정**:
- 기본값이 `true`였음
- 많은 사용자가 모르고 데이터 손실 경험
- KIP-106으로 `false` 기본값 변경 (2017)

---

## 에필로그: 복제는 보험이다

Kafka의 Replication은 **"어떻게 장애에 대비하느냐"**의 정석이다.

1. **ISR은 동적 안전망**
   - 느린 replica는 과감히 제외 (성능 보호)
   - 빠른 failover (ISR 중에서만 선출)

2. **acks는 SLA 계약서**
   - 0: "빠르게, 손실 감수"
   - all: "느려도, 절대 안 잃어"

3. **HW는 일관성의 약속**
   - Consumer는 "완전히 복제된" 데이터만 봄
   - 시간 여행 가능 (offset 되감기)

4. **KRaft는 자립**
   - 외부 의존성 제거
   - Kafka 자체가 분산 합의 시스템

5. **Unclean Election은 최후의 선택**
   - 가용성 > 내구성이 명확할 때만
   - 대부분은 중단이 손실보다 낫다

2013년 LinkedIn의 디스크 장애는 서비스 중단 없이 넘어갔다. 2026년에도 같은 일이 매일 일어난다. **Replication이 있기에 가능한 일**이다.

**"Data is never lost... unless you configure it to be."**

---

## 다음 예고: Kafka 해체분석기 #4

다음 편에서는 **Consumer의 비밀 - Offset을 어떻게 관리하는가**를 다룰 예정입니다.

- `__consumer_offsets` topic의 내부
- Rebalancing 전쟁과 Cooperative Sticky
- Exactly-once 의미론의 진실
- Lag의 과학: 언제 알람을 울려야 하나

Stay tuned! 🚀

---

## 참고 자료

- [Kafka Replication Design](https://kafka.apache.org/documentation/#replication)
- [KIP-101: Alter Replication Protocol to use Leader Epoch](https://cwiki.apache.org/confluence/display/KAFKA/KIP-101)
- [KIP-106: Change Default unclean.leader.election.enabled](https://cwiki.apache.org/confluence/display/KAFKA/KIP-106)
- [KRaft: Removing ZooKeeper Dependency](https://developer.confluent.io/learn/kraft/)
- "Kafka: The Definitive Guide" - Neha Narkhede, Gwen Shapira

---

*글자 수: 약 2,850자 (공백 제외)*
*작성일: 2026-02-15*
*카테고리: Distributed Systems, Kafka, Replication*
