---
title: "Git 해체분석기 #20: Bisect - 버그를 찾는 이진 탐색"
date: 2026-02-17T21:00:00+09:00
draft: false
summary: "1000개의 커밋 중 버그를 10번 만에 찾는다. git bisect의 이진 탐색 알고리즘, .git/BISECT_* 파일들의 정체, 그리고 bisect run으로 완전 자동화하는 법"
tags: ["git", "해체분석기", "bisect", "debugging", "binary-search"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 20
weight: 20
mermaid: true
toc: true
---

> "어디서 망가진 거지?" — 버그를 쫓는 모든 개발자의 한숨

## 들어가며

배포 후 얼마 지나지 않아 버그 리포트가 들어왔습니다.

```
❌ 결제 버튼을 눌러도 아무것도 안 됩니다.
```

분명 두 달 전엔 잘 됐는데. 그 사이 커밋이 300개.
어디서부터 잘못된 걸까요?

브루트포스로 찾으면 최악의 경우 300번의 테스트.
하지만 **git bisect**를 쓰면 최대 **9번**이면 됩니다.

---

## 1. Bisect: 커밋 히스토리의 이진 탐색

이진 탐색(Binary Search)은 정렬된 배열에서 값을 찾을 때 중간을 기준으로 범위를 반씩 줄여가는 알고리즘입니다.

```
[1, 3, 5, 7, 9, 11, 13] 에서 9 찾기
         ↑ 중간(7) → 9 > 7이므로 오른쪽
               ↑ 중간(11) → 9 < 11이므로 왼쪽
             ↑ 중간(9) → 찾았다!
```

`git bisect`는 이 원리를 커밋 히스토리에 적용합니다.

```
커밋: [A B C D E F G H I J] ← J가 bad, A는 good
                 ↑ E 테스트 → good → [F G H I J] 범위로
                     ↑ H 테스트 → bad → [F G] 범위로
                   ↑ G 테스트 → bad → [F G] 범위로
                 ↑ F 테스트 → good → G가 first bad!
```

**핵심 전제**: "버그가 단조롭다" — 어느 시점까지는 정상, 그 이후론 버그가 있습니다. 커밋 N개라면 최대 **⌈log₂(N)⌉번**의 테스트로 원인을 찾습니다.

| 커밋 수 | 최대 테스트 횟수 |
|---------|----------------|
| 10 | 4번 |
| 100 | 7번 |
| 1,000 | 10번 |
| 10,000 | 14번 |

---

## 2. 기본 흐름: start → good/bad → reset

실제로 써봅시다. 결제 버튼 버그를 추적하는 상황입니다.

```bash
# 1. bisect 시작
$ git bisect start

# 2. 현재(HEAD)는 버그가 있다
$ git bisect bad HEAD

# 3. 두 달 전 릴리즈 태그는 정상이었다
$ git bisect good v2.0.0

# Git이 자동으로 중간 커밋으로 이동!
Bisecting: 149 revisions left to test after this (roughly 7 steps)
[3f4e5d6abc...] feat: implement cart abandonment tracking

# 4. 이 커밋에서 테스트해보니 정상이다
$ git bisect good

# Git이 다시 중간으로 이동
Bisecting: 74 revisions left to test after this (roughly 6 steps)
[9a8b7c6d5...] refactor: payment service restructure

# 5. 이 커밋에서 버그 발생!
$ git bisect bad

# ... (반복) ...

# 범인 발견!
f1e2d3c4b5a6 is the first bad commit
commit f1e2d3c4b5a6
Author: 김철수 <chulsoo@example.com>
Date:   Mon Jan 15 14:23:11 2026 +0900

    feat: add payment analytics event

# 6. 원래 브랜치로 복귀
$ git bisect reset
Previous HEAD position was f1e2d3c feat: add payment analytics event
Switched to branch 'main'
```

7단계 예상에 실제로 6번 만에 찾았습니다.
`f1e2d3c` 커밋을 열어보면 결제 흐름에 analytics 이벤트를 추가하다가 비동기 처리를 빠뜨렸음이 눈에 띕니다.

---

## 3. 내부 동작: .git/BISECT_* 파일들

`git bisect start`를 실행하는 순간 `.git/` 안에 파일들이 생깁니다.

```bash
$ git bisect start
$ ls .git/BISECT*
.git/BISECT_HEAD    # 현재 테스트 중인 커밋
.git/BISECT_LOG     # bisect 세션 전체 이력
.git/BISECT_TERMS   # good/bad 용어 정의
.git/BISECT_START   # 원래 HEAD (reset 시 복귀 목적지)
```

<pre class="mermaid">
flowchart TB
    subgraph .git/
        BH[".git/BISECT_HEAD\n현재 테스트 커밋 SHA"]
        BL[".git/BISECT_LOG\n세션 이력 전체"]
        BT[".git/BISECT_TERMS\ngood=good\nbad=bad"]
        BS[".git/BISECT_START\n원래 브랜치명"]
        
        subgraph refs/bisect/
            direction LR
            GOOD["good-abc1234\ngood-def5678\n(good 커밋들)"]
            BAD["bad\n(최신 bad 커밋)"]
        end
    end

    HEAD["HEAD (detached)"] -->|"동일 SHA"| BH
</pre>

### BISECT_LOG를 직접 열어보면

```
# bad: [f1e2d3c] Add payment analytics event
# good: [a1b2c3d] Release v2.0.0
git bisect start
git bisect bad f1e2d3c
git bisect good a1b2c3d
# good: [3f4e5d6] Implement cart abandonment tracking
git bisect good 3f4e5d6
# bad: [9a8b7c6] Refactor payment service
git bisect bad 9a8b7c6
```

이 로그는 세션 재현에도 쓸 수 있습니다.

```bash
# 세션 저장
$ git bisect log > session.log

# 나중에 동일한 세션 재현
$ git bisect replay session.log
```

### 알고리즘: "최적 이등분점"

커밋이 단순 배열이면 중간값이면 되지만, Git 히스토리는 **DAG(방향 비순환 그래프)**입니다. merge가 있으면 단순 중간이 최적이 아닙니다.

<pre class="mermaid">
graph LR
    A --> B --> C
    A --> D --> E
    C --> F
    E --> F
    F --> G["G (bad)"]
</pre>

Git이 쓰는 알고리즘:

1. **범위 한정**: bad의 모든 조상이면서 good의 조상이 *아닌* 커밋들만 추림
2. **가중치 계산**: 각 커밋마다 "내가 good으로 판명 시 제거되는 커밋 수" 계산
3. **최적점 선택**: `min(good일 때 제거, bad일 때 제거)`를 **최대화**하는 커밋 선택

즉, "어느 쪽으로 결과가 나와도 가장 많이 제거되는 지점"을 고릅니다.

```bash
# bisect 점수 직접 확인 (각 커밋의 이분 가중치)
$ git rev-list --bisect-all HEAD --not v2.0.0
9a8b7c6d (dist=74)
3f4e5d6a (dist=72)
f1e2d3c4 (dist=68)
... 
```

---

## 4. git bisect run: 완전 자동화

매번 직접 테스트하고 `git bisect good/bad`를 입력하는 건 번거롭습니다.  
테스트 스크립트가 있다면 **한 번도 손 안 대고** 찾을 수 있습니다.

```bash
git bisect start
git bisect bad HEAD
git bisect good v2.0.0
git bisect run npm test  # 👈 이 한 줄로 끝
```

### exit code 규약

| exit code | 의미 |
|-----------|------|
| `0` | good (정상) |
| `1-124` | bad (버그 있음) |
| `125` | skip (이 커밋은 테스트 불가) |
| `128 이상` | bisect 자체 중단 |

### 실전 스크립트 패턴

빌드가 깨진 커밋은 skip하고, 테스트만 실행:

```bash
#!/bin/sh
# test-for-bisect.sh

# 빌드 안 되면 skip (테스트 불가 환경)
make || exit 125

# 특정 테스트만 실행
npm test -- --testPathPattern="payment"
```

```bash
git bisect run ./test-for-bisect.sh
```

### 성능 회귀 찾기

버그가 아닌 성능 저하를 찾을 때도 씁니다.

```bash
git bisect start --term-old=fast --term-new=slow
git bisect slow HEAD
git bisect fast v1.5.0
git bisect run sh -c '
  npm run build &&
  RESPONSE_TIME=$(curl -o /dev/null -s -w "%{time_total}" http://localhost:3000/api/test)
  [ $(echo "$RESPONSE_TIME > 0.5" | bc) -eq 0 ]  # 500ms 이하면 good(fast)
'
```

---

## 5. 실전 팁

### bisect skip: 테스트 불가 커밋 건너뛰기

```bash
# 이 커밋은 빌드가 안 돼서 테스트 불가
$ git bisect skip

# 범위 전체를 skip
$ git bisect skip v2.3.0..v2.3.5
```

skip이 많으면 Git은 무작위성을 섞어서 탐색합니다. "범인이 skipped 커밋일 수도 있다"는 경고가 뜨기도 합니다.

### bisect visualize: 남은 범위 시각화

```bash
# gitk로 남은 커밋 범위 시각화
$ git bisect visualize

# 터미널에서 텍스트로
$ git bisect visualize --oneline
9a8b7c6 refactor: payment service restructure
3f4e5d6 feat: implement cart abandonment tracking
f1e2d3c feat: add payment analytics event
...
```

### 실수했을 때 되돌리기

```bash
# 방금 good/bad 잘못 입력했다면?
# 로그에서 확인하고 다시 시작
$ git bisect log
$ git bisect reset
$ git bisect replay <(git bisect log)  # 마지막 명령 빼고 재현
```

---

## 6. 역사: Linus의 "정말 멍청한" 알고리즘

`git bisect`는 Git이 만들어진 지 약 5개월 후인 **2005년 9월 20일**, Linus Torvalds가 Linux Kernel Mailing List에 직접 소개했습니다.

리눅스 커널 개발에서 회귀 버그는 악명 높습니다. 수천 명이 수만 개의 커밋을 올리는 환경에서 "이번 릴리즈에서 저번 릴리즈 사이 어딘가에서 망가졌다"는 리포트는 일상이었습니다. `git bisect` 이전엔 개발자가 수동으로 체크아웃하며 테스트해야 했습니다.

Linus는 초기 알고리즘을 스스로 **"truly stupid"** 라고 불렀습니다. 실제로 단순히 커밋을 반으로 나누는 방식이었고, merge가 많은 DAG에선 최적이 아니었습니다.

이후 Junio Hamano(현 Git 메인테이너)가 `min(ancestors, N - ancestors)` 최대화 알고리즘으로 개선했고, **2008년** Git 1.5.4에서 `git bisect skip`이 추가됐습니다. skip된 커밋이 많을 때 랜덤화 알고리즘을 쓰는 방식은 Ingo Molnar와 H. Peter Anvin의 기여로 Git 1.6.4(2009년)에 완성됐습니다.

구현도 변했습니다. 처음엔 Shell 스크립트(`git-bisect.sh`)였지만, 성능 문제로 점진적으로 C 언어로 재구현되어 현재의 `builtin/bisect.c`가 됐습니다.

---

## 마치며

`git bisect`는 단순한 유틸리티가 아닙니다.  
버그를 찾는 과학적인 방법론입니다.

```
브루트포스: O(N)   — 300개 커밋, 최대 300번
Bisect:     O(logN) — 300개 커밋, 최대 9번
```

특히 `git bisect run`과 자동화 테스트를 조합하면, 야심한 밤에 커피 한 잔 내려놓고 명령어 세 줄을 치는 것만으로 범인 커밋이 화면에 나타납니다. Git이 log₂(N)번 혼자 테스트하는 동안 당신은 잠깐 쉬어도 됩니다.

> **"1000개의 커밋 중 버그를 10번 만에 찾는다."**  
> 이진 탐색은 그냥 알고리즘 교과서 속 얘기가 아니었습니다.

---

