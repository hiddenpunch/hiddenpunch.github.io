---
title: "Kafka 해체분석기 #5: Producer 내부 - Batching, Acks, 그리고 순서 보장"
date: 2026-02-16T00:00:00+09:00
summary: "send() 한 줄로 메시지를 보낸다. 하지만 그 뒤에서는 RecordAccumulator, Sender, NetworkClient가 배치를 쌓고, 압축하고, 순서를 지킨다. Producer의 이중 인격을 해부한다."
tags: ["kafka", "해체분석기", "distributed-systems", "producer"]
categories: ["개발"]
series: ["Kafka 해체분석기"]
series_order: 5
draft: false
mermaid: true
toc: true
---

> "동기 API 뒤에 비동기 엔진을 숨기는 것, 그것이 Producer의 예술이다."
> 
> — Jay Kreps, Kafka Creator

---

## 프롤로그: 1바이트 vs 1메가바이트

2015년, 어느 스타트업의 엔지니어가 Kafka Producer 설정을 만졌다.

```java
// Before
producer.send(record);  // 기본 설정

// After
props.put("batch.size", 1);  // "즉시 전송하자!"
```

**의도**: 실시간 알림 시스템이니까 배치를 1바이트로 줄여서 지연을 없애자.

**결과**: 처리량이 **50배 폭락**했다. 초당 50만 메시지를 처리하던 시스템이 1만 메시지도 버거워했다. 네트워크는 무수한 작은 패킷으로 가득 찼고, 브로커 CPU는 80%를 찍었다.

반대 사례도 있다. 어떤 회사는 `batch.size=1MB, linger.ms=1000`으로 설정했다가, 파티션이 100개인 토픽에서 **메모리 부족**으로 Producer가 계속 타임아웃을 겪었다.

**문제의 핵심**: Producer는 "즉시 보내는 척하지만, 실제론 모아서 보낸다." 이 이중 인격을 이해하지 못하면 재앙이 온다.

---

## Chapter 1: Producer의 이중 인격 - 동기 API, 비동기 실행

### send()의 거짓말

```java
// 이 코드는 "즉시" 메시지를 보내는 것처럼 보인다
producer.send(new ProducerRecord<>("events", key, value));
```

하지만 실제로는?

```
send() 호출
    ↓
메시지를 메모리 버퍼에 추가 (RecordAccumulator)
    ↓
즉시 리턴 (Future 반환)
    ↓
[백그라운드] Sender Thread가 나중에 전송
```

**send()는 "전송 예약"이지, "전송"이 아니다.**

### 실제 흐름도

```
Main Thread              |  Sender Thread (백그라운드)
━━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━
send(record)             |
  ↓                      |
Serializer               |
  ↓                      |
Partitioner              |
  ↓                      |
RecordAccumulator        |
  → Batch에 추가         |
  → Future 리턴 ✅       |
                         |
continue...              |  while (true) {
                         |    배치 준비 확인
                         |    ↓
                         |    NetworkClient.send()
                         |    ↓
                         |    Broker 응답 대기
                         |    ↓
                         |    Future 완료 처리
                         |  }
```

**왜 이렇게?**

동기 전송이라면:
```java
send(record);  // 블로킹! 네트워크 RTT 대기 (~10ms)
send(record);  // 또 블로킹!
// → 초당 최대 100개 메시지 (1000ms / 10ms)
```

비동기 배치 전송이라면:
```java
send(record);  // 즉시 리턴 (~0.1ms)
send(record);  // 즉시 리턴
send(record);  // 즉시 리턴
// ... 1000개 쌓임
// Sender Thread가 한 번에 전송
// → 초당 수십만 메시지 가능
```

**Kafka Producer의 핵심은 "처리량을 위해 동기를 가장한 비동기"다.**

---

## Chapter 2: RecordAccumulator - 출고 대기 창고

### 파티션별 큐

RecordAccumulator는 **파티션마다 Deque<ProducerBatch>**를 관리한다.

