# Kafka Consumer Offset 리서치 노트

## 1. Offset이란 무엇인가

### 정의
- **Offset**: 파티션 내에서 각 메시지의 순차적 위치를 나타내는 정수 (0부터 시작)
- **불변성**: 한 번 할당된 offset은 변경되지 않음 (파티션별 monotonic increasing)
- **용도**: Consumer가 "어디까지 읽었는지" 추적하는 북마크

### 파티션과 Offset의 관계

```
Topic: "user-events"
├─ Partition 0
│  ├─ offset 0: {"user": "alice", "action": "login"}
│  ├─ offset 1: {"user": "bob", "action": "click"}
│  ├─ offset 2: {"user": "alice", "action": "logout"}
│  └─ ... (계속 증가)
├─ Partition 1
│  ├─ offset 0: {"user": "charlie", "action": "login"}
│  ├─ offset 1: {"user": "dave", "action": "search"}
│  └─ ...
```

**핵심 특징**:
- Offset은 **파티션 단위**로 독립적 (Topic 전체가 아님)
- 각 파티션은 자신만의 offset 시퀀스 보유
- 파티션 0의 offset 5와 파티션 1의 offset 5는 완전히 다른 메시지

### Consumer Position vs Committed Offset

```
Partition Log:
[0] [1] [2] [3] [4] [5] [6] [7] [8] [9]
                 ↑           ↑
          committed(3)   current position(7)
```

**구분**:
- **Current Position**: Consumer가 다음에 읽을 offset (메모리에만 존재)
- **Committed Offset**: Kafka에 저장된 offset (재시작 시 이 위치부터 읽음)

**중요**: Current position과 committed offset 사이의 메시지들이 중복 처리 또는 손실 위험!

---

## 2. Offset 저장소의 진화

### 초기: ZooKeeper 저장 (Kafka 0.8 이전)

```
ZooKeeper 경로:
/consumers
  └── {consumer-group}
      ├── ids
      │   ├── {consumer-id-1}
      │   └── {consumer-id-2}
      └── offsets
          └── {topic}
              ├── {partition-0}: 12345
              ├── {partition-1}: 67890
              └── ...
```

**문제점**:
1. **성능 병목**: ZooKeeper는 높은 write 처리량에 최적화되지 않음
2. **확장성 한계**: Consumer가 많아질수록 ZooKeeper에 엄청난 write 발생
3. **외부 의존성**: Kafka와 ZooKeeper가 동기화되어야 함
4. **순서 보장 없음**: ZooKeeper는 순서 보장 메커니즘이 없어 offset 충돌 가능

**실제 사례**:
- 대규모 시스템에서 consumer 수천 개 → 초당 수만 건의 ZooKeeper write
- ZooKeeper 과부하로 전체 클러스터 불안정 발생 (LinkedIn 경험)

### 전환점: Kafka 0.9 (2015년 11월)

**KIP-13**: Offset 저장소를 Kafka 내부 토픽으로 이전

**마이그레이션 전략**:
```properties
# Consumer 설정
offsets.storage=kafka              # 새로운 방식
dual.commit.enabled=true           # 양쪽 모두에 commit
```

**Dual Commit 과정**:
```
1. Consumer가 offset commit 요청
2. ZooKeeper에 write
3. __consumer_offsets 토픽에도 write
4. 양쪽 모두 성공 시 ACK
```

**완전 전환 타임라인**:
- 0.9 (2015.11): `__consumer_offsets` 도입, dual commit 지원
- 0.10 (2016.05): Kafka 기본값으로 변경
- 0.11 (2017): ZooKeeper 저장 방식 deprecated
- 현재: ZooKeeper 저장 완전히 제거

### 현재: __consumer_offsets 토픽

#### 내부 구조

```
Topic: __consumer_offsets
├─ 파티션 수: 50 (기본값, offsets.topic.num.partitions)
├─ Replication Factor: 3 (기본값)
├─ Cleanup Policy: compact
└─ Segment Size: 104857600 (100MB)
```

**Key 구조**:
```
[group, topic, partition] → OffsetAndMetadata
예: ["analytics-group", "user-events", 0] → {offset: 12345, metadata: "..."}
```

