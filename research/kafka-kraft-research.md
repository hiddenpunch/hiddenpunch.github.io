# Kafka KRaft 리서치 노트

## 주제: "ZooKeeper에서 KRaft로 - 왜 ZooKeeper를 버렸나"

---

## 1. ZooKeeper의 역할

### 메타데이터 저장소
- **토픽 메타데이터**: 파티션 수, 레플리카 배치, 설정
- **Broker 등록**: 각 브로커의 ID, 호스트, 포트 정보
- **Controller 선출**: 클러스터당 1개의 Active Controller 선출
- **ACL/Quota**: 접근 제어 및 쿼터 정보

### Controller의 역할 (ZooKeeper 기반)
- 파티션 리더 선출
- 브로커 장애 감지 및 복구
- 토픽 생성/삭제 조율
- **모든 메타데이터를 ZooKeeper에서 읽어 메모리에 로드**

---

## 2. ZooKeeper의 한계

### 확장성 문제
- **파티션 제한**: ZooKeeper는 클러스터가 관리할 수 있는 파티션 수를 제한
  - Amazon MSK: ZooKeeper 모드 최대 30 브로커 vs KRaft 모드 60 브로커
- **메타데이터 병목**: 단일 Controller가 모든 ZooKeeper 읽기/쓰기를 중재
  - 파티션 수 증가 → ZooKeeper 부하 증가 → 성능 저하

### Controller Failover 지연
1. **현상**: Controller 장애 시 새 Controller 선출 후 전체 메타데이터를 ZooKeeper에서 가져옴
2. **문제**: 
   - 수만 개 파티션 환경에서 수십 초 소요
   - 그 동안 리더 선출 불가능 → 클러스터 멈춤
3. **전파 지연**: ZooKeeper 메시지가 모든 브로커에 전파되는 데 시간 걸림

### 운영 복잡도
- **이중 시스템 운영**: Kafka + ZooKeeper 앙상블 별도 관리
- **네트워크 레이턴시**: Kafka ↔ ZooKeeper 간 크로스 시스템 통신
- **ZooKeeper 전문성 필요**: 별도의 모니터링, 백업, 튜닝 요구

### 아키텍처 한계
- **외부 의존성**: Kafka가 ZooKeeper 상태에 종속
- **단일 리더 직렬화**: ZooKeeper의 모든 업데이트가 단일 리더를 거침 (이론상 50K ops/s 한계)
- **메모리 기반**: ZooKeeper는 메모리에 모든 데이터를 보관 → 스케일링 제약

---

## 3. KRaft (Kafka Raft) 등장 배경

### KIP-500 (2019년 제안)
- **목표**: "ZooKeeper 의존성 제거"
- **동기**:
  1. 단일 시스템으로 단순화
  2. 메타데이터 확장성 개선
  3. Controller Failover 고속화
  4. 운영 복잡도 감소

### 타임라인
- **2019**: KIP-500 제안
- **2020-2021**: KRaft 초기 프로토타입
- **Kafka 2.8 (2021)**: KRaft Early Access (프로덕션 비권장)
- **Kafka 3.3 (2022)**: KRaft Production Ready
- **Kafka 3.5 (2023)**: Combined Broker+Controller 모드 지원
- **Kafka 3.6+ (2024)**: Migration Tool 안정화
- **Kafka 4.0 (2025 예정)**: ZooKeeper 완전 제거, KRaft 기본값

---

## 4. KRaft Controller 구조

### Quorum Controller
- **Raft 합의 알고리즘** 기반 (Paxos 계열이 아닌 Raft)
- **투표자(Voters)**: 3-5개 Controller 노드가 Raft Quorum 형성
  - 예: `controller.quorum.voters=1@host1:9093,2@host2:9093,3@host3:9093`
- **리더 선출**: 과반수(⌊N/2⌋ + 1) 합의로 Active Controller 선출
  - 예: 3개 중 2개 필요

### Metadata Log (`__cluster_metadata`)
- **내부 토픽**: ZooKeeper 대신 Kafka 자체 토픽에 메타데이터 저장
- **Raft Log**: 모든 메타데이터 변경을 순차적 레코드로 기록
  - `VotersRecord`, `TopicRecord`, `PartitionRecord`, `ConfigRecord` 등
