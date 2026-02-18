---
title: "Git 해체분석기 #12: Stash - 작업을 잠시 숨기는 마법"
date: 2026-02-17
summary: "git stash는 어떻게 동작할까? .git/refs/stash의 정체, WIP 커밋의 비밀, 그리고 스택인 척하는 reflog"
tags: ["git", "해체분석기", "stash", "internals"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 12
weight: 12
draft: false
mermaid: true
---

> "잠깐만, 이거 어디다 뒀지?" — 모든 개발자가 `git stash pop` 전에 드는 생각

## 들어가며

급한 버그 수정 요청이 들어왔습니다. 지금 한창 피처를 개발하는 중인데.

```bash
$ git status
Changes not staged for commit:
  modified:   feature.ts

# 😰 커밋하기엔 너무 중간 단계고...
# 버리기엔 아깝고...

$ git stash
Saved working directory and index state WIP on main: abc1234 Previous work

# 😌 깔끔해졌다!
```

`git stash`는 마치 마법처럼 작업을 "어딘가"에 숨겨줍니다.  
오늘은 그 "어딘가"가 정확히 무엇인지 해체해봅니다.

---

## 1. Stash의 정체: 사실 커밋이었다

처음 `git stash`를 배울 때 대부분은 "임시 저장소" 정도로 이해합니다.  
**틀렸습니다.** Stash는 **진짜 커밋**입니다.

직접 확인해보죠.

```bash
# staged + unstaged 상태 만들기
$ echo "base" > base.txt && git add . && git commit -m "Initial"
$ echo "new feature" > feature.txt && git add feature.txt  # staged
$ echo "draft work" >> base.txt                             # unstaged

$ git stash push -m "WIP: feature work"
Saved working directory and index state On master: WIP: feature work

# stash가 커밋 SHA를 가지고 있다!
$ cat .git/refs/stash
e8c86e38043f4ced48d10dea804388e32eedbfd7

# 실제 커밋 객체로 조회 가능
$ git cat-file -p refs/stash
tree 4cf6d57d47d1c0d73bb48d3b5edfaca0c7442fad
parent 59b1d8c952bf66ef36e7713b88eec85d6a2b10c0
parent 077d6d8fd4053d3727060f47f83c70dc8598f5d1
author Test <test@test.com> 1771317389 +0900
committer Test <test@test.com> 1771317389 +0900

On master: WIP: feature work
```

**완전한 커밋 객체**입니다. tree, parent, author, message까지 전부 있어요.  
그런데 평범한 커밋과 다른 점이 하나 있습니다. **parent가 두 개**라는 것.

---

## 2. WIP 커밋: 두 부모를 가진 비밀

Stash는 커밋을 **두 개** 만듭니다. 하나가 아니라요.

<pre class="mermaid">
flowchart TB
    HEAD["HEAD (Initial commit)"]
    IDX["index commit\n(staged 변경사항)"]
    WIP["WIP commit\n(working directory)"]
    STASH["refs/stash"]

    WIP -->|"parent[0]"| HEAD
    WIP -->|"parent[1]"| IDX
    IDX -->|"parent"| HEAD
    STASH --> WIP

    style WIP fill:#ffcdd2,stroke:#c62828,stroke-width:3px
    style IDX fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    style HEAD fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style STASH fill:#b3e5fc,stroke:#0288d1,stroke-width:2px
</pre>

**parent[0]**: stash 당시의 HEAD 커밋  
**parent[1]**: index state 커밋 — staged 변경사항만 따로 보존한 특수 커밋

왜 staged와 unstaged를 분리해서 저장할까요?  
**`stash pop --index`** 옵션 때문입니다. stash를 복원할 때 staged 상태까지 완벽하게 재현할 수 있도록요.

```bash
# index state 커밋 살펴보기
$ git cat-file -p 077d6d8f
tree a05f42ad8a46a1dbbea2ae011d71fc607c2436f5
parent 59b1d8c952bf66ef36e7713b88eec85d6a2b10c0
author Test <test@test.com> 1771317389 +0900
committer Test <test@test.com> 1771317389 +0900

index on master: 59b1d8c Initial commit
```

---

## 3. -u 옵션: 세 번째 부모

`git stash push -u`를 쓰면 untracked 파일까지 stash됩니다.  
이때는 커밋이 **세 개**, parent도 **세 개**가 됩니다.

```bash
$ echo "new file" > untracked.txt  # untracked 파일
$ git stash push -u -m "With untracked"

$ git cat-file -p stash@{0}
tree 0571cb4f...
parent 86a87910... ← HEAD
parent 783a16f3... ← index state
parent cb424f38... ← untracked files commit  ← 세 번째!

# 세 번째 부모: untracked files를 담은 독립 커밋
$ git cat-file -p cb424f38
tree 4822b7ee...
(부모 없음!)         ← 이 커밋은 아무 브랜치에도 속하지 않음

untracked files on master: 86a8791 Initial
```

<pre class="mermaid">
flowchart LR
    HEAD["HEAD"]
    IDX["index\ncommit"]
    UNTRACKED["untracked\ncommit"]
    WIP["WIP commit\n(stash@{0})"]

    WIP -->|"p[0]"| HEAD
    WIP -->|"p[1]"| IDX
    WIP -->|"p[2]"| UNTRACKED
    IDX --> HEAD

    style UNTRACKED fill:#e8eaf6,stroke:#5c6bc0,stroke-width:2px
    style WIP fill:#ffcdd2,stroke:#c62828,stroke-width:3px
</pre>

---

## 4. .git/refs/stash: 스택인 척하는 reflog

여러 개를 stash해보면 더 흥미로운 사실을 발견합니다.

```bash
$ echo "A" >> base.txt && git stash push -m "Stash A"
$ echo "B" >> base.txt && git stash push -m "Stash B"
$ echo "C" >> base.txt && git stash push -m "Stash C"

$ git stash list
stash@{0}: On master: Stash C
stash@{1}: On master: Stash B
stash@{2}: On master: Stash A
```

3개가 쌓였습니다. 그런데 `.git/refs/stash`는 어떻게 생겼을까요?

```bash
$ cat .git/refs/stash
3b3b1c9d...  ← stash@{0} 하나의 SHA만 있음!

$ cat .git/logs/refs/stash
0000... 90b0b10... Test <> 1771317412 +0900  On master: Stash A
90b0b10... fc93f2d... Test <> 1771317412 +0900  On master: Stash B
fc93f2d... 3b3b1c9... Test <> 1771317412 +0900  On master: Stash C
```

**핵심 발견!**

`refs/stash`는 stash@{0} 하나만 가리킵니다.  
스택의 나머지 순서는 **reflog** (`.git/logs/refs/stash`)가 관리합니다.

<pre class="mermaid">
flowchart TB
    REFSFILE[".git/refs/stash\n→ SHA_C (최신만)"]
    LOG[".git/logs/refs/stash\n(reflog)"]
    
    LOG_A["0000 → SHA_A\n(Stash A)"]
    LOG_B["SHA_A → SHA_B\n(Stash B)"]
    LOG_C["SHA_B → SHA_C\n(Stash C)"]

    REFSFILE -->|"stash@{0} = SHA_C"| SHA_C["stash@{0}: Stash C"]
    LOG --> LOG_A
    LOG --> LOG_B
    LOG --> LOG_C
    LOG_C -->|"stash@{0}"| SHA_C
    LOG_B -->|"stash@{1}"| SHA_B["stash@{1}: Stash B"]
    LOG_A -->|"stash@{2}"| SHA_A["stash@{2}: Stash A"]

    style REFSFILE fill:#b3e5fc,stroke:#0288d1,stroke-width:2px
    style LOG fill:#fff9c4,stroke:#f57f17,stroke-width:2px
</pre>

그리고 각 stash 커밋의 parent[0]은 모두 **동일한 HEAD**를 가리킵니다.  
stash 커밋들 사이에는 직접적인 연결이 없습니다.

```bash
# 세 stash 모두 동일한 HEAD를 parent로 가짐
$ git rev-parse stash@{0}^1  # → 86a8791 (Initial)
$ git rev-parse stash@{1}^1  # → 86a8791 (Initial) ← 같음!
$ git rev-parse stash@{2}^1  # → 86a8791 (Initial) ← 같음!
```

**stash 스택은 실제로 linked list가 아닙니다.** reflog가 스택 역할을 하는 거예요.  
`stash@{N}` 표기법이 `HEAD@{N}`과 같은 방식인 이유가 바로 이겁니다.

---

## 5. push, pop, apply, drop, list 해체

### stash push가 하는 일

```
1. 현재 index 상태로 "index commit" 생성
2. 현재 working directory 상태로 "WIP commit" 생성
   └─ parent[0] = HEAD, parent[1] = index commit
3. refs/stash 업데이트 → 새 WIP 커밋 SHA
4. logs/refs/stash에 새 항목 추가 (old SHA → new SHA)
5. working tree와 index를 HEAD 상태로 복원
```

### stash pop = apply + drop

```bash
$ git stash pop
# 내부적으로:
# 1. git stash apply (3-way merge로 변경사항 재적용)
# 2. 성공하면 git stash drop (reflog에서 항목 제거)

# 충돌 발생 시: apply는 되지만 drop은 안 됨
# "The stash entry is kept in case you need it again."
```

### stash apply vs pop 차이

| 명령어 | stash 항목 | 충돌 시 |
|--------|-----------|---------|
| `git stash pop` | 제거됨 | 항목 유지 (자동 rollback) |
| `git stash apply` | 유지됨 | 항목 유지 |

apply는 안전합니다. 충돌이 두렵다면 pop 대신 apply를 쓰세요.

### stash drop이 하는 일

```bash
$ git stash drop stash@{1}
# .git/logs/refs/stash에서 해당 항목만 제거
# refs/stash도 필요시 업데이트
# drop된 WIP 커밋 → unreachable → 30일 후 gc 청소
```

---

## 6. stash와 worktree의 관계

Git worktree를 쓰고 있다면 중요한 사실이 있습니다.

```bash
# main 워크트리에서 stash
$ git stash push -m "Main stash"

# 다른 worktree에서도 보임!
$ cd /path/to/other-worktree
$ git stash list
stash@{0}: On master: Main stash  ← 여기서도 보임
```

**Stash는 리포지토리 전체에서 공유됩니다.**

이유는 간단합니다. 모든 worktree는 같은 `.git` 디렉토리를 공유하고,  
`.git/refs/stash`와 `.git/logs/refs/stash`가 거기 있으니까요.

<pre class="mermaid">
flowchart TB
    DOTGIT[".git/\n(공유 디렉토리)"]
    STASH_REF[".git/refs/stash"]
    STASH_LOG[".git/logs/refs/stash"]

    WT1["worktree 1\n(main)"]
    WT2["worktree 2\n(feature-branch)"]
    WT3["worktree 3\n(hotfix)"]

    WT1 --> DOTGIT
    WT2 --> DOTGIT
    WT3 --> DOTGIT
    DOTGIT --> STASH_REF
    DOTGIT --> STASH_LOG

    style DOTGIT fill:#ffcdd2,stroke:#c62828,stroke-width:3px
    style STASH_REF fill:#b3e5fc,stroke:#0288d1,stroke-width:2px
</pre>

주의: worktree A의 stash를 worktree B에서 pop하면, B의 브랜치 상태에 적용됩니다.  
원래 stash를 만든 브랜치를 자동으로 인식하지 않아요.

---

## 7. 역사: 2007년의 쉘 스크립트

`git stash`는 Git이 처음 나왔을 때부터 있지 않았습니다.

**2007년 2월, Shawn O. Pearce**가 메일링 리스트에서 요청을 받아 처음 구현했습니다.  
커밋 해시는 `d5464c0`. 당시 구현 언어는 **쉘 스크립트**였습니다.

```
이전에는 개발자들이 이렇게 했습니다:
  git diff > my-work.patch  # 변경사항을 패치 파일로 저장
  git checkout -- .         # 작업 트리 정리
  ... (다른 작업) ...
  git apply my-work.patch   # 다시 적용
```

Shawn Pearce는 이 패턴을 자동화해서 `git stash`로 만들었고,  
Git 1.5.3 (2007년 9월)에 정식 포함됐습니다.

```
역사적 명령어 변천:
git stash save "message"  →  deprecated
git stash push -m "message"  ← 현재 권장 방식
```

`save`에서 `push`로 바꾼 이유: `push/pop` 한 쌍으로 직관적이기 때문입니다.

그리고 최초 쉘 스크립트는 결국 C 코드로 재작성되어  
지금은 `builtin/stash.c`로 Git에 내장됩니다.

---

## 8. 충격적인 사실들

### 🤯 stash@{2.weeks.ago} 이게 됩니다

reflog 기반이기 때문에, 날짜 표현이 그대로 먹힙니다:

```bash
$ git stash apply stash@{2.weeks.ago}  # 2주 전 stash!
$ git stash show stash@{0.days.ago}    # 오늘 만든 stash
```

### 🤯 git log --all에는 stash가 안 보입니다

stash는 브랜치가 없는 커밋입니다. `refs/stash`로만 참조됩니다.

```bash
$ git log --all --oneline
abc1234 Latest commit
def5678 Initial commit
# stash 커밋은 없음!

# 명시적으로 가리켜야 보임
$ git log --oneline stash@{0}
e8c86e3 On master: WIP: feature work
59b1d8c Initial commit
```

### 🤯 stash pop은 merge입니다

단순 파일 복사가 아니라 **3-way merge**를 수행합니다:
- base: stash 당시 HEAD 트리  
- ours: 현재 HEAD 트리  
- theirs: stash WIP 트리

그래서 충돌이 발생할 수 있고, 충돌 마커도 생깁니다.

---

## 9. 직접 해보기

```bash
# 1. 테스트 저장소 만들기
$ mkdir stash-test && cd stash-test
$ git init && git config user.name "Test" && git config user.email "test@test.com"
$ echo "base" > base.txt && git add . && git commit -m "Initial"

# 2. 작업 상태 만들기
$ echo "feature work" > feature.txt && git add feature.txt  # staged
$ echo "draft" >> base.txt                                   # unstaged

# 3. Stash!
$ git stash push -m "WIP: my work"

# 4. 내부 구조 탐험
$ cat .git/refs/stash                    # stash@{0} SHA
$ git cat-file -p refs/stash             # WIP 커밋 보기
$ git cat-file -p refs/stash^2           # index state 보기
$ cat .git/logs/refs/stash               # stash 스택 (reflog)

# 5. 여러 개 쌓기
$ echo "more" >> base.txt && git stash push -m "Second stash"
$ echo "even more" >> base.txt && git stash push -m "Third stash"
$ git stash list                         # 스택 확인
$ cat .git/logs/refs/stash               # reflog 확인

# 6. 하나 drop
$ git stash drop stash@{1}
$ git stash list                         # 중간이 빠지고 재번호됨
$ cat .git/logs/refs/stash               # reflog에서도 제거됨
```

---

## 정리

<pre class="mermaid">
flowchart LR
    PUSH["git stash push"]
    POP["git stash pop"]
    APPLY["git stash apply"]
    DROP["git stash drop"]

    WIP["WIP 커밋\n(2~3 parents)"]
    REFLOG[".git/logs/refs/stash\n(스택 = reflog)"]
    REFSFILE[".git/refs/stash\n(stash@{0})"]

    PUSH -->|"생성"| WIP
    PUSH -->|"업데이트"| REFLOG
    PUSH -->|"업데이트"| REFSFILE

    POP -->|"= apply + drop"| APPLY
    POP --> DROP
    APPLY -->|"3-way merge"| WIP
    DROP -->|"항목 제거"| REFLOG

    style WIP fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style REFLOG fill:#fff9c4,stroke:#f57f17,stroke-width:2px
</pre>

| 개념 | 실체 |
|------|------|
| `git stash` | 2~3개의 커밋 객체 |
| stash 스택 순서 | `.git/logs/refs/stash` (reflog) |
| `stash@{N}` | reflog의 N번째 항목 |
| `stash pop` | 3-way merge + drop |
| `stash -u` | 부모 3개짜리 커밋 |
| worktree와 공유 | 동일한 .git 디렉토리 공유 |

**Git의 설계 철학 한 마디:**

> Stash는 "임시 저장"처럼 보이지만, 내부는 완전한 커밋입니다.  
> Git은 거의 모든 것을 커밋 객체로 표현합니다.  
> `refs/stash`는 그 철학의 가장 영리한 응용 사례 중 하나입니다.

---

## 다음 편 예고

> **해체분석기 #13: Git Worktree - 한 저장소, 여러 작업 공간**
>
> - worktree가 .git을 공유하는 방식
> - `.git/worktrees/` 디렉토리 구조
> - worktree별 HEAD, stash, branch 잠금

---

## 참고 자료

- [Git Official Docs - git-stash](https://git-scm.com/docs/git-stash)
- [Pro Git Book - Stashing and Cleaning](https://git-scm.com/book/en/v2/Git-Tools-Stashing-and-Cleaning)
- [Git Source Code - builtin/stash.c](https://github.com/git/git/blob/master/builtin/stash.c)
- [Git from the Bottom Up - Stashing and the reflog](https://jwiegley.github.io/git-from-the-bottom-up/4-Stashing-and-the-reflog.html)
