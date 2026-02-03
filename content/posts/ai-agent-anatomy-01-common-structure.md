---
title: "해체분석기 #2: AI Agent의 공통 구조"
date: 2026-02-03T21:54:00+09:00
summary: "LangChain, AutoGen, CrewAI... 겉보기엔 다 달라 보이지만, 뜯어보면 같은 뼈대를 공유합니다"
tags: ["ai-agent", "해체분석기", "langchain", "autogen", "crewai"]
categories: ["AI"]
series: ["해체분석기"]
draft: true
mermaid: true
---

> LangChain, AutoGen, CrewAI, DSPy, MetaGPT...  
> AI Agent 프레임워크가 쏟아지고 있지만, 결국 다 비슷한 구조 아닐까?

## 들어가며

2023년부터 AI Agent 프레임워크가 폭발적으로 늘어났습니다. 매주 새로운 프레임워크가 등장하고, 각각 "우리가 최고"라고 주장합니다.

하지만 이들을 뜯어보면 **공통된 뼈대**가 보입니다. 오늘은 그 뼈대를 해체해봅니다.

---

## 1. 모든 AI Agent의 공통 구조

거의 모든 Agent 프레임워크는 이 5가지 컴포넌트로 구성됩니다:

<pre class="mermaid">
flowchart TB
    ORCH[Orchestrator]
    PLAN[Planning]
    MEM[Memory]
    LLM[LLM Backbone]
    TOOLS[Tools]
    
    ORCH --> PLAN
    ORCH --> MEM
    PLAN --> LLM
    MEM --> LLM
    LLM --> TOOLS
    TOOLS --> ORCH
    
    style ORCH fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style PLAN fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
    style MEM fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style LLM fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style TOOLS fill:#ffecb3,stroke:#f57c00,stroke-width:2px
</pre>

| 컴포넌트 | 역할 | 비유 |
|---------|------|------|
| 🔴 **Orchestrator** | 전체 루프 관리, 작업 흐름 조율 | 지휘자 |
| 🟣 **Planning** | 복잡한 작업을 단계로 분해 | 전략가 |
| 🔵 **Memory** | 대화/작업 히스토리 유지 | 기억 |
| 🟢 **LLM Backbone** | 추론, 판단, 생성 | 두뇌 |
| 🟡 **Tools** | 외부 세계와 상호작용 | 손발 |

---

## 2. 각 컴포넌트 상세 분석

### 2.1 🟢 LLM Backbone: 두뇌

Agent의 핵심 추론 엔진입니다.

```python
# 거의 모든 프레임워크의 공통 패턴
response = llm.generate(
    prompt=current_context,
    tools=available_tools,
    temperature=0.7
)
```

**하는 일:**
- 현재 상황 이해
- 다음 행동 결정
- Tool 호출 여부 판단
- 최종 답변 생성

**주요 선택지:**
- OpenAI GPT-4
- Anthropic Claude
- Google Gemini
- Open source (Llama, Mistral 등)

---

### 2.2 🟡 Tools: 손발

LLM은 "생각"만 할 수 있습니다. 실제로 **행동**하려면 Tool이 필요합니다.

<pre class="mermaid">
flowchart LR
    LLM[LLM] -->|결정| ROUTER[Tool Router]
    ROUTER --> SEARCH[Web Search]
    ROUTER --> CODE[Code Executor]
    ROUTER --> API[API Call]
    ROUTER --> FILE[File System]
    
    SEARCH --> RESULT[결과]
    CODE --> RESULT
    API --> RESULT
    FILE --> RESULT
    
    RESULT --> LLM
    
    style LLM fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style ROUTER fill:#ffecb3,stroke:#f57c00,stroke-width:2px
</pre>

**일반적인 Tool 정의:**
```python
@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return search_engine.search(query)

@tool  
def execute_python(code: str) -> str:
    """Execute Python code and return the result."""
    return sandbox.run(code)
```

**핵심 포인트:**
- Tool은 **명확한 입출력**이 있어야 함
- LLM이 **언제 사용할지 판단**할 수 있도록 설명 필요
- 실패 처리가 중요 (네트워크 오류, 타임아웃 등)

---

### 2.3 🔵 Memory: 기억

LLM은 기본적으로 **stateless**입니다. 이전 대화를 기억하려면 Memory가 필요합니다.

<pre class="mermaid">
flowchart TB
    subgraph memory[Memory Types]
        SHORT[Short-term Memory]
        LONG[Long-term Memory]
        WORK[Working Memory]
    end
    
    SHORT --> |최근 N턴| CONTEXT[Context Window]
    LONG --> |벡터 검색| CONTEXT
    WORK --> |현재 작업 상태| CONTEXT
    CONTEXT --> LLM[LLM]
    
    style SHORT fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style LONG fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style WORK fill:#bbdefb,stroke:#1976d2,stroke-width:2px
</pre>

**Memory 종류:**

| 종류 | 저장 내용 | 예시 |
|------|----------|------|
| **Short-term** | 최근 대화 | 최근 10턴 메시지 |
| **Long-term** | 과거 정보 | 벡터 DB에 저장된 문서 |
| **Working** | 현재 작업 상태 | 진행 중인 단계, 중간 결과 |

