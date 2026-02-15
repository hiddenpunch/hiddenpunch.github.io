# Kafka Replication 리서치 노트

## 리서치 목표
"Replication의 비밀 - 데이터는 어떻게 안전해지나" 주제로 Kafka의 복제 메커니즘을 해체 분석

---

## 1. Leader-Follower 구조 선택 이유

### 왜 Master-Slave (Leader-Follower)?

**다른 선택지들:**
- **Multi-Master**: 모든 노드가 쓰기 가능 → Conflict resolution 복잡, 순서 보장 불가
- **Quorum-based**: 모든 쓰기마다 과반수 합의 → 높은 레이턴시

**Kafka의 선택:**
- 각 파티션마다 1개 Leader, N개 Follower
- **Leader만 읽기/쓰기** 처리
- Follower는 Leader로부터 **비동기 복제**

**장점:**
1. **단순성**: 순서 보장이 간단 (Leader의 append 순서가 전체 순서)
2. **성능**: 쓰기 시 합의 불필요, Leader가 즉시 append
3. **확장성**: 읽기 부하는 Leader에 집중 (Kafka는 partition 늘려서 확장)
4. **결정론적 복제**: Follower는 Leader의 log를 그대로 복사

**단점:**
- Leader 장애 시 failover 필요
- Follower는 읽기 불가 (최근 KIP-392로 Follower Fetching 추가됨)

### 역사적 맥락
- LinkedIn 2010년대 초, 기존 ActiveMQ는 단일 마스터 병목
- Jay Kreps는 "쓰기는 하나의 노드에서만"이라는 제약으로 복잡도 감소
- 대신 **파티셔닝으로 수평 확장** (파티션마다 독립적 Leader)

---

## 2. ISR (In-Sync Replicas) 개념과 동작

### ISR이란?
- **정의**: Leader를 포함해 "최신 데이터를 따라잡고 있는" replica 집합
- **동적 관리**: replica가 느려지면 ISR에서 제외, 다시 따라잡으면 재편입

### ISR 제외 조건
```
replica.lag.time.max.ms (default: 30초)
```
- Follower가 이 시간 내에 fetch 요청을 안 보내면 → ISR에서 제외
- 과거엔 `replica.lag.max.messages` (메시지 개수)도 있었으나 삭제됨
  - 이유: Burst traffic 시 false positive 많았음

### ISR 관리 메커니즘
```
Leader가 추적하는 정보:
- 각 Follower의 마지막 fetch 시간
- 각 Follower의 LEO (Log End Offset)

ISR shrink 조건:
if (currentTime - lastFetchTime > replica.lag.time.max.ms):
    remove from ISR

ISR expand 조건:
if (follower.LEO == leader.LEO):
    add to ISR
```

### 중요 포인트
- **ISR은 Leader가 관리**, Controller가 ZooKeeper(또는 metadata log)에 기록
- ISR 변경 시 모든 broker에게 metadata update 전파
- **Leader는 항상 ISR에 포함**

### Trade-offs
- 타이트한 `replica.lag.time.max.ms`: 빠른 감지, 하지만 네트워크 blip으로 오탐
- 느슨한 설정: 오탐 감소, 하지만 실제 장애 감지 늦음

---

## 3. acks=0, 1, all의 차이와 트레이드오프

### Producer Config: acks

| acks | 의미 | 레이턴시 | 내구성 | 데이터 손실 시나리오 |
|------|------|----------|--------|---------------------|
| **0** | Fire-and-forget | 최저 (~1ms) | 없음 | Leader가 받기 전 네트워크 끊김 |
| **1** | Leader만 ACK | 낮음 (~5ms) | 중간 | Leader가 받았지만 복제 전 crash |
| **all** (또는 -1) | 모든 ISR ACK | 높음 (~10-20ms) | 최고 | 모든 ISR 동시 장애 (극히 드묾) |

### acks=0: Fire-and-Forget
```java
props.put("acks", "0");
// Producer가 send() 후 즉시 리턴, broker 응답 안 기다림
```
**사용 사례:**
- 로그 수집, 메트릭 (일부 손실 허용)
- 극한의 throughput 필요

