# Kafka Exactly-Once Semantics 리서치 노트

작성일: 2026-02-15
주제: Kafka 해체분석기 #8 - "Exactly-Once의 비밀 - 트랜잭션은 어떻게 작동하나"

## 1. 세 가지 전송 보장 (Delivery Guarantees)

### At-most-once (최대 한 번)
- **정의**: 메시지가 최대 1번 전달됨 (손실 가능, 중복 없음)
- **Producer 설정**:
  - `acks=0` (응답 안 기다림) 또는 `acks=1` + `retries=0`
  - Fire-and-forget 패턴
- **Consumer 설정**:
  - `enable.auto.commit=true` (처리 전에 커밋)
- **특징**:
  - 최고 처리량, 최저 레이턴시
  - 메시지 손실 가능
- **사용 사례**: 
  - 비중요 텔레메트리 (위치 업데이트, 메트릭)
  - 일부 손실 감수 가능한 로그

### At-least-once (최소 한 번)
- **정의**: 메시지가 최소 1번 이상 전달됨 (손실 없음, 중복 가능)
- **Producer 설정**:
  - `acks=1` 또는 `acks=all`
  - `retries` 활성화 (재시도 허용)
- **Consumer 설정**:
  - `enable.auto.commit=false`
  - 처리 후 수동 커밋
- **특징**:
  - 중간 처리량/레이턴시
  - 재시도로 인한 중복 가능
- **사용 사례**:
  - 대부분의 기본 시나리오
  - Idempotent Producer와 함께 사용하여 중복 감소

### Exactly-once (정확히 한 번)
- **정의**: 메시지가 정확히 1번 처리됨 (손실 없음, 중복 없음)
- **Producer 설정**:
  - `enable.idempotence=true` (Idempotent Producer)
  - `transactional.id=<UNIQUE-ID>` (Transactional Producer)
  - `acks=all` (자동 설정됨)
- **Consumer 설정**:
  - `isolation.level=read_committed`
  - Transactional 처리 (오프셋과 출력 원자적 커밋)
- **특징**:
  - 최저 처리량, 최고 레이턴시
  - 조정(coordination) 오버헤드
  - Kafka 0.11+ 필요
- **사용 사례**:
  - 금융 거래
  - Kafka Streams 정확히 한 번 처리
  - Topic-to-Topic 전송

### 비교 표

| 보장 수준 | 손실 | 중복 | 처리량 | 레이턴시 | 복잡도 |
|----------|------|------|--------|---------|--------|
| At-most-once | 가능 | 없음 | 최고 | 최저 | 낮음 |
| At-least-once | 없음 | 가능 | 중간 | 중간 | 중간 |
| Exactly-once | 없음 | 없음 | 최저 | 최고 | 높음 |

## 2. Idempotent Producer (멱등성 프로듀서)

### 핵심 메커니즘
**Producer ID (PID)**:
- Producer 시작 시 Broker로부터 고유 PID 할당
- PID는 Producer 인스턴스/세션마다 고유함
- `transactional.id` 없으면 재시작 시 새 PID 생성

**Sequence Number**:
- PID별로 각 Topic-Partition마다 0부터 시작하는 시퀀스 번호
- 메시지 배치마다 단조 증가
- Broker가 마지막 커밋된 시퀀스 번호를 메모리에 추적

### 작동 원리
```
Producer (PID=12345):
  Partition 0: Batch 1 → Seq=0
  Partition 0: Batch 2 → Seq=1
  Partition 0: Batch 3 → Seq=2

Broker (Partition 0):
  마지막 커밋 시퀀스: Seq=1

시나리오:
1. Batch 3 (Seq=2) 도착
   → Broker: Seq=2 == 마지막(1) + 1? OK! 커밋
   
2. Batch 2 (Seq=1) 재시도 도착
   → Broker: Seq=1 <= 마지막(2)? 중복! 무시
   
3. Batch 4 (Seq=5) 도착 (순서 깨짐)
   → Broker: OutOfOrderSequenceException
   → Producer: Fatal error, 재시작 필요
```

