---
title: "Phoenix: LLM 애플리케이션 Observability 완벽 가이드"
date: 2026-03-06T17:30:00+09:00
summary: "Arize Phoenix를 활용한 LLM 트레이싱, 평가, 실험 환경 구축. 로컬부터 Kubernetes까지 다양한 배포 방법과 실전 사용법을 다룹니다."
tags: ["phoenix", "llm", "observability", "tracing", "opentelemetry", "ai"]
categories: ["AI/ML"]
draft: false
mermaid: true
---

> 이 글은 [Arize-ai/phoenix](https://github.com/Arize-ai/phoenix) 공식 문서와 레포지토리를 기반으로 작성되었습니다.

## Phoenix란?

**Phoenix**는 Arize AI에서 만든 오픈소스 LLM Observability 플랫폼입니다. LLM 애플리케이션의 트레이싱, 평가, 실험을 한 곳에서 관리할 수 있어요.

### 핵심 기능

| 기능 | 설명 |
|------|------|
| **Tracing** | OpenTelemetry 기반 LLM 호출 추적 |
| **Evaluation** | LLM-as-a-Judge로 품질 평가 |
| **Datasets** | 실험용 데이터셋 버전 관리 |
| **Experiments** | 프롬프트/모델 변경 A/B 테스트 |
| **Playground** | 프롬프트 최적화 및 모델 비교 |
| **Prompt Management** | 프롬프트 버전 관리 및 태깅 |

### 지원 프레임워크

```mermaid
graph LR
    subgraph Frameworks
        LangChain
        LlamaIndex
        DSPy
        CrewAI
        OpenAI_SDK[OpenAI Agents SDK]
        Vercel[Vercel AI SDK]
    end
    
    subgraph Providers
        OpenAI
        Anthropic
        Google[Google GenAI]
        Bedrock[AWS Bedrock]
        Mistral
    end
    
    Phoenix((Phoenix))
    
    Frameworks --> Phoenix
    Providers --> Phoenix
```

---

## 1. 빠른 시작: 로컬 설치

### pip 설치

```bash
pip install arize-phoenix
```

### Phoenix 서버 실행

```bash
# 터미널에서 직접 실행
phoenix serve

# 또는 Python에서
python -c "import phoenix as px; px.launch_app()"
```

기본적으로 `http://localhost:6006`에서 UI에 접근할 수 있습니다.

### Jupyter Notebook에서 실행

```python
import phoenix as px

# Phoenix 앱 실행 (백그라운드)
session = px.launch_app()

# UI 열기
session.view()
```

---

## 2. LLM 트레이싱 설정

### 2.1 OpenAI 트레이싱

```python
# 필요 패키지 설치
# pip install openinference-instrumentation-openai arize-phoenix-otel

from openinference.instrumentation.openai import OpenAIInstrumentor
from phoenix.otel import register
from openai import OpenAI

# Phoenix에 트레이스 전송 설정
tracer_provider = register()

# OpenAI 클라이언트 계측
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

# 이제 모든 OpenAI 호출이 자동으로 트레이싱됨
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### 2.2 LangChain 트레이싱

```python
# pip install openinference-instrumentation-langchain

from openinference.instrumentation.langchain import LangChainInstrumentor
from phoenix.otel import register

tracer_provider = register()
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

# LangChain 코드 실행 - 자동 트레이싱
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant."),
    ("user", "{input}")
])
llm = ChatOpenAI(model="gpt-4")
chain = prompt | llm

chain.invoke({"input": "What is LangChain?"})
```

### 2.3 LlamaIndex 트레이싱

```python
# pip install openinference-instrumentation-llama-index

from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
from phoenix.otel import register

tracer_provider = register()
LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
```

---

## 3. 배포 옵션

### 3.1 Docker (권장)

```bash
# 기본 실행
docker run -p 6006:6006 arizephoenix/phoenix:latest

# 데이터 영속화
docker run -p 6006:6006 \
  -v phoenix_data:/data \
  -e PHOENIX_WORKING_DIR=/data \
  arizephoenix/phoenix:latest
