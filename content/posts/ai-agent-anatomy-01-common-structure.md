---
title: "Agent 해체분석기 #1: AI Agent의 공통 구조"
date: 2026-02-03T21:54:00+09:00
summary: "LangGraph, AutoGen, CrewAI, DSPy... 실제 GitHub을 뜯어보며 공통점과 차이점을 분석합니다"
tags: ["ai-agent", "해체분석기", "langgraph", "autogen", "crewai", "dspy"]
categories: ["AI"]
series: ["Agent 해체분석기"]
series_order: 1
draft: false
mermaid: true
---

> 이 글은 실제 GitHub 레포지토리를 직접 분석하여 작성되었습니다.  
> 참조: LangGraph, AutoGen, CrewAI, DSPy, LlamaIndex, MetaGPT, smolagents, PydanticAI

## 들어가며

AI Agent 프레임워크가 쏟아지고 있습니다. 각각 다른 철학을 가지고 있지만, 뜯어보면 **공통된 뼈대**가 보입니다.

오늘은 주요 8개 프레임워크의 GitHub을 직접 분석해 공통 구조와 차별점을 정리합니다.

---

## 1. 프레임워크들의 자기 소개

먼저 각 프레임워크가 GitHub에서 자신을 어떻게 소개하는지 봅시다:

| 프레임워크 | 공식 설명 (GitHub) |
|-----------|-------------------|
| **LangGraph** | "low-level orchestration framework for building long-running, stateful agents" |
| **AutoGen** | "framework for creating multi-agent AI applications" |
| **CrewAI** | "Fast and Flexible Multi-Agent Automation Framework" |
| **DSPy** | "programming—not prompting—language models" |
| **LlamaIndex** | "data framework for building LLM-powered agents over your data" |
| **MetaGPT** | "First AI Software Company, Towards Natural Language Programming" |
| **smolagents** | "barebones library for agents that think in code" |
| **PydanticAI** | "GenAI Agent Framework, the Pydantic way" |

키워드를 뽑아보면:
- **Orchestration** (LangGraph)
- **Multi-Agent** (AutoGen, CrewAI, MetaGPT)
- **Programming** (DSPy, smolagents)
- **Data/RAG** (LlamaIndex)
- **Type-safe** (PydanticAI)

---

## 2. 공통 구조: 5가지 핵심 컴포넌트

모든 프레임워크가 공유하는 뼈대:

<pre class="mermaid">
flowchart TB
    ORCH[Orchestrator]
    PLAN[Planning]
    MEM[Memory]
    LLM[LLM]
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

| 컴포넌트 | 역할 | 모든 프레임워크에 존재? |
|---------|------|----------------------|
| 🔴 **Orchestrator** | 전체 루프/워크플로우 관리 | ✅ |
| 🟣 **Planning** | 작업 분해, 다음 액션 결정 | ✅ (복잡도 다름) |
| 🔵 **Memory** | 컨텍스트/히스토리 관리 | ✅ |
| 🟢 **LLM** | 추론/판단 | ✅ |
| 🟡 **Tools** | 외부 세계와 상호작용 | ✅ |

---

## 3. 각 프레임워크의 특화 영역

### 3.1 LangGraph: Orchestrator 특화

**철학:** "stateful agents as graphs"

LangGraph는 **상태 기계(State Machine)**를 그래프로 표현합니다.

```python
# LangGraph의 핵심 - StateGraph
from langgraph.graph import START, StateGraph

class State(TypedDict):
    text: str

graph = StateGraph(State)
graph.add_node("node_a", node_a)
graph.add_node("node_b", node_b)
graph.add_edge(START, "node_a")
graph.add_edge("node_a", "node_b")
```

**핵심 기능 (GitHub에서 강조):**
- Durable execution (실패해도 재개 가능)
- Human-in-the-loop (중간에 사람 개입)
- Comprehensive memory (단기 + 장기)

**언제 쓰나:** 복잡한 분기/루프가 있는 워크플로우

---

### 3.2 AutoGen: Multi-Agent 대화 특화

**철학:** "multi-agent AI applications"

