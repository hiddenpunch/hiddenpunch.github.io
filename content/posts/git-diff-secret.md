---
title: "Git 해체분석기 #4: Diff의 비밀 - 두 파일의 차이를 어떻게 찾나"
date: 2026-02-18T01:00:00+09:00
draft: false
tags: ["git", "해체분석기", "diff", "myers", "algorithm", "lcs"]
series: ["Git 해체분석기"]
series_order: 4
weight: 4
mermaid: true
toc: true
description: "git diff는 어떻게 두 파일의 차이를 찾는가? 1974년 Hunt-McIlroy부터 1986년 Myers 알고리즘까지, LCS와 diff의 수학적 원리를 해체분석합니다."
---

## Diff의 역사: 50년 된 알고리즘

`diff` 명령어는 1974년에 탄생했습니다. Unix의 역사와 함께했습니다.

### 1974: Hunt-McIlroy

James W. Hunt와 M. Douglas McIlroy가 Unix용 `diff`를 작성했습니다. 이것이 최초의 실용적인 diff 도구였습니다.

핵심 아이디어는 **LCS (Longest Common Subsequence, 최장 공통 부분 수열)** 였습니다.

> "두 파일의 차이 = 공통된 부분을 제외한 나머지"

두 파일에서 **공통으로 있는 줄들**을 찾고, 나머지를 추가/삭제로 표현하면 됩니다.

```bash
# 1974년 Unix diff의 출력 형식 (ed 스크립트)
$ diff old.txt new.txt
2a3
> 새로 추가된 줄
5d4
< 삭제된 줄
```

### 1986: Eugene Myers

그로부터 12년 후, Eugene Myers가 훨씬 효율적인 알고리즘을 발표합니다.

논문 제목: *"An O(ND) Difference Algorithm and Its Variations"* (1986)

이 알고리즘이 오늘날 **거의 모든 diff 도구의 기반**입니다. Git, GNU diff, GitHub, GitLab — 전부 Myers 알고리즘을 사용합니다.

O(ND)가 무슨 뜻인지는 곧 설명하겠습니다.

---

## LCS: 문제의 본질

Diff를 이해하려면 먼저 LCS를 이해해야 합니다.

### 문제 정의

두 문자열 A와 B가 있을 때, 두 문자열에 **공통으로 등장하는 가장 긴 부분 수열**을 찾아라.

예를 들어:

```
A = "ABCBDAB"
B = "BDCABA"

LCS = "BCBA" (길이 4)
```

수열(sequence)이라서 **연속**일 필요는 없습니다. 순서만 맞으면 됩니다.

### 파일에 적용하면

파일의 각 줄을 하나의 원소로 봅니다:

```
파일 A:
  1: def hello():
  2:     print("Hello")
  3:     return True

파일 B:
  1: def hello():
  2:     print("Hello World")
  3:     return True
```

LCS = `[def hello():, return True]` (2줄이 공통)

차이 = 2번 줄이 변경됨

### LCS의 복잡도 문제

단순한 DP(Dynamic Programming) 방식으로 LCS를 구하면 **O(N × M)** 시간과 공간이 필요합니다. N과 M은 두 파일의 줄 수.

큰 파일에서는 너무 느립니다. 10,000줄짜리 파일 두 개면 **1억 번의 연산**이 필요합니다.

Myers가 해결한 것이 바로 이 문제였습니다.

---

## Myers 알고리즘: Edit Graph의 최단 경로

Myers는 문제를 완전히 다르게 봤습니다.

### Edit Graph

두 파일의 차이를 **그래프 탐색 문제**로 바꿉니다.

```
A = ["a", "b", "c", "b", "d"]  (5개)
B = ["a", "b", "d"]            (3개)
```

Edit Graph는 (N+1) × (M+1) 격자입니다. 가로축(x)은 A를 소비한 개수, 세로축(y)은 B를 소비한 개수를 나타냅니다.

