# Kafka Tiered Storage 리서치 노트

## 주제
Kafka 해체분석기 #9: "Tiered Storage - 무한 보관의 비밀"

## 문제 상황

### 기존 스토리지의 한계
- Kafka는 모든 데이터를 로컬 디스크에 저장
- retention 기간이 길어질수록 스토리지 비용 폭증
- **3x 복제** + **2x over-provisioning** = 실제 데이터의 6배 비용
- 예: 50TB 데이터 → 304TB EBS 필요 → $24,300/월
- 브로커 장애 시 복구 시간이 데이터 양에 비례

### 실제 사용 패턴
- 대부분의 읽기는 **tail read** (최근 데이터)
- Page cache 활용 → 디스크 I/O 최소화
- 오래된 데이터 읽기는 backfill, 장애 복구 등 드문 케이스
- 현재는 ETL 파이프라인으로 HDFS/S3에 별도 복사

## KIP-405: Tiered Storage 설계

### 핵심 아이디어
**Two-Tier Architecture**
```
Local Tier (Hot)     Remote Tier (Cold)
- 최근 데이터         - 오래된 데이터
- Broker 디스크      - S3/HDFS/GCS
- 낮은 레이턴시      - 높은 레이턴시
- 짧은 retention    - 긴 retention
```

### 주요 컴포넌트

#### 1. RemoteLogManager (RLM)
- 각 브로커의 내부 컴포넌트
- Leader/Follower 파티션별 태스크 생성
- **Leader Task**: 로컬 세그먼트를 리모트로 복사
- **Follower Task**: 리모트 메타데이터 추적, 리모트에서 읽기

#### 2. RemoteStorageManager (RSM)
- 플러그인 가능한 인터페이스
- 주요 작업:
  - `copyLogSegment()`: 로컬 → 리모트 복사
  - `fetchLogSegment()`: 리모트 → 데이터 읽기
  - `deleteLogSegment()`: 리모트 삭제
- 구현체:
  - S3: `org.apache.kafka.tiered.storage.s3.S3RemoteStorageManager`
  - GCS: `GcsRemoteStorageManager`
  - Azure: `AzureBlobRemoteStorageManager`

#### 3. RemoteLogMetadataManager (RLMM)
- 리모트 세그먼트 메타데이터 관리
- 강한 일관성 보장
- 기본 구현: 내부 토픽 `__remote_log_metadata` 사용
- 메타데이터 캐싱으로 성능 최적화

### 오프셋 제약 조건
```
Rx  = Remote log start offset
Ry  = Remote log end offset
Lx  = Local log start offset
Ly  = Last stable offset (LSO)
Lz  = Local log end offset

Lz >= Ly >= Lx and Ly >= Ry >= Rx
```

### 데이터 이동 프로세스

1. **세그먼트 롤링**
   - Active 세그먼트가 롤링되면 Inactive 됨
   - 조건: `last offset < LSO`

2. **리모트 복사 (Leader만)**
   ```
   - 세그먼트 파일 (.log)
   - 오프셋 인덱스 (.index)
   - 타임스탬프 인덱스 (.timeindex)
   - 트랜잭션 인덱스 (.txnindex)
   - Leader epoch cache
   - Producer snapshot
   ```

3. **메타데이터 발행**
   - RemoteLogSegmentId (UUID) 생성
   - State: `COPY_SEGMENT_STARTED` → `COPY_SEGMENT_FINISHED`

4. **로컬 삭제**
   - `local.retention.ms` 경과 후 로컬 세그먼트 삭제
   - 리모트 세그먼트는 `retention.ms`까지 유지

## 주요 설정

### Broker 레벨
```properties
# Tiered Storage 활성화
remote.log.storage.system.enable=true

# RSM 구현체 지정
remote.log.storage.manager.class.name=org.apache.kafka.tiered.storage.s3.S3RemoteStorageManager

# RSM JAR 경로
remote.log.storage.manager.class.path=/path/to/kafka-tiered-storage-s3.jar

# RLMM 구현체 (기본값 사용 가능)
remote.log.metadata.manager.class.name=org.apache.kafka.server.log.remote.metadata.storage.TopicBasedRemoteLogMetadataManager

# 인덱스 캐시 크기
remote.log.index.file.cache.total.size.mb=1024

# RLM 태스크 인터벌
remote.log.manager.task.interval.ms=30000
```

### Topic 레벨
```properties
# Tiered Storage 활성화
remote.storage.enable=true

# 로컬 retention (예: 1시간)
local.retention.ms=3600000

# 전체 retention (예: 7일)
retention.ms=604800000
```

### S3 예제 (Aiven/MinIO)
```properties
rsm.config.minio.url=http://127.0.0.1:9000
rsm.config.minio.access.key=minioadmin
rsm.config.minio.secret.key=minioadmin
rsm.config.minio.bucket.name=kafka-tiered-storage
rsm.config.minio.auto.create.bucket=true
```

## Follower Replication 프로토콜

### 문제: Follower가 리모트 데이터를 어떻게 처리?
- Follower는 Leader의 **로컬 데이터만** 복제
- 리모트는 이미 S3에 있으므로 재복제 불필요
- 하지만 **Auxiliary State**(Leader epoch, Producer snapshot)는 구축 필요

### OFFSET_MOVED_TO_TIERED_STORAGE 에러
1. Follower가 오래된 오프셋 요청
2. Leader가 `OFFSET_MOVED_TO_TIERED_STORAGE` 에러 반환
3. Follower가 `ListOffset(timestamp=-4)` 요청
   - `-4` = `EARLIEST_LOCAL_TIMESTAMP` (Local log start offset)