**Value 구조 (OffsetAndMetadata)**:
```java
class OffsetAndMetadata {
    long offset;                  // 다음에 읽을 위치
    Optional<Integer> leaderEpoch; // Leader election epoch (정합성 체크)
    String metadata;              // 사용자 정의 메타데이터
    long commitTimestamp;         // Commit 시각
    long expireTimestamp;         // 만료 시각
}
```

#### 파티션 할당 로직

```java
// Consumer Group이 저장될 파티션 결정
int partition = abs(groupId.hashCode()) % numPartitions;
// 예: "analytics-group" → hash → partition 17
```

**중요**: 같은 Consumer Group의 모든 offset은 **하나의 파티션**에 집중!
- 장점: 해당 그룹의 offset은 순서 보장, 캐싱 효율적
- 단점: Hot partition 발생 가능 (그룹당 commit이 많으면)

#### Compaction 메커니즘

```
[Before Compaction]
Key: [group-A, topic-X, p0], Offset: 100, timestamp: T1
Key: [group-A, topic-X, p0], Offset: 150, timestamp: T2
Key: [group-A, topic-X, p0], Offset: 200, timestamp: T3
Key: [group-B, topic-Y, p1], Offset: 50,  timestamp: T4

[After Compaction]
Key: [group-A, topic-X, p0], Offset: 200, timestamp: T3  ← 최신만 유지
Key: [group-B, topic-Y, p1], Offset: 50,  timestamp: T4
```

**Compaction 설정**:
```properties
# Broker 설정
log.cleaner.enable=true
log.cleanup.policy=compact
log.segment.bytes=104857600
min.cleanable.dirty.ratio=0.5  # 50% 이상 중복 시 compaction
```

**Offset 만료**:
```properties
offsets.retention.minutes=10080  # 7일 (기본값)
```

- Consumer Group이 **비활성** 상태(아무도 소비하지 않음)이고
- 마지막 commit 이후 7일 경과하면
- 해당 그룹의 offset 자동 삭제

#### Offset 조회 방법

```bash
# 1. kafka-consumer-groups 명령어 (권장)
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group my-group \
  --describe

# 출력:
# GROUP           TOPIC      PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# my-group        events     0          12345           12500           155

# 2. __consumer_offsets 토픽 직접 읽기
kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic __consumer_offsets \
  --formatter "kafka.coordinator.group.GroupMetadataManager\$OffsetsMessageFormatter" \
  --from-beginning

# 출력:
# [my-group,events,0]::OffsetAndMetadata(offset=12345, leaderEpoch=Optional[3], ...)
```

---

## 3. auto.offset.reset - 최초 시작 위치

### 개념

**트리거 조건**: Consumer가 **committed offset을 찾을 수 없을 때**
1. 새로운 Consumer Group (첫 실행)
2. Offset이 retention으로 삭제됨
3. Offset이 로그 범위를 벗어남 (너무 오래된 offset 참조)

**주의**: Committed offset이 존재하면 `auto.offset.reset`은 **무시됨**!

### 3가지 옵션

#### 1. earliest
```
Partition Log:
[0] [1] [2] [3] [4] [5] [6] [7] [8] [9]
 ↑
 여기부터 시작 (가장 오래된 메시지)
```

**사용 사례**:
- 데이터 재처리 (reprocessing)
- Event Sourcing (전체 이벤트 히스토리 필요)
- 백업/복구 시나리오
- 새 Consumer가 과거 데이터도 처리해야 할 때

**위험**:
- 수백만 건의 메시지를 갑자기 읽어버림 → Consumer 과부하
- 의도치 않은 중복 처리

#### 2. latest (기본값)
```
Partition Log:
[0] [1] [2] [3] [4] [5] [6] [7] [8] [9]
                                      ↑
                                      여기부터 (다음 새 메시지)
```

**사용 사례**:
- 실시간 처리만 필요 (과거 데이터 불필요)
- Monitoring, Alerting 시스템
- 새 Consumer 추가 시 과거 부하 방지

**위험**:
- Consumer 재시작 중 도착한 메시지 **영구 손실**!
- 예: Consumer 다운 → offset 5-10 메시지 도착 → 재시작 → offset 11부터 읽음 → 5-10 손실

