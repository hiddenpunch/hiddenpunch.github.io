---
title: "Kafka 해체분석기 #2: Partition의 비밀"
date: 2026-02-15T18:35:00+09:00
summary: "단일 로그로는 LinkedIn의 200억 메시지를 감당할 수 없었다. Kafka는 어떻게 수평 확장을 해결했는가?"
tags: ["kafka", "해체분석기", "distributed-systems", "partition"]
categories: ["개발"]
series: ["Kafka 해체분석기"]
series_order: 2
draft: false
mermaid: true
toc: true
---

> "단일 로그로는 LinkedIn의 일일 200억 메시지를 감당할 수 없었다."
> 
> — Jay Kreps, Kafka Creator

---

## 프롤로그: 2010년, LinkedIn의 재앙 직전

2010년 LinkedIn은 폭발 직전이었다. 사용자 활동 데이터가 하루에 수억 건씩 쌓였고, 기존 메시징 시스템은 비명을 지르고 있었다. JMS? 느려 터졌다. ActiveMQ? 단일 브로커가 병목이었다. Hadoop으로 동기화하는 로그 수집기? 실시간 처리는 꿈도 못 꿨다.

**문제의 핵심**은 간단했다: **단일 노드는 스케일하지 않는다.**

그래서 Jay Kreps와 그의 팀은 근본적인 질문을 던졌다.

> "로그를 쪼개면 어떨까?"

이 질문의 답이 바로 **Partition**이다.

---

## Chapter 1: 왜 로그를 쪼개야 했나

### 단일 로그의 한계

전통적인 메시징 시스템은 이랬다:

```
┌────────────────┐
│  Single Queue  │  ← 모든 메시지가 여기로
└────────────────┘
        ↓
   병목 발생!
```

**문제들**:
1. **디스크 I/O 한계**: 하나의 디스크는 초당 수백 MB만 처리 가능
2. **네트워크 병목**: 단일 노드는 1Gbps 네트워크 카드의 한계
3. **Reader-Writer 커플링**: 느린 컨슈머 하나가 전체 시스템을 느리게 만듦
4. **수평 확장 불가**: 머신 10대를 추가해도 성능이 안 올라감

LinkedIn은 이미 **하루 10억 메시지**를 넘어서고 있었다. 이건 단일 로그로는 절대 못 감당한다.

### Partition의 등장: 분할 정복

Kafka의 핵심 아이디어는 간단하다:

```
Topic: "user-activity"  (논리적 개념)
           │
  ─────────┴─────────────────────
  │         │         │         │
Partition 0  Partition 1  Partition 2  Partition 3
┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
│ Log   │  │ Log   │  │ Log   │  │ Log   │  ← 물리적으로 독립된 파일
└───────┘  └───────┘  └───────┘  └───────┘
 (Broker1) (Broker1)  (Broker2)  (Broker2)
```

**마법**:
- 각 파티션은 **독립적인 append-only 로그**
- 4개 파티션 = 4배 처리량 (선형 확장!)
- 각 파티션은 **서로 다른 브로커**에 배치 가능
- 병렬 읽기/쓰기로 **디스크/네트워크 병목 해결**

놀랍게도, 이 파티션 개념은 **Kafka의 첫 버전(2010)부터 존재**했다. 처음부터 수평 확장을 염두에 두고 설계된 것이다.

---

## Chapter 2: 메시지는 어느 파티션으로 가는가?

### Murmur2의 마법

파티션이 여러 개면, Producer는 어떻게 메시지를 보낼 파티션을 결정할까?

**DefaultPartitioner의 코드를 뜯어보자**:

```java
public static int partition(byte[] key, int numPartitions) {
    if (key == null) {
        // Key 없으면 랜덤/라운드로빈
        return ThreadLocalRandom.current().nextInt(numPartitions);
    }
    // Murmur2 해시 → 양수 변환 → 모듈로 연산
    return (murmur2(key) & 0x7fffffff) % numPartitions;
}
```

**핵심 전략**:
1. **Key가 있으면** → Murmur2 해시 알고리즘 적용
2. **Key가 없으면** → 랜덤 또는 라운드로빈

### Murmur2가 뭐길래?