```
        A[0]  A[1]  A[2]  A[3]  A[4]
         a     b     c     b     d
    ┌────┬────┬────┬────┬────┬────┐
    │0,0 │1,0 │2,0 │3,0 │4,0 │5,0 │
B[0]├────┼────┼────┼────┼────┼────┤
 a  │0,1 │1,1↖│2,1 │3,1 │4,1 │5,1 │
B[1]├────┼────┼────┼────┼────┼────┤
 b  │0,2 │1,2 │2,2↖│3,2 │4,2 │5,2 │
B[2]├────┼────┼────┼────┼────┼────┤
 d  │0,3 │1,3 │2,3 │3,3 │4,3 │5,3↖│
    └────┴────┴────┴────┴────┴────┘
```

이동 규칙:

- **오른쪽(→)**: A에서 한 줄 삭제 (x+1, 비용 1)
- **아래쪽(↓)**: B에서 한 줄 삽입 (y+1, 비용 1)
- **대각선(↘)**: A[x]와 B[y]가 같을 때만! (비용 0, 무료)

최단 경로 (0,0) → (5,3):

<pre class="mermaid">
graph LR
    p00["(0,0)"] -->|"↘ a=a"| p11["(1,1)"]
    p11 -->|"↘ b=b"| p22["(2,2)"]
    p22 -->|"→ 삭제 c"| p32["(3,2)"]
    p32 -->|"→ 삭제 b"| p42["(4,2)"]
    p42 -->|"↘ d=d"| p53["(5,3) ✓"]
    
    style p00 fill:#69db7c
    style p53 fill:#ffd43b
</pre>

결과: **2번의 편집** (c 삭제, b 삭제)으로 A를 B로 변환

**(0,0)에서 (N,M)까지의 최단 경로** = 최소한의 편집으로 A를 B로 바꾸는 방법

### 핵심 통찰: D와 k

Myers는 두 가지를 정의합니다:

- **D**: 편집 횟수 (삽입 + 삭제의 합)
- **k = x - y**: 현재 위치에서의 대각선 번호

그리고 다음을 증명합니다:

> D번의 편집을 할 때, 대각선 k에서 도달할 수 있는 **x 좌표의 최댓값**만 알면 된다.

이를 이용해 D=0, D=1, D=2, ... 순서로 BFS처럼 탐색합니다.

### O(ND) 의미

N = 두 파일의 줄 수 합계, D = 실제 편집 횟수

두 파일이 비슷할수록 D가 작아집니다. 따라서:
- 비슷한 파일: 거의 O(N) — 엄청나게 빠름
- 완전히 다른 파일: O(N²) — 최악의 경우

실제 코드 변경은 대부분 **비슷한 파일** 사이에서 일어나므로, 현실적으로 매우 빠릅니다.

---

## Diff의 출력: Unified Format

이제 알고리즘으로 차이를 찾았습니다. 어떻게 보여줄까요?

```bash
$ git diff
diff --git a/hello.py b/hello.py
index a1b2c3d..d4e5f6a 100644
--- a/hello.py
+++ b/hello.py
@@ -1,5 +1,6 @@
 def hello():
-    print("Hello")
+    print("Hello World")
+    print("Greetings!")
     return True
```

이 형식이 **Unified diff** 입니다. GNU diff가 1988년에 도입했습니다.

### 헤더 읽기

```
@@ -1,5 +1,6 @@
```

- `-1,5`: 원본 파일에서 1번 줄부터 5줄
- `+1,6`: 새 파일에서 1번 줄부터 6줄
- ` `: 변경 없음 (context)
- `-`: 삭제됨
- `+`: 추가됨

### Git이 보여주는 추가 정보

```
diff --git a/hello.py b/hello.py
index a1b2c3d..d4e5f6a 100644
```

- `a/hello.py`: 이전 버전 경로
- `b/hello.py`: 새 버전 경로
- `a1b2c3d..d4e5f6a`: 두 blob object의 해시
- `100644`: 파일 권한 (일반 파일)

Git의 diff는 **파일 시스템이 아니라 object store**를 비교합니다.

---

## Git이 Diff를 사용하는 곳들

`git diff`가 전부가 아닙니다. Git 내부 곳곳에서 diff 알고리즘을 사용합니다.

