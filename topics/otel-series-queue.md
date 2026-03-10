# OpenTelemetry 해체분석기 시리즈 큐

> 자동 파이프라인용 주제 큐. 위에서부터 순서대로 소비됨.

## 대기 중

- id: otel-trace
  series_order: 2
  slug: otel-trace-internals
  title: "Trace 해체분석 - Span의 내부 구조"
  brief: "Span 데이터 모델, TraceID/SpanID 생성, Context Propagation 원리"

- id: otel-collector
  series_order: 3
  slug: otel-collector-internals
  title: "Collector 해체분석 - 파이프라인 아키텍처"
  brief: "Receiver/Processor/Exporter 구조, 데이터 흐름, 배포 패턴"

- id: otel-metric
  series_order: 4
  slug: otel-metric-internals
  title: "Metric 해체분석 - 시계열 데이터 모델"
  brief: "Counter/Gauge/Histogram, Temporality, Aggregation"

- id: otel-context
  series_order: 5
  slug: otel-context-propagation
  title: "Context Propagation 해체분석 - 분산 추적의 핵심"
  brief: "W3C Trace Context, Baggage, 언어별 Context API"

## 완료됨

- id: otel-philosophy
  series_order: 1
  slug: otel-philosophy-and-architecture
  title: "OpenTelemetry의 철학과 전체 구조"
  completed: 2026-03-10