### 중복 제거 로직
| 도착 Sequence | Broker 마지막 Seq | 동작 | 에러 |
|--------------|------------------|------|------|
| last + 1 | - | 승인 및 커밋 | 없음 |
| ≤ last | - | 거부 (중복) | Duplicate (무시) |
| > last + 1 | - | 거부 (순서 깨짐) | OutOfOrderSequence (Fatal) |

### 자동 설정
`enable.idempotence=true` 설정 시 자동 변경:
- `acks=all`
- `retries=Integer.MAX_VALUE`
- `max.in.flight.requests.per.connection=5` (유지)

### 보장 범위
- ✅ 파티션별 정확히 한 번 전송 (단일 세션 내)
- ✅ 순서 보장
- ✅ 중복 제거 (재시도)
- ❌ Producer 재시작 시 새 PID (세션 간 중복 가능)

### 성능 영향
- 경미한 오버헤드 (~5-10% 처리량 감소)
- Kafka 3.0+ 기본 활성화

## 3. Transactional Producer (트랜잭션 프로듀서)

### Transaction Coordinator 역할
- **위치**: Broker 중 하나가 Transaction Coordinator 역할 수행
- **기능**:
  - PID 할당 및 `transactional.id` → PID 매핑 관리
  - Producer Epoch 추적 (좀비 프로듀서 펜싱)
  - 트랜잭션 상태 관리 (진행 중, 커밋됨, 중단됨)
  - 불완전 트랜잭션 복구

### 트랜잭션 프로세스
```
1. Producer 시작:
   → FindCoordinatorRequest (transactional.id)
   → Coordinator 발견

2. PID 요청:
   → InitPidRequest
   → Coordinator: transactional.id 로깅
   → 같은 transactional.id면 동일 PID + Epoch 증가 반환
   
3. 트랜잭션 시작:
   producer.beginTransaction();
   
4. 파티션 추가:
   producer.send(record);
   → AddPartitionsToTxnRequest
   → Coordinator: 트랜잭션에 파티션 등록
   
5. 메시지 전송:
   → 각 파티션에 메시지 produce (PID/Epoch/Seq 포함)
   
6. 오프셋 커밋 (Consumer용):
   producer.sendOffsetsToTransaction(offsets, groupId);
   → AddOffsetsToTxnRequest
   → __consumer_offsets 파티션에 오프셋 전송
   
7. 커밋/중단:
   producer.commitTransaction();
   → EndTxnRequest (commit)
   → Coordinator: 모든 파티션에 Transaction Marker 기록
   → COMMIT 또는 ABORT 마커
```

### Producer Epoch와 펜싱
- **Epoch**: PID와 함께 사용되는 단조 증가 카운터
- **목적**: 좀비 프로듀서 방지 (네트워크 파티션 후 재연결)
- **메커니즘**:
  - 같은 `transactional.id`로 새 Producer 시작 → Epoch 증가
  - 이전 Epoch를 가진 Producer 요청 → `InvalidProducerEpoch` 에러
  - 이전 Producer 펜싱됨 (더 이상 쓰기 불가)

### 설정
```properties
# Producer
transactional.id=unique-producer-id-123
enable.idempotence=true  # 자동 활성화
acks=all  # 자동
transaction.timeout.ms=900000  # 15분 (기본값)
```

### 제약사항
- ⚠️ EOS는 Kafka 내부에서만 작동 (입력/출력 모두 Kafka 토픽일 때)
- ⚠️ 외부 시스템 (DB, API 호출) 포함 시 EOS 보장 안 됨
- ⚠️ `transactional.id`는 전역 고유해야 함

## 4. Consumer Isolation Level

