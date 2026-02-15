# Kafka 해체분석기 #7 리서치 노트
# Log Compaction - 로그는 어떻게 정리되나

**작성일**: 2026-02-15
**작성자**: 서브에이전트 (kafka-compaction)

---

## 1. Log Retention vs Log Compaction

### 1.1 근본적인 차이

**Log Retention (cleanup.policy=delete)**:
- **시간/크기 기반 삭제**: `retention.ms`(기본 7일), `retention.bytes`로 제어
- **Segment 단위**: 전체 세그먼트를 통째로 삭제
- **데이터 유형**: 시계열 데이터, 이벤트 로그 (과거 데이터가 중요하지 않은 경우)
- **공간 관리**: 시간이 지나면 무조건 삭제 → 예측 가능한 디스크 사용량

**Log Compaction (cleanup.policy=compact)**:
- **Key 기반 중복 제거**: 각 Key의 최신 값만 유지
- **Record 단위**: 개별 메시지 수준 처리
- **데이터 유형**: 상태 데이터, Key-Value 스토어 (최신 상태가 중요한 경우)
- **공간 관리**: 유니크 Key 수에 비례 → 무한정 증가 가능

### 1.2 Hybrid 모드 (cleanup.policy=compact,delete)

```
동작 순서:
1. 먼저 Compaction 수행 (Key당 최신 값만 남김)
2. 그 다음 Retention 정책 적용 (오래된 Segment 삭제)

사용 사례:
- CDC (Change Data Capture)에서 최근 N일간의 최신 상태만 유지
- 감사 로그: 최신 상태 + 시간 제한
```

---

## 2. Compaction의 동작 원리

### 2.1 Cleaner Thread 아키텍처

**LogCleaner 구조** (Scala 코드 분석):
```scala
// LogCleaner.scala
class LogCleaner(config: CleanerConfig, 
                 logDirs: Seq[File],
                 logs: Pool[TopicAndPartition, Log],
                 time: Time) {
  
  // Cleaner thread pool (기본 1개)
  private val cleaners = (0 until config.numThreads).map(
    new CleanerThread(_)
  )
  
  // 공유 I/O throttler (기본 1.5 MB/s)
  private val throttler = new Throttler(
    desiredRatePerSec = config.maxIoBytesPerSecond,
    checkIntervalMs = 300
  )
}
```

**Thread 동작 흐름**:
1. `LogCleanerManager`가 "가장 더러운" 로그 선택
   - Dirty Ratio = (Dirty Bytes) / (Total Bytes)
   - `min.cleanable.dirty.ratio` (기본 0.5, 즉 50% 이상) 넘으면 정리 대상
2. 선택된 로그 Compaction 수행
3. 통계 기록 및 다음 로그 처리

### 2.2 Compaction 알고리즘 (단계별)

**Phase 1: Offset Map 구축**
```
목적: Key → 최신 Offset 매핑 테이블 생성
메모리: log.cleaner.dedupe.buffer.size (기본 64MB)

동작:
1. Dirty Section (아직 정리 안 된 부분) 스캔
2. 각 Key의 가장 높은 Offset 기록
3. 해시맵 or SkimpyOffsetMap 사용

예시:
Offset 100: {key: "user:1", value: "Alice"}
Offset 105: {key: "user:2", value: "Bob"}
Offset 110: {key: "user:1", value: "Alice Updated"}

→ OffsetMap: {"user:1" → 110, "user:2" → 105}
```

**Phase 2: Clean Section 재작성**
```
목적: Clean Section (이미 정리된 부분)에서 중복 제거

동작:
1. Clean Section을 순차적으로 읽기
2. 각 Record의 Key를 OffsetMap에서 조회
3. 만약 더 최신 Offset이 있으면 → Skip (버림)
4. 최신이면 → 새 Segment에 기록
5. 원본과 새 Segment 스왑

메모리/I/O:
- Read Buffer: log.cleaner.io.buffer.size (기본 512KB)
- Write Buffer: 동일
- Throttling: 공유 throttler로 속도 제한
```