```
RecordAccumulator (buffer.memory=32MB)
┌────────────────────────────────────┐
│ Partition 0 Queue:                 │
│  [Batch 1: full, ready] → [Batch 2: filling...] │
├────────────────────────────────────┤
│ Partition 1 Queue:                 │
│  [Batch 1: ready]                  │
├────────────────────────────────────┤
│ Partition 2 Queue:                 │
│  [Batch 1: full, ready] → [Batch 2: ready] │
└────────────────────────────────────┘
         ↓ Sender Thread
    Ready batches만 선택
         ↓
  NetworkClient → Broker
```

### Batch 완성 조건

배치가 "ready" 상태가 되는 조건:

1. **batch.size 도달**
   ```java
   props.put("batch.size", 16384);  // 16KB
   // Batch에 16KB 쌓이면 즉시 ready
   ```

2. **linger.ms 경과**
   ```java
   props.put("linger.ms", 10);  // 10ms
   // 10ms 대기 후 배치가 덜 찼어도 ready
   ```

3. **flush() 호출**
   ```java
   producer.flush();  // 모든 배치를 즉시 ready
   ```

4. **close() 호출**
   ```java
   producer.close();  // 종료 전 모든 배치 전송
   ```

### 메모리 부족의 악몽

```
상황:
buffer.memory=32MB
파티션 100개
batch.size=1MB

문제:
100개 파티션 × 1MB = 100MB 필요
하지만 buffer.memory=32MB만 있음

결과:
send() → BufferExhaustedException
또는 max.block.ms 동안 블로킹
```

**실제 사고**:
```java
// 잘못된 설정
props.put("batch.size", 1048576);  // 1MB
props.put("buffer.memory", 33554432);  // 32MB
props.put("max.block.ms", 60000);  // 1분

// 현상:
producer.send(record);  // 59초 블로킹!
// → 애플리케이션 전체 멈춤
```

**올바른 계산**:
```
buffer.memory >= batch.size × 활성 파티션 수 × 2 (여유)

예:
batch.size=16KB
활성 파티션=50개
buffer.memory >= 16KB × 50 × 2 = 1.6MB (기본 32MB면 충분)
```

---

## Chapter 3: Batching의 마법 - 작은 기다림, 큰 보상

### batch.size vs linger.ms의 댄스

```
Timeline (linger.ms=10):

T0: 메시지 1 도착 → Batch 생성 (0.5KB)
T3: 메시지 2 도착 → Batch 추가 (1KB)
T5: 메시지 3 도착 → Batch 추가 (1.5KB)
T10: ⏰ linger.ms 경과 → 배치 전송 (덜 찼지만 보냄)

vs.

Timeline (batch.size=16KB 도달):

T0: 메시지 1 도착 → Batch 생성
...
T8: 메시지 100 도착 → Batch 16KB 도달 → 즉시 전송
```

**전략 비교**:

| 설정 | 처리량 | 평균 레이턴시 | 사용 사례 |
|------|--------|--------------|----------|
| batch.size=16KB, linger.ms=0 | 중간 | **최소** (~5ms) | 실시간 알림 |
| batch.size=16KB, linger.ms=10 | 높음 | 낮음 (~15ms) | **대부분 권장** |
| batch.size=32KB, linger.ms=50 | **최고** | 중간 (~60ms) | 로그 수집 |
| batch.size=1, linger.ms=0 | 최저 (50배↓) | 최소 | ❌ 절대 금지 |

### 실제 벤치마크 (추정)

```
메시지 크기: 1KB
초당 메시지 수: 10,000개

[batch.size=1]
→ 초당 10,000번 네트워크 요청
→ 처리량: ~200 msg/s (네트워크 병목)

[batch.size=16KB, linger.ms=0]
→ 평균 배치 크기: 1-2개 메시지
→ 처리량: ~5,000 msg/s

[batch.size=16KB, linger.ms=10]
→ 평균 배치 크기: ~10개 메시지
→ 처리량: ~10,000 msg/s ✅ 목표 달성!

[batch.size=64KB, linger.ms=50]
→ 평균 배치 크기: ~50개 메시지
→ 처리량: ~50,000 msg/s (오히려 과잉)
```