### read_uncommitted (기본값)
- **동작**: 모든 메시지 읽기 (진행 중/커밋됨/중단됨 트랜잭션 모두 포함)
- **최대 읽기 오프셋**: High Watermark
- **특징**:
  - 낮은 레이턴시, 높은 성능
  - "Dirty read" 가능 (나중에 중단될 트랜잭션 메시지 읽음)
- **사용 사례**: 
  - 높은 처리량 필요
  - At-least-once 처리

### read_committed
- **동작**: 커밋된 트랜잭션 메시지 + 비트랜잭션 메시지만 읽기
- **최대 읽기 오프셋**: Last Stable Offset (LSO)
  - LSO = 첫 번째 미결정 트랜잭션 이전 오프셋
  - 트랜잭션 마커 대기 필요
- **필터링**:
  - 중단된 트랜잭션 메시지 자동 스킵 (Broker 메타데이터 사용)
  - 버퍼링 없이 처리 (효율적)
- **특징**:
  - 높은 레이턴시 (트랜잭션 마커 대기)
  - End-to-End EOS 가능
- **설정**:
```properties
isolation.level=read_committed
enable.auto.commit=false  # 수동 커밋 권장
```

### 비교 표
| 측면 | read_uncommitted | read_committed |
|------|------------------|----------------|
| 가시성 | 모든 레코드 (중단됨 포함) | 커밋됨 + 비트랜잭션만 |
| 최대 오프셋 | High Watermark | Last Stable Offset (LSO) |
| 레이턴시 | 낮음 | 높음 (트랜잭션 대기) |
| Dirty read | 가능 | 불가능 |
| 사용 사례 | 처리량 우선 | 정확성 우선, EOS |

### LSO 개념
```
Partition Offsets:
0  1  2  3  4  5  6  7  8  9  10 (High Watermark)
                     ↑
                     LSO (Last Stable Offset)
                     
Offset 6-9: 진행 중 트랜잭션
Offset 10+: 아직 복제 중

read_committed Consumer:
→ Offset 0-5까지만 읽을 수 있음
→ Offset 6-9 트랜잭션 완료 대기
→ 트랜잭션 커밋 시 LSO → 10으로 이동
```

## 5. Kafka Streams의 EOS

### 설정
```properties
processing.guarantee=exactly_once_v2  # Kafka 2.5+
# 또는
processing.guarantee=exactly_once  # 레거시 (Kafka 0.11+)
```

### 작동 원리
Kafka Streams는 Consume-Process-Produce 패턴에서 원자성 보장:

```
1. Consumer가 메시지 읽기 (read_committed)
2. 메시지 처리 (상태 저장소 업데이트)
3. 트랜잭션 시작
4. 처리 결과 출력 토픽에 produce
5. 입력 오프셋 __consumer_offsets에 커밋
6. 상태 저장소 변경사항 changelog 토픽에 produce
7. 트랜잭션 커밋 (원자적 커밋)
```

### 원자성 보장
- 모든 작업이 단일 트랜잭션 내에서 실행:
  - 출력 메시지
  - 오프셋 커밋
  - 상태 저장소 changelog
- 실패 시 모두 롤백 → 재처리 시 정확히 같은 상태에서 시작

### exactly_once vs exactly_once_v2
| 버전 | Kafka 버전 | 개선사항 |
|------|-----------|---------|
| exactly_once | 0.11+ | 초기 구현 |
| exactly_once_v2 | 2.5+ | - 트랜잭션 펜싱 개선<br>- 성능 향상<br>- Consumer Group 재조정 시 더 빠른 복구 |

### 성능 오버헤드
- **레이턴시**: 트랜잭션 조정으로 인한 추가 Round-trip
- **처리량**: 일반적으로 10-20% 감소 (벤치마크에 따라 다름)
- **메모리**: 트랜잭션 버퍼 추가 사용
- **Trade-off**: 데이터 정확성 중요 시 감수할 만한 오버헤드

### 제한사항
- Kafka Streams 내부에서만 EOS 보장
- 외부 시스템 (DB, REST API) 호출 시 EOS 깨짐
- 해결책: Outbox Pattern, Two-Phase Commit 등 별도 전략 필요