**실제 사례**:
```python
# 잘못된 설정 예시
consumer = KafkaConsumer(
    'critical-transactions',
    group_id='payment-processor',
    auto_offset_reset='latest',  # ⚠️ 위험!
    enable_auto_commit=True
)

# 문제:
# 1. Consumer 재시작 중 결제 이벤트 도착
# 2. latest로 시작 → 해당 결제 처리 안 됨
# 3. 금전적 손실 발생!
```

#### 3. none
```properties
auto.offset.reset=none
```

**동작**: Offset을 찾을 수 없으면 `NoOffsetForPartitionException` 발생

**사용 사례**:
- 프로덕션 환경에서 **의도치 않은 데이터 손실/중복 방지**
- 명시적인 offset 관리 강제
- 장애 발생 시 수동 개입 필요

**Best Practice**:
```python
# 프로덕션 권장 설정
consumer = KafkaConsumer(
    'critical-events',
    auto_offset_reset='none',  # 예외 발생시켜 명시적 처리 강제
    enable_auto_commit=False,  # 수동 commit
)

try:
    for message in consumer:
        process(message)
        consumer.commit()
except NoOffsetForPartitionException as e:
    # 명시적으로 초기 offset 지정
    consumer.seek_to_beginning()
    # 또는 특정 offset으로 이동
    consumer.seek(partition, specific_offset)
```

### 의사결정 가이드

| 상황 | 권장 설정 | 이유 |
|------|----------|------|
| 실시간 알림 시스템 | `latest` | 과거 알림 재전송 불필요 |
| 금융 거래 처리 | `earliest` + Manual commit | 모든 거래 보장 필수 |
| 로그 분석 | `earliest` | 전체 로그 필요 |
| 테스트 환경 | `latest` | 빠른 피드백 |
| 프로덕션 (일반) | `none` | 명시적 제어 |

---

## 4. enable.auto.commit의 함정

### Auto Commit의 작동 원리

```properties
enable.auto.commit=true  # 기본값
auto.commit.interval.ms=5000  # 5초마다 자동 commit
```

**타임라인**:
```
T0: poll() → 메시지 [10-19] 가져옴
T1: 메시지 [10-14] 처리 중...
T5: Auto commit 발생 → offset 20 저장 (다음 읽을 위치)
T6: 메시지 [15-19] 처리 중...
T7: ❌ Consumer 크래시!
재시작: offset 20부터 읽음 → 메시지 [15-19] 영구 손실!
```

### At-Most-Once (최대 한 번) - 메시지 손실 가능

```
Commit 시점: 메시지를 읽은 직후 (처리 전)

Timeline:
1. poll() → offset 10 메시지 받음
2. commit() → offset 11 저장 ✅
3. process(message) 시작
4. ❌ Crash! → 메시지 손실
```

**코드 예시**:
```python
# At-Most-Once 패턴 (잘못된 예시)
for message in consumer:
    consumer.commit()  # 처리 전 commit!
    process(message)   # 여기서 실패하면 손실
```

**발생 시나리오**:
- Auto commit이 처리 완료 전 발생
- Consumer가 메시지를 읽고 commit 했지만 처리 중 실패

**적합한 사례**:
- 로그 수집 (일부 손실 허용)
- 메트릭 집계 (대략적 값 허용)

### At-Least-Once (최소 한 번) - 중복 가능

```
Commit 시점: 메시지 처리 완료 후

Timeline:
1. poll() → offset 10 메시지 받음
2. process(message) ✅
3. commit() 시도...
4. ❌ Crash! (commit 실패)
재시작:
5. offset 10부터 다시 읽음 → 중복 처리
```

**코드 예시**:
```python
# At-Least-Once 패턴 (일반적)
for message in consumer:
    process(message)   # 먼저 처리
    consumer.commit()  # 성공 후 commit
```

**발생 시나리오**:
- 처리는 완료했지만 commit 전 실패
- Network timeout으로 commit ACK 못 받음

**적합한 사례**:
- 멱등성(idempotent) 처리 가능한 작업
- 데이터베이스 UPSERT
- 중복 제거 로직이 있는 시스템

### Enable Auto Commit의 구체적 문제들

#### 문제 1: 처리 시간이 auto.commit.interval.ms보다 긴 경우

```python
# 설정
auto.commit.interval.ms=5000  # 5초
max.poll.interval.ms=300000   # 5분

# 시나리오
for message in consumer:
    process_heavy_task(message)  # 10초 소요
    # 5초마다 자동 commit 발생
    # → 처리 중인 메시지도 commit됨!
```