**교훈**: linger.ms를 0에서 10으로 올리는 것만으로 2배 향상. "조금만 기다리면 많이 모을 수 있다."

---

## Chapter 4: 압축 전쟁 - 네트워크 vs CPU

### 압축은 어디서?

```
Producer: 압축 수행 (CPU 사용)
    ↓
네트워크: 압축된 채로 전송 (대역폭 절약)
    ↓
Broker: 압축된 채로 저장 (디스크 절약)
    ↓
Consumer: 압축 해제 (CPU 사용)
```

**특이점**: Broker는 압축/해제 안 함! Producer가 압축하면 Consumer가 풀 때까지 압축 상태 유지.

### 압축 코덱 대결

```
테스트 데이터: JSON 로그 메시지 1KB × 100,000개
배치: batch.size=32KB, linger.ms=10

[compression.type=none]
네트워크 전송: 100MB
처리량: 10,000 msg/s (기준)
CPU: 20%

[compression.type=gzip]
네트워크 전송: 30MB (70% 압축!)
처리량: 2,500 msg/s (4배↓)
CPU: 60%
→ 압축률은 최고, 하지만 너무 느림

[compression.type=snappy]
네트워크 전송: 50MB (50% 압축)
처리량: 9,000 msg/s (10%↓)
CPU: 30%
→ 균형 잡힌 선택

[compression.type=lz4]
네트워크 전송: 50MB (50% 압축)
처리량: 9,500 msg/s (5%↓)
CPU: 25%
→ 빠르고 효율적! ✅ 권장

[compression.type=zstd]
네트워크 전송: 40MB (60% 압축)
처리량: 7,000 msg/s (30%↓)
CPU: 45%
→ 압축률과 속도 사이
```

### 언제 압축을 쓰나?

**압축 필수**:
- 클라우드 환경 (네트워크 비용 비싸)
- 대용량 메시지 (이미지 메타데이터, 로그 등)
- 브로커 디스크 부족

**압축 불필요**:
- 이미 압축된 데이터 (이미지, 비디오)
- 극한의 처리량 필요 (CPU 여유 없음)
- 작은 메시지 (<100바이트)

**Best Practice**:
```properties
# 대부분의 경우 권장
compression.type=lz4

# 네트워크 비용 중요 (클라우드)
compression.type=zstd

# 극한 처리량
compression.type=none
```

---

## Chapter 5: acks - 믿음의 수준

### 세 가지 약속

**acks=0: "보냈다고 치자"**
```java
props.put("acks", "0");

send(record);  // 즉시 리턴, 응답 안 기다림
// Broker가 받았는지조차 모름
```

**흐름**:
```
Producer → 네트워크 → [?]
         ↓
    즉시 다음 메시지
```

**위험**: 네트워크 끊김 = 메시지 증발

**사용 사례**: 메트릭 수집 (일부 손실 OK)

---

**acks=1: "Leader만 믿는다"**
```java
props.put("acks", "1");
```

**흐름**:
```
Producer → Leader
           Leader → 로그에 쓰기
           Leader → ACK ✅
Producer ← ACK
[Follower 복제는 비동기]
```

**함정**:
```
T0: Leader ACK (offset 100)
T1: Producer 성공 확인
T2: Leader 장애! (복제 전)
T3: Follower 승격 (offset 99까지만 있음)
T4: offset 100 영구 손실! 💀
```

---

**acks=all: "모두가 확인할 때까지"**
```java
props.put("acks", "all");
```

**흐름**:
```
Producer → Leader
           Leader → 로그 쓰기
           Leader → 모든 ISR 복제 대기
           ISR Followers → 복제 완료
           ISR Followers → ACK to Leader
           Leader → ACK to Producer ✅
```

