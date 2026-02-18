---
title: "Git 해체분석기 #15: Merge의 비밀 - 두 브랜치는 어떻게 합쳐지나"
date: 2026-02-16T20:00:00+09:00
draft: false
tags: ["git", "해체분석기", "merge", "3-way", "conflict"]
series: ["Git 해체분석기"]
series_order: 15
weight: 15
mermaid: true
toc: true
---

## 이전 글 요약

[지난 글](/posts/git-branches-birth/)에서 Branch의 탄생을 봤다.

Branch는 **41바이트 텍스트 파일**이었다. commit hash를 담은 이름표.

```bash
$ cat .git/refs/heads/feature
d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd
```

이제 브랜치를 만들 수 있다. 하지만 한 가지 문제가 남았다:

**"어떻게 합치지?"**

---

## 문제: 두 개의 역사

`main`에서 작업하고, `feature`에서도 작업했다.

```
main:    A → B → D
feature:     B → C
```

이제 `feature`의 작업을 `main`에 합치고 싶다. 어떻게?

SVN 같은 중앙집중형 시스템에서는 이게 간단했다. "최신 버전 가져오기 → 내 작업 적용"

하지만 Git은 **분산**이다. 두 브랜치 모두 정당한 역사를 가지고 있다. 누구를 기준으로?

---

## 답: Merge

```bash
git checkout main
git merge feature
```

이 명령 하나가 두 브랜치의 역사를 **하나로** 만든다. 하지만 내부에서는 **두 가지 완전히 다른 일**이 일어날 수 있다.

---

## Fast-forward: 사실 Merge가 아니다

가장 간단한 경우부터 보자.

```
main:    A → B
feature:     B → C → D
```

`main`은 B 이후로 아무 일도 없었다. `feature`만 앞으로 갔다.

```bash
$ git merge feature
Updating abc123..def456
Fast-forward
 file.txt | 2 ++
 1 file changed, 2 insertions(+)
```

"Fast-forward"라는 메시지가 뜬다. 뭘 했을까?

```bash
# merge 전
$ cat .git/refs/heads/main
abc123...  (commit B)

# merge 후
$ cat .git/refs/heads/main
def456...  (commit D)
```

**그냥 파일을 수정했다.** `main` 브랜치 파일의 내용을 `feature`와 똑같이 바꿨을 뿐.

<pre class="mermaid">
flowchart LR
    A --> B
    B --> C
    C --> D
    
    main1[main before] -.-> B
    main2[main after] -.-> D
    feature[feature] -.-> D
    
    style main1 fill:#ff6b6b
    style main2 fill:#51cf66
    style feature fill:#339af0
</pre>

### 왜 "Fast-forward"인가?

브랜치 포인터를 **빨리 감기(fast-forward)** 했기 때문이다. VCR 테이프 감듯이.

**새 커밋을 만들지 않는다.** 히스토리도 바뀌지 않는다. 포인터만 이동.

### 이게 merge가 아니라고?

엄밀히 말하면 맞다. 두 역사를 **합치는(merge)** 게 아니라 하나가 다른 하나를 **따라잡는(catch up)** 것.

실제로 merge commit도 없다:

```bash
$ git log --oneline --graph
* def456 (HEAD -> main, feature) Add feature
* bcd234 Implement feature
* abc123 Initial commit
```

선형 히스토리다. 마치 처음부터 `main`에서 작업한 것처럼.

---

## 3-way Merge: 진짜 병합

이제 진짜 문제를 보자.

```
main:    A → B → D
feature:     B → C
```

이번엔 `main`도 움직였다. `feature`도 움직였다. **두 브랜치 모두 새 커밋이 있다.**

```bash
$ git merge feature
Merge made by the 'recursive' strategy.
```

"recursive strategy"로 merge했다고 한다. 뭘 했을까?

```bash
$ git log --oneline --graph
*   e5f6a7b (HEAD -> main) Merge branch 'feature'
|\
| * c8d9e0f (feature) Add feature C
* | d1e2f3a Update main
|/
* b2c3d4e Initial commit B
```

**다이아몬드 모양**이 생겼다. 그리고 맨 위에 **merge commit**이 있다:

```bash
$ git cat-file -p e5f6a7b
tree 1a2b3c4d...
parent d1e2f3a  # main의 tip
parent c8d9e0f  # feature의 tip
author ...
committer ...

Merge branch 'feature'
```

**두 개의 parent**를 가진 커밋이다. 이게 merge commit의 정체다.

<pre class="mermaid">
flowchart LR
    A --> B
    B --> D
    B --> C
    D --> M[Merge M]
    C --> M
    
    main[main] -.-> M
    feature[feature] -.-> C
    
    style M fill:#ffd43b
    style main fill:#51cf66
    style feature fill:#339af0