<pre class="mermaid">
flowchart TD
    DIFF["Myers Diff Algorithm"]
    
    DIFF --> GD["git diff\n두 커밋/브랜치 비교"]
    DIFF --> MERGE["git merge\n충돌 감지 및 자동 병합"]
    DIFF --> BLAME["git blame\n각 줄의 마지막 변경자"]
    DIFF --> PATCH["git format-patch\n패치 파일 생성"]
    DIFF --> APPLY["git apply\n패치 적용"]
    DIFF --> CHERRY["git cherry-pick\n특정 커밋 이식"]
    DIFF --> REBASE["git rebase\n커밋 재배치"]
    
    style DIFF fill:#ffd43b
    style GD fill:#74c0fc
    style MERGE fill:#f783ac
    style BLAME fill:#69db7c
</pre>

### git diff: 다양한 비교 모드

```bash
# Working tree vs Index (스테이징 전 변경사항)
$ git diff

# Index vs HEAD (스테이징된 변경사항)
$ git diff --staged   # 또는 --cached

# 두 커밋 비교
$ git diff abc123 def456

# 두 브랜치 비교
$ git diff main feature

# 특정 파일만
$ git diff main feature -- src/hello.py

# 브랜치 분기 이후 변경사항
$ git diff main...feature  # 점 3개!
```

점 3개(`...`)와 점 2개(`..`)의 차이:

```
git diff main..feature  = main의 tip vs feature의 tip
git diff main...feature = main과 feature의 공통 조상 vs feature의 tip
```

### git merge: Diff가 충돌을 찾는다

merge 내부에서 diff는 두 번 실행됩니다:

```
Base → Ours   (우리 변경사항)
Base → Theirs (상대방 변경사항)
```

같은 줄이 양쪽에서 다르게 바뀌면 → 충돌(conflict)

```python
# Base
x = 1

# Ours: x = 2
# Theirs: x = 3

# 결과: 충돌!
<<<<<<< HEAD
x = 2
=======
x = 3
>>>>>>> feature
```

### git blame: 줄별 히스토리 추적

`git blame`은 각 줄이 **어느 커밋에서 마지막으로 수정됐는지** 보여줍니다.

```bash
$ git blame hello.py
abc1234 (Alice 2026-01-10) def hello():
def5678 (Bob   2026-01-15)     print("Hello World")
abc1234 (Alice 2026-01-10)     return True
```

내부적으로 커밋마다 diff를 역추적해 각 줄의 기원을 찾습니다.

```bash
# 특정 줄 범위만 blame
$ git blame -L 10,20 hello.py

# 특정 커밋 시점의 blame
$ git blame abc123 -- hello.py

# 공백 무시
$ git blame -w hello.py
```

---

## Diff 옵션들: 더 스마트하게

기본 diff만으로는 부족할 때가 있습니다. Git은 다양한 diff 모드를 제공합니다.

### --word-diff: 단어 단위 비교

```bash
$ git diff --word-diff

@@ -1,3 +1,3 @@
def hello():
    print("Hello [-World-]{+Universe+}")
    return True
```

줄 전체가 아니라 **단어 단위**로 변경사항을 보여줍니다.

문서 작업이나 주석 수정 시 매우 유용합니다.

### --color-words: 색상으로 단어 강조

```bash
$ git diff --color-words

# 삭제된 단어는 빨간색, 추가된 단어는 녹색으로 표시
```

`--word-diff`보다 더 시각적으로 보기 좋습니다.

### --patience: 더 나은 diff 결과

```bash
$ git diff --diff-algorithm=patience
```

**Patience diff**는 특수한 상황에서 Myers보다 더 읽기 쉬운 결과를 냅니다.

예를 들어 함수 재배치:

```python
# Before
def foo():
    pass

def bar():
    pass

# After
def bar():
    pass

def foo():
    pass
```

Myers: 전부 삭제하고 다시 추가한 것처럼 보임
Patience: foo()와 bar()가 순서만 바뀐 것으로 표시

알고리즘 원리: **유일한 줄**을 먼저 앵커로 잡고, 그 사이를 재귀적으로 채움

```bash
# 기본값을 patience로 변경
$ git config --global diff.algorithm patience
```

### --histogram: 또 다른 선택지

```bash
$ git diff --diff-algorithm=histogram
```

Git 2.x부터 추가된 알고리즘. Patience의 개선 버전으로, 더 큰 파일에서 빠릅니다.

GitHub의 기본 diff 알고리즘이기도 합니다.

### -U: Context 줄 수 조정