## 6. 성능 오버헤드와 Trade-off

### 레이턴시 영향
```
설정별 평균 레이턴시 (추정):
- acks=0: ~1-2ms
- acks=1: ~5-10ms
- acks=all (idempotent): ~10-20ms
- acks=all + transaction: ~20-50ms
```

**트랜잭션 추가 오버헤드**:
- PID 등록: 초기 1회 (수 ms)
- Epoch 체크포인트: 트랜잭션당 추가 RTT
- Commit/Abort: 모든 파티션에 마커 기록 (수십 ms)

### 처리량 영향
| 설정 | 상대 처리량 | 비고 |
|------|------------|------|
| acks=0 | 100% (기준) | 최대 처리량 |
| acks=1 | ~80-90% | 중간 |
| acks=all (idempotent) | ~70-80% | 경미한 감소 |
| acks=all + transaction | ~50-70% | 조정 오버헤드 |

**실제 벤치마크 (일반적 경향)**:
- Idempotent Producer: ~5-10% 처리량 감소
- Transactional Producer: ~20-30% 처리량 감소
- Kafka Streams EOS: ~10-20% 처리량 감소

### Trade-off 분석

**언제 Exactly-Once를 사용해야 하나?**

✅ **사용 권장**:
- 금융 거래, 결제 시스템
- 정확한 집계/통계 필요 (예: 광고 클릭 수)
- 중복이 비즈니스 로직을 깨뜨리는 경우
- Kafka Streams 복잡한 상태 처리

❌ **불필요한 경우**:
- 메트릭/로그 수집 (일부 손실/중복 OK)
- 멱등성 있는 소비자 (Consumer가 중복 처리 가능)
- 극한의 처리량 필요 (레이턴시보다 처리량)
- 간단한 ETL (At-least-once + 멱등성 소비자로 충분)

### 최적화 전략

**1. Batching 활용**:
```properties
# 트랜잭션 내 더 많은 메시지 배치
batch.size=32768  # 32KB
linger.ms=20
```

**2. 트랜잭션 크기 조정**:
```java
// 나쁜 예: 메시지마다 트랜잭션
for (record : records) {
    producer.beginTransaction();
    producer.send(record);
    producer.commitTransaction();  // 오버헤드 큼!
}

// 좋은 예: 배치로 트랜잭션
producer.beginTransaction();
for (record : records) {
    producer.send(record);
}
producer.commitTransaction();
```

**3. 파티션 수 최소화**:
- 트랜잭션당 파티션 수 증가 = 조정 복잡도 증가
- 필요한 만큼만 파티션 사용

**4. Transaction Timeout 조정**:
```properties
# 긴 처리 시간 필요 시
transaction.timeout.ms=1800000  # 30분
# 주의: 너무 길면 좀비 트랜잭션 지연 증가
```

## 7. 실제 구현 예시

### Producer - Transactional 설정
```java
Properties props = new Properties();
props.put("bootstrap.servers", "localhost:9092");
props.put("transactional.id", "unique-txn-id-123");
props.put("enable.idempotence", "true");  // 자동이지만 명시
props.put("acks", "all");

KafkaProducer<String, String> producer = new KafkaProducer<>(props);

try {
    producer.initTransactions();
    
    producer.beginTransaction();
    
    producer.send(new ProducerRecord<>("output-topic", key, value));
    
    // Consumer용 오프셋 커밋
    Map<TopicPartition, OffsetAndMetadata> offsets = ...;
    producer.sendOffsetsToTransaction(offsets, "consumer-group-id");
    
    producer.commitTransaction();
} catch (ProducerFencedException | OutOfOrderSequenceException | AuthorizationException e) {
    // Fatal errors - 종료
    producer.close();
} catch (KafkaException e) {
    // 재시도 가능 - 롤백
    producer.abortTransaction();
}
```

