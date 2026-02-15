# Kafka Producer 내부 리서치 노트

## 주제: Producer 내부 - Batching, Acks, 그리고 순서 보장

---

## 1. Producer 내부 아키텍처

### 전체 흐름
```
Producer API
    ↓
Serializer (Key, Value)
    ↓
Partitioner (파티션 선택)
    ↓
RecordAccumulator (메모리 배치 버퍼)
    ↓
Sender Thread (비동기 전송)
    ↓
NetworkClient (네트워크 I/O)
    ↓
Broker
```

### 핵심 컴포넌트

**RecordAccumulator**:
- 파티션별로 배치를 메모리에 쌓음
- `buffer.memory` (기본 32MB) 내에서 관리
- Deque<ProducerBatch> 구조로 파티션별 큐 유지
- batch.size 또는 linger.ms 조건 충족 시 배치 완성

**Sender Thread**:
- 별도 스레드로 동작 (메인 스레드와 분리)
- RecordAccumulator에서 준비된 배치를 가져와 전송
- NetworkClient를 통해 실제 네트워크 I/O 수행
- 응답 처리 및 재시도 관리

**NetworkClient**:
- Selector 기반 non-blocking I/O
- Connection pooling 관리
- In-flight requests 추적
- 네트워크 타임아웃, 에러 핸들링

### 주요 특징
- **비동기 전송**: send() 호출은 즉시 리턴, Sender Thread가 백그라운드에서 처리
- **배치 최적화**: 동일 파티션으로 가는 메시지를 모아서 한 번에 전송
- **메모리 관리**: buffer.memory 초과 시 send() 블로킹 (max.block.ms)

---

## 2. Batching 전략

### batch.size
- **정의**: 배치의 최대 크기 (bytes)
- **기본값**: 16KB (16384 bytes)
- **동작**: 배치가 이 크기에 도달하면 즉시 전송
- **영향**:
  - 너무 작으면: 빈번한 네트워크 요청 → 처리량 저하
  - 너무 크면: 메모리 낭비 (메시지가 적을 때 큰 버퍼 할당)

### linger.ms
- **정의**: 배치를 보내기 전 대기 시간
- **기본값**: 5ms (Kafka 4.0부터, 이전엔 0)
- **동작**: batch.size에 도달 안 해도 linger.ms 경과 시 전송
- **영향**:
  - 0으로 설정: 즉시 전송 (최소 레이턴시)
  - 높게 설정 (50-100ms): 더 많은 메시지 배치 → 압축률↑, 처리량↑, 레이턴시↑

### 처리량 비교 (추정)
```
batch.size=16KB, linger.ms=0:      빠른 응답, 낮은 처리량
batch.size=16KB, linger.ms=10:     균형
batch.size=32KB, linger.ms=50:     높은 처리량, 약간의 레이턴시
batch.size=64KB, linger.ms=100:    최대 처리량, 높은 레이턴시
```

### Best Practice
- **실시간 알림**: batch.size=16KB, linger.ms=0-5
- **로그 수집**: batch.size=32-64KB, linger.ms=20-50
- **분석 파이프라인**: batch.size=64-128KB, linger.ms=100

---

## 3. 압축 (compression.type)

### 옵션 비교

| Codec | 압축률 | 압축 속도 | 압축 해제 속도 | CPU 사용 | 처리량 | 사용 사례 |
|-------|--------|----------|---------------|---------|--------|----------|
| **none** | 0% | N/A | N/A | 최소 | 기준 | 작은 메시지, 이미 압축된 데이터 |
| **gzip** | 최고 (~70%) | 느림 (530 MB/s) | 중간 (1700 MB/s) | 높음 | 낮음 (830 msg/s) | 네트워크 병목, 스토리지 절약 우선 |
| **snappy** | 중간 | 빠름 (670 MB/s) | 매우 빠름 (2250 MB/s) | 중간 | 높음 (~3400 msg/s) | 균형 잡힌 선택 |
| **lz4** | 중간 (snappy와 유사) | **매우 빠름** | **매우 빠름** | 낮음 | **최고** (~3400 msg/s) | 실시간 처리, 낮은 레이턴시 |
| **zstd** | 높음 (조절 가능) | 빠름 (710 MB/s) | 빠름 (1750 MB/s) | 중간 | 중간 (2180 msg/s) | 유연한 압축률/속도 조절 |

### 실제 데이터 (벤치마크 참고)
- LZ4와 Snappy: gzip 대비 228% 높은 처리량
- Gzip: 최고 압축률, 하지만 처리량 1/4 수준
- Zstd: Intel 하드웨어에서 35% 처리량 향상