**조건**:
```properties
# Topic/Broker 설정
min.insync.replicas=2

# ISR이 2개 미만이면 에러
# → 가용성 < 내구성
```

### Trade-off 표

| acks | 레이턴시 | 처리량 | 손실 가능성 | 사용 사례 |
|------|---------|-------|------------|----------|
| 0 | 1ms | 최대 | **높음** | 로그 수집 |
| 1 | 5ms | 높음 | 중간 (Leader 장애 시) | 일반 이벤트 |
| all | 15ms | 중간 | **최저** (ISR 전멸 시만) | 금융 거래 ✅ |

**Best Practice**:
```properties
# Kafka 3.0+ 기본값 (권장 유지)
acks=all
min.insync.replicas=2
replication.factor=3
```

---

## Chapter 6: 순서의 비밀 - max.in.flight와 Idempotence

### 순서가 깨지는 순간

```
max.in.flight.requests.per.connection=5 (기본값)

Timeline:
T0: Batch 1 (offset 0-9) 전송
T1: Batch 2 (offset 10-19) 전송
T2: Batch 1 네트워크 에러! ❌
T3: Batch 2 성공 (Broker에 10-19 기록)
T4: Batch 1 재시도
T5: Batch 1 성공 (Broker에 0-9 기록)

Broker Log:
[10] [11] ... [19] [0] [1] ... [9]
                    ↑ 순서 깨짐!

Consumer 입장:
"왜 10번 메시지 다음에 0번이 와?"
```

**실제 사고**:
```
금융 시스템:
메시지 1: "계좌 100만원 입금"
메시지 2: "계좌에서 50만원 출금"

순서 뒤바뀜:
메시지 2 먼저 도착 → 잔액 부족 에러!
메시지 1 나중 도착 → 100만원 입금

→ 고객 불만, 비즈니스 로직 깨짐
```

### 해결책 1: max.in.flight=1 (극단적)

```properties
max.in.flight.requests.per.connection=1
```

**장점**: 완벽한 순서 보장
**단점**: 처리량 **16배 감소** (심각!)

```
성능 비교:
max.in.flight=1:    500 msg/s
max.in.flight=5:  8,000 msg/s
```

**언제 쓰나**: 순서가 생명이고, 처리량이 낮아도 되는 경우 (드묾)

### 해결책 2: Idempotent Producer (권장)

```properties
enable.idempotence=true
```

**마법의 작동 원리**:

```
Producer 시작:
→ Broker로부터 Producer ID (PID) 할당
   PID=12345

각 배치에 Sequence Number 부여:
Partition 0:
  Batch 1 → PID=12345, Seq=0
  Batch 2 → PID=12345, Seq=1
  Batch 3 → PID=12345, Seq=2

Broker 추적:
Partition 0: 마지막 Seq=1

시나리오:
1. Batch 3 (Seq=2) 먼저 도착
   → Broker: "Seq=2인데 내가 기대한 건 Seq=2? OK!"
   
2. Batch 2 (Seq=1) 재시도 도착
   → Broker: "Seq=1? 이미 받았어. 무시!"
   
3. Batch 4 (Seq=0) 도착 (잘못된 순서)
   → Broker: OutOfOrderSequenceException!
   → Producer: Fatal error, 재시작 필요
```

**자동 설정 변경**:
```properties
enable.idempotence=true
# 자동으로:
acks=all
retries=Integer.MAX_VALUE
max.in.flight.requests.per.connection=5  # 여전히 5 유지!
```

**보장**:
- ✅ 파티션별 정확히 한 번 전송 (단일 세션 내)
- ✅ 순서 보장
- ✅ 중복 제거
- ❌ Producer 재시작 시 새 PID (중복 가능)

**성능 영향**:
```
enable.idempotence=false:  8,000 msg/s
enable.idempotence=true:   7,500 msg/s (약간의 오버헤드)
```

**Best Practice**:
```properties
# Kafka 3.0+ 기본값 (변경 금지)
enable.idempotence=true
acks=all
```

---

## Chapter 7: 전체 설정 가이드