### acks=1: Leader Only
```java
props.put("acks", "1");
// Leader가 append 후 ACK, follower 복제 전
```
**위험:**
```
1. Producer → Leader 전송
2. Leader → append to log
3. Leader → ACK to Producer ✅
4. [Leader crashes before replication]
5. Follower가 Leader로 승격
6. → 메시지 손실!
```

**Kafka 3.0 이전 기본값**, 현재는 `acks=all` 기본

### acks=all: Strongest Durability
```java
props.put("acks", "all");
props.put("min.insync.replicas", "2"); // topic/broker level
```
**동작:**
1. Producer → Leader 전송
2. Leader → append
3. Leader → 모든 ISR follower가 fetch & append 대기
4. 모든 ISR ACK → Leader ACK to Producer

**함정:**
```yaml
Scenario: replication.factor=3, min.insync.replicas=2

- 정상: 3개 replica → ISR 2개 이상 → OK
- 1개 장애: 2개 남음 → ISR 2개 → OK
- 2개 장애: 1개 남음 → ISR < 2 → Producer Error!
  "NOT_ENOUGH_REPLICAS" exception
```

**Best Practice:**
```
replication.factor = 3
min.insync.replicas = 2
acks = all

→ 1개 장애 허용, 2개 장애 시 쓰기 중단 (가용성 < 내구성)
```

---

## 4. High Watermark와 Log End Offset

### 용어 정의

**LEO (Log End Offset)**:
- 각 replica의 log 마지막 offset + 1
- 각 replica마다 다를 수 있음

**HW (High Watermark)**:
- **모든 ISR이 복제 완료한 offset**
- `HW = min(ISR의 모든 LEO)`
- **Consumer는 HW까지만 읽을 수 있음** (uncommitted data 보호)

### 예시
```
Leader LEO: 10
Follower A LEO: 10
Follower B LEO: 8 (lagging)

ISR = {Leader, A, B}
HW = min(10, 10, 8) = 8

→ Consumer는 offset 0~7까지만 읽음
→ offset 8~9는 "uncommitted" (아직 복제 중)
```

### Two-Fetch Delay Problem

**문제:**
HW는 **두 번째 fetch에서 업데이트**됨

```
Time 0:
Leader writes offset 5~7, LEO=8
Follower A fetch → receives 5~7, updates LEO=8

Time 1:
Follower A second fetch
→ Leader sees "A has LEO=8"
→ Leader updates HW=8
→ Leader responds with HW=8
→ Follower updates its HW=8
```

**왜 이렇게?**
1. Follower가 fetch 요청 시 자신의 현재 offset 전송
2. Leader는 그 정보로 "follower가 어디까지 있는지" 파악
3. 다음 fetch 때 HW 업데이트

**영향:**
- Producer → Consumer latency에 최소 1 RTT 추가
- Kafka 0.11+ KIP-101로 개선 (leader epoch 도입)

### Leader Epoch
```
문제: HW 업데이트 전 Leader crash → Follower가 승격 → HW 불일치

해결: Leader Epoch (단조 증가 카운터)
- 각 leader 교체마다 epoch 증가
- Follower는 epoch 확인으로 "내 데이터가 최신인지" 판단
- HW 불일치 시 truncate
```

---

## 5. Leader 선출 (Controller, ZK → KRaft)

### ZooKeeper 시대 (Kafka 3.0 이전)

**구조:**
```
ZooKeeper Ensemble
    ↓
Controller (Kafka broker 중 1대)
    ↓
Partition Leaders (각 파티션마다)
```

**Controller 역할:**
- Partition Leader 선출
- ISR 관리
- Broker failure 감지 (ephemeral znode)

**Leader Election 흐름:**
1. Broker failure → ZK ephemeral node 삭제
2. Controller가 감지 (watch trigger)
3. Controller가 ISR에서 새 Leader 선택
4. ZK에 metadata 업데이트
5. 모든 broker에게 update 전파

**문제점:**
- **ZK 의존성**: 외부 시스템 장애 시 Kafka 전체 마비
- **Metadata 병목**: 대규모 클러스터(10,000+ partition)에서 ZK 부하
- **Split-brain 위험**: Network partition 시 두 개의 controller

### KRaft 시대 (Kafka 3.3+)

**핵심 변화:**
- ZooKeeper 완전 제거
- **Metadata를 Kafka topic처럼 관리** (`__cluster_metadata`)
- **Raft 합의 알고리즘** 사용