```

### 3.2 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  phoenix:
    image: arizephoenix/phoenix:latest
    ports:
      - "6006:6006"
      - "4317:4317"  # OTLP gRPC
    environment:
      - PHOENIX_WORKING_DIR=/data
      - PHOENIX_ENABLE_AUTH=true
      - PHOENIX_SECRET_KEY=your-secret-key
    volumes:
      - phoenix_data:/data

volumes:
  phoenix_data:
```

```bash
docker-compose up -d
```

### 3.3 Kubernetes (Helm)

```bash
# Helm 레포 추가
helm repo add phoenix https://arizephoenix.github.io/phoenix-helm

# 설치
helm install phoenix phoenix/phoenix \
  --namespace phoenix \
  --create-namespace \
  --set persistence.enabled=true \
  --set persistence.size=10Gi
```

### 3.4 프로덕션 구성 예시 (PostgreSQL 백엔드)

```yaml
# values.yaml
phoenix:
  image:
    tag: "version-8.0.0"  # 버전 고정 권장
  
  env:
    - name: PHOENIX_SQL_DATABASE_URL
      value: "postgresql://user:pass@postgres:5432/phoenix"
    - name: PHOENIX_ENABLE_AUTH
      value: "true"
    - name: PHOENIX_SECRET_KEY
      valueFrom:
        secretKeyRef:
          name: phoenix-secrets
          key: secret-key

  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "2Gi"
      cpu: "1000m"

  persistence:
    enabled: true
    size: 20Gi
```

---

## 4. 환경 변수 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `PHOENIX_PORT` | HTTP 포트 | 6006 |
| `PHOENIX_GRPC_PORT` | OTLP gRPC 포트 | 4317 |
| `PHOENIX_WORKING_DIR` | 데이터 저장 경로 | ~/.phoenix |
| `PHOENIX_SQL_DATABASE_URL` | PostgreSQL 연결 URL | (SQLite) |
| `PHOENIX_ENABLE_AUTH` | 인증 활성화 | false |
| `PHOENIX_SECRET_KEY` | JWT 서명 키 | (필수 if auth) |

---

## 5. 클라이언트에서 원격 Phoenix 연결

### Python

```python
import os
from phoenix.otel import register

# 원격 Phoenix 서버 지정
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "https://my-phoenix.example.com"
os.environ["PHOENIX_API_KEY"] = "your-api-key"  # 인증 사용 시

tracer_provider = register()
```

### TypeScript/Node.js

```typescript
import { register } from "@arizeai/phoenix-otel";

register({
  endpoint: "https://my-phoenix.example.com",
  headers: {
    "api-key": "your-api-key"
  }
});
```

---

## 6. 평가 (Evaluation) 실행

Phoenix의 강력한 기능 중 하나는 **LLM-as-a-Judge** 평가입니다.

### 6.1 기본 평가

```python
from phoenix.evals import (
    OpenAIModel,
    llm_classify,
    RAG_RELEVANCY_PROMPT_TEMPLATE,
)
import pandas as pd

# 평가용 데이터 준비
df = pd.DataFrame({
    "input": ["What is Python?", "How to cook pasta?"],
    "output": ["Python is a programming language.", "Boil water and add pasta."],
    "reference": ["Python is a high-level programming language.", "Cook pasta in boiling water."]
})

# 관련성 평가
model = OpenAIModel(model="gpt-4")
results = llm_classify(
    dataframe=df,
    template=RAG_RELEVANCY_PROMPT_TEMPLATE,
    model=model,
    rails=["relevant", "irrelevant"],
)
```

### 6.2 제공되는 평가 템플릿

| 템플릿 | 용도 |
|--------|------|
| `RAG_RELEVANCY` | 검색 결과 관련성 |
| `HALLUCINATION` | 환각 탐지 |
| `QA_CORRECTNESS` | 답변 정확성 |
| `TOXICITY` | 유해성 탐지 |
| `SUMMARIZATION` | 요약 품질 |