**결과**: 처리 완료 전에 offset이 commit되어 **메시지 손실** 위험

#### 문제 2: Rebalancing 중 중복

```
Consumer A:
1. poll() → messages [100-199]
2. 처리 중... (offset 120까지 처리)
3. Auto commit 예정 (T+5초)
4. Rebalancing 발생! ⚠️
   → Commit 안 됨

Consumer B (새로 할당받음):
5. offset 100부터 다시 처리
   → [100-120] 중복!
```

#### 문제 3: 배치 처리 실패

```python
# 배치로 DB 저장
messages = consumer.poll(timeout_ms=1000)  # 100개 메시지
for msg in messages:
    batch.add(msg)

db.bulk_insert(batch)  # ⚠️ 실패!
# 하지만 auto commit은 이미 발생 → 100개 손실
```

### Manual Commit 전략

#### 1. commitSync() - 동기 커밋

```python
consumer = KafkaConsumer(
    enable_auto_commit=False,
)

for message in consumer:
    try:
        process(message)
        consumer.commitSync()  # 블로킹, 확실한 commit
    except CommitFailedException:
        log.error("Commit failed, will retry on next message")
```

**장점**:
- 확실한 commit 보장
- 간단한 에러 처리

**단점**:
- 블로킹으로 인한 성능 저하
- 네트워크 지연 시 처리량 감소

**처리량 영향**:
```
Auto commit: 10,000 msg/sec
commitSync (매 메시지): 500 msg/sec  ← 20배 저하!
```

#### 2. commitAsync() - 비동기 커밋

```python
def on_commit(offsets, exception):
    if exception:
        log.error(f"Commit failed: {exception}")
    else:
        log.info(f"Committed: {offsets}")

for message in consumer:
    process(message)
    consumer.commitAsync(callback=on_commit)  # Non-blocking
```

**장점**:
- 높은 처리량 유지
- 네트워크 지연 영향 최소화

**단점**:
- Commit 실패를 알아도 재시도 어려움 (순서 보장 이슈)
- Rebalancing 시 중복 가능성 높음

#### 3. Best Practice: Hybrid 전략

```python
consumer = KafkaConsumer(enable_auto_commit=False)

try:
    for message in consumer:
        process(message)
        consumer.commitAsync()  # 일반적으로 비동기
except KeyboardInterrupt:
    pass
finally:
    consumer.commitSync()  # 종료 시에만 확실하게 동기 commit
    consumer.close()
```

**또 다른 전략: 배치 커밋**

```python
BATCH_SIZE = 100
batch = []

for message in consumer:
    batch.append(message)
    
    if len(batch) >= BATCH_SIZE:
        process_batch(batch)
        consumer.commitSync()  # 배치마다 commit
        batch = []
```

**처리량 비교**:
```
매 메시지 commitSync: 500 msg/sec
배치 (100개) commitSync: 8,000 msg/sec
commitAsync: 9,500 msg/sec
```

---

## 5. Consumer Lag 모니터링

### Lag의 정의

```
Consumer Lag = Log End Offset - Current Offset

예:
Partition 0:
├─ Log End Offset (LEO): 10,000  ← Producer가 쓴 마지막 위치
├─ Current Offset: 9,500         ← Consumer가 읽은 위치
└─ Lag: 500 messages             ← 처리해야 할 잔여 메시지
```

**의미**:
- Lag = 0: Consumer가 실시간으로 따라가는 중 ✅
- Lag > 0 && 안정적: 정상적인 지연 (초당 유입 < 처리)
- Lag 계속 증가: Consumer 병목 ⚠️

### kafka-consumer-groups CLI

```bash
# 기본 사용법
kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --group analytics-group \
  --describe

# 출력:
GROUP           TOPIC      PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
analytics-group events     0          9500            10000           500
analytics-group events     1          8200            8200            0
analytics-group events     2          7890            9000            1110
```

**주요 필드**:
- `CURRENT-OFFSET`: Consumer가 commit한 offset
- `LOG-END-OFFSET`: Partition의 최신 offset
- `LAG`: 차이 (처리 대기 중인 메시지 수)