4. Leader가 Earliest Local Offset (ELO) + Leader Epoch 반환
5. Follower가 **BuildingRemoteLogAux** 상태 진입
   - RLMM에서 리모트 세그먼트 메타데이터 조회
   - RSM에서 Leader epoch cache, Producer snapshot 다운로드
6. Auxiliary state 구축 완료 후 **Fetching** 상태로 전환

### Unclean Leader Election 시나리오
- 리모트 스토리지에도 로그 분기 가능
- Leader epoch로 올바른 세그먼트 식별
- 예: seg-0-3 (uuid1, LE-0) vs seg-0-3 (uuid2, LE-1)
- KIP-101, KIP-279의 기존 로직 그대로 적용

## 성능 고려사항

### Cold Read Latency
| 스토리지 타입 | 평균 레이턴시 | 처리량 |
|--------------|-------------|--------|
| Local (page cache) | ~5 ms | 3.2M records/s |
| Tiered (최적화) | ~19 ms | 로컬의 40% |
| Tiered (작은 세그먼트) | ~172 ms | 로컬의 5% |

**핵심 요소:**
- **세그먼트 크기**: 작을수록 느림 (더 많은 리모트 요청)
- **백엔드 스토리지**: S3 Standard vs MinIO vs NetApp ONTAP
- **네트워크 대역폭**: 40 Gbps 환경에서는 네트워크가 병목

### 실제 벤치마크
- **Strimzi 테스트**: Producer latency 1953-5002ms (p99: 6663ms)
- **MinIO**: 40 Gbps 네트워크 포화, 스토리지 병목 아님
- **NetApp ONTAP**: 31 GBps 집합 처리량 달성
- **PureStorage FlashBlade**: S3 대비 4배 빠른 읽기

### 비용 분석
| 시나리오 (50TB, 3x 복제) | 로컬 디스크 (EBS GP3) | S3 Tiered |
|-------------------------|---------------------|-----------|
| 원본 스토리지 비용 | $24,300/월 (304TB) | $2,926/월 (50TB) |
| 실효 비용/GB | $0.24 | $0.023 |
| 절감율 | - | **~90%** |

**추가 고려사항:**
- Cross-AZ 트래픽: $0.01-0.02/GB
- S3 API 호출 비용 (LIST, GET)
- 로컬에 5-10GB EBS만 유지 → $0.8/월

## Thread Pool 아키텍처

### RLM Thread Pool
- 전용 스레드 풀로 I/O 스레드와 분리
- 리모트 장애 시 로컬 작업에 영향 없음
- Exponential backoff으로 재시도
- 설정: `remote.log.manager.task.interval.ms`

### Remote Storage Fetcher Thread Pool
- Consumer fetch 요청 처리
- `RemoteFetchPurgatory`로 타임아웃 관리
- 실패 시 재시도, 최종 타임아웃까지 대기

## 제한사항 (KIP-405 GA)
- ❌ Compaction 지원 안 됨 (delete만 가능)
- ❌ JBOD 지원 안 됨
- ✅ Kafka 3.6.0+ (KIP-405)
- ✅ Confluent 7.5+ GA

## State Transitions
```
Remote Segment:
COPY_SEGMENT_STARTED → COPY_SEGMENT_FINISHED
DELETE_SEGMENT_STARTED → DELETE_SEGMENT_FINISHED

Partition:
DELETE_PARTITION_MARKED → DELETE_PARTITION_STARTED → DELETE_PARTITION_FINISHED
```

## 주요 인용

### KIP-405 Motivation
> "The total storage required on a cluster is proportional to the number of topics/partitions, the rate of messages, and most importantly the retention period."

### Two-Tier 철학
> "Tail reads leverage OS's page cache to serve the data instead of disk reads. Older data is typically read from the disk for backfill or failure recovery purposes and is infrequent."

### 비용 효율
> "This solution allows scaling storage independent of memory and CPUs in a Kafka cluster enabling Kafka to be a long-term storage solution."

## 코드 분석 포인트

### RemoteStorageManager 인터페이스 (예상)
```java
interface RemoteStorageManager {
    void copyLogSegment(RemoteLogSegmentMetadata metadata, 
                       LogSegmentData segmentData);
    
    InputStream fetchLogSegment(RemoteLogSegmentMetadata metadata, 
                                long startPosition, 
                                long endPosition);
    
    void deleteLogSegment(RemoteLogSegmentMetadata metadata);
}
```

### RemoteLogSegmentMetadata
```java
class RemoteLogSegmentMetadata {
    RemoteLogSegmentId remoteLogSegmentId; // UUID
    long startOffset;
    long endOffset;
    int brokerId;
    long maxTimestampMs;
    int segmentSizeInBytes;
    RemoteLogSegmentState state;
}
```

## 다이어그램 아이디어

1. **Two-Tier Architecture**
   - Local Tier (최근 1시간)
   - Remote Tier (나머지 6일 23시간)
   - Arrow: 자동 이동

2. **비용 비교**
   - 로컬 전용: 막대 그래프 높음
   - Tiered: 막대 그래프 낮음 (90% 절감)

3. **Follower Replication 프로토콜**
   - Leader/Follower 상호작용
   - OFFSET_MOVED_TO_TIERED_STORAGE
   - BuildingRemoteLogAux state

4. **Thread Pool 구조**
   - RLM Thread Pool
   - Remote Fetcher Thread Pool
   - 메인 I/O 스레드와 분리

## 참고 자료
- KIP-405: https://cwiki.apache.org/confluence/x/KJDQBQ
- Kafka 3.6+ 공식 문서
- Strimzi blog: Tiered Storage deep dive
- Instaclustr blog: Tiered Storage benchmarks
- mgoblin/minio-rsm: GitHub 구현체
- Aiven tiered-storage-for-apache-kafka