---

## 7. 실험 (Experiments) 워크플로

```mermaid
graph LR
    A[데이터셋 생성] --> B[실험 정의]
    B --> C[태스크 실행]
    C --> D[평가 실행]
    D --> E[결과 비교]
```

### 데이터셋 & 실험 예시

```python
from phoenix.client import Client

client = Client()

# 데이터셋 생성
dataset = client.create_dataset(
    name="qa-test-v1",
    examples=[
        {"input": "What is AI?", "expected": "Artificial Intelligence"},
        {"input": "What is ML?", "expected": "Machine Learning"},
    ]
)

# 실험 실행
def my_task(example):
    # LLM 호출 로직
    return {"output": call_llm(example["input"])}

experiment = client.run_experiment(
    dataset=dataset,
    task=my_task,
    evaluators=["correctness", "relevance"],
)

# 결과 확인
print(experiment.results)
```

---

## 8. MCP 서버로 활용

Phoenix는 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 서버로도 동작합니다.

```bash
# MCP 서버 실행
npx @arizeai/phoenix-mcp --baseUrl http://localhost:6006
```

Cursor나 다른 MCP 클라이언트에서 Phoenix 데이터에 접근 가능!

---

## 9. 아키텍처 이해

```mermaid
graph TB
    subgraph App["Your LLM App"]
        OI[OpenInference Instrumentation]
    end
    
    subgraph Phoenix["Phoenix Server"]
        OTLP[OTLP Receiver :4317]
        API[REST API :6006]
        UI[Web UI]
        DB[(Storage)]
    end
    
    OI -->|gRPC/HTTP| OTLP
    OTLP --> DB
    API --> DB
    UI --> API
    
    subgraph Storage["Storage Options"]
        SQLite
        PostgreSQL
    end
    
    DB --> Storage
```

### 스토리지 옵션

- **SQLite** (기본): 로컬 개발, 소규모 팀
- **PostgreSQL**: 프로덕션, 대규모 데이터, 고가용성

---

## 10. 팁 & 베스트 프랙티스

### 프로덕션 체크리스트

- [ ] Docker 이미지 버전 고정 (`version-X.X.X`)
- [ ] PostgreSQL 백엔드 사용
- [ ] 인증 활성화 (`PHOENIX_ENABLE_AUTH=true`)
- [ ] 데이터 보존 정책 설정
- [ ] 리소스 제한 설정 (K8s)
- [ ] Ingress + TLS 구성

### 트레이싱 최적화

```python
# 배치 처리로 성능 향상
from phoenix.otel import register

tracer_provider = register(
    batch=True,           # 배치 전송
    max_queue_size=2048,  # 큐 크기
    max_export_batch_size=512,
)
```

### 민감 정보 필터링

```python
from phoenix.otel import register

def redact_pii(span):
    # 민감 정보 마스킹
    if "ssn" in span.attributes.get("input", ""):
        span.attributes["input"] = "[REDACTED]"
    return span

tracer_provider = register(
    span_processor=redact_pii
)
```

---

## 마무리

Phoenix는 LLM 애플리케이션 개발에 필수적인 Observability를 제공합니다:

1. **쉬운 시작**: `pip install` 한 줄로 로컬 실행
2. **프로덕션 레디**: Docker, K8s, Helm 지원
3. **벤더 중립**: OpenTelemetry 표준 기반
4. **통합 플랫폼**: 트레이싱 + 평가 + 실험

LLM 앱을 운영 중이라면, Phoenix로 "블랙박스"를 열어보세요!

---

## 참고 자료

- [Phoenix GitHub](https://github.com/Arize-ai/phoenix)
- [Phoenix 공식 문서](https://arize.com/docs/phoenix/)
- [Phoenix Cloud](https://app.phoenix.arize.com/) - 무료 호스팅 버전
- [OpenInference](https://github.com/Arize-ai/openinference) - 계측 라이브러리