- **복제**: Quorum Controller 간 Raft 프로토콜로 복제
- **일관성**: 과반수 확인 후 커밋 (Kafka의 ISR과 유사)

### 동작 원리
```
메타데이터 변경 요청 (예: 토픽 생성)
    ↓
Active Controller → Metadata Log에 기록
    ↓
Quorum Controller들에 복제 (Raft AppendEntries)
    ↓
과반수 확인 (예: 3개 중 2개)
    ↓
변경 커밋
    ↓
모든 Broker에게 메타데이터 델타 전송 (push 방식!)
```

**ZooKeeper vs KRaft 차이**:
- **ZooKeeper**: Broker가 ZK를 polling → 지연
- **KRaft**: Controller가 Broker에게 push → 빠름

---

## 5. 마이그레이션 과정 (ZK → KRaft)

### 전제 조건
- Kafka 2.8+ (권장: 3.6+)
- 모든 데이터 백업
- 테스트 클러스터에서 먼저 검증

### 5단계 프로세스 (KIP-866 기반)

#### Phase 1: KRaft Controller 배포
- 설정: `zookeeper.metadata.migration.enable=true` + ZK 연결 정보
- 상태: **PREMIGRATION**
- Controller Quorum 형성, 리더 선출
- Broker 등록 대기

#### Phase 2: Broker 등록 (Hybrid)
- Broker 설정에 마이그레이션 플래그 추가
- Rolling restart (한 대씩)
- 상태: **HYBRID_DUAL_WRITE**
- Broker들이 KRaft Controller에 등록
- 아직 ZK 모드로 동작

#### Phase 3: Dual Write (마지막 롤백 포인트)
- 상태: **MIGRATION / MIGRATION_COMPLETED**
- **핵심**: KRaft Controller가 메타데이터 처리하면서 ZK에도 동시 기록
- Broker는 여전히 ZK 모드
- 검증: `kafka-migration-check status` or `/migration` 노드

#### Phase 4: Broker KRaft 전환
- Broker 설정에서 ZK 연결 제거, 마이그레이션 플래그 `false`
- Rolling restart
- Broker가 완전히 KRaft 모드로 전환
- Controller는 여전히 Dual Write 중

#### Phase 5: Finalization
- Controller 설정에서 ZK 제거
- Rolling restart controllers
- 상태: **FINALIZED**
- Dual Write 종료
- ZooKeeper 클러스터 폐기 가능

### 롤백 정책
- **Phase 1-3**: 완전 롤백 가능 (ZK 설정 복구 후 재시작)
- **Phase 4 이후**: `/migration` 노드 클리어 필요
- **Phase 5 이후**: 롤백 불가능 (ZK 데이터 버림)

---

## 6. KRaft의 장점

### 단일 프로세스
- **Before**: Kafka JVM + ZooKeeper JVM (최소 6개 프로세스: 3 Kafka + 3 ZK)
- **After**: Kafka JVM만 (3-5개 Controller + N개 Broker)
- 운영 비용 40-50% 감소 (AWS MSK 예시)

### 빠른 리더 선출
- **ZooKeeper 모드**: Controller failover 수십 초 (대규모 클러스터)
- **KRaft 모드**: 수백 ms~수 초
- 이유:
  1. Metadata Log에서 즉시 읽기 (ZK 왕복 없음)
  2. Raft 합의가 ZAB보다 단순/빠름
  3. Broker에게 push (polling 지연 없음)

### 확장성 향상
- **파티션 한계 제거**: ZK의 메모리/직렬화 병목 없음
- **Broker 수 확장**: Amazon MSK 60 브로커 (ZK는 30)
- **메타데이터 크기**: `__cluster_metadata`는 Log Compaction으로 무한 확장 가능

### 일관성 모델 개선
- **ZooKeeper**: 최종 일관성 (propagation delay)
- **KRaft**: Raft 합의 (강한 일관성)
- 메타데이터 불일치 버그 감소

