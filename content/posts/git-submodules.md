---
title: "Git 해체분석기 #15: Submodules - 저장소 안의 저장소"
date: 2026-02-17T18:00:00+09:00
draft: false
summary: "git clone 했더니 폴더가 비어 있다. --recurse-submodules를 빠뜨린 것이다. Submodule이 내부적으로 무엇인지, 왜 이렇게 동작하는지를 해체한다."
tags: ["git", "해체분석기", "submodule", "subtree", "monorepo"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 15
weight: -15
mermaid: true
toc: true
---

> "저장소 안에 저장소가 있다. 근데 파일 시스템에선 그냥 폴더처럼 보인다."  
> **Submodule의 본질은 하나의 SHA다.**

## 들어가며

팀에 합류하거나 오픈소스를 clone할 때 이런 상황을 만난 적 있을 겁니다.

```bash
$ git clone https://github.com/example/awesome-project.git
$ cd awesome-project
$ ls libs/engine/
# 아무것도 없다...

$ cat libs/engine/.git
# 파일도 없다
```

분명 `libs/engine/`이라는 디렉토리가 있는데, 안이 텅 비어 있습니다.  
README에는 "먼저 `git submodule update --init --recursive`를 실행하라"고 적혀 있죠.

왜 이렇게 동작할까요?  
오늘은 **Git Submodule의 내부 구조**를 해체합니다.

---

## 1. Submodule이란?

**Submodule = 다른 Git 저장소를 현재 저장소의 특정 경로에 포함시키는 메커니즘.**

비유하자면, 책 안에 다른 책의 "특정 페이지를 가리키는 포스트잇"을 붙여두는 것입니다.  
포스트잇이 책의 내용 자체를 담지 않듯, submodule도 외부 저장소의 파일을 직접 복사하지 않습니다.  
대신 "이 경로는 저 저장소의 **이 커밋**을 사용하시오"라는 정보만 저장합니다.

```
프로젝트 저장소
├── src/
├── README.md
├── .gitmodules         ← submodule 메타데이터
└── libs/
    └── engine/         ← 여기가 외부 저장소 (특정 커밋에 고정)
```

Submodule이 유용한 상황:
- 게임 프로젝트가 물리 엔진 라이브러리를 소스 수준으로 포함할 때
- 조직 공통 CI 스크립트를 여러 저장소에서 공유할 때
- 외부 라이브러리의 **정확히 이 버전**을 보장해야 할 때

---

## 2. Gitlink: Submodule의 진짜 정체

이것이 오늘의 핵심입니다.

Git은 파일을 tree 객체로 저장합니다. tree 안에는 보통 이런 항목들이 있습니다:

```bash
$ git ls-tree HEAD
100644 blob a1b2c3  README.md
100644 blob d4e5f6  package.json
040000 tree 789abc  src
```

앞의 숫자는 파일 모드입니다.
- `100644` = 일반 파일
- `100755` = 실행 파일
- `040000` = 디렉토리(tree)

그런데 submodule이 있으면 이상한 모드가 등장합니다.

```bash
$ git ls-tree HEAD
100644 blob a1b2c3  README.md
100644 blob d4e5f6  package.json
040000 tree 789abc  src
160000 commit 7a8b9c  libs/engine   ← ❓
```

**`160000 commit`** — 이것이 **gitlink**입니다.

일반 파일이나 디렉토리와 달리, gitlink는 **외부 저장소의 커밋 SHA를 직접 가리킵니다.**  
`libs/engine/` 디렉토리처럼 보이지만, git 내부에서는 완전히 다른 타입입니다.

```bash
$ git rev-parse HEAD:libs/engine
7a8b9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6789
# 이것이 외부 저장소(engine)의 특정 커밋 SHA
```

이게 submodule의 본질입니다. **부모 저장소는 자식 저장소의 커밋 SHA 하나만 기억합니다.**

<pre class="mermaid">
flowchart TD
    subgraph PARENT ["부모 저장소 (awesome-project)"]
        T["tree (HEAD)"]
        B1["blob: README.md"]
        B2["blob: package.json"]
        GL["gitlink\n160000 commit\n7a8b9c1..."]
        T --> B1
        T --> B2
        T --> GL
    end

    subgraph CHILD ["외부 저장소 (engine.git)"]
        C["commit 7a8b9c1"]
        CT["tree"]
        CB["blob: engine.h\nblob: engine.c\n..."]
        C --> CT --> CB
    end

    GL -->|"SHA만 저장"| C

    style GL fill:#fff3e0,stroke:#e65100
    style C fill:#e8f5e9,stroke:#388e3c
</pre>

---

## 3. .gitmodules 파일

gitlink는 SHA만 알고 있습니다. 그렇다면 "어디서 그 저장소를 clone해 와야 하는가?"는 어디에 있을까요?  
바로 `.gitmodules`입니다.

```ini
# .gitmodules (저장소 루트, 버전 관리됨)
[submodule "libs/engine"]
    path = libs/engine
    url = https://github.com/example/engine.git
    branch = main

[submodule "themes/default"]
    path = themes/default
    url = git@github.com:example/theme.git
```

`.gitmodules`는 **버전 관리됩니다.** 팀원 모두가 어느 URL에서 외부 저장소를 가져오는지 공유할 수 있습니다.

그런데 `.git/config`에도 비슷한 내용이 있습니다.

```ini
# .git/config (로컬, 버전 관리 안 됨)
[submodule "libs/engine"]
    url = https://github.com/example/engine.git
    active = true
```

두 파일의 역할:
- **`.gitmodules`**: 공개 정보. 팀 공유용. "공식 URL"
- **`.git/config`**: 로컬 설정. 개인이 URL을 오버라이드할 수 있음

이 두 파일이 어긋날 때 사용하는 명령이 `git submodule sync`입니다.  
`.gitmodules`의 URL을 `.git/config`에 덮어씁니다.

---

## 4. add, update, sync 동작

### submodule add

```bash
$ git submodule add https://github.com/example/engine.git libs/engine
```

내부에서 벌어지는 일:

<pre class="mermaid">
flowchart TD
    A["git submodule add URL path"]
    B["외부 저장소를 path에 clone"]
    C[".gitmodules에 설정 추가"]
    D[".git/config에도 설정 추가"]
    E["path를 gitlink로 staging 등록\n(git add path)"]
    F[".git/modules/path/에\n실제 git 데이터 저장"]

    A --> B --> C --> D --> E --> F

    style F fill:#fff9c4,stroke:#f9a825
</pre>

여기서 흥미로운 점이 있습니다. `libs/engine/` 안의 `.git`을 들여다보면:

```bash
$ cat libs/engine/.git
gitdir: ../../.git/modules/libs/engine
```

**파일입니다.** 디렉토리가 아니라 파일.

submodule의 실제 git 데이터는 부모 저장소의 `.git/modules/libs/engine/`에 있습니다.  
`libs/engine/.git`은 그곳을 가리키는 포인터에 불과합니다.

```
.git/
├── modules/
│   └── libs/engine/    ← 진짜 git 저장소 데이터
│       ├── HEAD
│       ├── objects/
│       └── config
libs/
└── engine/
    ├── .git            ← 파일 (포인터)
    ├── engine.h
    └── engine.c
```

### submodule update

```bash
$ git submodule update --init --recursive
```

1. `--init`: `.gitmodules` 정보를 `.git/config`에 등록 (아직 clone 안 함)
2. `update`: 부모의 gitlink가 가리키는 SHA로 체크아웃
3. `--recursive`: 중첩 submodule까지 처리

결과적으로 submodule은 **detached HEAD 상태**가 됩니다.

```bash
$ cd libs/engine
$ git status
HEAD detached at 7a8b9c1
nothing to commit, working tree clean
```

브랜치에 있지 않습니다. 특정 커밋에 직접 고정되어 있습니다.  
이건 버그가 아닙니다. submodule의 설계입니다. "이 커밋을 써라"가 목적이기 때문입니다.

---

## 5. Submodule vs Subtree vs Monorepo

외부 코드를 관리하는 방법은 submodule만 있지 않습니다.

### git subtree: 히스토리를 병합하는 방식

```bash
# subtree 추가 (--squash: 외부 히스토리를 하나의 커밋으로 압축)
$ git subtree add --prefix=libs/engine \
    https://github.com/example/engine.git main --squash

# 업데이트
$ git subtree pull --prefix=libs/engine \
    https://github.com/example/engine.git main --squash
```

subtree는 외부 저장소의 내용을 **현재 저장소 히스토리에 직접 병합**합니다.  
`libs/engine/` 안의 파일들이 일반 파일처럼 저장됩니다.

장점: clone 시 `--recurse-submodules` 없이 바로 사용 가능.  
단점: 업스트림에 변경사항을 돌려주려면 `git subtree push`가 필요하고 복잡합니다.

### Monorepo: 전부 한 저장소에

Google, Meta, Twitter가 사용하는 방식. 모든 프로젝트를 단일 저장소에 넣습니다.  
외부 의존성 문제가 없지만, 저장소 크기와 빌드 관리가 과제입니다.

### 비교

| 항목 | Submodule | Subtree | Monorepo |
|------|:---------:|:-------:|:--------:|
| clone 복잡도 | 높음 | 낮음 | 낮음 |
| 특정 버전 고정 | ✅ 쉬움 | 가능 | 브랜치로 |
| 업스트림 기여 | ✅ 쉬움 | 복잡 | 해당 없음 |
| 히스토리 분리 | ✅ | ❌ 병합됨 | ❌ |
| 팀 러닝 커브 | 높음 | 중간 | 낮음 |
| 저장소 크기 | 작음 | 큼 | 매우 큼 |

**선택 기준:**
- 외부 라이브러리를 특정 버전으로 고정하고 싶다 → **Submodule**
- 외부 코드를 수정해서 upstream에 자주 기여한다 → **Fork + 패키지 매니저**
- 같은 조직 내 여러 서비스를 관리한다 → **Monorepo**
- 단순히 외부 코드를 "붙여넣고" 싶다 → **Subtree**

---

## 6. Submodule의 함정들

submodule은 개념은 간단하지만, 함정이 많습니다. 실제로 많은 팀이 고통받는 지점들입니다.

### 🪤 함정 1: clone 후 빈 디렉토리

```bash
$ git clone https://example.com/repo.git
$ ls libs/engine/
# 비어 있음!
```

`git clone`은 기본적으로 submodule을 초기화하지 않습니다.

```bash
# 해결: clone 시 함께
$ git clone --recurse-submodules URL

# 해결: clone 후
$ git submodule update --init --recursive

# 팀 전체 기본값으로 설정 (Git 2.15+)
$ git config --global submodule.recurse true
```

### 🪤 함정 2: submodule 수정 후 부모를 업데이트 안 함

```bash
$ cd libs/engine
$ git checkout -b fix/bug
$ # 코드 수정, 커밋, push
$ cd ..

$ git status
  modified: libs/engine   ← 부모가 "gitlink가 바뀌었다"고 인식
```

submodule에서 커밋을 만들면, 부모 저장소도 업데이트해야 합니다.

```bash
$ git add libs/engine
$ git commit -m "chore: update engine submodule to latest fix"
$ git push
```

이 단계를 빠뜨리면 팀원들은 여전히 옛날 SHA를 가리키게 됩니다.

### 🪤 함정 3: submodule push 빠뜨리기

```bash
# submodule에서 커밋 후 부모만 push
$ cd .. && git add libs/engine && git commit -m "update" && git push

# 팀원이 받으면:
$ git submodule update
error: Server does not allow request for unadvertised object 7a8b9c1...
# 부모는 SHA를 가리키는데, 그 커밋이 원격에 없다!
```

```bash
# 해결: submodule push를 포함해서
$ git push --recurse-submodules=on-demand
# submodule이 먼저 push된 후 부모가 push됨
```

### 🪤 함정 4: `git submodule update`가 변경사항을 날린다

```bash
$ cd libs/engine
$ git commit -m "WIP: experimenting"
$ cd ..
$ git submodule update   # 부모의 gitlink(SHA)로 되돌림
# 방금 만든 WIP 커밋은 이제 dangling (브랜치 없음, gc 대상)
```

submodule 안에서 작업할 때는 반드시 **브랜치를 만들고** 작업하세요.

```bash
$ cd libs/engine
$ git checkout -b my-feature   # 브랜치 먼저!
$ # 그 후 작업
```

### 🪤 함정 5: submodule 상태 파악이 어렵다

```bash
$ git submodule status
-7a8b9c1 libs/engine    # 앞에 - : init 안 됨
+7a8b9c1 libs/engine    # 앞에 + : 부모 gitlink와 다른 SHA
 7a8b9c1 libs/engine    # 앞에 공백: 정상
U7a8b9c1 libs/engine    # 앞에 U: 충돌 상태
```

prefix의 의미를 외워두면 디버깅이 빠릅니다.

---

## 7. 충격적인 사실들

### 🤯 `.git`이 파일이다

submodule 안의 `.git`은 디렉토리가 아닙니다. 파일입니다.

```bash
$ cat libs/engine/.git
gitdir: ../../.git/modules/libs/engine
```

실제 git 데이터는 부모 저장소의 `.git/modules/`에 있습니다.  
이렇게 설계된 이유: submodule 디렉토리를 실수로 삭제해도 git 데이터가 살아남게 하기 위해.

### 🤯 gitlink는 blob도 tree도 아니다

git object 타입은 `blob`, `tree`, `commit`, `tag` 4가지입니다.  
gitlink는 tree 안에 `commit` 타입의 SHA를 직접 저장하는 특수 케이스입니다.  
git 객체 타입을 추가하지 않고, 기존 tree 구조를 "재활용"한 설계입니다.

### 🤯 모든 git 명령이 submodule 안에서 동작한다

submodule은 완전한 독립 저장소입니다.

```bash
$ cd libs/engine
$ git log --oneline
$ git branch -a
$ git remote -v
# 전부 동작
```

### 🤯 `foreach`로 모든 submodule에 명령을 한 번에

```bash
# 모든 submodule 업데이트
$ git submodule foreach 'git pull origin main'

# 모든 submodule 상태 확인
$ git submodule foreach --recursive 'git status'

# 모든 submodule에서 브랜치 확인
$ git submodule foreach 'git branch --show-current'
```

---

## 8. Submodule 제거하는 법 (의외로 복잡)

```bash
# 1. submodule 등록 해제 (로컬 설정에서 제거)
$ git submodule deinit libs/engine

# 2. 파일 시스템에서 제거 + git index에서 제거
$ git rm libs/engine

# 3. 캐시된 git 데이터 제거
$ rm -rf .git/modules/libs/engine

# 4. 커밋
$ git commit -m "chore: remove engine submodule"
```

이 네 단계를 모두 해야 깔끔히 제거됩니다.  
어느 하나라도 빠뜨리면 나중에 다시 같은 경로로 `submodule add`할 때 오류가 납니다.

---

## 정리

<pre class="mermaid">
flowchart TB
    subgraph CONCEPT ["Submodule의 본질"]
        GL["gitlink (160000 commit)\n외부 저장소의 SHA 하나를 가리킴"]
        GM[".gitmodules\nURL + path 매핑\n(버전 관리됨)"]
        GC[".git/config\n로컬 URL 설정"]
        GD[".git/modules/\n실제 git 데이터 저장"]
        GL --- GM
        GM -->|"sync"| GC
        GL --- GD
    end

    subgraph OPS ["주요 명령어"]
        ADD["git submodule add\nURL path"]
        INIT["git submodule init\n.gitmodules → .git/config"]
        UPDATE["git submodule update\nSHA로 체크아웃"]
        SYNC["git submodule sync\nURL 동기화"]
        FOREACH["git submodule foreach\n'명령' 일괄 실행"]
    end

    subgraph TRAPS ["주요 함정"]
        T1["clone 후 빈 디렉토리\n→ --recurse-submodules"]
        T2["submodule 수정 후\n부모 미업데이트"]
        T3["push 시 submodule\npush 빠뜨리기"]
        T4["update가 WIP\n커밋 날리기"]
    end

    style CONCEPT fill:#e3f2fd,stroke:#1565c0
    style OPS fill:#e8f5e9,stroke:#2e7d32
    style TRAPS fill:#fce4ec,stroke:#c62828
</pre>

| 항목 | 내용 |
|------|------|
| **본질** | 외부 저장소의 커밋 SHA를 gitlink(160000)로 저장 |
| **핵심 파일** | `.gitmodules` (공개), `.git/config` (로컬) |
| **clone 후** | `git submodule update --init --recursive` 필수 |
| **detached HEAD** | 정상 동작. 특정 커밋 고정이 목적이기 때문 |
| **수정 시** | 브랜치 만들고 작업, 부모 저장소도 업데이트 필수 |
| **push 시** | `--recurse-submodules=on-demand` 권장 |

**Submodule의 핵심:**
> 저장소 안의 저장소처럼 보이지만, 실제로는 **커밋 SHA 하나**다.  
> 그 SHA 하나가 외부 저장소의 특정 상태를 고정한다.  
> 복잡성은 그 단순한 포인터 하나를 관리하는 과정에서 온다.

---

## 직접 해보기

```bash
# 1. 새 저장소 초기화
mkdir my-project && cd my-project
git init && echo "# My Project" > README.md
git add . && git commit -m "init"

# 2. submodule 추가
git submodule add https://github.com/git/git.git vendor/git --depth=1

# 3. 구조 확인
cat .gitmodules                    # 설정 파일
cat vendor/git/.git                # 파일! (디렉토리 아님)
git ls-tree HEAD vendor/           # 160000 commit 확인

# 4. gitlink가 가리키는 SHA 확인
git rev-parse HEAD:vendor/git      # 외부 저장소의 커밋 SHA
cd vendor/git && git log --oneline -1  # 동일한 SHA

# 5. 모두 커밋
cd ../..
git add .
git commit -m "chore: add git as submodule"
```

---


> **해체분석기 #16: Worktrees - 하나의 저장소, 여러 작업공간**
>
> - `git worktree add`의 내부 구조
> - `.git/worktrees/`에 저장되는 것
> - submodule과 worktree가 만날 때

---

## 참고 자료

- [Git Official Docs - gitsubmodules](https://git-scm.com/docs/gitsubmodules)
- [Pro Git Book - Git Tools: Submodules](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- [Git Internals - gitlink object](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
- [Atlassian - Git Submodules](https://www.atlassian.com/git/tutorials/git-submodule)
- [Git Subtree: an alternative to Git Submodule](https://www.atlassian.com/git/tutorials/git-subtree)