</pre>

### 어떻게 만들었나?

1. **공통 조상(merge base) 찾기**: B
2. **두 diff 계산**:
   - B → D (main의 변경사항)
   - B → C (feature의 변경사항)
3. **두 diff를 B에 적용**: 새 tree 생성
4. **merge commit 생성**: parent는 D와 C

이게 **3-way merge**다. 세 개의 커밋을 본다:
- Base (B)
- Ours (D)
- Theirs (C)

---

## Merge Base: 공통 조상 찾기

3-way merge의 핵심은 **merge base**를 찾는 것이다.

```bash
$ git merge-base main feature
b2c3d4e  # commit B
```

> 💡 merge-base가 왜 필요한지, Git 역사에서 어떻게 등장했는지는 [Git 해체분석기 #4: 첫 2주](/posts/git-evolution-first-two-weeks/)의 Day 11에서 자세히 다뤘다.

merge base가 **여러 개**인 복잡한 경우, Git은 **recursive strategy**를 쓴다. 여러 base를 먼저 병합해 가상의 base를 만들고, 그걸로 최종 병합한다. 이래서 "recursive"다.

---

## Conflict: 충돌의 원리

두 브랜치가 **같은 파일의 같은 위치**를 다르게 고쳤다면?

```
Base (B):    def hello():
                 print("Hello")

Main (D):    def hello():
                 print("Hello World")

Feature (C): def hello():
                 print("Hello Git")
```

Git은 이걸 병합할 수 없다. 어느 쪽을 선택해야 할지 모른다.

```bash
$ git merge feature
Auto-merging hello.py
CONFLICT (content): Merge conflict in hello.py
Automatic merge failed; fix conflicts and then commit the result.
```

### Conflict Marker

파일을 열어보면:

```python
def hello():
<<<<<<< HEAD
    print("Hello World")
=======
    print("Hello Git")
>>>>>>> feature
```

- `<<<<<<< HEAD`: 현재 브랜치 (main)의 내용
- `=======`: 구분선
- `>>>>>>> feature`: 병합 대상 브랜치의 내용

### diff3 모드

더 나은 방법이 있다:

```bash
$ git config --global merge.conflictstyle diff3
```

이제 충돌이 이렇게 보인다:

```python
def hello():
<<<<<<< HEAD
    print("Hello World")
||||||| merged common ancestor
    print("Hello")
=======
    print("Hello Git")
>>>>>>> feature
```

**원본(base)까지 보여준다!**

이제 의도를 알 수 있다:
- Main: "Hello" → "Hello World" (World 추가)
- Feature: "Hello" → "Hello Git" (Git 추가)

해결:

```python
def hello():
    print("Hello World Git")  # 둘 다 반영
```

---

## Octopus Merge: 여러 브랜치 동시 병합

Git의 숨겨진 기능: **한 번에 여러 브랜치 병합**

```bash
$ git merge feature1 feature2 feature3
Merge made by the 'octopus' strategy.
```

<pre class="mermaid">
flowchart LR
    A --> F1[feature1]
    A --> F2[feature2]
    A --> F3[feature3]
    A --> M
    
    F1 --> M[Octopus Merge]
    F2 --> M
    F3 --> M
    
    style M fill:#ffd43b
</pre>

Merge commit의 parent가 **4개**다:

```bash
$ git cat-file -p HEAD
tree abc123...
parent aaa111  # main
parent bbb222  # feature1
parent ccc333  # feature2
parent ddd444  # feature3
```

### 언제 쓸까?

독립적인 topic branch 여러 개를 한 번에 통합할 때:

```bash
# CI/CD에서
git merge origin/fix-123 origin/fix-456 origin/fix-789
```

### 제한사항

**Conflict가 있으면 중단한다.** 수동 해결이 필요한 경우 octopus는 작동 안 함.

```bash
error: 'octopus' strategy refuses to handle this case.
Please resolve the conflict manually.
```

단순한 병합만 가능. 복잡하면 하나씩 해야 한다.

---

## 초기 Git의 Merge

첫 커밋(2005-04-07)에는 merge가 없었다.

### Day 12: 첫 Merge

초기 구현은 `read-tree -m`이었다:

```bash
git-read-tree -m <tree-ish1> <tree-ish2>
```

**Trivial merge**만 지원:

| Ancestor | HEAD | Remote | Result |
|----------|------|--------|--------|
| (empty) | (empty) | file | file ✓ |
| (empty) | file | (empty) | file ✓ |
| file1 | file1 | file1 | file1 ✓ |
| file1 | file1 | file2 | file2 ✓ |
| file1 | file2 | file1 | file2 ✓ |
| file1 | file2 | file3 | **ERROR** ✗ |

마지막 경우는 conflict. 자동으로 못 한다.

### 진화

1. **read-tree -m** (Day 12): Low-level, trivial만
2. **resolve strategy** (2005 중반): 첫 고급 merge
3. **recursive strategy** (2005 후반): 기본 전략
4. **ort strategy** (Git 2.34+): 최적화된 현재 기본

20년이 지났지만 **기본 원리는 동일**하다:
1. Merge base 찾기
2. 3-way diff
3. Conflict 감지
4. Merge commit 생성

---

## 실제로 보자

직접 확인해보자:

```bash
# 1. 두 브랜치 만들기
$ git checkout -b feature
$ echo "feature work" >> file.txt
$ git commit -am "Add feature"

$ git checkout main
$ echo "main work" >> file.txt
$ git commit -am "Update main"

# 2. Merge base 확인
$ git merge-base main feature
abc123...

# 3. Merge 실행 (dry-run은 없지만 preview 가능)
$ git merge --no-commit --no-ff feature
Automatic merge went well; stopped before committing as requested

# 4. 결과 확인
$ git status
On branch main
All conflicts fixed but you are still merging.

# 5. Commit
$ git commit

# 6. 히스토리 확인
$ git log --oneline --graph --all
*   e5f6a7b (HEAD -> main) Merge branch 'feature'
|\
| * c8d9e0f (feature) Add feature
* | d1e2f3a Update main
|/
* abc123 Initial commit
```

### Merge Commit 내부

```bash
$ git cat-file -p HEAD
tree 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0
parent d1e2f3a  # main
parent c8d9e0f  # feature
author Your Name <you@example.com>
committer Your Name <you@example.com>

Merge branch 'feature'
```

특별한 게 없다. 그냥 **parent가 두 개**인 commit일 뿐.

---

## Merge vs Rebase

잠깐, merge 말고 다른 방법은 없나?

있다: **rebase**

```bash
# Merge:
main:    A → B → D → M
feature:     B → C ↗

# Rebase:
main:    A → B → D → C'
```

Rebase는 C를 D 위로 "옮긴다". 히스토리를 **재작성**한다.

| | Merge | Rebase |
|---|-------|--------|
| 히스토리 | 분기 보존 | 선형으로 재작성 |
| 새 커밋 | Merge commit | Rebased commits |
| 안전성 | 안전 (히스토리 변경 X) | 위험 (히스토리 변경 O) |
| 추적 | 병합 시점 명확 | 병합 기록 없음 |

**Golden Rule**: 공개된 브랜치는 rebase하지 마라. 다른 사람이 혼란스러워한다.

Merge는 "이 시점에 두 브랜치가 합쳐졌다"는 **사실을 기록**한다. 히스토리는 복잡해지지만 **진실**을 담는다.

---

## 정리: Merge의 본질

| 개념 | 설명 |
|------|------|
| Fast-forward | 포인터 이동 (새 커밋 없음) |
| 3-way Merge | Base + Ours + Theirs → Merge commit |
| Merge Base | LCA 알고리즘으로 찾은 공통 조상 |
| Conflict | 같은 위치를 다르게 수정 |
| Merge Commit | 두 개(이상)의 parent를 가진 커밋 |
| Octopus | 여러 브랜치 동시 병합 |

**Merge는 역사를 합치는 것이다.** 두 브랜치의 차이를 하나로 만들되, **분기했던 사실**을 보존한다.

---

## 다음 글 예고

Merge를 이해했으니 이제 마지막 퍼즐이 남았다:

**"이걸 어떻게 다른 사람과 공유하지?"**

Push, pull, fetch의 비밀. Remote의 진실. 그리고 Git 프로토콜의 탄생.

다음 시간에 계속.

---

## 참고 자료

- [Git SCM: Basic Branching and Merging](https://git-scm.com/book/en/v2/Git-Branching-Basic-Branching-and-Merging)
- [Git SCM: Advanced Merging](https://git-scm.com/book/en/v2/Git-Tools-Advanced-Merging)
- [Git Internals: How Git Merge Really Works](https://dev.to/shrsv/git-internals-how-git-merge-really-works-2dn5)
- [Understanding Git Merge](https://www.biteinteractive.com/understanding-git-merge/)
- [Diff3 Conflict Resolution](https://blog.nilbus.com/take-the-pain-out-of-git-conflict-resolution-use-diff3/)
- [Git Merge Strategies](https://git-scm.com/docs/merge-strategies)
- [Trivial Merge Documentation](https://git-scm.com/docs/trivial-merge)