**결과**:
```
Before Compaction:
[100: user:1→Alice] [105: user:2→Bob] [110: user:1→Alice2] [115: user:3→Carol]

After Compaction:
[105: user:2→Bob] [110: user:1→Alice2] [115: user:3→Carol]
→ Offset 100의 user:1은 110에 더 최신 값이 있으므로 제거
```

### 2.3 보호 메커니즘

**Active Segment 보호**:
- 현재 쓰이는 Segment는 절대 Compaction 대상 안 됨
- Producer가 쓰는 중인 데이터 손실 방지

**min.compaction.lag.ms** (기본 30초):
- 최근 기록된 메시지는 일정 시간 보호
- "Head-of-log" 변경사항이 너무 빨리 사라지는 것 방지
- Consumer가 최신 변경을 놓치지 않도록 보장

**min.cleanable.dirty.ratio** (기본 0.5):
- 로그의 절반 이상이 중복이어야 정리 시작
- 너무 자주 정리하면 I/O 낭비
- 낮추면 (예: 0.1) 더 공격적으로 정리 (저장 공간 절약, CPU 사용 증가)

---

## 3. Tombstone 메시지 (삭제 마커)

### 3.1 개념 및 필요성

**Tombstone이란**:
```java
// Producer 코드
ProducerRecord<String, String> tombstone = 
    new ProducerRecord<>("users", "user:123", null);
    //                                        ↑ null payload

producer.send(tombstone);
```

**왜 필요한가?**:
- Compaction은 "최신 값 유지"가 원칙
- 삭제를 표현하려면 "null 값"이라는 특수 메시지 필요
- 단순히 안 보내면 → 이전 값이 계속 남음

### 3.2 Two-Phase Deletion

**Phase 1: Tombstone 유지 (Grace Period)**
```
설정: delete.retention.ms (기본 86,400,000ms = 24시간)

동작:
1. Tombstone 발행 → Topic에 기록
2. Compaction 수행 시 Tombstone도 "최신 값"으로 유지
3. 오래된 값들은 제거되지만 Tombstone은 남음
4. Consumer가 "user:123 삭제됨"을 인식할 시간 확보
```

**Phase 2: Tombstone 제거**
```
조건: delete.retention.ms 경과 후 다음 Compaction 시

동작:
1. Log Cleaner가 Tombstone의 timestamp 확인
2. 24시간 이상 지났으면 Tombstone 자체도 제거
3. 완전히 삭제 완료

결과:
- 과거부터 읽는 Consumer: Tombstone 발견 → 삭제 처리
- 너무 늦게 읽는 Consumer: 해당 Key 자체가 없음
```

### 3.3 주의사항

**진짜 null이어야 함**:
```java
// ❌ 잘못된 예 (문자열 "null")
producer.send(new ProducerRecord<>("topic", "key", "null"));

// ✅ 올바른 예 (진짜 null)
producer.send(new ProducerRecord<>("topic", "key", null));
```

**Transaction과의 상호작용**:
- Transactional Producer의 경우 abort된 Tombstone은 무시
- `CleanedTransactionMetadata`가 commit/abort 추적

---

## 4. Compaction Thread와 성능 영향

### 4.1 Thread 설정 및 리소스

**주요 설정**:
```properties
# Broker 설정 (server.properties)
log.cleaner.enable=true                      # Cleaner 활성화
log.cleaner.threads=2                        # Thread 개수 (기본 1)
log.cleaner.io.max.bytes.per.second=1572864  # I/O throttle (1.5MB/s)
log.cleaner.dedupe.buffer.size=134217728     # 128MB per thread
log.cleaner.io.buffer.size=524288            # 512KB read/write buffer

# Topic 설정
cleanup.policy=compact
min.cleanable.dirty.ratio=0.5
segment.bytes=104857600                      # 100MB segments
min.compaction.lag.ms=30000                  # 30초
```