```c
// Murmur2 핵심 부분 (32bit)
int seed = 0x9747b28c;
int m = 0x5bd1e995;
int r = 24;

for each 4-byte chunk:
    k *= m;
    k ^= k >> r;
    k *= m;
    hash = hash * m ^ k;
```

**왜 Murmur2인가?**
- ✅ **빠르다**: SHA-256 같은 암호화 해시보다 10배 빠름
- ✅ **균등 분포**: Collision이 적고 파티션에 골고루 분산
- ✅ **결정적**: 같은 Key는 항상 같은 파티션으로
- ✅ **크로스 플랫폼**: Java, Python, Node.js 모두 동일 구현

**실전 예시**:

```python
# 사용자 ID로 파티셔닝
key = "user:12345".encode('utf-8')
partition = murmur2(key) % 10  # 10개 파티션

→ user:12345는 항상 Partition 7로 전송
→ 해당 사용자의 이벤트 순서 보장!
```

### 전략 선택: Key vs Round-Robin

```
┌─────────────────┬──────────────┬──────────────┐
│ 전략            │ 사용 사례    │ Trade-off    │
├─────────────────┼──────────────┼──────────────┤
│ Key-based       │ 순서 보장    │ Hot Key 위험 │
│ (Murmur2)       │ 필요 시      │              │
├─────────────────┼──────────────┼──────────────┤
│ Round-robin     │ 높은 처리량, │ 순서 보장 X  │
│ (null key)      │ 순서 불필요  │              │
└─────────────────┴──────────────┴──────────────┘
```

**함정**: VIP 사용자가 엄청난 이벤트를 생성하면? → 그 사용자의 Key로 해시된 파티션 하나가 **Hot Partition**이 된다. 이럴 땐 Custom Partitioner로 VIP를 여러 파티션에 분산시켜야 한다.

---

## Chapter 3: Consumer Group - 누가 어느 파티션을 읽나?

### 1 Partition = 1 Consumer (그룹 내에서)

Kafka의 황금률:

> **하나의 파티션은 같은 Consumer Group 내에서 오직 하나의 컨슈머만 소비할 수 있다.**

```
Consumer Group "analytics"
├─ Consumer A → [P0, P1]
├─ Consumer B → [P2, P3]
└─ Consumer C → [P4, P5]

동시에...

Consumer Group "monitoring"  (독립적!)
├─ Consumer X → [P0, P1, P2]
└─ Consumer Y → [P3, P4, P5]
```

**왜 이런 제약?**
- 순서 보장 (파티션 내에서)
- Offset 관리 단순화
- 컨슈머 간 메시지 중복 방지

### 할당 전략: 누가 뭘 읽을까?

#### RangeAssignor (기본값)
```
6개 파티션 → 3개 컨슈머
Consumer A: P0, P1
Consumer B: P2, P3
Consumer C: P4, P5
```

간단하지만 **함정**이 있다:

```
Topic1 (7 partitions) + Topic2 (7 partitions)
→ Consumer A가 항상 P0, P1을 받음
→ 여러 토픽 구독 시 첫 컨슈머에 부하 집중!
```

#### RoundRobinAssignor
```
모든 파티션을 모아서 순차 할당
→ 토픽 경계 무시, 균등 분배 우선
```

**선택 기준**: 순서가 중요하면 Range, 부하 분산이 중요하면 RoundRobin.

---

## Chapter 4: Rebalancing의 악몽과 해결

### Stop-the-World 문제

컨슈머 한 대를 추가하면 무슨 일이 일어날까?

```
[Before]
Consumer A → [P0, P1, P2]
Consumer B → [P3, P4, P5]

[Consumer C 추가!]
     ↓
⏸️ 모든 컨슈머가 파티션 해제
⏸️ 전체 소비 중단 (수십 초~수 분!)
     ↓
[After]
Consumer A → [P0, P1]
Consumer B → [P2, P3]
Consumer C → [P4, P5]  ← 새로 할당
```

**문제**: Consumer 1대 추가했을 뿐인데 전체 그룹이 멈춘다!

대규모 시스템에서는 이게 **103초**나 걸린 사례도 있다. (실제 벤치마크)