**Quorum Controller Election:**
```
1. Controller quorum (예: 3대)
2. Raft leader election
   - 각 controller가 vote
   - majority (2/3) 획득한 controller가 leader
3. Leader는 metadata log에 쓰기
4. Follower controller는 복제

Leader Election 조건:
- Candidate의 log가 최신이어야 함 (last offset + epoch)
- Majority vote 필요
```

**장점:**
- 외부 의존성 제거
- Metadata 복제가 Kafka 자체 메커니즘 활용
- 더 빠른 failover (ZK round-trip 제거)

**Trade-offs:**
- 초기 설정 복잡도 증가 (quorum 구성)
- KRaft는 비교적 신규 (3.3에서 production-ready)

---

## 6. Unclean Leader Election의 위험성

### Clean vs Unclean Election

**Clean Election (default):**
```
unclean.leader.election.enable = false

조건: 새 Leader는 반드시 ISR 중에서
결과: ISR이 전멸하면 partition 불가용 (쓰기/읽기 중단)
```

**Unclean Election:**
```
unclean.leader.election.enable = true

조건: ISR이 없으면 out-of-sync replica도 Leader 가능
결과: 데이터 손실 가능, 하지만 partition 가용
```

### 데이터 손실 시나리오

```
Time 0:
Leader: offset 0~100 (ISR)
Follower A: offset 0~100 (ISR)
Follower B: offset 0~80 (out-of-sync, 네트워크 지연)

Time 1:
Leader crashes
Follower A crashes (동시 장애, 예: rack failure)

Time 2:
ISR = {} (empty!)

Clean election: partition 불가용
Unclean election: B를 Leader로 승격
  → offset 81~100 영구 손실!
```

**생산자 입장:**
```
Producer는 offset 100까지 ack 받았지만,
새 Leader는 offset 80까지만 가짐
→ Consumer는 81~100을 영영 못 봄
```

### 설정 전략

| 시스템 유형 | unclean election | 이유 |
|------------|------------------|------|
| 금융 거래 | **false** | 데이터 무결성 > 가용성 |
| 로그 수집 | **true** | 일부 손실 < 전체 중단 |
| 일반 이벤트 | **false** (권장) | Kafka 0.11+부터 기본값 |

**Best Practice:**
```yaml
# Production 권장
unclean.leader.election.enable=false
replication.factor=3
min.insync.replicas=2

# High availability 필요 시
unclean.leader.election.enable=true
+ 별도 클러스터에 mirror (disaster recovery)
```

### KIP-106: Default 변경
- Kafka 0.11.0.0 (2017)부터 `false` 기본
- 이전 버전은 `true`가 기본 → **무심코 데이터 손실 위험**

---

## 핵심 인사이트

1. **Leader-Follower는 트레이드오프 선택**
   - 단순성/성능 vs 복잡성
   - Kafka는 "순서 보장 + 확장성"을 위해 선택

2. **ISR은 동적 안전망**
   - 느린 replica 자동 제외 → 쓰기 지연 방지
   - 빠른 failover (ISR 중에서만 선출)

3. **acks는 SLA 정의**
   - 0: 로그 수집 (손실 허용)
   - 1: 일반 이벤트 (균형)
   - all: 금융/주문 (절대 손실 불가)

4. **HW는 일관성의 경계선**
   - Consumer는 "완전히 복제된" 데이터만 읽음
   - uncommitted data 보호

5. **KRaft는 아키텍처 단순화**
   - ZK 제거 → 운영 복잡도 감소
   - Metadata도 Kafka로 → self-contained

6. **Unclean election은 마지막 수단**
   - 가용성 > 내구성이 명확할 때만
   - 대부분은 partition 중단이 데이터 손실보다 나음

---

## 참고 자료

- [Kafka Design - Replication](https://kafka.apache.org/documentation/#replication)
- [KIP-101: Alter Replication Protocol](https://cwiki.apache.org/confluence/display/KAFKA/KIP-101)
- [KIP-106: Unclean Leader Election](https://cwiki.apache.org/confluence/display/KAFKA/KIP-106)
- [KRaft: Kafka Without ZooKeeper](https://developer.confluent.io/learn/kraft/)
- [The Log (Jay Kreps)](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying)

---

**작성일**: 2026-02-15  
**다음 단계**: 초안 작성 (2000-3000자, 해체분석기 톤)
