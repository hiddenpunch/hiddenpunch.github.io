---
title: "Agent 해체분석기 #2: OpenAI Agents SDK 깊게 파보기"
date: 2026-02-04T10:12:00+09:00
summary: "OpenAI가 만든 멀티 에이전트 프레임워크. 어떻게 구성되어 있고, 각 컴포넌트가 어떤 역할을 하는지 뜯어봅니다"
tags: ["ai-agent", "해체분석기", "openai", "agents-sdk"]
categories: ["AI"]
series: ["Agent 해체분석기"]
series_order: 2
draft: false
mermaid: true
---

> 이 글은 [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) GitHub과 공식 문서를 직접 분석하여 작성되었습니다.

## 들어가며

OpenAI가 2024년 말 공개한 **Agents SDK**. 

공식 설명은 이렇습니다:
> "A lightweight yet powerful framework for building multi-agent workflows"

가볍지만 강력하다? 진짜인지 뜯어봅시다.

---

## 1. 전체 구조 한눈에 보기

<pre class="mermaid">
flowchart TB
    subgraph sdk[OpenAI Agents SDK]
        AGENT[Agent]
        RUNNER[Runner]
        HANDOFF[Handoffs]
        GUARD[Guardrails]
        TRACE[Tracing]
    end
    
    AGENT --> RUNNER
    AGENT --> HANDOFF
    AGENT --> GUARD
    RUNNER --> TRACE
    
    style AGENT fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style RUNNER fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style HANDOFF fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style GUARD fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style TRACE fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

| 컴포넌트 | 역할 |
|---------|------|
| 🟢 **Agent** | LLM + 설정 (instructions, tools, handoffs) |
| 🔵 **Runner** | Agent 실행 루프 관리 |
| 🟠 **Handoffs** | 다른 Agent로 제어 전환 |
| 🔴 **Guardrails** | 입출력 검증/안전장치 |
| 🟣 **Tracing** | 실행 추적/디버깅 |

---

## 2. Agent: 핵심 빌딩 블록

공식 문서:
> "Agents are the core building block in your apps. An agent is a large language model (LLM), configured with instructions and tools."

### 2.1 Agent 기본 구성

```python
from agents import Agent, function_tool

@function_tool
def get_weather(city: str) -> str:
    """returns weather info for the specified city."""
    return f"The weather in {city} is sunny"

agent = Agent(
    name="Weather Agent",           # 필수: 에이전트 이름
    instructions="Always be helpful", # 시스템 프롬프트
    model="gpt-4o",                  # 사용할 모델
    tools=[get_weather],             # 사용 가능한 도구들
    handoffs=[other_agent],          # 제어 전환 가능한 다른 에이전트
    guardrails=[my_guardrail],       # 안전장치
)
```

<pre class="mermaid">
flowchart LR
    subgraph agent[Agent]
        NAME[name]
        INST[instructions]
        MODEL[model]
        TOOLS[tools]
        HO[handoffs]
        GR[guardrails]
    end
    
    NAME --- INST
    INST --- MODEL
    MODEL --- TOOLS
    TOOLS --- HO
    HO --- GR
    
    style agent fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

### 2.2 주요 속성들

| 속성 | 필수 | 설명 |
|-----|-----|------|
| `name` | ✅ | 에이전트 식별자 |
| `instructions` | ❌ | 시스템 프롬프트 (행동 지침) |
| `model` | ❌ | LLM 모델 (기본: gpt-4o) |
| `tools` | ❌ | 사용 가능한 함수들 |
| `handoffs` | ❌ | 전환 가능한 다른 에이전트들 |
| `output_type` | ❌ | 구조화된 출력 타입 (Pydantic) |
| `guardrails` | ❌ | 입출력 검증 |
| `mcp_servers` | ❌ | MCP 서버 연결 |

### 2.3 output_type: 구조화된 출력

일반 텍스트 대신 **정해진 형식**으로 응답받고 싶을 때:

```python
from pydantic import BaseModel

class CalendarEvent(BaseModel):
    name: str
    date: str
    participants: list[str]

agent = Agent(
    name="Calendar extractor",
    instructions="Extract calendar events from text",
    output_type=CalendarEvent,  # 👈 구조화된 출력
)
```

내부적으로 OpenAI의 [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)를 사용합니다.

---

## 3. Runner: 실행 엔진

Agent를 실행하는 **메인 루프**입니다.

### 3.1 기본 사용법

```python
from agents import Agent, Runner

agent = Agent(name="Assistant", instructions="You are helpful")

# 동기 실행
result = Runner.run_sync(agent, "Hello!")

# 비동기 실행
result = await Runner.run(agent, "Hello!")

# 스트리밍
async for event in Runner.run_streamed(agent, "Hello!"):
    print(event)
```

### 3.2 Agent Loop 동작 방식

`Runner.run()`이 호출되면 다음 루프가 실행됩니다:

<pre class="mermaid">
flowchart TB
    START[시작] --> LLM[1. LLM 호출]
    LLM --> RESPONSE[2. 응답 받음]
    RESPONSE --> CHECK{3. final output?}
    CHECK -->|Yes| END[종료]
    CHECK -->|No| HANDOFF{4. handoff?}
    HANDOFF -->|Yes| SWITCH[에이전트 전환]
    SWITCH --> LLM
    HANDOFF -->|No| TOOLS[5. Tool 실행]
    TOOLS --> APPEND[6. 결과 추가]
    APPEND --> LLM
    
    style START fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style END fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style LLM fill:#bbdefb,stroke:#1976d2,stroke-width:2px
</pre>

**루프 상세 설명:**

1. **LLM 호출**: 현재 에이전트의 model, instructions, 메시지 히스토리로 호출
2. **응답 분석**: tool calls, handoff, 일반 텍스트 구분
3. **Final Output 체크**:
   - `output_type` 있으면: 해당 타입 응답이 오면 종료
   - `output_type` 없으면: tool call/handoff 없는 응답이 오면 종료
4. **Handoff 체크**: 다른 에이전트로 전환 요청이면 에이전트 교체
5. **Tool 실행**: tool call이 있으면 실행
6. **결과 추가**: tool 결과를 히스토리에 추가 후 다시 1번으로

### 3.3 max_turns: 무한 루프 방지

```python
result = await Runner.run(
    agent, 
    "Complex task",
    max_turns=10  # 최대 10번 반복
)
```

---

## 4. Handoffs: 에이전트 간 협업

**Handoff**는 한 에이전트가 다른 에이전트에게 **제어를 넘기는** 메커니즘입니다.

### 4.1 기본 개념

```python
spanish_agent = Agent(
    name="Spanish agent",
    instructions="You only speak Spanish.",
)

english_agent = Agent(
    name="English agent",
    instructions="You only speak English",
)

triage_agent = Agent(
    name="Triage agent",
    instructions="Handoff to the appropriate agent based on language.",
    handoffs=[spanish_agent, english_agent],  # 👈 전환 가능한 에이전트
)
```

### 4.2 내부 동작

Handoff는 **특수한 Tool**로 구현됩니다:

<pre class="mermaid">
flowchart LR
    TRIAGE[Triage Agent]
    
    TOOL1[transfer_to_spanish_agent]
    TOOL2[transfer_to_english_agent]
    
    SPANISH[Spanish Agent]
    ENGLISH[English Agent]
    
    TRIAGE --> TOOL1
    TRIAGE --> TOOL2
    TOOL1 --> SPANISH
    TOOL2 --> ENGLISH
    
    style TRIAGE fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style SPANISH fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style ENGLISH fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

LLM 입장에서는 `transfer_to_spanish_agent`라는 **tool**을 호출하는 것!

### 4.3 Handoff 커스터마이징

```python
from agents import handoff, RunContextWrapper

async def on_handoff(ctx: RunContextWrapper, input_data: EscalationData):
    print(f"Escalation reason: {input_data.reason}")

escalation_handoff = handoff(
    agent=escalation_agent,
    tool_name_override="escalate_to_human",
    tool_description_override="Use when customer is very angry",
    on_handoff=on_handoff,  # 전환 시 콜백
    input_type=EscalationData,  # LLM이 제공할 데이터 타입
)
```

---

## 5. Guardrails: 안전장치

입출력을 **검증**하고 **차단**하는 메커니즘입니다.

### 5.1 세 가지 종류

| 종류 | 실행 시점 | 용도 |
|-----|----------|------|
| **Input Guardrails** | 사용자 입력 직후 | 악의적 요청 차단 |
| **Output Guardrails** | 최종 응답 직전 | 부적절한 응답 차단 |
| **Tool Guardrails** | Tool 실행 전후 | Tool 호출 검증 |

### 5.2 Input Guardrails 예시

```python
from agents import Agent, input_guardrail, GuardrailFunctionOutput

@input_guardrail
async def block_homework(ctx, agent, input_text: str) -> GuardrailFunctionOutput:
    # 저렴한 모델로 빠르게 체크
    result = await cheap_model.check(input_text)
    
    if "homework" in result:
        return GuardrailFunctionOutput(
            tripwire_triggered=True,  # 👈 차단!
            output_info={"reason": "Homework request detected"}
        )
    return GuardrailFunctionOutput(tripwire_triggered=False)

agent = Agent(
    name="Assistant",
    input_guardrails=[block_homework],  # 👈 입력 검증
)
```

### 5.3 실행 모드

<pre class="mermaid">
flowchart LR
    subgraph parallel[Parallel Mode - 기본]
        INPUT1[입력] --> GUARD1[Guardrail]
        INPUT1 --> AGENT1[Agent]
        GUARD1 -.->|실패 시 취소| AGENT1
    end
    
    subgraph blocking[Blocking Mode]
        INPUT2[입력] --> GUARD2[Guardrail]
        GUARD2 -->|통과 시| AGENT2[Agent]
    end
</pre>