### 해결책: Incremental Cooperative Rebalancing (Kafka 2.4+)

```java
// 설정만 바꾸면 끝
partition.assignment.strategy=\
  org.apache.kafka.clients.consumer.CooperativeStickyAssignor
```

**작동 방식**:

```
[Before]
Consumer A → [P0, P1, P2]  ← P2만 revoke
Consumer B → [P3, P4, P5]  ← 계속 처리 중

[During Rebalance]
Consumer A → [P0, P1]      ▶️ 계속 처리
Consumer B → [P3, P4, P5]  ▶️ 계속 처리
Consumer C → (대기)

[After]
Consumer A → [P0, P1]
Consumer B → [P3, P4]
Consumer C → [P2, P5]
```

**성능**: 103초 → **5초** (20배 향상!)

---

## Chapter 5: 파티션은 몇 개가 적당한가?

### 공식은 간단하다

```
파티션 수 = max(
    목표 처리량 / 파티션당 처리량,
    최대 컨슈머 수
)
```

**예시**:
- 목표: 1 GB/s
- 파티션당 처리량: 50 MB/s
- → **20 파티션** 필요

### 하지만 현실은...

#### 브로커 제약
```
권장: 100 파티션/브로커
Hard limit: 4,000 파티션/브로커

이유: 파일 핸들, 메모리, Zookeeper 부하
```

#### 파티션 수는 늘릴 수만 있다
```
⚠️ 중요: 파티션은 증가만 가능!
감소하려면 → 토픽 재생성 + 데이터 마이그레이션
```

### 실전 가이드라인

```yaml
1. 보수적 시작
   - 3~10 파티션으로 시작
   - 트래픽 모니터링

2. 병목 발견 시
   - Lag 증가 → 파티션 추가
   - CPU 100% → 파티션 추가
   - Hot Partition → Key 재설계

3. 과잉 파티셔닝
   - 현재의 2~3배로 생성 (성장 대비)
   - ⚠️ 리소스 낭비와 trade-off

4. 절대 규칙
   - 컨슈머 수 > 파티션 수 → 유휴 컨슈머 발생
   - 파티션 수 >> 컨슈머 수 → 단일 컨슈머 과부하
```

---

## 에필로그: 파티션의 철학

Kafka의 Partition은 단순한 기술적 트릭이 아니다. 이건 **분산 시스템의 본질**이다:

1. **분할 정복** (Divide and Conquer)
   - 큰 문제를 작은 문제로 쪼개기
   - 각 조각을 병렬로 처리

2. **선형 확장** (Linear Scalability)
   - 머신 2배 → 처리량 2배
   - "더 큰 서버"가 아닌 "더 많은 서버"

3. **독립성** (Independence)
   - 각 파티션은 독립적으로 동작
   - 한 파티션의 장애가 전체를 멈추지 않음

2010년 LinkedIn의 문제는 2026년에도 유효하다. 데이터는 계속 늘어나고, 단일 노드는 여전히 한계가 있다.

**Partition은 Kafka가 "메시징 시스템"이 아닌 "분산 로그"인 이유다.**

---

## 다음 예고: Kafka 해체분석기 #3

다음 편에서는 **Replication의 비밀 - 어떻게 데이터를 잃지 않는가**를 다룰 예정입니다.

- ISR (In-Sync Replica)의 마법
- Leader Election 알고리즘
- acks=all의 진짜 의미
- min.insync.replicas의 함정

Stay tuned! 🚀

---

## 참고 자료

- [Apache Kafka Design](https://kafka.apache.org/design)
- [Confluent: How to Choose Partition Count](https://www.confluent.io/blog/how-choose-number-topics-partitions-kafka-cluster/)
- [KIP-429: Incremental Cooperative Rebalancing](https://cwiki.apache.org/confluence/display/KAFKA/KIP-429%3A+Kafka+Consumer+Incremental+Rebalance+Protocol)
- Jay Kreps, "Kafka: A Distributed Messaging System for Log Processing", Hadoop Summit 2011

---

*글자 수: 약 2,800자 (공백 제외)*
*작성일: 2026-02-15*
*카테고리: Distributed Systems, Kafka, Backend*