**메모리 계산**:
```
Per Thread 메모리:
= dedupe.buffer.size + (2 × io.buffer.size)
= 128MB + (2 × 512KB)
≈ 129MB

2개 Thread → ~258MB
10개 Thread → ~1.3GB

⚠️ 주의: Thread당 2GB 넘으면 ByteBuffer overflow 가능
```

### 4.2 성능 영향 분석

**CPU 부하**:
```
높은 부하 상황:
1. Offset Map 구축: 모든 Dirty Record 스캔 + 해싱
2. Key 비교: Clean Section 순회하며 Map lookup
3. Segment 재작성: 압축, 직렬화

측정 예시 (로그):
[kafka-log-cleaner-thread-0]: Log cleaner thread 0 cleaned log user-events-0 
  (dirty section = [100000, 200000])
  45.6 MB of log processed in 3.2 seconds (14.25 MB/sec)
  Indexed 120000 records, deleted 35000 records
  Max buffer utilization: 87.3%
```

**I/O 부하**:
```
Read I/O:
- Dirty Section 전체 읽기
- Clean Section 스캔

Write I/O:
- 새 Segment 작성

Throttling:
- 공유 Throttler로 전체 Thread 제어
- Producer/Consumer 영향 최소화
```

**영향 최소화 전략**:
1. **Off-peak 정리**: `log.retention.check.interval.ms`로 주기 조정
2. **Segment 크기 조정**: 작으면 → 자주 정리 (오버헤드 ↑), 크면 → 덜 정리 (저장 공간 ↑)
3. **Dirty Ratio 조정**: 높이면 → 덜 정리 (I/O 절약), 낮추면 → 자주 정리 (공간 절약)
4. **Thread 수 증가**: 많은 Compact Topic이 있다면 병렬 처리

### 4.3 모니터링 메트릭

**JMX Metrics**:
```
kafka.log:type=LogCleanerManager,name=max-dirty-percent
  → 가장 더러운 로그의 Dirty Ratio

kafka.log:type=LogCleanerStats,name=MaxBufferUtilizationPct
  → Offset Map 버퍼 사용률

kafka.log:type=LogCleaner,name=cleaner-recopy-percent
  → 재작성된 비율 (낮을수록 효율적)

kafka.log:type=LogCleaner,name=max-clean-time-secs
  → 가장 오래 걸린 Compaction 시간
```

---

## 5. 사용 사례

### 5.1 CDC (Change Data Capture)

**시나리오**: MySQL 데이터베이스 변경 스트림

```sql
-- MySQL users 테이블
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(100),
  email VARCHAR(100)
);

-- 변경 발생
INSERT INTO users VALUES (1, 'Alice', 'alice@example.com');
UPDATE users SET email='alice@newdomain.com' WHERE id=1;
UPDATE users SET name='Alice Smith' WHERE id=1;
DELETE FROM users WHERE id=1;
```

**Kafka Topic (compact)**:
```
Topic: mysql.users (cleanup.policy=compact)

Offset 100: {key: "1", value: {name: "Alice", email: "alice@example.com"}}
Offset 105: {key: "1", value: {name: "Alice", email: "alice@newdomain.com"}}
Offset 110: {key: "1", value: {name: "Alice Smith", email: "alice@newdomain.com"}}
Offset 115: {key: "1", value: null}  ← Tombstone

Compaction 후:
Offset 115: {key: "1", value: null}  ← 최신 값(삭제)만 남음
```

**장점**:
- 전체 DB 스냅샷 없이 현재 상태 복원 가능
- Consumer는 earliest부터 읽어서 최신 상태 구축
- 저장 공간 = 현재 테이블 크기에 비례 (히스토리 무관)

### 5.2 KTable (Kafka Streams)