### 압축의 영향
- **네트워크**: 최대 97% 데이터 크기 감소
- **브로커 부하**: 압축된 채로 저장, Consumer까지 전달
- **CPU**: Producer와 Consumer 양쪽에서 CPU 사용 증가
- **배치 효율**: 큰 배치일수록 압축률 향상

### 권장 설정
- **기본 권장**: lz4 (빠르고 효율적)
- **네트워크 비용 중요**: gzip (클라우드 환경)
- **극한 처리량**: lz4 또는 snappy
- **스토리지 비용 중요**: zstd 또는 gzip

---

## 4. acks와 retries의 관계

### acks 옵션

**acks=0 (Fire-and-Forget)**:
- Producer가 응답을 기다리지 않음
- **retries 무의미**: 실패 여부조차 모름
- 최고 처리량, 최악의 안정성

**acks=1 (Leader Only)**:
- Leader가 로그에 쓴 후 즉시 응답
- Follower 복제 전 Leader 장애 시 손실 가능
- **retries 제한적**: Leader 장애는 복구 불가

**acks=all (All In-Sync Replicas)**:
- 모든 ISR이 복제 완료 후 응답
- **retries와 궁합**: 일시적 장애 시 재시도 성공 가능
- 최고 내구성, 낮은 처리량

### retries 관련 설정
```properties
retries=Integer.MAX_VALUE         # 기본값 (무제한)
delivery.timeout.ms=120000        # 2분 (전체 재시도 시간 제한)
retry.backoff.ms=100              # 첫 재시도 대기
retry.backoff.max.ms=1000         # 최대 재시도 간격
```

### 문제 시나리오
```
acks=1 + retries=무제한:
1. Leader ACK → Producer 성공으로 간주
2. Leader 즉시 장애 (복제 전)
3. Follower 승격 (해당 메시지 없음)
4. → 메시지 손실 (재시도해도 소용없음)

acks=all + retries=무제한:
1. 일시적 네트워크 장애 → 타임아웃
2. 재시도 → 성공
3. → 메시지 보장
```

### Best Practice
```properties
acks=all
retries=Integer.MAX_VALUE  # 기본값
enable.idempotence=true    # 중복 방지
```

---

## 5. max.in.flight.requests.per.connection과 순서 보장

### 정의
- 응답을 받기 전에 보낼 수 있는 최대 요청 수
- 기본값: 5

### 순서 보장 문제

**max.in.flight.requests.per.connection=5 (기본값)**:
```
Timeline:
T0: Batch 1 전송 (offset 0-9)
T1: Batch 2 전송 (offset 10-19)
T2: Batch 1 실패 (네트워크 에러)
T3: Batch 2 성공 (offset 10-19 기록됨)
T4: Batch 1 재시도 (offset 0-9 기록됨)

결과: Broker에 [10-19] → [0-9] 순서로 저장 (순서 깨짐!)
```

### 해결 방법

**방법 1: max.in.flight.requests.per.connection=1**
```properties
max.in.flight.requests.per.connection=1
```
- **장점**: 완벽한 순서 보장
- **단점**: 처리량 급격히 감소 (16배 차이 발생 가능)

**방법 2: Idempotent Producer (권장)**
```properties
enable.idempotence=true
max.in.flight.requests.per.connection=5  # 기본값 유지
```
- Producer ID + Sequence Number로 순서 보장
- 처리량 유지하면서 순서 보장

### 성능 영향 (추정)
```
max.in.flight=1:          500 msg/s (기준)
max.in.flight=5:        8,000 msg/s (16배)
idempotence=true:       7,500 msg/s (약간의 오버헤드)
```

---

## 6. Idempotent Producer (enable.idempotence)

### 핵심 메커니즘

**Producer ID (PID)**:
- Producer 시작 시 Broker로부터 고유 ID 할당
- Producer 세션 동안 유지 (재시작 시 새 ID)

**Sequence Number**:
- 각 (PID, Topic, Partition) 조합마다 0부터 시작
- 배치마다 monotonically increasing
- Broker가 마지막 sequence number 추적

```
Producer sends:
PID=12345, Partition=0, Seq=0 → [msg 1, 2, 3]
PID=12345, Partition=0, Seq=1 → [msg 4, 5, 6]
PID=12345, Partition=0, Seq=2 → [msg 7, 8, 9]

Broker expects:
Seq=0 → OK
Seq=1 → OK
Seq=1 again (retry) → Duplicate! Ignore
Seq=3 → OutOfOrderSequenceException! (Seq=2 expected)
```