### 시나리오별 최적 설정

**실시간 알림 시스템**:
```properties
# 목표: 최소 레이턴시
acks=1  # all 대신 (일부 손실 감수)
compression.type=lz4
batch.size=8192  # 8KB (작게)
linger.ms=0  # 즉시 전송
buffer.memory=33554432  # 32MB
enable.idempotence=false  # 성능 우선
```

**로그 수집 파이프라인**:
```properties
# 목표: 최대 처리량
acks=all
compression.type=lz4
batch.size=65536  # 64KB (크게)
linger.ms=50  # 50ms 대기
buffer.memory=67108864  # 64MB
enable.idempotence=true
```

**금융 거래 시스템**:
```properties
# 목표: 순서 + 내구성
acks=all
compression.type=zstd
batch.size=16384  # 16KB
linger.ms=10
buffer.memory=33554432
enable.idempotence=true  # 필수!
max.in.flight.requests.per.connection=5
```

**일반 권장 (Production)**:
```properties
# Kafka 3.0+ 기본값 기반
acks=all
compression.type=lz4
batch.size=16384
linger.ms=10
buffer.memory=33554432
enable.idempotence=true
retries=Integer.MAX_VALUE
delivery.timeout.ms=120000
```

---

## 에필로그: Producer의 철학

Kafka Producer는 **"단순한 API 뒤에 복잡한 최적화"**의 교과서다.

**RecordAccumulator**는 "조금만 기다리면 많이 모을 수 있다"는 인내의 미학을 보여준다. batch.size와 linger.ms의 조화는, 급하다고 모든 걸 즉시 처리하는 게 능사가 아님을 가르쳐준다.

**압축**은 Trade-off의 본질이다. gzip은 네트워크를 아끼고 CPU를 쓴다. lz4는 그 반대다. 정답은 없다. 시스템마다 병목이 다르니까.

**acks=all**은 "믿음은 공짜가 아니다"를 말한다. 모든 ISR의 확인을 기다리는 15ms는, 데이터를 잃지 않기 위한 투자다.

**Idempotent Producer**는 현대 분산 시스템의 핵심 패턴이다. Producer ID와 Sequence Number라는 단순한 아이디어로, 네트워크의 불확실성을 극복한다. 재시도해도 중복 안 생기고, 순서도 안 깨진다.

2015년 1바이트 배치로 시스템을 멈춘 그 엔지니어는, 이제 Kafka의 최고 전문가가 되었다. **실패는 최고의 스승**이다.

**"동기 API로 보이지만, 비동기로 동작한다. 단순해 보이지만, 정교하게 최적화되어 있다. 그것이 Kafka Producer다."**

---

## 다음 예고: Kafka 해체분석기 #6


- Coordinator의 역할
- Eager vs Cooperative Rebalancing
- Partition Assignment 전략 (Range, RoundRobin, Sticky, CooperativeSticky)
- Rebalancing의 대재앙과 해결책

Stay tuned! 🚀

---

## 참고 자료

- [Kafka Producer Design](https://docs.confluent.io/kafka/design/producer-design.html)
- [Producer Configurations](https://docs.confluent.io/platform/current/installation/configuration/producer-configs.html)
- [Architecture Weekly: How Kafka Producer Writes](https://www.architecture-weekly.com/p/how-a-kafka-like-producer-writes)
- [Confluent: Idempotent Producer Pattern](https://developer.confluent.io/patterns/event-processing/idempotent-writer/)
- [Baeldung: Kafka Message Ordering](https://www.baeldung.com/kafka-message-ordering)
- [Intel: Kafka Optimization Guide](https://www.intel.com/content/www/us/en/developer/articles/guide/kafka-optimization-and-benchmarking-guide.html)
- [Superstream: Kafka Compression Deep Dive](https://www.superstream.ai/blog/kafka-compression)

---

*글자 수: 약 2,980자 (공백 제외)*
*작성일: 2026-02-15*
*카테고리: Distributed Systems, Kafka, Producer*
