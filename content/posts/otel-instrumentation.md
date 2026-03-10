---
title: "OpenTelemetry 해체분석기 #7: Instrumentation — 텔레메트리는 어떻게 만들어지는가"
date: 2026-03-11T00:00:00+09:00
summary: "Zero-code는 런타임 마법으로 코드 변경 없이 텔레메트리를 뽑아내고, Code-based는 API/SDK로 비즈니스 맥락을 직접 심는다. 둘은 양자택일이 아니라 조합이다."
tags: ["opentelemetry", "observability", "해체분석기", "instrumentation", "auto-instrumentation"]
categories: ["Observability"]
series: ["OpenTelemetry 해체분석기"]
series_order: 7
draft: false
mermaid: true
toc: true
---

> 이 글은 [OpenTelemetry Zero-code Instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/zero-code/), [Code-based Instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/code-based/), [Libraries](https://opentelemetry.io/docs/concepts/instrumentation/libraries/) 공식 문서를 기반으로 작성되었습니다.

[#6](/posts/otel-baggage-and-profiles/)까지 OTel의 다섯 가지 신호를 모두 다뤘다. 이제 **"그 신호들은 실제로 어떻게 만들어지는가"**에 답할 차례다.

OTel은 텔레메트리를 생성하는 두 가지 경로를 제공한다: **Zero-code**와 **Code-based**. 이름 그대로, 코드를 안 건드리느냐 건드리느냐의 차이다.

---

## Zero-Code Instrumentation: 코드 변경 없이 텔레메트리 얻기

### 원리

Zero-code(자동) instrumentation의 핵심 아이디어는 단순하다:

> **라이브러리의 함수 호출을 가로채서, 원래 동작 전후에 OTel API 호출을 끼워넣는다.**

HTTP 클라이언트의 `send()`, DB 드라이버의 `execute()` 같은 함수를 감싸서(wrap), 개발자가 작성한 코드는 그대로 두되 **실행 시점에 텔레메트리가 자동 생성**되게 하는 것이다.

```mermaid
sequenceDiagram
    participant App as 애플리케이션
    participant Wrap as OTel Wrapper
    participant Lib as 원본 라이브러리
    participant SDK as OTel SDK

    App->>Wrap: requests.get(url)
    Wrap->>SDK: span.start("HTTP GET")
    Wrap->>Lib: 원본 requests.get(url)
    Lib-->>Wrap: response
    Wrap->>SDK: span.set_attribute("http.status_code", 200)
    Wrap->>SDK: span.end()
    Wrap-->>App: response
```

앱 코드는 `requests.get()`을 호출했을 뿐인데, 사이에 끼어든 Wrapper가 Span을 만들고 Attribute를 채우고 닫는다.

### 언어별 "끼워넣기" 방식

이 "가로채기"를 구현하는 방식은 언어 런타임마다 다르다:

| 기법 | 대상 언어 | 원리 |
|------|-----------|------|
| **Bytecode Instrumentation** | Java, .NET | 클래스 로딩 시 **바이트코드를 수정**해서 계측 코드 주입. JVM Agent나 CLR Profiling API 사용 |
| **Monkey Patching** | Python, Node.js, Ruby | 런타임에 기존 함수/모듈을 **계측 버전으로 교체**. 동적 언어의 유연성 활용 |
| **eBPF** | Go, C/C++ (Linux) | **커널 레벨**에서 시스템 콜·네트워크를 모니터링. 바이너리 수정 없이 동작하지만 Linux 전용 |

방식은 달라도 결과는 같다: **앱 코드 변경 없이, 인프라 레벨 Span이 자동 생성**된다.

### 실행 예시 (Python)

```bash
# 1. OTel 배포판 + OTLP Exporter 설치
pip install opentelemetry-distro opentelemetry-exporter-otlp

# 2. 사용 중인 라이브러리를 감지해서 계측 패키지 자동 설치
opentelemetry-bootstrap -a install

# 3. 계측 에이전트로 앱 실행 — 코드 수정 없음
OTEL_SERVICE_NAME=order-service \
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 \
opentelemetry-instrument python app.py
```

이것만으로 Flask/Django 라우트, requests/urllib3 HTTP 호출, psycopg2/pymongo DB 쿼리 등에서 Span이 자동으로 만들어진다.

### 자동 계측의 한계

Zero-code가 잡아주는 건 **라이브러리 경계의 I/O 동작**뿐이다:

```
✅ 자동으로 잡히는 것              ❌ 안 잡히는 것
─────────────────────            ─────────────────────
HTTP 요청/응답                    비즈니스 로직 흐름
DB 쿼리 실행                      도메인 Attribute (userId, orderId)
gRPC 호출                         조건부 분기 내 세부 동작
메시지 큐 produce/consume          커스텀 이벤트, 에러 분류
```

"DB 쿼리가 느리다"는 알 수 있지만, **"어떤 사용자의 어떤 주문 때문에 느린지"**는 알 수 없다. 여기서 Code-based가 필요해진다.

---

## Code-Based Instrumentation: 비즈니스 맥락을 직접 심기

### API와 SDK의 분리

Code-based instrumentation을 이해하려면 OTel의 핵심 설계 원칙부터 알아야 한다:

```mermaid
flowchart LR
    subgraph "라이브러리 (공유 코드)"
        API["OTel API\n텔레메트리 기록 인터페이스"]
    end

    subgraph "애플리케이션 (진입점)"
        SDK["OTel SDK\n처리 + 내보내기 구현체"]
    end

    API -->|"SDK가 있으면\n실제 동작"| SDK
    API -.->|"SDK가 없으면\nno-op (아무것도 안 함)"| NOOP["∅"]
```

| | API | SDK |
|---|---|---|
| **역할** | 텔레메트리 **기록** 인터페이스 | 텔레메트리 **처리·내보내기** 구현체 |
| **누가 의존?** | 라이브러리 작성자 | 앱 운영자 |
| **무게** | 가벼움 | 무거움 (Exporter, Processor 포함) |

왜 이렇게 나눠놨을까? **라이브러리는 API만 의존하면 된다.** 그 라이브러리를 쓰는 앱이 SDK를 설정하면 텔레메트리가 수집되고, 안 하면 no-op으로 빠진다. 라이브러리 입장에서는 어느 쪽이든 안전하게 동작한다.

### 직접 계측하기

Code-based의 전형적인 흐름:

```python
from opentelemetry import trace

# Tracer 이름은 "계측 주체"를 식별한다
# — 라이브러리라면 라이브러리 이름, 서비스라면 서비스 이름
tracer = trace.get_tracer("order-service", "1.2.0")

def process_order(order_id: str, user_id: str):
    with tracer.start_as_current_span("process-order") as span:
        # 비즈니스 맥락을 Attribute로 — Zero-code로는 불가능한 부분
        span.set_attribute("order.id", order_id)
        span.set_attribute("user.id", user_id)

        validate_payment(order_id)

        span.add_event("payment-validated", {"amount": 150.0})

        ship_order(order_id)
```

Zero-code가 만든 HTTP/DB Span 위에, Code-based로 **비즈니스 의미가 담긴 Span과 Attribute**를 추가하는 것이다.

---

## Instrumentation Library와 Native Instrumentation

사실 Zero-code와 Code-based 사이에는 **계측을 누가 작성하느냐**에 따른 중요한 구분이 하나 더 있다.

### Instrumentation Library: 외부에서 감싸기

대부분의 라이브러리(Flask, requests, psycopg2 등)는 OTel 코드가 내장돼 있지 않다. 그래서 OTel 커뮤니티가 **별도 패키지**로 감싸는 계측을 만들어 둔 것이 Instrumentation Library다:

```python
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# Flask 자체에는 OTel 코드가 없지만,
# 이 패키지가 before_request/after_request 훅을 이용해 Span을 만든다
FlaskInstrumentor().instrument_app(app)
```

코드 한 줄이긴 하지만, 바깥에서 감싸는 것이기 때문에 **라이브러리가 공개한 훅과 인터페이스만큼만** 계측할 수 있다는 한계가 있다. Zero-code 에이전트가 내부적으로 하는 일도 결국 이 Instrumentation Library를 런타임에 자동 적용하는 것이다.

### Native Instrumentation: 라이브러리 자체에 내장

OTel이 궁극적으로 지향하는 방향은 **라이브러리 작성자가 직접 OTel API를 호출**하는 것이다:

```python
# HTTP 프레임워크 내부 코드 — API"만" 의존
from opentelemetry import trace

tracer = trace.get_tracer("my-http-framework", "2.0.0")

class Router:
    def handle_request(self, request):
        with tracer.start_as_current_span(f"{request.method} {request.path}") as span:
            span.set_attribute("http.method", request.method)
            return self._dispatch(request)
```

라이브러리 작성자가 내부 동작을 가장 잘 알기 때문에, 외부 Wrapper보다 **더 정확하고 풍부한 텔레메트리**를 만들 수 있다.

핵심 규칙: **API만 의존하고, 절대 SDK에 의존하지 않는다.** SDK가 없으면 모든 API 호출이 no-op이 되어 성능 영향이 제로다. 라이브러리 사용자가 SDK를 설정할지 말지 **선택**하게 두는 것이다.

OTel 프로젝트의 공식 입장도 명확하다: "장기적으로는 Native Instrumentation이 표준이 되길 바라고, Instrumentation Library는 그 갭을 메우는 과도기적 해법이다."

### 세 계층을 한 그림으로

```mermaid
flowchart TB
    subgraph layer1["Layer 1: Zero-Code Agent"]
        Z["에이전트가 런타임에 자동 주입\n코드 변경 제로"]
    end

    subgraph layer2["Layer 2: Instrumentation Library"]
        IL["외부 패키지가 훅/콜백으로 감싸기\n코드 한 줄"]
    end

    subgraph layer3["Layer 3: Native + Code-Based"]
        N["라이브러리가 API 직접 호출\n+ 앱에서 비즈니스 Span 추가"]
    end

    layer1 -->|"같은 원리,\n자동 적용"| layer2
    layer2 -->|"더 정밀한\n계측 가능"| layer3

    style layer1 fill:#e8f5e9,stroke:#4caf50
    style layer2 fill:#e3f2fd,stroke:#2196f3
    style layer3 fill:#fff3e0,stroke:#ff9800
```

아래로 갈수록 **정밀도와 맥락이 풍부**해지고, 위로 갈수록 **코드 변경이 적다**. 실무에서는 세 계층을 조합한다: Zero-code로 인프라 가시성을 확보하고, Instrumentation Library로 프레임워크 계측을 보강하고, Native/Code-based로 비즈니스 맥락을 심는다.

---

## 시리즈 네비게이션

| # | 주제 | 링크 |
|---|------|------|
| 1 | Observability란 무엇인가 | [보기](/posts/otel-observability-primer/) |
| 2 | Context Propagation | [보기](/posts/otel-context-propagation/) |
| 3 | Traces — Span 해부 | [보기](/posts/otel-traces-deep-dive/) |
| 4 | Metrics — 숫자로 말한다 | [보기](/posts/otel-metrics-deep-dive/) |
| 5 | Logs — 연결한다 | [보기](/posts/otel-logs-deep-dive/) |
| 6 | Baggage & Profiles | [보기](/posts/otel-baggage-and-profiles/) |
| **7** | **Instrumentation** | **현재 글** |