**스크립트 예시**:
```bash
# Lag 합계 계산
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group my-group --describe | \
  awk '{sum+=$6} END {print "Total Lag:", sum}'

# Lag이 큰 파티션 찾기
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group my-group --describe | \
  awk '$6 > 1000 {print $0}'
```

### Burrow - LinkedIn의 Lag 모니터링 도구

**특징**:
- Threshold-free: Lag 절대값이 아닌 **트렌드** 기반 알림
- Sliding Window: 시간에 따른 Lag 변화 분석
- Multi-cluster 지원
- HTTP API 제공

**설치**:
```bash
# Docker로 실행
docker run -d -p 8000:8000 \
  -v /path/to/burrow.toml:/etc/burrow/burrow.toml \
  linkedin/burrow
```

**API 사용**:
```bash
# Consumer Group 상태 확인
curl http://localhost:8000/v3/kafka/local/consumer/my-group/status

# 응답:
{
  "status": "OK",  # OK | WARNING | ERROR | STOP
  "complete": 1.0,
  "partitions": [
    {
      "topic": "events",
      "partition": 0,
      "status": "OK",
      "lag": 500,
      "lag_last": 520
    }
  ],
  "maxlag": {
    "topic": "events",
    "partition": 2,
    "lag": 1110
  }
}
```

**상태 구분**:
- **OK**: Lag이 안정적 또는 감소 중
- **WARNING**: Lag이 증가 추세지만 아직 소비 중
- **ERROR**: Lag이 빠르게 증가하거나 소비 멈춤
- **STOP**: Consumer가 완전히 멈춤

**알림 설정**:
```toml
[notifier.email]
class-name="notifier.EmailNotifier"
interval=60
threshold-ok=OK
threshold-warn=WARNING
threshold-error=ERROR

[notifier.email.smtp]
server="smtp.gmail.com:587"
from="burrow@company.com"
to=["oncall@company.com"]
```

### Prometheus + Grafana 통합

#### JMX Exporter 설정

```yaml
# jmx_exporter.yml
rules:
- pattern: kafka.consumer<type=consumer-fetch-manager-metrics, client-id=(.*), topic=(.*), partition=(.*)><>records-lag
  name: kafka_consumer_records_lag
  labels:
    client_id: "$1"
    topic: "$2"
    partition: "$3"

- pattern: kafka.consumer<type=consumer-fetch-manager-metrics, client-id=(.*)><>records-lag-max
  name: kafka_consumer_records_lag_max
  labels:
    client_id: "$1"
```

#### Prometheus 쿼리

```promql
# 총 Lag (Consumer Group별)
sum by (consumergroup) (kafka_consumergroup_lag)

# Lag 증가율 (5분간)
rate(kafka_consumergroup_lag[5m])

# Lag이 5000 이상인 파티션
kafka_consumergroup_lag > 5000

# 평균 처리 시간
kafka_consumer_fetch_latency_avg
```

#### Grafana 대시보드

**패널 1: Lag Trend**
```
메트릭: kafka_consumergroup_lag
타입: Time series
색상: Lag > 1000 → Red
```

**패널 2: Consumer Throughput**
```
메트릭: rate(kafka_consumer_records_consumed_total[1m])
타입: Graph
단위: messages/sec
```

**패널 3: Lag Heatmap**
```
메트릭: kafka_consumergroup_lag
타입: Heatmap
X축: Time
Y축: Partition
Color: Lag 수치
```

### Lag 발생 원인과 해결

#### 원인 1: Consumer 처리 속도 < Producer 생산 속도

**진단**:
```bash
# Producer 처리량 확인
kafka-run-class kafka.tools.JmxTool \
  --object-name kafka.producer:type=producer-metrics,client-id=* \
  --attributes record-send-rate

# Consumer 처리량 확인
kafka-run-class kafka.tools.JmxTool \
  --object-name kafka.consumer:type=consumer-fetch-manager-metrics,client-id=* \
  --attributes records-consumed-rate
```

**해결**:
- Consumer 인스턴스 추가 (파티션 수 범위 내)
- 처리 로직 최적화 (DB 쿼리, API 호출 등)
- 파티션 수 증가 (기존 토픽은 불가, 새 토픽으로 마이그레이션)

#### 원인 2: Consumer 장애/재시작

**진단**:
```bash
# Rebalancing 로그 확인
grep "Rebalance" consumer.log

# Heartbeat 실패 확인
grep "session timeout" consumer.log
```