AutoGen은 **여러 Agent가 대화**하며 문제를 해결합니다.

```python
# AutoGen의 핵심 - AgentTool로 Agent를 Tool처럼 사용
math_agent = AssistantAgent("math_expert", model_client=model_client)
math_agent_tool = AgentTool(math_agent)

chemistry_agent = AssistantAgent("chemistry_expert", model_client=model_client)
chemistry_agent_tool = AgentTool(chemistry_agent)

# 메인 Agent가 전문가 Agent들을 도구로 활용
agent = AssistantAgent(
    "assistant",
    tools=[math_agent_tool, chemistry_agent_tool],
)
```

**특징:**
- Agent를 Tool처럼 조합
- MCP Server 지원 (Playwright 등)
- Microsoft에서 개발 (→ Agent Framework로 발전 중)

**언제 쓰나:** 여러 전문 Agent가 협업해야 할 때

---

### 3.3 CrewAI: 역할 기반 협업 특화

**철학:** "role-playing, autonomous AI agents"

CrewAI는 **조직 구조**를 모방합니다.

```python
# CrewAI의 핵심 - Crew와 Flow
# Crews: 자율적 협업
# Flows: 이벤트 기반 정밀 제어
```

**GitHub에서 강조하는 차별점:**
- "Built from scratch, independent of LangChain"
- "High Performance: Optimized for speed"
- "Code = SOP(Team)" 철학 (MetaGPT와 유사)

**언제 쓰나:** PM/개발자/QA 같은 역할 분담이 명확할 때

---

### 3.4 DSPy: LLM 최적화 특화

**철학:** "programming—not prompting—language models"

DSPy는 **프롬프트를 코드처럼 컴파일**합니다.

```python
# DSPy의 핵심 - 선언적 프로그래밍
# 프롬프트를 직접 쓰지 않고, 
# 원하는 입출력을 정의하면 DSPy가 최적화
```

**Stanford NLP 논문 기반:**
> "Compiling Declarative Language Model Calls into Self-Improving Pipelines"  
> (ICLR 2024)

**언제 쓰나:** 프롬프트 엔지니어링에 지쳤을 때, 자동 최적화가 필요할 때

---

### 3.5 LlamaIndex: Data/RAG 특화

**철학:** "data framework for LLM-powered agents over your data"

LlamaIndex는 **데이터 연결과 검색**에 집중합니다.

```python
# LlamaIndex의 핵심 - 데이터 프레임워크
# 1. Data Connectors (PDF, API, SQL 등)
# 2. Indices/Graphs (데이터 구조화)
# 3. Retrieval/Query Interface (검색)
```

**핵심 개념:**
- "How do we best augment LLMs with our own private data?"
- 300+ 통합 패키지 (LlamaHub)

**언제 쓰나:** 내 데이터 기반 QA, RAG 파이프라인

---

### 3.6 MetaGPT: SW 개발 특화

**철학:** "Software Company as Multi-Agent System"

MetaGPT는 **소프트웨어 회사**를 시뮬레이션합니다.

```bash
# MetaGPT의 핵심 - 한 줄로 SW 개발
metagpt "Create a 2048 game"
# → PRD, 설계문서, 코드 전부 생성
```

**조직 구조:**
> "product managers / architects / project managers / engineers"

**핵심 철학:**
> Code = SOP(Team)

**언제 쓰나:** 요구사항 → 완성된 소프트웨어 자동화

---

### 3.7 smolagents: 경량화 특화

**철학:** "barebones library" + "agents that think in code"

smolagents는 **미니멀리즘**을 추구합니다.

```python
# smolagents의 핵심 - 코드 1000줄로 Agent
from smolagents import CodeAgent, WebSearchTool

agent = CodeAgent(tools=[WebSearchTool()], model=model)
agent.run("How many seconds...")
```

**HuggingFace에서 강조:**
- "logic for agents fits in ~1,000 lines of code"
- CodeAgent: 액션을 코드로 작성
- 샌드박스 실행 (E2B, Docker, Pyodide)

**언제 쓰나:** 가볍게 시작하고 싶을 때, 코드 실행 Agent

