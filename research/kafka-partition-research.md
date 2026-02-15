# Kafka Partition 리서치 노트

## 1. LinkedIn의 규모 문제와 단일 로그의 한계

### 배경: LinkedIn의 데이터 폭발 (2010년)
- **규모**: 2010년 7월 프로덕션 투입, 2011년 일일 10억 메시지 → 이후 200억 메시지/일
- **데이터 유형**: 
  - 사용자 활동 데이터 (페이지뷰, 검색, 프로필 조회, 초대 등)
  - 시스템 메트릭, 보안 이벤트
  - 실시간 처리 + 오프라인 배치 처리 모두 필요

### 기존 솔루션의 실패
1. **전통적 로그 수집기**: 
   - 단일 노드 설계로 스케일 불가
   - Hadoop/Oracle로의 동기화만 지원 (실시간 처리 X)
   
2. **메시징 시스템 (JMS, RabbitMQ, ActiveMQ)**:
   - 1,000배 데이터 증가에 대응 못함
   - 단일 브로커 병목
   - Reader/Writer 커플링 → 느린 컨슈머가 전체 시스템 성능 저하

### 단일 로그 문제의 본질
- **Fan-out 요구사항**: 하나의 데이터를 수십~수백 개의 시스템에 동시 전달
- **실시간 제약**: 몇 시간이 아닌 몇 초 내 데이터 전달
- **디커플링**: Writer와 Reader의 속도 차이를 버퍼로 흡수
- **수평 확장 불가능**: 단일 로그는 단일 노드의 디스크/네트워크 한계

---

## 2. Partition 개념의 탄생 시점

### 초기 설계 (2010)
- **창시자**: Jay Kreps, Neha Narkhede, Jun Rao (LinkedIn)
- **개발 기간**: 약 1년 (2009-2010)
- **프로덕션 투입**: 2010년 7월
- **오픈소스**: 2011년 초 Apache 인큐베이터 프로젝트로 공개

### 핵심 설계 철학: "Distributed Commit Log"
```
전통적 메시징    Kafka 설계
┌───────┐       ┌─────────────┐
│ Queue │       │Topic (논리) │
└───────┘       └──────┬──────┘
                       │
    VS          ┌──────┴──────┐
           Partition 0   Partition 1   Partition 2
           ┌─────┐      ┌─────┐      ┌─────┐
           │ Log │      │ Log │      │ Log │
           └─────┘      └─────┘      └─────┘
            (물리)       (물리)       (물리)
```

- **Topic**: 논리적 카테고리 (예: "user-activity")
- **Partition**: 물리적으로 독립된 순차 로그 파일들
- **왜 처음부터 파티션?**: LinkedIn의 요구사항이 이미 수평 확장 필수였기 때문
  - 단일 머신으로는 수백 GB/일 처리 불가
  - 병렬 처리를 위한 컨슈머 그룹 설계

---

## 3. Partition Key와 해싱 전략

### 기본 파티셔닝 로직 (DefaultPartitioner)

```java
// Apache Kafka Utils.murmur2 구현
public static int partition(byte[] key, int numPartitions) {
    if (key == null) {
        // Key 없으면 Round-robin 또는 Random
        return ThreadLocalRandom.current().nextInt(numPartitions);
    }
    // Murmur2 해시 → 양수 변환 → 모듈로 연산
    return (murmur2(key) & 0x7fffffff) % numPartitions;
}
```

### Murmur2 해시 알고리즘
- **선택 이유**:
  - 비암호화 해시 → 빠른 속도
  - 균일한 분포 (collision 최소화)
  - 32비트 고정 길이 출력
- **시드**: `0x9747b28c`
- **상수**: `m=0x5bd1e995`, `r=24`

### 크로스 클라이언트 일관성
| 클라이언트 | 구현 | 비고 |
|-----------|------|------|
| Java (공식) | `Utils.murmur2` | 표준 구현 |
| kafka-python | Pure Python port | Java와 동일 결과 보장 |
| KafkaJS (Node) | Murmur2 port | 상호 운용성 확보 |
| Go 클라이언트 | Ported Murmur2 | 동일 |