### 자동 설정 변경
```properties
enable.idempotence=true
# 자동으로 다음 설정 적용:
acks=all                              # 강제
retries=Integer.MAX_VALUE             # 강제
max.in.flight.requests.per.connection=5  # 최대 5까지 허용
```

### 보장 범위
- ✅ **단일 Producer 세션 내** 정확히 한 번 전송
- ✅ **재시도로 인한 중복 제거**
- ✅ **순서 보장** (파티션별)
- ❌ **Producer 재시작 시 중복 가능** (새 PID 할당)
- ❌ **트랜잭션 간 일관성 X** (트랜잭션 필요 시 transactional.id 사용)

### 에러 처리
**Fatal Errors** (Producer 재생성 필요):
- `ProducerFencedException`: 다른 Producer가 같은 transactional.id 사용
- `InvalidProducerEpochException`: PID epoch 불일치
- `UnknownProducerIdException`: Broker가 PID 모름 (타임아웃 등)

**Retriable Errors**:
- 네트워크 타임아웃
- Leader 선출 중
- NotEnoughReplicas

### Best Practice
```properties
# Kafka 3.0+ 기본값 (권장 유지)
enable.idempotence=true
acks=all
min.insync.replicas=2
```

---

## 7. 실제 사고 사례 (리서치 중 발견)

### LinkedIn ZooKeeper 폭발 (2014)
- Consumer offset 관련이지만, Producer도 metadata 조회로 영향
- 교훈: Metadata 관리의 중요성

### 순서 보장 실패 사례
- max.in.flight.requests.per.connection > 1 + retries
- 금융 거래 시스템에서 "취소 → 결제" 순서가 "결제 → 취소"로 뒤바뀜
- 해결: enable.idempotence=true

### 배치 크기 과대 설정
- batch.size=1MB, linger.ms=1000
- 메모리 부족 (buffer.memory=32MB에 파티션 100개)
- send() 블로킹 → 타임아웃 폭증

---

## 8. 스타일링 아이디어

### 프롤로그 후보
- **Option 1**: LinkedIn/Uber의 실제 Producer 장애 사례
- **Option 2**: "메시지는 어떻게 브로커에 도달하는가?" 철학적 질문
- **Option 3**: batch.size=1바이트 vs 1MB의 극단적 비교

### 다이어그램 아이디어
```
[RecordAccumulator 구조]
Partition 0: [Batch 1 (ready)] [Batch 2 (filling...)]
Partition 1: [Batch 1 (ready)]
Partition 2: [Batch 1 (full, ready)]

↓ Sender Thread picks ready batches

NetworkClient → Broker
```

### 비유/은유
- RecordAccumulator = "출고 대기 창고"
- Batching = "택배 상자에 물건 모으기"
- linger.ms = "택배 기사가 기다려주는 시간"
- Idempotent Producer = "고유 송장 번호"

---

## 9. 참고 자료 정리

### 공식 문서
- [Kafka Producer Design](https://docs.confluent.io/kafka/design/producer-design.html)
- [Producer Configurations](https://docs.confluent.io/platform/current/installation/configuration/producer-configs.html)

### 기술 블로그
- [Architecture Weekly: How Kafka Producer Writes](https://www.architecture-weekly.com/p/how-a-kafka-like-producer-writes)
- [Confluent: Idempotent Producer](https://developer.confluent.io/patterns/event-processing/idempotent-writer/)
- [Baeldung: Kafka Message Ordering](https://www.baeldung.com/kafka-message-ordering)

### 벤치마크
- [Intel Kafka Optimization Guide](https://www.intel.com/content/www/us/en/developer/articles/guide/kafka-optimization-and-benchmarking-guide.html)
- [Superstream: Kafka Compression](https://www.superstream.ai/blog/kafka-compression)

---

## 10. 글 구성 초안

### 목차 (예상)
1. 프롤로그: [실제 사례]
2. Chapter 1: Producer의 이중 인격 - 동기 API, 비동기 실행
3. Chapter 2: RecordAccumulator - 출고 대기 창고
4. Chapter 3: Batching의 마법 - batch.size vs linger.ms
5. Chapter 4: 압축 전쟁 - gzip vs lz4 vs zstd
6. Chapter 5: acks - 믿음의 수준
7. Chapter 6: 순서의 비밀 - max.in.flight와 Idempotence
8. 에필로그: Producer의 철학

---

## 메모
- 기존 해체분석기 #4 (Consumer Offset) 스타일 참고
- 프롤로그는 실제 사고 사례로 시작
- 코드 블록과 ASCII 다이어그램 적극 활용
- 2800-3000자 목표
- Trade-off 명시적 분석 강조
- "왜 이렇게 설계했는가" 중심으로 서술