```bash
# 변경 전후 10줄씩 보여줌 (기본값은 3줄)
$ git diff -U10

# Context 없이 변경된 줄만
$ git diff -U0
```

### --stat: 숫자로 요약

```bash
$ git diff --stat main feature
 src/hello.py | 3 ++-
 tests/test.py | 10 +++++-----
 2 files changed, 7 insertions(+), 6 deletions(-)
```

변경 규모를 한눈에 파악할 수 있습니다.

### --name-only / --name-status

```bash
# 변경된 파일 이름만
$ git diff --name-only main feature
src/hello.py
tests/test.py

# 파일별 변경 유형 (A=추가, M=수정, D=삭제)
$ git diff --name-status main feature
M       src/hello.py
M       tests/test.py
```

CI/CD 스크립트에서 어떤 파일이 변경됐는지 확인할 때 유용합니다.

---

## 실제로 해보자

직접 Myers 알고리즘의 결과를 확인해봅시다.

```bash
# 두 파일 준비
$ cat > old.txt << EOF
alpha
beta
gamma
delta
epsilon
EOF

$ cat > new.txt << EOF
alpha
beta
zeta
delta
eta
epsilon
EOF

# diff 실행
$ diff old.txt new.txt
3c3
< gamma
---
> zeta
5a6
> eta
```

이제 git에서:

```bash
$ git init test-diff && cd test-diff
$ cp ../old.txt file.txt
$ git add file.txt && git commit -m "initial"

$ cp ../new.txt file.txt
$ git diff
diff --git a/file.txt b/file.txt
index 4abc123..8def456 100644
--- a/file.txt
+++ b/file.txt
@@ -1,5 +1,6 @@
 alpha
 beta
-gamma
+zeta
 delta
+eta
 epsilon
```

### 알고리즘 비교

같은 변경에 대해 알고리즘에 따라 결과가 달라질 수 있습니다:

```bash
# 기본 (Myers)
$ git diff

# Patience
$ git diff --diff-algorithm=patience

# Histogram
$ git diff --diff-algorithm=histogram

# Minimal (가능한 한 작은 diff)
$ git diff --diff-algorithm=minimal
```

대부분의 경우 결과가 같지만, 코드 블록이 이동하거나 재배치된 경우 차이가 납니다.

---

## 정리: Diff의 본질

| 개념 | 설명 |
|------|------|
| LCS | Longest Common Subsequence, diff의 수학적 기반 |
| Myers (1986) | O(ND) diff 알고리즘, 오늘날 표준 |
| Unified diff | `@@` 헤더를 가진 표준 diff 형식 |
| Patience | 가독성 좋은 diff, 함수 이동에 강함 |
| Histogram | Myers+Patience의 장점을 합친 알고리즘 |
| --word-diff | 단어 단위 비교 |
| --color-words | 색상으로 단어 강조 |

```
두 파일의 차이 = Edit Graph의 최단 경로
```

50년 전 Unix에서 탄생한 아이디어가 오늘날 Git의 핵심을 이루고 있습니다. `git diff`를 실행할 때마다 1986년 Myers의 논문이 조용히 실행됩니다.

---

## 다음 글 예고

Diff의 원리를 알았습니다. 이제 Git의 또 다른 강력한 도구를 살펴볼 차례입니다.

**"파일 내용으로 커밋을 찾는다 — git grep과 pickaxe의 비밀"**

`-S` 옵션 하나로 "이 코드가 언제 추가됐는지"를 찾는 방법. 다음 시간에 계속.

---

## 참고 자료

- [Myers, E. W. (1986). "An O(ND) Difference Algorithm and Its Variations"](https://dl.acm.org/doi/10.1007/BF01840446)
- [Hunt, J. W. & McIlroy, M. D. (1976). "An Algorithm for Differential File Comparison"](https://www.cs.dartmouth.edu/~doug/diff.pdf)
- [Git SCM: git-diff documentation](https://git-scm.com/docs/git-diff)
- [The Myers Diff Algorithm: Part 1](https://blog.jcoglan.com/2017/02/12/the-myers-diff-algorithm-part-1/)
- [Patience Diff Advantages](https://bramcohen.livejournal.com/73318.html)
- [How Git Stores Data](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
