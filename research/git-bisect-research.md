# Git Bisect 리서치 노트

## 주제: "Bisect - 버그를 찾는 이진 탐색"

작성일: 2026-02-17

---

## 1. Bisect란 무엇인가?

### 핵심 개념
- **Bisect = 이진 탐색으로 버그 커밋 찾기**: "이 버전엔 있는데 저 버전엔 없다"는 정보로 범위를 절반씩 줄여가며 원인 커밋을 찾는 도구
- 커밋 히스토리가 N개면 최대 **log₂(N)번**의 테스트로 범인을 특정
- Linear search라면 1000개 커밋 = 최대 1000번. Bisect = 최대 10번!
- 수동으로 했던 "이 커밋 테스트해봐" 과정을 Git이 자동으로 안내

### 핵심 전제
- **버그가 단조롭다**: 어떤 시점까지는 정상, 그 이후로는 버그가 있음
  - good: 정상 동작하는 오래된 커밋
  - bad: 버그가 있는 현재 커밋
  - 사이의 커밋들 중 "첫 번째 bad"를 찾는 것이 목표

---

## 2. git bisect 기본 흐름

### 명령어 시퀀스
```
git bisect start          ← bisect 세션 시작
git bisect bad HEAD       ← 현재(bad)로 표시
git bisect good v1.0      ← 정상이었던 커밋/태그 표시
                          ← Git이 중간 커밋으로 checkout
                          ← 테스트 후...
git bisect good           ← 이 커밋은 정상
                          ← Git이 다시 중간으로 checkout
git bisect bad            ← 이 커밋은 버그 있음
                          ← ...반복...
                          ← "first bad commit" 발견!
git bisect reset          ← 원래 HEAD로 복귀, 세션 종료
```

### bisect skip
- 특정 커밋이 테스트 불가(빌드 실패 등)할 때: `git bisect skip`
- 스킵된 커밋이 많아지면 Git이 랜덤 선택 알고리즘으로 다음 커밋 결정
- Exit code 125: `git bisect run`에서 skip을 의미

### bisect terms (커스텀 용어)
```bash
git bisect start --term-old=fixed --term-new=broken
git bisect broken HEAD
git bisect fixed v2.0
```
- 성능 회귀 같은 경우: `--term-old=fast --term-new=slow`
- 기본값은 good/bad

---

## 3. 내부 동작 원리 (.git/BISECT_* 파일들)

### bisect 세션 중 생성되는 파일들
```
.git/
├── BISECT_HEAD       ← 현재 테스트 중인 커밋 SHA
├── BISECT_LOG        ← bisect 세션 전체 이력
├── BISECT_TERMS      ← 현재 세션의 good/bad 용어 정의
├── BISECT_START      ← bisect 시작 시의 원래 HEAD (reset용)
└── refs/
    └── bisect/
        ├── good-<sha>    ← good으로 마킹된 커밋들
        └── bad           ← bad로 마킹된 최신 커밋
```

### BISECT_LOG 예시
```
# bad: [f1e2d3c] Add new payment flow
# good: [a1b2c3d] Release v1.0
git bisect start
git bisect bad f1e2d3c
git bisect good a1b2c3d
# good: [7890abc] Implement user auth
git bisect good 7890abc
# bad: [3f4e5d6] Add cart abandonment tracking
git bisect bad 3f4e5d6
```

### BISECT_TERMS 내용
```
BISECT_TERM_OLD=good
BISECT_TERM_NEW=bad
```

### 핵심 발견: BISECT_HEAD
- `git bisect start`를 하면 Git은 HEAD를 detached 상태로 만듦
- `BISECT_HEAD`가 detached HEAD를 추적
- `.git/HEAD`는 `ref: refs/bisect/HEAD`가 아니라 직접 SHA 가리킴

### 알고리즘: 최적 이등분점 찾기
1. bad 커밋의 모든 조상 + good 커밋의 조상이 아닌 것 = "의심 범위"
2. 각 커밋에 "자신이 선택됐을 때 제거되는 커밋 수" 계산
3. `min(자신이 good일 때 제거, bad일 때 제거)`를 최대화하는 커밋 선택
4. = 어느 방향으로 결과가 나와도 최대한 많이 제거되는 지점