### 파티셔닝 전략 비교
```
┌──────────────┬─────────────────┬──────────────┬─────────────┐
│ 전략         │ 사용 사례       │ 장점         │ 단점        │
├──────────────┼─────────────────┼──────────────┼─────────────┤
│ Key-based    │ 사용자별 순서   │ 순서 보장    │ Hot key 위험│
│ (Murmur2)    │ 보장 필요       │              │             │
├──────────────┼─────────────────┼──────────────┼─────────────┤
│ Round-robin  │ 높은 처리량,    │ 균등 분산    │ 순서 X      │
│ (null key)   │ 순서 불필요     │ Hot 방지     │             │
├──────────────┼─────────────────┼──────────────┼─────────────┤
│ Custom       │ 지역별 샤딩,    │ 세밀한 제어  │ 개발 복잡도 │
│ Partitioner  │ 복잡한 로직     │              │             │
└──────────────┴─────────────────┴──────────────┴─────────────┘
```

---

## 4. Consumer Group과 파티션 할당

### Consumer Group 프로토콜

```
Consumer Group "analytics"
├─ Consumer A: [Partition 0, 1]
├─ Consumer B: [Partition 2, 3]
└─ Consumer C: [Partition 4, 5]

동시에...

Consumer Group "monitoring"
├─ Consumer X: [Partition 0, 1, 2]
└─ Consumer Y: [Partition 3, 4, 5]
```

**핵심 원칙**: 
- 하나의 파티션은 그룹 내 **오직 하나의 컨슈머**에게만 할당
- 서로 다른 그룹은 **동일 파티션을 독립적으로** 소비 가능

### 할당 전략 (Assignment Strategy)

#### 1. RangeAssignor (기본값)
```
Topic: events (6 partitions)
Consumers: [A, B, C] (알파벳 순 정렬)

할당:
Consumer A → P0, P1  (6/3 = 2개)
Consumer B → P2, P3
Consumer C → P4, P5

⚠️ 문제: 여러 토픽 구독 시 첫 컨슈머에 부하 집중
```

#### 2. RoundRobinAssignor
```
모든 파티션을 순차적으로 라운드로빈 할당
→ 토픽 경계 무시, 균등 분배 우선

장점: 여러 토픽에서도 균등 분배
단점: 관련 파티션이 흩어질 수 있음
```

#### 3. StickyAssignor (Kafka 0.11+)
```
목표: Rebalancing 시 파티션 이동 최소화
→ 기존 할당 최대한 유지하면서 균형 조정
```

### 할당 과정 (Group Coordinator Protocol)
```
1. JoinGroup 요청
   Consumer → Coordinator: "나 그룹 참여할게"
   
2. Leader 선출
   Coordinator → 첫 컨슈머: "너가 리더야"
   
3. Assignment 계산
   Leader: 전략 적용해서 파티션 배정
   
4. SyncGroup
   Leader → Coordinator → All Consumers: 배정 결과 전달
   
5. 소비 시작
   각 컨슈머가 할당받은 파티션 처리
```

---

## 5. Rebalancing 문제와 해결책

### Stop-the-World 문제 (전통적 Eager Rebalancing)

```
Rebalance 발생 (컨슈머 추가/제거/실패)
     ↓
모든 컨슈머가 파티션 해제 (revoke all)
     ↓
전체 소비 중단 ⏸️ (수십 초~수 분)
     ↓
새로운 할당 계산
     ↓
파티션 재할당
     ↓
소비 재개 ▶️
```

**문제점**:
- Consumer 한 대 추가했을 뿐인데 전체 그룹이 멈춤
- 대규모 그룹에서 수 분간 지연 발생
- 백로그 누적 → 지연 확대

### Rebalancing 트리거
1. 컨슈머 추가/제거
2. Heartbeat 타임아웃 (`session.timeout.ms`)
3. `max.poll.interval.ms` 초과 (처리가 너무 느림)
4. Topic/Partition 변경
5. 유휴 컨슈머 감지

### 해결책: Incremental Cooperative Rebalancing (Kafka 2.4+)

```
전통적 방식 (Eager)          협력적 방식 (Cooperative)
┌─────────────────┐          ┌─────────────────┐
│ 전체 중단       │          │ 일부만 revoke   │
│ ⏸️⏸️⏸️⏸️⏸️       │   VS    │ ▶️▶️⏸️▶️▶️       │
│ 103초 소요      │          │ 5초 소요 (20배) │
└─────────────────┘          └─────────────────┘
```

**작동 방식**:
```java
// CooperativeStickyAssignor 설정
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor

// 단계적 Rebalancing
1. 영향받는 파티션만 revoke
2. 나머지 파티션은 계속 처리
3. 여러 라운드에 걸쳐 점진적으로 재배정
```

