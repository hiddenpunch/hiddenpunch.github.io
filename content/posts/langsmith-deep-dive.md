---
title: "Agent 해체분석기 #4: LangSmith 구조와 원리"
date: 2026-02-05T20:30:00+09:00
summary: "LangChain 에코시스템의 LLM Observability 플랫폼. 어떻게 trace를 수집하고, 어디에 저장하고, 무엇을 분석할 수 있는지 뜯어봅니다"
tags: ["llm", "해체분석기", "langsmith", "observability", "tracing"]
categories: ["AI"]
series: ["Agent 해체분석기"]
series_order: 4
draft: false
mermaid: true
---

> 이 글은 [LangSmith SDK](https://github.com/langchain-ai/langsmith-sdk) 소스코드와 공식 문서를 직접 분석하여 작성되었습니다.

## 들어가며

LLM 앱을 만들다 보면 이런 고민이 생긴다:
- "이 응답이 왜 이렇게 나왔지?"
- "어디서 시간이 오래 걸리는 거야?"
- "토큰을 얼마나 쓰고 있는 거지?"

**LangSmith**는 LangChain 팀이 만든 LLM Observability 플랫폼이다. 실행 흐름을 추적하고, 디버깅하고, 평가하는 도구.

근데 내부에서 어떻게 동작하는 걸까? 뜯어보자.

---

## 1. LangChain 에코시스템에서의 위치

<pre class="mermaid">
flowchart LR
    subgraph ecosystem[LangChain Ecosystem]
        LC[LangChain<br/>프레임워크]
        LG[LangGraph<br/>워크플로우]
        LS[LangServe<br/>API 배포]
        LSM[LangSmith<br/>관측성/평가]
    end
    
    LC --> LG
    LG --> LS
    LC --> LSM
    LG --> LSM
    LS --> LSM
    
    style LC fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style LG fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style LS fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style LSM fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

| 컴포넌트 | 역할 |
|---------|------|
| 🟢 **LangChain** | LLM 앱 프레임워크 (chains, agents) |
| 🔵 **LangGraph** | 복잡한 워크플로우 오케스트레이션 |
| 🟠 **LangServe** | LangChain 앱 → REST API 배포 |
| 🟣 **LangSmith** | 관측성, 평가, 모니터링 |

LangSmith는 나머지 컴포넌트들의 **눈**이 되어준다.

---

## 2. 핵심 개념 5가지

### 2.1 Run (Span)

**한 번의 작업**을 의미하는 가장 기본 단위.

- LLM 호출 1회
- 체인 실행 1회
- 도구 호출 1회

```python
# SDK 내부 스키마 (schemas.py)
class RunBase(BaseModel):
    id: UUID
    name: str
    run_type: str  # "llm" | "chain" | "tool" | ...
    start_time: datetime
    end_time: Optional[datetime]
    
    # 핵심 데이터
    inputs: dict
    outputs: Optional[dict]
    error: Optional[str]
    
    # 트리 구조
    trace_id: UUID           # 같은 Trace로 묶음
    parent_run_id: Optional[UUID]  # 부모 Run
    dotted_order: str        # 실행 순서 (예: "1.2.1")
```

### 2.2 Trace

**여러 Run을 트리 구조로 묶은 것**. 하나의 요청이 만들어내는 전체 실행 흐름.

```
Trace (trace_id로 묶임)
│
├── Run: agent_call (root)
│     ├── Run: llm_generation
│     ├── Run: tool_call (search)
│     │     └── Run: api_request
│     └── Run: llm_generation (final)
```

- `trace_id`: 같은 Trace 식별
- `parent_run_id`: 부모-자식 관계
- `dotted_order`: 실행 순서 보장 ("1.2.1" 형태)

### 2.3 Project (TracerSession)

**Trace들을 담는 컨테이너**. UI에서 "Project"로 표시된다.

```python
class TracerSessionResult(TracerSession):
    run_count: Optional[int]           # 총 실행 수
    latency_p50: Optional[timedelta]   # 지연시간 중앙값
    latency_p99: Optional[timedelta]   # 지연시간 99퍼센타일
    total_tokens: Optional[int]        # 총 토큰 수
    total_cost: Optional[Decimal]      # 총 비용
    error_rate: Optional[float]        # 에러율
    feedback_stats: Optional[dict]     # 피드백 통계
```

분석/집계의 기본 단위다.

### 2.4 Feedback

**Run이나 Trace에 붙이는 평가/라벨**.

```python
class FeedbackBase(BaseModel):
    run_id: Optional[UUID]      # 대상 Run
    trace_id: Optional[UUID]    # 또는 전체 Trace
    key: str                    # 지표명 ("accuracy", "relevance" 등)
    score: SCORE_TYPE           # 점수
    value: VALUE_TYPE           # 값
    comment: Optional[str]      # 코멘트
    correction: Optional[str]   # 수정 제안
```

정확도, 유용성, 안전성 등 원하는 지표를 자유롭게 기록할 수 있다.

### 2.5 Dataset / Example

**평가의 기준 데이터**. Dataset은 Example(입력/정답)의 모음.

```
Dataset
├── Example 1: {input: "서울 날씨", output: "맑음"}
├── Example 2: {input: "부산 날씨", output: "흐림"}
└── Example N: ...
```

핵심 연결고리:
- `Run.reference_example_id` → "이 Example을 평가 대상으로 사용"
- `Example.source_run_id` → "이 Run에서 생성된 Example"

이 연결로 **(예측 vs 정답)** 분석이 가능해진다.

---

## 3. Tracing 원리: 어떻게 수집하나?

**핵심**: 이벤트 기반 Push. 각 실행 시점에 데이터를 생성하고 비동기로 전송.

### 3.1 방식 1: Callback Handler (LangChain용)

LangChain 내부에 이벤트 훅이 있다. 각 컴포넌트 실행 시점마다 콜백이 호출됨.

```python
class LangSmithHandler(BaseCallbackHandler):
    def on_llm_start(self, serialized, prompts, **kwargs):
        # LLM 호출 시작 → span 생성, 입력 기록
        
    def on_llm_end(self, response, **kwargs):
        # LLM 호출 끝 → span 종료, 출력/토큰 수 기록
        
    def on_chain_start(self, serialized, inputs, **kwargs):
        # 체인 시작
        
    def on_tool_start(self, serialized, input_str, **kwargs):
        # 도구 호출 시작
```

환경변수만 설정하면 자동 활성화:
```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_...
```

### 3.2 방식 2: @traceable 데코레이터 (범용)

LangChain 아닌 코드도 추적 가능.

```python
from langsmith import traceable

@traceable
def my_function(query: str):
    # 이 함수 실행이 자동으로 span이 됨
    result = call_some_api(query)
    return process(result)
```

내부적으로 이런 일이 일어난다:

```python
# @traceable이 실제로 하는 일 (단순화)
def traceable_wrapper(func):
    def wrapper(*args, **kwargs):
        span = start_span(func.__name__, inputs=args)
        try:
            result = func(*args, **kwargs)
            span.end(outputs=result)
            return result
        except Exception as e:
            span.error(e)
            raise
    return wrapper
```

### 3.3 Context Propagation

부모 span ID를 자식에게 전달해서 트리 구조를 유지한다.

```python
from langsmith import tracing_context

with tracing_context(parent=parent_span_id):
    child_function()  # 이 안의 span들은 parent의 자식이 됨
```

<pre class="mermaid">
flowchart TB
    subgraph trace[Trace Context]
        R[Root Span]
        C1[Child 1]
        C2[Child 2]
        G1[Grandchild]
    end
    
    R --> C1
    R --> C2
    C1 --> G1
    
    style R fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style C1 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style C2 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style G1 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
</pre>

---

## 4. 수집 파이프라인: RunTree와 2단계 전송

### 4.1 RunTree: 트리 빌더

```python
# run_trees.py
class RunTree(RunBase):
    parent_run: Optional[RunTree] = None
    child_runs: list[RunTree] = []
    session_name: str = "default"  # = project_name
    dotted_order: str = ""         # 실행 순서
    trace_id: UUID                 # 최상위 trace 식별자
```

자식 Run 생성 시 `parent_run_id`, `trace_id`, `dotted_order`가 **자동으로 설정**된다.

### 4.2 2단계 전송: post() → patch()

| 단계 | 시점 | 동작 |
|-----|-----|------|
| `post()` | 시작 | `create_run` API - Run 생성 |
| `patch()` | 종료 | `update_run` API - outputs/error 업데이트 |

```python
# 실제 흐름
run = RunTree(name="my_chain", inputs={"query": "..."})
run.post()  # → POST /runs (run 생성)

try:
    result = execute_chain()
    run.outputs = {"result": result}
except Exception as e:
    run.error = str(e)
finally:
    run.end()
    run.patch()  # → PATCH /runs/{id} (결과 업데이트)
```

왜 2단계일까? **실행이 실패해도 시작 기록은 남기기 위해서**.

---

## 5. 비동기 큐: 앱 성능을 지키는 비밀

매번 API 호출하면 앱이 느려진다. LangSmith는 **비동기 큐 + 백그라운드 스레드**로 이를 해결한다.

### 5.1 구조

<pre class="mermaid">
flowchart LR
    subgraph main[Main Thread]
        APP[App Code]
        CQ[create_run]
        UQ[update_run]
    end
    
    subgraph bg[Background Thread]
        Q[(Queue)]
        W[Worker]
        B[Batch]
    end
    
    subgraph api[LangSmith]
        API[API Server]
    end
    
    APP --> CQ
    APP --> UQ
    CQ --> Q
    UQ --> Q
    Q --> W
    W --> B
    B -->|HTTP POST| API
    
    style APP fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style Q fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style W fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style API fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

### 5.2 내부 구현 (단순화)

```python
class Client:
    def __init__(self):
        self._tracing_queue = Queue()      # 이벤트 버퍼
        self._tracing_thread = Thread(     # 백그라운드 워커
            target=self._background_worker,
            daemon=True  # 앱 종료 시 같이 종료
        )
        self._tracing_thread.start()
    
    def create_run(self, **kwargs):
        # 메인 스레드: 큐에 넣고 즉시 반환
        self._tracing_queue.put(("create", kwargs))
    
    def update_run(self, **kwargs):
        self._tracing_queue.put(("update", kwargs))
    
    def _background_worker(self):
        """백그라운드에서 큐 소비"""
        batch = []
        while True:
            try:
                item = self._tracing_queue.get(timeout=0.5)
                batch.append(item)
            except Empty:
                pass
            
            # 배치가 차면 전송
            if len(batch) >= BATCH_SIZE or timeout_reached:
                self._batch_ingest_runs(batch)
                batch = []
```

### 5.3 Client 최적화 옵션

| 최적화 | 설명 |
|--------|------|
| **샘플링** | trace 단위로 수집율 조절 (예: 10%만 수집) |
| **배치** | 여러 이벤트 묶어서 한 번에 전송 |
| **압축** | gzip으로 페이로드 압축 |
| **비동기 큐** | 앱 스레드 블로킹 없이 백그라운드 전송 |

```python
# 샘플링 예시 (client.py)
def create_run(self, name, inputs, run_type, ...):
    run_create = {"name": name, "inputs": inputs, ...}
    
    # 샘플링 필터
    if not self._filter_for_sampling([run_create]):
        return  # 샘플링에서 제외됨
    
    self._create_run(run_create)
```

---

## 6. 저장: ClickHouse 기반

LangSmith 백엔드는 **ClickHouse**(컬럼 기반 분석 DB)를 사용한다.

```
LangSmith Backend (ClickHouse)
│
├── Run 테이블
│     ├── trace_id      → 같은 Trace로 그룹핑
│     ├── parent_run_id → 트리 구조 복원
│     └── dotted_order  → 실행 순서 정렬
│
├── Project 테이블
│     └── 집계: run_count, latency_p50/p99, cost, error_rate
│
├── Feedback 테이블
│     └── run_id/trace_id + key + score
│
└── Dataset/Example 테이블
      └── reference_example_id로 Run과 조인
```

트리 복원 쿼리:
```sql
SELECT * FROM runs
WHERE trace_id = :trace_id
ORDER BY dotted_order
```

`dotted_order`가 "1.2.1" 같은 형태라서, 문자열 정렬만으로 실행 순서가 보장된다.

---

## 7. 분석의 3갈래

수집된 데이터로 할 수 있는 분석:

### 7.1 Observability (운영 관측)

Project 단위 집계:
- latency p50/p99
- error_rate
- total_tokens, total_cost
- tags facet (필터링)

**"프로덕션에서 무슨 일이 일어나고 있나?"**

### 7.2 Feedback (품질 분석)

Run/Trace에 Feedback 연결:
- 정확도, 유용성, 안전성 등 지표 기록
- `feedback_stats`로 집계

**"응답 품질이 어떤가?"**

### 7.3 Experiment (벤치마크)

Dataset ↔ Run ↔ Feedback 연결:

<pre class="mermaid">
flowchart LR
    D[Dataset]
    E[Example]
    T[Target]
    R[Run]
    EV[Evaluator]
    F[Feedback]
    
    D --> E
    E -->|input| T
    T --> R
    R -->|reference_example_id| E
    R -->|outputs| EV
    E -->|expected outputs| EV
    EV --> F
    
    style D fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style R fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style F fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

```python
from langsmith import evaluate

evaluate(
    target=my_chain,
    data=dataset,
    evaluators=[accuracy_evaluator],
    experiment_prefix="v2_test",
    upload_results=True
)
```

**"버전 A와 B 중 뭐가 더 나은가?"**

---

## 8. 전체 흐름 정리

<pre class="mermaid">
flowchart TB
    subgraph app[Application]
        CODE[Your Code]
        DEC[@traceable / Callback]
        RT[RunTree]
    end
    
    subgraph client[LangSmith Client]
        Q[(Queue)]
        BG[Background Thread]
        BATCH[Batch + Compress]
    end
    
    subgraph backend[LangSmith Backend]
        API[API Server]
        CH[(ClickHouse)]
    end
    
    subgraph ui[LangSmith UI]
        TRACE[Trace View]
        DASH[Dashboard]
        EVAL[Evaluation]
    end
    
    CODE --> DEC
    DEC --> RT
    RT -->|post/patch| Q
    Q --> BG
    BG --> BATCH
    BATCH -->|HTTP| API
    API --> CH
    CH --> TRACE
    CH --> DASH
    CH --> EVAL
    
    style CODE fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style Q fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style CH fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style TRACE fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

**한 줄 요약**:
> Callback/@traceable로 캡처 → RunTree로 구조화 → 비동기 배치 전송 → ClickHouse 저장 → UI에서 분석

---

## 마무리

LangSmith를 뜯어보면 결국 **분산 추적 시스템의 정석**을 따르고 있다:

1. **Span 트리 구조** (trace_id + parent_run_id + dotted_order)
2. **Context Propagation** (부모-자식 연결)
3. **비동기 수집** (큐 + 백그라운드 스레드 + 배치)
4. **컬럼 기반 저장** (ClickHouse)

OpenTelemetry, Jaeger, Zipkin 같은 APM 도구들과 본질적으로 같은 패턴이다. 다만 **LLM 특화 기능**(토큰 카운팅, 프롬프트 버전 관리, 평가 시스템)이 추가된 것.

LLM Observability 도구를 고를 때, 이 내부 구조를 알면 더 현명한 선택을 할 수 있다.

---

## 참고 자료

- [LangSmith SDK GitHub](https://github.com/langchain-ai/langsmith-sdk)
- [LangSmith 공식 문서](https://docs.langchain.com/langsmith)
- [LangSmith Observability Concepts](https://docs.langchain.com/langsmith/observability-concepts)