### 성능
- **처리량**: 벤치마크상 10-20% 향상 (메타데이트 오버헤드 감소)
- **레이턴시**: Controller 통신 레이턴시 감소

---

## 코드/설정 예시

### ZooKeeper 모드 설정 (legacy)
```properties
# broker.properties
broker.id=0
zookeeper.connect=zk1:2181,zk2:2181,zk3:2181
```

### KRaft 모드 설정 (Separated 모드)
```properties
# controller.properties
node.id=1
process.roles=controller
controller.quorum.voters=1@host1:9093,2@host2:9093,3@host3:9093
controller.listener.names=CONTROLLER
listeners=CONTROLLER://:9093

# broker.properties
node.id=101
process.roles=broker
controller.quorum.voters=1@host1:9093,2@host2:9093,3@host3:9093
```

### Combined 모드 (Small Cluster)
```properties
# server.properties (3.5+)
node.id=1
process.roles=broker,controller
controller.quorum.voters=1@host1:9093,2@host2:9093,3@host3:9093
controller.listener.names=CONTROLLER
listeners=PLAINTEXT://:9092,CONTROLLER://:9093
```

### Migration 설정
```properties
# Phase 2: Controller
zookeeper.metadata.migration.enable=true
zookeeper.connect=zk1:2181,zk2:2181,zk3:2181

# Phase 2: Broker
zookeeper.metadata.migration.enable=true
```

---

## 참고 자료

### 공식 문서
- [KIP-500: Replace ZooKeeper with a Self-Managed Metadata Quorum](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum)
- [Kafka 4.1 Documentation: KRaft](https://kafka.apache.org/41/operations/kraft/)
- [Kafka ZooKeeper to KRaft Migration Guide](https://kafka.apache.org/41/getting-started/zk2kraft/)
- [KIP-853: Dynamic Kafka Controller Quorum](https://cwiki.apache.org/confluence/x/nyH1D)

### 아티클
- [Confluent: KRaft Overview](https://developer.confluent.io/learn/kraft/)
- [AWS MSK: KRaft Support Announcement](https://aws.amazon.com/blogs/big-data/introducing-support-for-apache-kafka-on-raft-mode-kraft-with-amazon-msk-clusters/)
- [RedPanda: Migration from ZooKeeper to KRaft](https://www.redpanda.com/blog/migration-apache-zookeeper-kafka-kraft)
- [Strimzi: KRaft Migration Journey](https://strimzi.io/blog/2024/03/21/kraft-migration/)

### 벤치마크/비교
- [Performance Comparison: ZooKeeper vs KRaft](https://ijcaonline.org/archives/volume187/number46/evaluating-apache-kafka-performance-and-operational-efficiency-a-comparative-study-of-zookeeper-and-kraft-architectures/)
- [Zendesk Engineering: KRaft Quorum Stability](https://zendesk.engineering/kraft-at-zendesk-part-2-quorum-stability-is-all-you-need-running-kraft-on-kubernetes-782698a94ddb)

---

## 핵심 인사이트

### 왜 ZooKeeper를 버렸나?
1. **아키텍처적 불일치**: Kafka는 로그 기반 시스템, ZK는 트리 기반 → 임피던스 불일치
2. **확장성의 천장**: 파티션/브로커 수 증가 시 ZK가 병목
3. **복잡성 비용**: 이중 시스템 운영의 오버헤드 > 단일 시스템의 복잡성
4. **Raft의 성숙**: 2010년대 후반 Raft 알고리즘이 산업 표준으로 자리잡음 (etcd, Consul 등)

### KRaft의 본질
- "Kafka를 자기 자신을 위한 합의 시스템으로 사용"
- 메타데이터도 결국 로그 → Kafka의 장점 활용
- Quorum Controller = 특수한 목적의 Kafka Broker

### 마이그레이션의 철학
- **Dual Write**: 과거(ZK)와 미래(KRaft)를 동시에 쓰며 안전하게 전환
- **점진적 롤아웃**: 다운타임 없이 5단계에 걸쳐 전환
- **롤백 윈도우**: Phase 3까지 언제든 되돌릴 수 있는 안전망

---

*리서치 완료일: 2026-02-15*
*다음: 초안 작성*