DAG(방향 비순환 그래프)에서의 이진탐색이라 단순 중간값 아님!

---

## 4. git bisect run (자동화)

### 기본 구조
```bash
git bisect run <command> [args...]
```

### Exit code 규칙
- `0` → good (정상)
- `1-124, 126-127` → bad (버그 있음)
- `125` → skip (이 커밋은 테스트 불가, 건너뜀)
- `128+` → bisect 자체를 중단 (치명적 오류)

### 실전 예시들

```bash
# 단순 테스트
git bisect run npm test

# 빌드 성공 여부
git bisect run make

# 특정 테스트만
git bisect run pytest tests/test_payment.py -k test_checkout

# 복합 스크립트
git bisect run ./test-regression.sh
```

### 스크립트 패턴 (빌드 실패는 skip)
```bash
#!/bin/sh
# test-regression.sh
make || exit 125  # 빌드 안 되면 skip
./run-test        # 테스트 실행 (0=good, non-zero=bad)
```

---

## 5. 실전 디버깅 사례

### 사례 1: 프론트엔드 성능 회귀
```bash
git bisect start --term-old=fast --term-new=slow
git bisect slow HEAD
git bisect fast v2.1.0
git bisect run sh -c 'npm run build && node measure-perf.js'
```

### 사례 2: 테스트 자동화
```bash
git bisect start HEAD v3.0.0
git bisect run pytest tests/ -x --tb=no -q
```

### 사례 3: 결과 로그 재현
```bash
# bisect log 저장
git bisect log > bisect-session.log

# 나중에 재현
git bisect replay bisect-session.log
```

### 사례 4: 커스텀 터미널
```bash
git bisect visualize  # gitk로 남은 범위 시각화
git bisect visualize --oneline  # 터미널에서 텍스트로
```

---

## 6. Bisect 구현 역사

### 최초 구현 (2005년 9월)
- **Linus Torvalds**가 2005년 9월 20일 Linux Kernel Mailing List에 소개
- 초기 버전은 "truly stupid" 알고리즘 (Linus 본인이 표현)
  - 단순히 커밋을 반으로 나누는 방식
  - merge가 많은 DAG에서는 최적이 아니었음
- 리눅스 커널 개발에서 회귀 버그 찾기의 실용적 필요성에서 출발

### 알고리즘 개선 (Junio Hamano)
- Junio Hamano가 DAG 기반 최적 이등분점 알고리즘으로 개선
- `min(ancestors, N - ancestors)` 최대화로 최악의 경우도 보장
- `git rev-list --bisect-all`로 각 커밋의 bisect 점수 확인 가능

### git bisect skip 추가 (2008년 2월)
- Git 1.5.4 (2008-02-01)에서 skip 기능 도입
- 초기엔 단순히 다음 커밋 선택
- Git 1.6.4 (2009-07-29)에서 랜덤화 알고리즘으로 개선
  - Ingo Molnar, H. Peter Anvin의 기여
  - skip 커밋이 많을 때 더 효과적으로 탐색

### Shell → C 재구현
- 초기: Shell 스크립트 (`git-bisect.sh`)
- 현재: C 언어 구현 (`builtin/bisect.c`)
- Shell 버전의 성능 문제를 해결하기 위해 점진적으로 이전

### bisect--helper 중간 단계
- `git bisect--helper`라는 중간 단계 존재
- Shell에서 C 함수를 호출하는 하이브리드 방식이 있었음
- 현재는 완전히 C로 통합

---

## 주요 참고 자료

- [git-bisect 공식 문서](https://git-scm.com/docs/git-bisect)
- [git-bisect-lk2009: 알고리즘 심층 분석](https://git-scm.com/docs/git-bisect-lk2009)
- [Linus의 첫 bisect 소개 메일](https://yarchive.net/comp/linux/git_bisect.html)
- [LWN bisect run 소개 글](https://lwn.net/Articles/317154/)