### Consumer - read_committed 설정
```java
Properties props = new Properties();
props.put("bootstrap.servers", "localhost:9092");
props.put("group.id", "consumer-group-id");
props.put("isolation.level", "read_committed");
props.put("enable.auto.commit", "false");

KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
consumer.subscribe(Arrays.asList("input-topic"));

while (true) {
    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
    
    for (ConsumerRecord<String, String> record : records) {
        // 처리 로직
        process(record);
    }
    
    // 수동 커밋 (트랜잭션 외부 - Consumer만 사용 시)
    // Producer와 함께 사용 시 sendOffsetsToTransaction 사용
    consumer.commitSync();
}
```

### Kafka Streams - EOS 설정
```java
Properties props = new Properties();
props.put(StreamsConfig.APPLICATION_ID_CONFIG, "streams-app");
props.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
props.put(StreamsConfig.PROCESSING_GUARANTEE_CONFIG, StreamsConfig.EXACTLY_ONCE_V2);

StreamsBuilder builder = new StreamsBuilder();
KStream<String, String> source = builder.stream("input-topic");

source
    .mapValues(value -> process(value))
    .to("output-topic");

KafkaStreams streams = new KafkaStreams(builder.build(), props);
streams.start();
```

## 8. 핵심 요약

### Idempotent Producer
- PID + Sequence Number로 중복 제거
- 단일 세션 내 파티션별 정확히 한 번 보장
- 경미한 오버헤드 (~5-10%)
- Kafka 3.0+ 기본 활성화

### Transactional Producer
- Transaction Coordinator 사용
- 여러 파티션에 원자적 쓰기
- Producer Epoch로 좀비 펜싱
- 오프셋 커밋 포함 가능 (Consume-Process-Produce)
- 중간 오버헤드 (~20-30%)

### Consumer Isolation Level
- `read_uncommitted`: 빠르지만 dirty read 가능
- `read_committed`: LSO까지만 읽기, EOS 필수
- 레이턴시 Trade-off

### Kafka Streams EOS
- `processing.guarantee=exactly_once_v2` 설정
- 상태 저장소 + 오프셋 + 출력 원자적 커밋
- 외부 시스템 포함 시 보장 안 됨

### 성능 Trade-off
- At-most-once: 빠르지만 손실 가능
- At-least-once: 균형 잡힘, 중복 가능
- Exactly-once: 느리지만 정확, 금융/집계에 필수

## 참고 자료

### 공식 문서
- [Kafka Design: Delivery Semantics](https://docs.confluent.io/kafka/design/delivery-semantics.html)
- [KIP-98: Exactly Once Delivery and Transactional Messaging](https://cwiki.apache.org/confluence/display/KAFKA/KIP-98+-+Exactly+Once+Delivery+and+Transactional+Messaging)
- [Kafka Streams Core Concepts](https://kafka.apache.org/41/streams/core-concepts/)

### 블로그/튜토리얼
- [Confluent: Exactly-Once Semantics Are Possible](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)
- [Strimzi: Kafka Transactions](https://strimzi.io/blog/2023/05/03/kafka-transactions/)
- [WarpStream: Kafka Transactions Explained Twice](https://www.warpstream.com/blog/kafka-transactions-explained-twice)
- [HelloFresh Engineering: Demystifying Kafka EOS](https://engineering.hellofresh.com/demystifying-kafka-exactly-once-semantics-eos-390ae1c32bba)
- [Baeldung: Kafka Message Ordering](https://www.baeldung.com/kafka-message-ordering)

### 성능/벤치마크
- [Strimzi: Producer Tuning](https://strimzi.io/blog/2020/10/15/producer-tuning/)
- [AutoMQ: Kafka Latency Optimization](https://github.com/AutoMQ/automq/wiki/Kafka-Latency:-Optimization-&-Benchmark-&-Best-Practices)
- [Confluent: Kafka Performance Testing](https://www.confluent.io/learn/kafka-performance-testing/)

---

*다음 단계: 초안 작성*