**성능 개선**:
- 벤치마크: 103초 → 5초 (20배 향상)
- 전체 중단 없이 부하 재분배
- 상태 저장소/버퍼 플러시 최소화

### Rebalancing 최소화 전략

```yaml
# 타임아웃 튜닝
session.timeout.ms: 30000      # 30초 (기본 10초)
heartbeat.interval.ms: 10000   # 10초 (session의 1/3)
max.poll.interval.ms: 300000   # 5분 (처리 시간 충분히 확보)

# Static Membership (Kafka 2.3+)
group.instance.id: "consumer-01"  # 고정 ID
  → 재시작 시 Rebalancing 발생 안 함
  → 동일 파티션 자동 재할당
```

---

## 6. 파티션 수 결정 가이드라인

### 계산 공식

```
필요 파티션 수 = max(
    목표 처리량 / 파티션당 처리량,
    최대 컨슈머 수
)
```

**예시**:
- 목표: 1 GB/s 처리
- 파티션당 처리량: 50 MB/s (단일 컨슈머 기준)
- 계산: 1000 MB/s ÷ 50 MB/s = **20 파티션**

### 브로커 용량 제약

| 제약 조건 | 가이드라인 | 이유 |
|----------|-----------|------|
| **기본 권장** | 100 파티션/브로커 | 병렬성과 효율성 균형 |
| **Low latency** | ≤ 100 × 브로커수 × RF | 파일 핸들, 메모리 압박 |
| **Hard limit** | ≤ 4,000 파티션/브로커 | 안정성 한계 |
| **클러스터 전체** | 수만 개 수준 | Zookeeper/Controller 부하 |

**리소스 소비**:
```
파티션당 오버헤드:
- Producer: 수십 KB 버퍼
- Consumer: 수십 KB 버퍼
- Broker: 파일 핸들, 세그먼트, 메모리

예: 1,000 파티션 × 50KB = ~50MB 메모리
```

### 실전 가이드라인

#### 1. 초기 설정
```
- 보수적 시작: 3~10 파티션
- 트래픽 모니터링
- 필요 시 증가 (감소는 불가능!)
```

#### 2. 증가 시점 판단
```bash
# Lag 모니터링
kafka-consumer-groups --describe --group my-group

# CPU/디스크 사용률
# Throughput 메트릭

→ 병목 발견 시 파티션 추가
```

#### 3. 과잉 파티셔닝 전략
```
현재 필요량의 2~3배로 생성
  → 향후 확장 대비
  ⚠️ 단, 리소스 낭비와 trade-off
```

#### 4. 데이터 스큐 대응
```python
# Hot Key 감지
def analyze_partition_load():
    for partition in partitions:
        if partition.bytes_in > avg * 3:
            print(f"Hot partition detected: {partition}")
            # → Key 재설계 또는 Custom Partitioner
```

### 파티션 수 증가의 영향

```
증가 시:
✅ 병렬 처리 증가
✅ 컨슈머 스케일 아웃 가능
❌ Rebalancing 발생 (일시적 중단)
❌ 브로커 리소스 증가
❌ 엔드-투-엔드 레이턴시 증가 가능

감소는 불가능:
→ 토픽 재생성 + 데이터 마이그레이션 필요
```

---

## 참고 자료

### 공식 문서
- Apache Kafka Design Documentation: https://kafka.apache.org/design
- Confluent Partitioning Guide: https://www.confluent.io/blog/how-choose-number-topics-partitions-kafka-cluster/

### 초기 설계 논문/발표
- Jay Kreps Hadoop Summit 2011: "Kafka: A Distributed Messaging System for Log Processing"
- LinkedIn Engineering Blog: Creating Kafka

### 커뮤니티 리소스
- GitHub apache/kafka (초기 커밋 분석)
- Kafka Improvement Proposals (KIP-429: Incremental Cooperative Rebalancing)
- Perplexity 검색 결과 (2026-02-15)

---

## 다음 단계

- [ ] 코드 예제 추가 (Java/Python DefaultPartitioner 직접 분석)
- [ ] GitHub 초기 커밋에서 파티션 관련 코드 직접 확인
- [ ] Rebalancing 성능 벤치마크 그래프 추가
- [ ] 파티션 수 계산기 도구 개발