**KStream vs KTable**:
```java
// KStream: 이벤트 스트림 (모든 변경)
KStream<String, String> stream = builder.stream("user-actions");
stream.foreach((key, value) -> {
  // 모든 action 하나씩 처리
});

// KTable: 상태 스냅샷 (최신 값만)
KTable<String, String> table = builder.table("user-profiles");
table.toStream().foreach((key, value) -> {
  // 각 user의 최신 profile만 처리
});
```

**Changelog Topic**:
```
KTable의 내부 Changelog: cleanup.policy=compact 자동 설정

예시:
// Code
KTable<String, Long> wordCounts = stream
  .groupByKey()
  .count();  // Internal changelog: wordCounts-STATE-STORE-0000000001-changelog

Changelog Topic 내용:
Offset 1: {key: "hello", value: 1}
Offset 2: {key: "world", value: 1}
Offset 3: {key: "hello", value: 2}  ← 최신

Compaction 후 → {hello: 2, world: 1} 만 남음

장점: Streams 앱 재시작 시 전체 히스토리 재처리 불필요
```

### 5.3 상태 저장 (User Profile, Configuration)

**사용자 프로필 관리**:
```
Topic: user-profiles (compact)

이벤트:
Offset 1000: {key: "user:alice", value: {age: 25, city: "Seoul"}}
Offset 1050: {key: "user:bob", value: {age: 30, city: "Busan"}}
Offset 1100: {key: "user:alice", value: {age: 26, city: "Seoul"}}
                                          ↑ 생일 지나서 나이 증가

Compaction 후:
{
  "user:alice" → {age: 26, city: "Seoul"},
  "user:bob"   → {age: 30, city: "Busan"}
}

Consumer 시작 시:
- auto.offset.reset=earliest 설정
- Topic 처음부터 읽기 → 모든 user의 최신 profile 복원
- 메모리 또는 로컬 DB에 적재
```

**설정 관리 (Feature Flags)**:
```
Topic: feature-flags (compact)

Offset 500: {key: "new-ui", value: "enabled"}
Offset 505: {key: "beta-feature", value: "disabled"}
Offset 510: {key: "new-ui", value: "disabled"}  ← 롤백

애플리케이션:
1. 시작 시 feature-flags Topic 읽기
2. 최신 flag 상태 로드
3. Consumer 계속 구독 → 실시간 flag 업데이트
```

### 5.4 __consumer_offsets (내부 Topic)

**Kafka 자체가 사용**:
```
Topic: __consumer_offsets (cleanup.policy=compact)

Key: {group: "my-app", topic: "orders", partition: 0}
Value: {offset: 12345, metadata: "...", timestamp: ...}

동작:
1. Consumer가 commit → __consumer_offsets에 기록
2. 같은 group+topic+partition 조합은 최신 offset만 필요
3. Compaction으로 이전 commit은 삭제

결과: 
- Consumer group당 partition당 1개 record만 유지
- 수백만 consumer여도 공간 효율적
```

---

## 6. cleanup.policy 설정 비교

### 6.1 delete (기본값)

```properties
cleanup.policy=delete
retention.ms=604800000       # 7일
retention.bytes=-1           # 무제한
segment.bytes=1073741824     # 1GB
log.retention.check.interval.ms=300000  # 5분마다 체크
```

**동작**:
```
Timeline:
Day 0  ──> Day 7 ──> Day 14
[Seg 1] [Seg 2] [Seg 3] [Seg 4]
         ↓ 7일 경과
      [삭제]   유지    유지    유지

특징:
- Segment 단위 삭제 (Segment 내 모든 메시지 동시 삭제)
- retention.ms 기준은 "Segment의 가장 최신 메시지 timestamp"
- 예측 가능한 디스크 사용량
```

**적합한 경우**:
- 로그, 메트릭, 이벤트 스트림
- 과거 데이터가 불필요
- 순서만 중요 (중복 상관없음)