**해결**:
```properties
# Timeout 튜닝
session.timeout.ms=30000      # 30초 (기본 10초)
heartbeat.interval.ms=10000   # 10초
max.poll.interval.ms=600000   # 10분 (처리 시간 충분히)
```

#### 원인 3: 데이터베이스/외부 API 지연

**진단**:
```python
# 타이밍 측정
import time

start = time.time()
result = db.query(...)
log.info(f"DB query took {time.time() - start}s")
```

**해결**:
- 연결 풀 크기 증가
- 비동기 처리 도입
- 캐싱 레이어 추가
- 배치 처리로 전환

#### 원인 4: Hot Partition

**진단**:
```bash
# 파티션별 메시지 크기 확인
kafka-log-dirs \
  --bootstrap-server localhost:9092 \
  --describe --topic-list events

# 파티션별 Lag 비교
kafka-consumer-groups --describe --group my-group | \
  sort -k6 -n  # LAG 기준 정렬
```

**해결**:
- Partitioning 전략 재설계 (Custom Partitioner)
- Hot Key 분산 (Key에 Random suffix 추가)

---

## 6. 실전 시나리오별 권장 설정

### 시나리오 1: 금융 거래 처리 (무손실 필수)

```properties
# Consumer 설정
enable.auto.commit=false
auto.offset.reset=earliest
isolation.level=read_committed  # 트랜잭션 완료된 것만

# 수동 commit
max.poll.records=1  # 메시지 하나씩 처리
```

```python
for message in consumer:
    with db.transaction():
        process_payment(message)
        db.commit()
    consumer.commitSync()  # DB commit 후 offset commit
```

### 시나리오 2: 실시간 알림 (속도 우선, 일부 손실 허용)

```properties
enable.auto.commit=true
auto.commit.interval.ms=1000  # 1초마다
auto.offset.reset=latest
max.poll.records=500
```

### 시나리오 3: 로그 수집 (대용량, 중복 허용)

```properties
enable.auto.commit=false
auto.offset.reset=earliest
max.poll.records=10000  # 대량 배치
```

```python
BATCH_SIZE = 10000
batch = []

for message in consumer:
    batch.append(message)
    if len(batch) >= BATCH_SIZE:
        elasticsearch.bulk_insert(batch)
        consumer.commitSync()
        batch = []
```

### 시나리오 4: Stream Processing (Exactly-Once)

```properties
# Kafka Streams 자동 설정
enable.auto.commit=false
isolation.level=read_committed
processing.guarantee=exactly_once_v2
```

---

## 참고 자료

### 공식 문서
- Kafka Design - Consumers: https://kafka.apache.org/design#theconsumer
- Confluent Consumer Offset Guide: https://www.confluent.io/blog/guide-to-consumer-offsets/
- Apache Kafka 0.9 Documentation: https://kafka.apache.org/090/implementation/distribution/

### 오픈소스 도구
- Burrow (LinkedIn): https://github.com/linkedin/Burrow
- kafka-lag-exporter (Lightbend): https://github.com/lightbend/kafka-lag-exporter
- kafka_exporter (Prometheus): https://github.com/danielqsj/kafka_exporter

### 블로그/아티클
- Baeldung - Kafka Consumer Offset: https://www.baeldung.com/kafka-consumer-offset
- Architecture Weekly - How Kafka Knows What Was Read: https://www.architecture-weekly.com/p/how-does-kafka-know-what-was-the
- AutoMQ - Kafka Offsets Best Practices: https://www.automq.com/blog/kafka-offsets-best-practices

### 논문/발표
- Kafka 초기 논문 (2011): "Kafka: A Distributed Messaging System for Log Processing"
- KIP-98: Exactly Once Delivery and Transactional Messaging
- KIP-447: Producer scalability for exactly once semantics

---

## 다음 단계

- [ ] __consumer_offsets 내부 구조 코드 분석 (Scala 소스)
- [ ] Burrow 알고리즘 상세 분석 (Sliding Window 로직)
- [ ] Exactly-Once Semantics 심화 (Transactional Producer + Idempotent Consumer)
- [ ] 실제 프로덕션 Lag 모니터링 대시보드 구축 예제
- [ ] Consumer Rebalancing과 Offset의 상관관계 실험
