---
title: "해체분석기 #4: Pydantic AI - FastAPI 느낌의 Agent 프레임워크"
date: 2026-02-04T12:30:00+09:00
summary: "Pydantic 팀이 만든 타입 안전한 AI Agent 프레임워크. 의존성 주입, 구조화된 출력, Graph까지 뜯어봅니다"
tags: ["ai-agent", "해체분석기", "pydantic-ai", "pydantic"]
categories: ["AI"]
series: ["해체분석기"]
draft: false
mermaid: true
---

> 이 글은 [Pydantic AI](https://github.com/pydantic/pydantic-ai) GitHub과 [공식 문서](https://ai.pydantic.dev/)를 직접 분석하여 작성되었습니다.

## 들어가며

Pydantic AI의 공식 소개:

> "A Python agent framework designed to help you quickly, confidently, and painlessly build **production grade** applications"

핵심 메시지는 "FastAPI 느낌을 GenAI 개발에 가져오겠다"입니다.

실제로 Pydantic은 OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex, CrewAI 등 거의 모든 AI 라이브러리의 **validation layer**입니다. "파생 라이브러리 말고 본가를 쓰세요" 라는 자신감이 느껴집니다.

---

## 1. 전체 구조 한눈에 보기

<pre class="mermaid">
flowchart TB
    subgraph Core["Core Components"]
        Agent["Agent<br/>Generic[DepsT, OutputT]"]
        RunContext["RunContext<br/>Dependency Carrier"]
        Tool["@agent.tool<br/>Function Tools"]
    end
    
    subgraph Output["Output System"]
        Pydantic["Pydantic Models<br/>Structured Output"]
        Validation["Auto Validation<br/>+ Retry on Error"]
    end
    
    subgraph Advanced["Advanced Features"]
        Graph["pydantic-graph<br/>State Machine"]
        MCP["MCP Integration<br/>External Tools"]
        Durable["Durable Execution<br/>Temporal/DBOS/Prefect"]
    end
    
    subgraph Observability["Observability"]
        Logfire["Pydantic Logfire<br/>OpenTelemetry"]
    end
    
    Agent --> RunContext
    Agent --> Tool
    Agent --> Pydantic
    Pydantic --> Validation
    Agent --> Graph
    Agent --> MCP
    Agent --> Durable
    Agent --> Logfire
</pre>

Pydantic AI는 **단순함을 유지하면서도 확장 가능한** 구조입니다. 핵심은 `Agent` 클래스 하나입니다.

---

## 2. Agent: 타입 안전한 설계

### Generic Type Parameters

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class SupportOutput(BaseModel):
    advice: str
    risk: int

# Agent[DependencyType, OutputType]
agent = Agent[MyDeps, SupportOutput](
    'openai:gpt-5',
    deps_type=MyDeps,
    output_type=SupportOutput,
)
```

Agent는 두 가지 타입으로 제네릭화됩니다:
- **DepsT**: 의존성 타입 (DB 연결, 사용자 정보 등)
- **OutputT**: 출력 타입 (Pydantic 모델로 검증)

IDE가 타입을 추론하고, 잘못된 타입은 **컴파일 타임**에 잡힙니다.

### 실행 방법 5가지

| 메서드 | 특징 |
|--------|------|
| `run()` | async, 완료된 결과 반환 |
| `run_sync()` | sync wrapper |
| `run_stream()` | async context manager, 스트리밍 |
| `run_stream_events()` | 이벤트 단위 스트리밍 |
| `iter()` | Graph 노드 단위 순회 |

```python
# 동기 실행
result = agent.run_sync('What is my balance?', deps=deps)

# 스트리밍
async with agent.run_stream('Tell me a story') as response:
    async for text in response.stream_text():
        print(text, end='')
```

---

## 3. Dependency Injection: RunContext

다른 프레임워크와 차별화되는 핵심 기능입니다.

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class SupportDependencies:
    customer_id: int
    db: DatabaseConn

agent = Agent('openai:gpt-5', deps_type=SupportDependencies)

@agent.tool
async def customer_balance(
    ctx: RunContext[SupportDependencies],  # 타입 체크!
    include_pending: bool
) -> float:
    """Returns the customer's current account balance."""
    return await ctx.deps.db.customer_balance(
        id=ctx.deps.customer_id,
        include_pending=include_pending,
    )
```

**RunContext가 하는 일:**
- 의존성을 타입 안전하게 전달
- Tool 함수에서 `ctx.deps`로 접근
- 잘못된 타입은 static type checker가 잡음

**왜 좋은가:**
- 테스트할 때 mock 주입 쉬움
- DB 연결, API 클라이언트 등을 깔끔하게 전달
- FastAPI의 `Depends`와 같은 철학

---

## 4. Structured Output: Pydantic 본가의 위력

```python
from pydantic import BaseModel, Field

class SupportOutput(BaseModel):
    support_advice: str = Field(description='Advice returned to the customer')
    block_card: bool = Field(description="Whether to block the customer's card")
    risk: int = Field(description='Risk level of query', ge=0, le=10)

agent = Agent(
    'openai:gpt-5',
    output_type=SupportOutput,  # 반드시 이 형태로 출력
)
```

**동작 방식:**
1. Pydantic 모델 → JSON Schema 자동 생성
2. LLM에게 스키마 전달
3. 응답을 Pydantic으로 검증
4. **검증 실패 시 → 에러 메시지와 함께 LLM에게 재요청** (Self-correction)

다른 프레임워크도 Pydantic을 쓰지만, **본가답게 통합이 매끄럽습니다.**

---

## 5. Tools: 데코레이터 기반 등록

```python
@agent.tool_plain  # context 불필요
def roll_dice() -> str:
    """Roll a six-sided die and return the result."""
    return str(random.randint(1, 6))

@agent.tool  # context 필요
def get_player_name(ctx: RunContext[str]) -> str:
    """Get the player's name."""
    return ctx.deps
```

**두 가지 데코레이터:**
- `@agent.tool`: RunContext 필요 (의존성 접근)
- `@agent.tool_plain`: 순수 함수

**Docstring = LLM에게 전달되는 설명:**
```python
@agent.tool
async def weather_forecast(ctx: RunContext, location: str) -> str:
    """Get weather forecast for a location.
    
    Args:
        location: City name or coordinates
    """
```

Docstring의 Args 섹션까지 파싱해서 파라미터 설명으로 사용합니다.

---

## 6. Instructions: 정적 + 동적

```python
# 정적 instructions
agent = Agent(
    'openai:gpt-5',
    instructions='You are a helpful bank support agent.',
)

# 동적 instructions (DI 활용)
@agent.instructions
async def add_customer_name(ctx: RunContext[SupportDependencies]) -> str:
    customer_name = await ctx.deps.db.customer_name(id=ctx.deps.customer_id)
    return f"The customer's name is {customer_name!r}"
```

동적 instructions는 **런타임에 의존성을 기반으로** 프롬프트를 구성합니다. 고객 이름, 현재 시간, 사용자 권한 등을 동적으로 주입할 수 있습니다.

---

## 7. pydantic-graph: 별도의 그래프 라이브러리

복잡한 워크플로우를 위한 **상태 기계** 라이브러리입니다. Pydantic AI와 별도로 사용할 수 있습니다.

```python
from dataclasses import dataclass
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

@dataclass
class DivisibleBy5(BaseNode[None, None, int]):
    foo: int

    async def run(self, ctx: GraphRunContext) -> 'Increment | End[int]':
        if self.foo % 5 == 0:
            return End(self.foo)
        return Increment(self.foo)

@dataclass
class Increment(BaseNode):
    foo: int

    async def run(self, ctx: GraphRunContext) -> DivisibleBy5:
        return DivisibleBy5(self.foo + 1)

graph = Graph(nodes=[DivisibleBy5, Increment])
result = graph.run_sync(DivisibleBy5(4))
print(result.output)  # 5
```

**특징:**
- 노드는 dataclass
- 반환 타입 annotation = 다음 노드 (엣지)
- `End[T]` 반환 = 그래프 종료
- Mermaid 다이어그램 자동 생성

<pre class="mermaid">
stateDiagram-v2
    [*] --> DivisibleBy5
    DivisibleBy5 --> Increment
    DivisibleBy5 --> [*]
    Increment --> DivisibleBy5
</pre>

공식 문서의 경고:
> "Graphs are a nail gun. Don't use a nail gun unless you need a nail gun."

대부분의 경우 단순한 Agent 조합으로 충분하고, Graph는 **정말 복잡한 상태 기계**가 필요할 때만 쓰라는 조언입니다.

---

## 8. MCP 통합

Model Context Protocol을 세 가지 방식으로 지원합니다:

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServer

# MCP 서버에 연결
agent = Agent(
    'openai:gpt-5',
    toolsets=[MCPServer('http://localhost:8080')],
)
```

**지원 방식:**
1. **MCPServer**: Pydantic AI가 직접 MCP 클라이언트로 연결
2. **FastMCPToolset**: FastMCP 라이브러리 활용
3. **MCPServerTool**: 모델 프로바이더의 built-in MCP 지원

---

## 9. Durable Execution

장시간 실행, 실패 복구가 필요한 워크플로우를 위해 세 가지 솔루션과 통합됩니다:

| 솔루션 | 특징 |
|--------|------|
| **Temporal** | 가장 성숙한 워크플로우 엔진 |
| **DBOS** | 데이터베이스 기반 durability |
| **Prefect** | Python 네이티브 오케스트레이션 |

API 실패, 앱 재시작에도 진행 상태를 보존하고 이어서 실행할 수 있습니다.

---

## 10. Observability: Pydantic Logfire

```python
import logfire

logfire.configure()  # OpenTelemetry 설정
logfire.instrument_pydantic_ai()  # 자동 계측
```

**제공 기능:**
- 실시간 디버깅
- 비용 추적
- Evals 기반 성능 모니터링
- 기존 OTel 백엔드와도 호환

---

## 11. 다른 프레임워크와 비교

| 특징 | Pydantic AI | LangGraph | CrewAI |
|------|-------------|-----------|--------|
| **철학** | FastAPI 스타일 | 그래프 우선 | Role-playing |
| **타입 안전성** | ⭐⭐⭐ 최고 | ⭐⭐ | ⭐ |
| **학습 곡선** | 낮음 | 높음 | 중간 |
| **유연성** | 높음 | 매우 높음 | 중간 |
| **Structured Output** | 네이티브 | 별도 설정 | 별도 설정 |
| **Graph 지원** | 별도 라이브러리 | 핵심 기능 | X |

**Pydantic AI가 적합한 경우:**
- FastAPI 경험이 있는 팀
- 타입 안전성이 중요한 프로덕션 환경
- 구조화된 출력이 핵심인 애플리케이션
- 복잡한 그래프 없이 깔끔한 에이전트가 필요한 경우

---

## 12. 코드로 보는 핵심 패턴

### 완전한 예제: 은행 지원 에이전트

```python
from dataclasses import dataclass
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

# 1. Dependencies 정의
@dataclass
class SupportDependencies:
    customer_id: int
    db: DatabaseConn

# 2. Output 스키마 정의
class SupportOutput(BaseModel):
    support_advice: str = Field(description='Advice for customer')
    block_card: bool = Field(description='Whether to block card')
    risk: int = Field(ge=0, le=10)

# 3. Agent 생성
support_agent = Agent(
    'openai:gpt-5',
    deps_type=SupportDependencies,
    output_type=SupportOutput,
    instructions='You are a bank support agent.',
)

# 4. Dynamic instructions
@support_agent.instructions
async def add_customer_name(ctx: RunContext[SupportDependencies]) -> str:
    name = await ctx.deps.db.customer_name(id=ctx.deps.customer_id)
    return f"Customer name: {name}"

# 5. Tools
@support_agent.tool
async def customer_balance(
    ctx: RunContext[SupportDependencies], 
    include_pending: bool
) -> float:
    """Returns the customer's current account balance."""
    return await ctx.deps.db.customer_balance(
        id=ctx.deps.customer_id,
        include_pending=include_pending,
    )

# 6. 실행
async def main():
    deps = SupportDependencies(customer_id=123, db=DatabaseConn())
    result = await support_agent.run('What is my balance?', deps=deps)
    print(result.output)  # SupportOutput 타입 보장
```

---

## 마무리

Pydantic AI의 핵심 가치:

1. **"If it compiles, it works"** - Rust 철학을 Python에
2. **FastAPI 경험의 재활용** - 익숙한 패턴
3. **본가의 통합** - Pydantic validation이 네이티브
4. **점진적 복잡성** - 단순하게 시작, 필요하면 Graph

복잡한 그래프나 멀티 에이전트가 필요하지 않다면, **가장 깔끔하고 타입 안전한** 선택지입니다.

---

## 참고 자료

- [GitHub: pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai)
- [공식 문서](https://ai.pydantic.dev/)
- [pydantic-graph 문서](https://ai.pydantic.dev/graph/)
- [Pydantic Logfire](https://pydantic.dev/logfire)