### 6.2 compact

```properties
cleanup.policy=compact
min.cleanable.dirty.ratio=0.5
segment.bytes=104857600           # 100MB (작을수록 자주 정리)
min.compaction.lag.ms=0           # 즉시 정리 가능
max.compaction.lag.ms=-1          # 무제한
delete.retention.ms=86400000      # Tombstone 보관 시간
```

**동작**:
```
Before Compaction (Dirty Ratio 50% 도달):
[k1:v1][k2:v2][k1:v3][k3:v4][k2:v5]
  ↓
After Compaction:
[k1:v3][k3:v4][k2:v5]  ← 각 Key의 최신 값만

특징:
- Record 단위 중복 제거
- Key 없는 메시지는 보관 (null key)
- 디스크 사용량 = f(unique keys)
```

**적합한 경우**:
- CDC, KTable, User Profile
- 최신 상태만 중요
- Key 카디널리티가 제한적 (수백만~수십억)

### 6.3 compact,delete (Hybrid)

```properties
cleanup.policy=compact,delete
min.cleanable.dirty.ratio=0.5
retention.ms=2592000000           # 30일
delete.retention.ms=86400000      # 1일
```

**동작**:
```
Step 1 (Compaction):
[Day 0 records...] [Day 15 records...] [Day 30 records...]
          ↓ Key 기반 중복 제거
[Day 0 latest keys] [Day 15 latest keys] [Day 30 latest keys]

Step 2 (Deletion):
[Day 0 latest keys] [Day 15 latest keys] [Day 30 latest keys]
   ↓ 30일 경과
 [삭제됨]             유지              유지

결과: 최근 30일간의 최신 상태만 유지
```

**적합한 경우**:
- CDC with TTL (예: GDPR 준수)
- 감사 로그 (최신 + 시간 제한)
- 무한 증가 방지하면서 최신 상태 유지

### 6.4 설정 비교표

| 설정 | delete | compact | compact,delete |
|------|--------|---------|----------------|
| **삭제 기준** | 시간/크기 | Key 중복 | 둘 다 |
| **공간 예측** | 쉬움 (시간 비례) | 어려움 (Key 수 비례) | 중간 |
| **CPU/I/O** | 낮음 | 높음 (Compaction) | 높음 |
| **데이터 보장** | 시간 내 전체 히스토리 | 최신 상태 영구 | 최신 상태 + 시간 제한 |
| **Tombstone** | 불필요 | 필수 | 필수 |
| **Use Case** | 로그, 메트릭 | CDC, KTable | CDC with TTL |

---

## 7. 실전 설정 예시

### 7.1 CDC Topic (Debezium 등)

```properties
# Topic: mysql.inventory.customers
cleanup.policy=compact,delete
retention.ms=2592000000              # 30일
min.cleanable.dirty.ratio=0.1        # 공격적 정리 (10%)
segment.bytes=52428800               # 50MB (자주 정리)
min.compaction.lag.ms=60000          # 1분 (최신 변경 보호)
delete.retention.ms=86400000         # 1일 (Tombstone 보관)

# 이유:
# - 최신 DB 상태를 Topic에서 재구성 가능
# - 30일 이후 오래된 상태는 삭제 (GDPR)
# - 자주 업데이트되는 테이블이면 10% dirty ratio로 공간 절약
```

### 7.2 User Profile Topic

```properties
# Topic: user-profiles
cleanup.policy=compact
min.cleanable.dirty.ratio=0.5        # 기본값 (50%)
segment.bytes=104857600              # 100MB
min.compaction.lag.ms=0              # 즉시 정리 가능
max.compaction.lag.ms=604800000      # 7일 이내 반드시 정리
delete.retention.ms=86400000         # Tombstone 1일

# 이유:
# - 영구 보존 (사용자 탈퇴 시 Tombstone)
# - 업데이트 빈도 낮음 → 50% dirty ratio 충분
# - max.compaction.lag.ms로 너무 오래 중복 남지 않도록
```