- **Parallel (기본)**: Guardrail과 Agent가 동시에 실행. 빠르지만 토큰 소비 가능
- **Blocking**: Guardrail 통과 후 Agent 실행. 느리지만 비용 절약

---

## 6. Tracing: 디버깅과 모니터링

모든 실행을 **자동으로 추적**합니다.

### 6.1 추적되는 것들

| Span 종류 | 추적 내용 |
|----------|----------|
| `agent_span` | 에이전트 실행 |
| `generation_span` | LLM 호출 |
| `function_span` | Tool 호출 |
| `guardrail_span` | Guardrail 실행 |
| `handoff_span` | Handoff 발생 |

### 6.2 Trace 구조

<pre class="mermaid">
flowchart TB
    TRACE[Trace: Customer Support]
    
    TRACE --> AGENT1[Agent Span: Triage]
    AGENT1 --> GEN1[Generation Span]
    AGENT1 --> HANDOFF1[Handoff Span]
    
    TRACE --> AGENT2[Agent Span: Refund]
    AGENT2 --> GEN2[Generation Span]
    AGENT2 --> FUNC1[Function Span: process_refund]
    
    style TRACE fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

### 6.3 커스텀 Trace

```python
from agents import trace

with trace("My custom workflow"):
    result1 = await Runner.run(agent1, "Step 1")
    result2 = await Runner.run(agent2, "Step 2")
    # 두 실행이 하나의 trace로 묶임
```

---

## 7. 전체 흐름 예시

고객 지원 시스템을 만든다고 가정:

<pre class="mermaid">
flowchart TB
    USER[사용자 입력]
    
    subgraph guardrails[입력 검증]
        IG[Input Guardrail]
    end
    
    subgraph agents[에이전트들]
        TRIAGE[Triage Agent]
        REFUND[Refund Agent]
        FAQ[FAQ Agent]
    end
    
    subgraph tools[도구들]
        DB[DB 조회]
        API[환불 API]
    end
    
    USER --> IG
    IG -->|통과| TRIAGE
    TRIAGE -->|handoff| REFUND
    TRIAGE -->|handoff| FAQ
    REFUND --> DB
    REFUND --> API
    
    style USER fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style IG fill:#ffcdd2,stroke:#c62828,stroke-width:2px
</pre>

```python
from agents import Agent, Runner, function_tool, input_guardrail

# 1. Tools 정의
@function_tool
def lookup_order(order_id: str) -> str:
    return db.get_order(order_id)

@function_tool  
def process_refund(order_id: str, amount: float) -> str:
    return payment_api.refund(order_id, amount)

# 2. Guardrail 정의
@input_guardrail
async def block_abuse(ctx, agent, input_text):
    # 욕설/악용 체크
    ...

# 3. 전문 에이전트들
refund_agent = Agent(
    name="Refund Agent",
    instructions="You handle refund requests.",
    tools=[lookup_order, process_refund],
)

faq_agent = Agent(
    name="FAQ Agent", 
    instructions="You answer common questions.",
)

# 4. Triage 에이전트
triage_agent = Agent(
    name="Triage Agent",
    instructions="Route to the appropriate agent.",
    handoffs=[refund_agent, faq_agent],
    input_guardrails=[block_abuse],
)

# 5. 실행
result = await Runner.run(triage_agent, "I want a refund for order #123")
```

---

## 8. 정리: OpenAI Agents SDK의 설계 철학

| 특징 | 설명 |
|-----|------|
| **경량** | 핵심 컴포넌트가 5개 (Agent, Runner, Handoff, Guardrail, Trace) |
| **Provider-agnostic** | OpenAI뿐 아니라 100+ LLM 지원 |
| **Handoff = Tool** | 에이전트 전환을 tool call로 통일 |
| **안전 우선** | Guardrails로 입출력 검증 내장 |
| **관측 가능** | Tracing 기본 내장 |

### 다른 프레임워크와 비교

| 항목 | OpenAI Agents SDK | LangGraph | AutoGen |
|-----|-------------------|-----------|---------|
| 복잡도 | 낮음 | 높음 | 중간 |
| 멀티에이전트 | Handoffs | Graph Edges | Agent Chat |
| 상태 관리 | Sessions | StateGraph | Context |
| 안전장치 | Guardrails 내장 | 별도 구현 | 별도 구현 |

---

> **해체분석기 #4: LangGraph vs OpenAI Agents SDK 실전 비교**
>
> - 같은 문제를 두 프레임워크로 구현
> - 코드량, 성능, 유지보수성 비교

---

## 참고 자료

- [OpenAI Agents SDK GitHub](https://github.com/openai/openai-agents-python)
- [공식 문서](https://openai.github.io/openai-agents-python/)
- [Agents 문서](https://openai.github.io/openai-agents-python/agents/)
- [Handoffs 문서](https://openai.github.io/openai-agents-python/handoffs/)
- [Guardrails 문서](https://openai.github.io/openai-agents-python/guardrails/)
- [Tracing 문서](https://openai.github.io/openai-agents-python/tracing/)