---

### 3.8 PydanticAI: 타입 안전성 특화

**철학:** "bring that FastAPI feeling to GenAI"

PydanticAI는 **검증과 타입**에 집중합니다.

**Pydantic 팀의 자부심:**
> "Pydantic Validation is the validation layer of OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex, AutoGPT, CrewAI..."

**핵심:**
- Fully Type-safe
- Pydantic Logfire 통합 (Observability)
- 구조화된 출력 보장

**언제 쓰나:** 프로덕션 안정성이 중요할 때

---

## 4. 한눈에 보는 비교표

| 프레임워크 | 특화 컴포넌트 | 핵심 철학 | 적합한 상황 |
|-----------|-------------|----------|-----------|
| **LangGraph** | Orchestrator | 상태 기계 as 그래프 | 복잡한 워크플로우, 분기/루프 |
| **AutoGen** | Orchestrator | Multi-Agent 대화 | 전문가 협업, Microsoft 생태계 |
| **CrewAI** | Planning | 역할 기반 협업 | 조직 구조 모방, LangChain 독립 |
| **DSPy** | LLM | 프롬프트 컴파일/최적화 | 프롬프트 자동화, 연구용 |
| **LlamaIndex** | Memory | 데이터 프레임워크 | RAG, 내 데이터 기반 QA |
| **MetaGPT** | Planning | SW 회사 시뮬레이션 | 자동 코드 생성, 요구사항→SW |
| **smolagents** | 전체 | 미니멀리즘, 코드 Agent | 가볍게 시작, HuggingFace 생태계 |
| **PydanticAI** | Tools | 타입 안전성 | 프로덕션, FastAPI 스타일 |

---

## 5. 어떤 프레임워크를 선택할까?

**결정 트리:**

```
복잡한 워크플로우가 필요한가?
├─ Yes → LangGraph
└─ No
    └─ 여러 Agent 협업이 필요한가?
        ├─ Yes → AutoGen or CrewAI
        └─ No
            └─ RAG/데이터 검색이 핵심인가?
                ├─ Yes → LlamaIndex
                └─ No
                    └─ 프롬프트 자동 최적화가 필요한가?
                        ├─ Yes → DSPy
                        └─ No
                            └─ 타입 안전성이 중요한가?
                                ├─ Yes → PydanticAI
                                └─ No → smolagents (가볍게 시작)
```

---

## 6. 정리

**모든 AI Agent의 공통 공식:**

```
Agent = Orchestrator(
    brain = LLM,
    hands = Tools,
    memory = Memory,
    strategy = Planning
)
```

**프레임워크의 차이는 "어디에 힘을 줬느냐":**

<pre class="mermaid">
flowchart LR
    LG[LangGraph]
    AG[AutoGen]
    CR[CrewAI]
    DS[DSPy]
    LI[LlamaIndex]
    MG[MetaGPT]
    SM[smolagents]
    PA[PydanticAI]
    
    LG -->|Orchestrator| ORCH[복잡한 워크플로우]
    AG -->|Multi-Agent| MULTI[Agent 대화/협업]
    CR -->|Roles| MULTI
    DS -->|Compiler| OPT[프롬프트 최적화]
    LI -->|Data| RAG[검색/RAG]
    MG -->|SOP| SW[SW 개발]
    SM -->|Minimal| SIMPLE[경량화]
    PA -->|Types| SAFE[타입 안전]
</pre>

---

## 다음 편 예고

> **해체분석기 #3: LangGraph 깊게 파보기**
>
> - StateGraph 실제 구현 분석
> - 왜 Graph 구조인가?
> - Durable execution은 어떻게 동작하나?

---

## 참고 자료

직접 분석한 GitHub 레포:
- [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
- [microsoft/autogen](https://github.com/microsoft/autogen)
- [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)
- [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy)
- [run-llama/llama_index](https://github.com/run-llama/llama_index)
- [geekan/MetaGPT](https://github.com/geekan/MetaGPT)
- [huggingface/smolagents](https://github.com/huggingface/smolagents)
- [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai)