### 7.3 Kafka Streams Changelog

```properties
# Streams가 자동 생성하는 Topic
cleanup.policy=compact
min.cleanable.dirty.ratio=0.1        # 빠른 정리
segment.bytes=52428800               # 50MB
min.compaction.lag.ms=0
segment.ms=86400000                  # 1일마다 새 Segment
delete.retention.ms=3600000          # Tombstone 1시간

# 이유:
# - State Store 복원 시 빠른 로딩
# - 자주 업데이트 → 낮은 dirty ratio
# - Tombstone은 짧게 (Consumer가 Streams 자신뿐)
```

---

## 8. 코드 분석 포인트

### 8.1 LogCleaner.scala 핵심 구조

```scala
// kafka/log/LogCleaner.scala
class LogCleaner(config: CleanerConfig, ...) {
  private val cleaners = (0 until config.numThreads).map(
    new CleanerThread(_)
  )
  
  private class CleanerThread(id: Int) extends ShutdownableThread {
    private val cleaner = new Cleaner(
      id = id,
      offsetMap = new SkimpyOffsetMap(...),
      ioBufferSize = config.ioBufferSize,
      maxIoBufferSize = config.maxMessageSize,
      dupBufferLoadFactor = config.hashAlgorithm,
      throttler = throttler,
      time = time,
      checkDone = checkDone
    )
    
    override def doWork(): Unit = {
      cleanOrSleep()
    }
    
    private def cleanOrSleep(): Unit = {
      val cleaned = manager.grabFilthiestCompactedLog(time) match {
        case None => false
        case Some(cleanable) =>
          clean(cleanable)
          true
      }
      if (!cleaned) backOffWaitLatch.await(config.backOffMs, TimeUnit.MILLISECONDS)
    }
  }
}
```

### 8.2 Offset Map (SkimpyOffsetMap)

```scala
// 메모리 효율적인 Key → Offset 매핑
class SkimpyOffsetMap(val memory: Int, hashAlgorithm: String = "MD5") {
  private val bytes = ByteBuffer.allocate(memory)
  private val slots = memory / bytesPerEntry
  
  def put(key: ByteBuffer, offset: Long): Unit = {
    val hash = hash(key)
    val slot = (hash & Int.MaxValue) % slots
    // Collision handling (linear probing)
    // Store: [hash(8B)] [offset(8B)] per entry
  }
  
  def get(key: ByteBuffer): Long = {
    // Lookup by hash
  }
}
```

### 8.3 Compaction 통계 로깅

```scala
// Cleaner.scala
private def recordStats(...): Unit = {
  info(f"Log cleaner thread ${cleaner.id} cleaned log $logName " +
       f"(dirty section = [$startOffset, $endOffset])\n" +
       f"  ${stats.bytesRead / (1024.0 * 1024.0)}%.1f MB of log processed " +
       f"in ${stats.elapsedSecs}%.1f seconds " +
       f"(${stats.mbPerSec}%.1f MB/sec)\n" +
       f"  Indexed ${stats.mapMessagesRead}%,d records " +
       f"with ${stats.bytesRead}%,d bytes\n" +
       f"  Buffer utilization: ${stats.bufferUtilization}%.1f%%\n" +
       f"  ${stats.messagesWritten}%,d messages re-written " +
       f"(${stats.messagesRead - stats.messagesWritten}%,d were duplicates)")
}
```

---

## 9. 다이어그램 아이디어

### 9.1 Compaction Before/After

