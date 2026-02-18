---
title: "Git 해체분석기 #16: Worktree - 하나의 저장소, 여러 작업 디렉토리"
date: 2026-02-17
summary: "git worktree는 어떻게 같은 .git을 공유하면서 다른 브랜치를 동시에 열 수 있을까? .git/worktrees/ 구조, GIT_COMMON_DIR의 비밀, 그리고 clone 대신 worktree를 써야 하는 이유"
tags: ["git", "해체분석기", "worktree", "internals"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 16
weight: -16
draft: false
mermaid: true
---

> "급한 버그 수정인데 지금 작업 중인 게 너무 아깝고..." — `git stash`를 쓰기도, `git clone`을 하기도 애매한 그 순간

## 들어가며

피처 개발 한창 중입니다. 파일 30개를 수정했고, 아직 커밋할 상태는 아니에요.  
그때 슬랙 알림이 옵니다. **"프로덕션 장애! 지금 당장 hotfix 필요"**

```bash
$ git status
modified:   src/auth/oauth.ts      # 오늘 3시간 작업한 것
modified:   src/api/users.ts       # 리팩토링 중
modified:   src/components/Nav.tsx  # 절반만 완성

# 😰 stash 하기엔 너무 복잡하고
# 새로 clone 하기엔 5GB 저장소라 10분 걸리고
```

`git worktree`가 이 문제를 해결합니다.  
오늘은 worktree의 내부가 어떻게 생겼는지 해체해봅니다.

---

## 1. Worktree란 무엇인가

**하나의 `.git` 저장소에 여러 작업 디렉토리를 붙이는 기능**입니다.

```bash
# 현재 feature/big-refactor에서 작업 중
$ git worktree add ../hotfix hotfix/critical-bug

# 이제 두 디렉토리가 동시에 존재
$ ls ..
my-project/   # feature/big-refactor 브랜치
hotfix/       # hotfix/critical-bug 브랜치 ← 새로 생성!

# 각각 독립적인 working directory
$ cd ../hotfix && cat .git
gitdir: /path/to/my-project/.git/worktrees/hotfix
# ↑ 파일입니다! 디렉토리가 아니에요
```

핵심은 **`.git`이 파일**이라는 점입니다.  
linked worktree의 `.git`은 디렉토리가 아니라, 진짜 `.git`이 어디 있는지 알려주는 포인터 파일입니다.

---

## 2. .git/worktrees/ 내부 구조

```bash
$ git worktree add ../wt-hotfix -b hotfix/urgent
$ git worktree add ../wt-review feature/login
$ git worktree list
/path/to/main     abc1234 [main]
/path/to/wt-hotfix  def5678 [hotfix/urgent]
/path/to/wt-review  def5678 [feature/login]
```

main 저장소의 `.git`을 들여다보면:

```
.git/
├── objects/        ← 모든 커밋/트리/블롭 (공유!)
├── refs/           ← 모든 브랜치/태그 (공유!)
├── config          ← 저장소 설정 (공유!)
├── hooks/          ← Git 훅 (공유!)
├── HEAD            ← main worktree의 현재 브랜치
├── index           ← main worktree의 staging area
└── worktrees/
    ├── wt-hotfix/  ← hotfix worktree 전용 메타데이터
    │   ├── HEAD        ← "ref: refs/heads/hotfix/urgent"
    │   ├── index       ← hotfix 전용 staging area
    │   ├── commondir   ← "../.." (공유 .git 경로)
    │   ├── gitdir      ← "/path/wt-hotfix/.git" (역방향 링크)
    │   └── logs/HEAD   ← hotfix HEAD 이동 기록
    └── wt-review/
        ├── HEAD        ← "ref: refs/heads/feature/login"
        ├── index       ← review 전용 staging area
        └── ...
```

<pre class="mermaid">
flowchart TB
    subgraph MAIN[".git/ (공유)"]
        OBJ["objects/\n(커밋, 트리, 블롭)"]
        REFS["refs/\n(브랜치, 태그)"]
        CFG["config, hooks"]
        WT["worktrees/"]
    end

    subgraph WTH[".git/worktrees/wt-hotfix/"]
        HEAD_H["HEAD\nref: hotfix/urgent"]
        IDX_H["index\n(staging area)"]
        CMN_H["commondir\n→ ../.."]
    end

    subgraph WTR[".git/worktrees/wt-review/"]
        HEAD_R["HEAD\nref: feature/login"]
        IDX_R["index\n(staging area)"]
    end

    WKDIR1["wt-hotfix/\n.git → worktrees/wt-hotfix"]
    WKDIR2["wt-review/\n.git → worktrees/wt-review"]

    WT --> WTH
    WT --> WTR
    WKDIR1 -.->|"포인터 파일"| WTH
    WKDIR2 -.->|"포인터 파일"| WTR
    WTH --> MAIN
    WTR --> MAIN

    style MAIN fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style WTH fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style WTR fill:#fce4ec,stroke:#c2185b,stroke-width:2px
</pre>

---

## 3. 공유되는 것과 독립적인 것

이 두 가지를 명확히 이해하면 worktree가 왜 "안전하고 효율적인지" 알 수 있습니다.

### 공유 (main .git/)
```bash
# 어느 worktree에서 commit해도 objects는 하나!
$ du -sh /path/to/main/.git/objects
850M  objects  ← 5GB 저장소여도 단 하나

# 브랜치도 공유
$ cat .git/refs/heads/  # 모든 워크트리에서 동일하게 보임
```

### 독립 (worktrees/<name>/)
```bash
# HEAD: 각 worktree가 다른 브랜치를 가리킴
$ cat .git/HEAD
ref: refs/heads/main  ← main worktree

$ cat .git/worktrees/wt-hotfix/HEAD
ref: refs/heads/hotfix/urgent  ← hotfix worktree

# index: staging area도 완전히 독립
# → wt-hotfix에서 git add해도 main의 staged 파일에 영향 없음
```

### 브랜치 잠금 — 실수 방지 장치
```bash
$ cd wt-hotfix
$ git checkout main  # main에서 이미 사용 중!
fatal: 'main' is already used by worktree at '/path/to/main'
```

같은 브랜치를 두 worktree에서 동시에 체크아웃하는 건 **금지**됩니다.  
파일 시스템 레벨의 충돌을 막는 Git의 안전장치입니다.

---

## 4. add, list, remove — 명령어 해체

### git worktree add

```bash
# 기본: 새 브랜치 만들면서 추가
git worktree add ../hotfix -b hotfix/critical-bug

# 기존 브랜치로 추가
git worktree add ../review feature/login

# 특정 커밋으로 (detached HEAD)
git worktree add --detach ../inspect abc1234

# orphan 브랜치 (히스토리 없는 새 브랜치, Git 2.39+)
git worktree add --orphan -b fresh-start ../new-area
```

add가 하는 일:
1. `<path>` 디렉토리 생성
2. `.git/worktrees/<name>/` 메타데이터 디렉토리 생성
3. `<path>/.git` 파일 생성 (포인터)
4. 해당 브랜치 파일들 checkout

### git worktree list

```bash
$ git worktree list
/path/main     abc1234 [main]
/path/hotfix   def5678 [hotfix/urgent]
/path/review   def5678 [feature/login] (locked)

# 기계가 읽기 좋은 포맷
$ git worktree list --porcelain
worktree /path/main
HEAD abc1234...
branch refs/heads/main

worktree /path/hotfix
HEAD def5678...
branch refs/heads/hotfix/urgent
```

### git worktree remove

```bash
# 정상 제거 (clean working tree만 가능)
git worktree remove /path/hotfix

# 강제 제거 (변경사항 있어도)
git worktree remove -f /path/hotfix

# 삭제된 worktree 메타데이터 정리
git worktree prune
```

---

## 5. 실전 활용 3가지 패턴

### 패턴 1: 긴급 핫픽스 — stash 없이

```bash
# 상황: feature/big-refactor 작업 중 장애 발생
$ git worktree add ../hotfix hotfix/v2.1.1
$ cd ../hotfix

# 독립된 디렉토리에서 수정 & 테스트
$ vim src/payment/processor.ts
$ npm test
$ git commit -am "fix: payment timeout issue"
$ git push

# 원래 작업으로 복귀
$ cd ../my-project
$ git status
# 변경사항 그대로! stash pop 필요 없음

# hotfix worktree 정리
$ git worktree remove ../hotfix
```

### 패턴 2: PR 리뷰 — 실제로 실행하면서

```bash
$ git fetch origin pull/142/head:pr/142
$ git worktree add ../review-pr-142 pr/142
$ cd ../review-pr-142

# 동료 코드를 실제로 실행해보면서 리뷰
$ npm run dev  # 3001 포트에서 실행
# 내 dev 서버(3000)와 동시에 켜서 비교 가능!
```

### 패턴 3: 동시 빌드 / 버전 비교

```bash
$ git worktree add ../build-v2 v2.0-release
$ git worktree add ../build-main main

# 두 버전 병렬 빌드
$ (cd ../build-v2 && npm run build) &
$ (cd ../build-main && npm run build) &
wait

# 번들 사이즈 비교
$ du -sh ../build-v2/dist ../build-main/dist
```

---

## 6. Worktree vs Branch switch vs Clone

```
상황: "main 작업 중 feature 브랜치 코드 확인이 필요하다"

Branch switch:  git stash → checkout → 작업 → checkout → stash pop
                [✗ 컨텍스트 스위칭, ✗ stash 관리 부담]

Clone:          git clone . ../temp → 작업 → rm -rf ../temp
                [✗ 대형 저장소 복사 시간, ✗ 디스크 낭비, ✗ remote 분리]

Worktree:       git worktree add ../temp feature → 작업 → remove
                [✓ 즉시, ✓ objects 공유, ✓ stash/remote 공유]
```

<pre class="mermaid">
flowchart LR
    subgraph CLONE["Clone (별도 저장소)"]
        REPO1[".git\n(objects 복사)"]
        REPO2[".git\n(objects 복사)"]
    end

    subgraph WT["Worktree (하나의 저장소)"]
        GIT[".git/\nobjects 공유"]
        W1["worktree 1\nHEAD, index"]
        W2["worktree 2\nHEAD, index"]
        GIT --> W1
        GIT --> W2
    end

    style GIT fill:#c8e6c9,stroke:#388e3c,stroke-width:3px
    style REPO1 fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style REPO2 fill:#ffcdd2,stroke:#c62828,stroke-width:2px
</pre>

---

## 7. 역사: 2015년, 숨겨진 .git의 등장

`git worktree`는 Git **2.5** (2015년 7월)에 처음 등장했습니다.

그 전에는 어떻게 했을까요?

```bash
# 2015년 이전 개발자들의 워크플로우

# 방법 1: 저장소 통째로 clone
git clone . /path/to/work2

# 방법 2: 패치 파일 방식
git diff > my-work.patch && git checkout -- .
... (다른 작업) ...
git apply my-work.patch

# 방법 3: 그냥 커밋하고 나중에 squash
git commit -m "WIP: 임시"
```

핵심 설계 결정 두 가지:

**① `.git` 파일 (포인터) 개념**  
linked worktree는 `.git` 디렉토리 대신 `.git` **텍스트 파일**을 가집니다.  
이미 submodule에서 사용하던 패턴을 worktree에도 적용했습니다.

**② GIT_COMMON_DIR 도입**  
"이 경로는 worktree마다 독립이고, 저 경로는 공유다"를 Git이 구분하려면 새로운 개념이 필요했습니다.  
`GIT_COMMON_DIR` 환경변수와 `commondir` 파일이 이를 가능하게 합니다.

```bash
# Git이 내부적으로 경로를 해석하는 방식
HEAD  →  GIT_DIR (worktree 전용)     → .git/worktrees/hotfix/HEAD
index →  GIT_DIR (worktree 전용)     → .git/worktrees/hotfix/index
refs/ →  GIT_COMMON_DIR (공유)       → .git/refs/
objects/ → GIT_COMMON_DIR (공유)     → .git/objects/
```

이후 버전에서 조금씩 성숙해졌습니다:

| 버전 | 추가된 기능 |
|------|-----------|
| 2.5 (2015) | `add`, `list`, `prune` 최초 도입 |
| 2.15 (2017) | `lock` / `unlock` 추가 |
| 2.36 (2022) | `--reason` 옵션 개선 |
| 2.39 (2022) | `--orphan` 옵션 추가 |

---

## 8. 직접 해보기

```bash
# 1. 테스트 저장소 만들기
mkdir wt-demo && cd wt-demo
git init && git config user.name "Test" && git config user.email "test@test.com"
echo "main content" > main.txt
git add . && git commit -m "Initial"
git branch feature/login

# 2. worktree 추가
git worktree add ../wt-hotfix -b hotfix/urgent
git worktree add ../wt-review feature/login
git worktree list

# 3. 내부 탐험
cat ../wt-hotfix/.git          # 포인터 파일!
ls .git/worktrees/wt-hotfix/   # 메타데이터 디렉토리
cat .git/worktrees/wt-hotfix/HEAD      # hotfix 브랜치 가리킴
cat .git/worktrees/wt-hotfix/commondir # "../.." (main .git)

# 4. 독립 작업
cd ../wt-hotfix
echo "hotfix!" > hotfix.txt && git add . && git commit -m "Hotfix work"
cd ../wt-review
echo "review!" > review.txt && git add . && git commit -m "Review work"

# 5. 브랜치 잠금 확인
git checkout main  # fatal! main is already used by worktree

# 6. lock 걸기
cd ..
git -C wt-demo worktree lock --reason "CI 빌드 중" ../wt-hotfix
cat wt-demo/.git/worktrees/wt-hotfix/locked  # "CI 빌드 중"
git -C wt-demo worktree remove ../wt-hotfix  # fatal! locked

# 7. 정리
git -C wt-demo worktree unlock ../wt-hotfix
git -C wt-demo worktree remove ../wt-hotfix
git -C wt-demo worktree remove ../wt-review
git -C wt-demo worktree list  # 하나만 남음
```

---

## 정리

<pre class="mermaid">
flowchart TB
    ADD["git worktree add"]
    LIST["git worktree list"]
    REMOVE["git worktree remove"]
    LOCK["git worktree lock"]

    ADD -->|"만든다"| LINKED["Linked Worktree\n(.git 파일 + .git/worktrees/<name>/)"]
    LINKED -->|"공유"| SHARED["objects, refs, config, hooks"]
    LINKED -->|"독립"| PRIVATE["HEAD, index, logs/HEAD"]
    LIST -->|"조회"| LINKED
    REMOVE -->|"삭제"| LINKED
    LOCK -->|"보호"| LINKED

    style LINKED fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style SHARED fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style PRIVATE fill:#fff9c4,stroke:#f57f17,stroke-width:2px
</pre>

| 개념 | 실체 |
|------|------|
| linked worktree의 `.git` | 포인터 파일 (텍스트) |
| HEAD, index | worktree별 독립 |
| objects, refs | 저장소 전체 공유 |
| 브랜치 잠금 | 동일 브랜치 동시 사용 불가 |
| `commondir` | 공유 `.git` 경로 |
| stash | 전체 공유 (refs/stash가 공유 .git에) |

**Git의 설계 철학 한 마디:**

> Clone은 독립을 택한다. Worktree는 공유를 택한다.  
> Git은 "같은 것은 한 번만 저장"하는 원칙을 여기서도 지킵니다.  
> objects를 복사하지 않고, 포인터 하나로 여러 현실을 동시에 만들어내는 것.  
> 그게 worktree의 본질입니다.

---

---

## 참고 자료

- [Git Official Docs - git-worktree](https://git-scm.com/docs/git-worktree)
- [Git 2.5 Release Notes](https://raw.githubusercontent.com/git/git/master/Documentation/RelNotes/2.5.0.txt)
- [Pro Git Book - Worktrees](https://git-scm.com/book/en/v2/Git-Tools-Worktrees)
- [Git Source Code - worktree.c](https://github.com/git/git/blob/master/worktree.c)
- [Git Source Code - builtin/worktree.c](https://github.com/git/git/blob/master/builtin/worktree.c)