**구현 예시:**
```python
class ConversationMemory:
    def __init__(self, max_turns=10):
        self.messages = []
        self.max_turns = max_turns
    
    def add(self, role, content):
        self.messages.append({"role": role, "content": content})
        # 오래된 메시지 삭제
        if len(self.messages) > self.max_turns * 2:
            self.messages = self.messages[-self.max_turns * 2:]
    
    def get_context(self):
        return self.messages
```

---

### 2.4 🟣 Planning: 전략

복잡한 작업을 **작은 단계로 분해**합니다.

<pre class="mermaid">
flowchart TB
    GOAL[목표: 경쟁사 분석 보고서 작성]
    
    GOAL --> STEP1[1. 경쟁사 목록 파악]
    GOAL --> STEP2[2. 각 경쟁사 정보 수집]
    GOAL --> STEP3[3. 비교 분석]
    GOAL --> STEP4[4. 보고서 작성]
    
    STEP1 --> TOOL1[Tool: Web Search]
    STEP2 --> TOOL2[Tool: Web Scraping]
    STEP3 --> TOOL3[Tool: LLM Analysis]
    STEP4 --> TOOL4[Tool: Document Gen]
    
    style GOAL fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

**주요 Planning 전략:**

| 전략 | 설명 | 사용 사례 |
|------|------|----------|
| **ReAct** | Reasoning + Acting 반복 | 범용 |
| **Plan-and-Execute** | 먼저 계획, 후 실행 | 복잡한 작업 |
| **Tree of Thoughts** | 여러 경로 탐색 | 창의적 문제 |
| **Reflexion** | 실패 시 반성 후 재시도 | 학습 필요한 작업 |

---

### 2.5 🔴 Orchestrator: 지휘자

모든 것을 조율하는 **메인 루프**입니다.

```python
# 가장 기본적인 Agent 루프
def agent_loop(goal: str):
    memory = Memory()
    
    while True:
        # 1. 현재 상태 파악
        context = memory.get_context()
        
        # 2. LLM에게 판단 요청
        action = llm.decide(context, goal, available_tools)
        
        # 3. 완료 조건 확인
        if action.type == "finish":
            return action.result
        
        # 4. Tool 실행
        result = execute_tool(action.tool, action.args)
        
        # 5. 결과 저장
        memory.add("tool_result", result)
```

<pre class="mermaid">
flowchart TB
    START[시작] --> CONTEXT[컨텍스트 수집]
    CONTEXT --> DECIDE[LLM 판단]
    DECIDE --> CHECK{완료?}
    CHECK -->|Yes| END[종료]
    CHECK -->|No| EXECUTE[Tool 실행]
    EXECUTE --> SAVE[결과 저장]
    SAVE --> CONTEXT
    
    style START fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style END fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

---

## 3. 전체 그림: 모든 것이 연결된다

<pre class="mermaid">
flowchart TB
    USER[User Input] --> ORCH
    
    subgraph agent[Agent System]
        ORCH[Orchestrator]
        
        subgraph reasoning[Reasoning Layer]
            PLAN[Planning]
            LLM[LLM Backbone]
        end
        
        subgraph state[State Management]
            MEM[Memory]
        end
        
        subgraph action[Action Layer]
            TOOLS[Tools]
        end
    end
    
    ORCH --> PLAN
    PLAN --> LLM
    MEM <--> LLM
    LLM --> TOOLS
    TOOLS --> ORCH
    ORCH --> OUTPUT[Output]
    
    style ORCH fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style LLM fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style TOOLS fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style MEM fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style PLAN fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
</pre>

---

## 4. 그래서 프레임워크마다 뭐가 다른데?

공통 구조는 같지만, **어디에 힘을 줬느냐**가 다릅니다:

| 프레임워크 | 특화 컴포넌트 | 설계 철학 |
|-----------|-------------|----------|
| **LangGraph** | Orchestrator | 복잡한 상태 기계, 분기/루프 |
| **AutoGen** | Orchestrator | 멀티 에이전트 대화 |
| **CrewAI** | Planning | 역할 기반 협업 (PM, Dev, QA) |
| **DSPy** | LLM Backbone | 프롬프트 자동 최적화 |
| **LlamaIndex** | Memory | RAG, 문서 검색 특화 |
| **MetaGPT** | Planning | SW 개발 파이프라인 |
| **smolagents** | 전체 | 경량화, 최소 의존성 |
| **PydanticAI** | Tools | 타입 안전한 출력 |

---

## 5. 정리

**모든 AI Agent의 공식:**

```
Agent = Orchestrator(
    brain = LLM,
    hands = Tools,
    memory = Memory,
    strategy = Planning
)
```

프레임워크 선택 기준:

- **복잡한 워크플로우** → LangGraph
- **여러 Agent 협업** → AutoGen, CrewAI
- **문서 기반 QA** → LlamaIndex
- **프롬프트 최적화** → DSPy
- **가볍게 시작** → smolagents

---

## 다음 편 예고

> **해체분석기 #3: LangGraph 깊게 파보기**
>
> - 상태 기계(State Machine)란?
> - 왜 Graph 구조인가?
> - 실제 구현 예시

---

## 참고 자료

- [LangChain Conceptual Guide](https://python.langchain.com/docs/concepts/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [Building Effective Agents - Anthropic](https://www.anthropic.com/research/building-effective-agents)