```
Before Compaction (Dirty Section):
┌────────────────────────────────────────────────┐
│ Clean Section    │    Dirty Section            │
│ (이미 정리됨)    │    (정리 필요)              │
├──────────────────┼─────────────────────────────┤
│ k1:v1 k2:v2      │ k1:v3 k3:v4 k2:v5 k1:v6     │
│ Offset 0-99      │ Offset 100-199              │
└──────────────────┴─────────────────────────────┘
         ↓ Compaction (OffsetMap: k1→199, k2→105, k3→104)
         
After Compaction:
┌────────────────────────────────────────────────┐
│          All Clean Now                         │
├────────────────────────────────────────────────┤
│ k2:v2 k3:v4 k2:v5 k1:v6                        │
│ (k1:v1, k1:v3 제거됨 - k1의 최신은 v6)         │
└────────────────────────────────────────────────┘
```

### 9.2 Tombstone Lifecycle

```
Timeline:
T=0      T=1      T=2      T=24h    T=25h
│        │        │        │        │
INSERT   UPDATE   DELETE   Compact  Compact
k1:v1    k1:v2    k1:null  k1:null  [완전삭제]
                  ↑        ↑        ↑
                  Tombstone Tombstone Tombstone
                  발행      유지      제거
                           (Consumer가
                            읽을 시간)
```

### 9.3 Cleanup Policy 비교

```
delete:
[─────Segment 1─────][─────Segment 2─────][─Segment 3─]
   7일 경과             4일 경과            1일 경과
   [완전 삭제]          [유지]              [유지]

compact:
[k1:v1,k2:v2,k1:v3,k3:v4] → [k1:v3,k2:v2,k3:v4]
 중복 제거 후 최신만

compact,delete:
[k1:v3,k2:v2,k3:v4]
    ↓ retention.ms 경과
 [Segment 삭제]
```

---

## 10. 참고 자료

1. **Kafka 공식 문서**: https://kafka.apache.org/documentation/#compaction
2. **Confluent 문서**: https://docs.confluent.io/kafka/design/log_compaction.html
3. **LogCleaner 소스**: https://github.com/apache/kafka/blob/trunk/core/src/main/scala/kafka/log/LogCleaner.scala
4. **관련 블로그**:
   - "Kafka Log Compaction Explained" (dev.to)
   - "How Does Kafka Log Compaction Work" (Redpanda)
   - "Kafka as a Key-Value Store" (WarpStream)

---

## 11. 스토리텔링 포인트

### 11.1 "Retention의 한계"
- 시간 기반 삭제는 "상태"를 관리할 수 없다
- 사용자가 탈퇴해도 7일간 데이터가 남는 문제
- "최신 상태만 필요한데 왜 과거를 보관하나?"

### 11.2 "Log의 두 얼굴"
- Append-only log의 철학과 충돌?
- 아니다! "논리적으로는 append-only, 물리적으로는 정리"
- Offset은 절대 변하지 않음 (불변성 유지)
- 단지 중복이 사라질 뿐

### 11.3 "Database WAL의 재발견"
- MySQL binlog도 compaction 비슷한 개념
- Replication lag 줄이기 위해 중복 제거
- Kafka는 이를 분산 시스템 수준으로 확장

### 11.4 "Key 설계의 중요성"
- Compaction의 효율성은 Key 설계에 달림
- 잘못된 Key (예: timestamp 포함) → Compaction 무용지물
- 올바른 Key (예: user ID) → 공간 절약

---

## 결론

Log Compaction은 Kafka를 "단순 메시징 시스템"에서 "분산 Key-Value 저장소"로 진화시킨 핵심 기능이다. 

**핵심 통찰**:
1. **Key 기반 중복 제거**: 시간이 아닌 "상태"를 기준으로 정리
2. **Tombstone**: 삭제도 "이벤트"로 표현 (불변성 유지)
3. **백그라운드 처리**: Producer/Consumer에 영향 최소화
4. **유연한 정책**: delete, compact, 둘 다 → 다양한 use case 지원

CDC, KTable, User Profile 등 "현재 상태"가 중요한 모든 시스템에 필수적인 기능이다.
