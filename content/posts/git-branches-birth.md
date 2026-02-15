---
title: "Git 해체분석기 #5: Branch는 어떻게 탄생했나"
date: 2026-02-06T16:00:00+09:00
draft: false
tags: ["git", "해체분석기", "branch", "refs"]
series: ["Git 해체분석기"]
series_order: 5
mermaid: true
toc: true
---

## 이전 글 요약

[지난 글](/posts/git-evolution-first-two-weeks/)에서 Git의 첫 2주를 살펴봤다.

Day 1에는 저장만, Day 12에는 머지까지. 하지만 한 가지 빠진 게 있었다.

**Branch가 없었다.**

---

## 문제: Hash를 외워야 했다

첫 커밋의 Git에는 branch 개념이 없었다. commit을 만들면 40자 hash가 나온다:

```bash
$ echo "commit message" | commit-tree abc123...
d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd
```

이 hash를 **직접 기억**해야 했다.

```bash
# 어제 작업하던 commit으로 돌아가려면?
git-read-tree d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd

# 아니, 그게 뭐였지...?
```

GitLab 블로그의 표현을 빌리면:

> "There were no branches, tags, or even references. **Users were expected to manually keep track of object IDs.**"

팀이 5명이고, 각자 작업 중인 commit이 3개씩 있다면? 75개의 hash를 관리해야 한다.

---

## 해결: 이름표를 붙이자

생각해보면 답은 간단하다. **Hash에 이름을 붙이면 된다.**

```
d1f4e8b7c9a... → "main"
a2b3c4d5e6f... → "feature"
```

이게 바로 **refs (references)** 시스템이다.

### 파일 하나가 전부다

Git의 branch는 놀랍도록 단순하다:

```bash
$ cat .git/refs/heads/main
d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd
```

**그냥 텍스트 파일이다.** 40자 hash가 적혀 있을 뿐.

```
.git/
├── objects/          # 실제 데이터
└── refs/
    └── heads/
        ├── main      # "main" 브랜치 = commit hash
        └── feature   # "feature" 브랜치 = commit hash
```

Branch를 만든다는 건? **파일 하나 만드는 것**이다:

```bash
# feature 브랜치 생성
echo "d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd" > .git/refs/heads/feature
```

이게 `git branch feature`가 하는 일의 전부다.

### 왜 이렇게 설계했을까?

1. **빠르다**: 파일 하나 읽는 것 = O(1)
2. **가볍다**: Branch 1000개 = 파일 1000개 (각 41바이트)
3. **단순하다**: 특별한 자료구조 없이 파일시스템이 해준다

SVN에서 branch는 **디렉토리 전체 복사**였다. Git에서 branch는 **41바이트 파일**이다.

---

## HEAD: "지금 어디 있지?"

Branch가 "commit에 붙인 이름표"라면, **HEAD**는 "지금 내가 보고 있는 branch"다.

```bash
$ cat .git/HEAD
ref: refs/heads/main
```

HEAD는 branch를 가리키는 **포인터의 포인터**다:

<pre class="mermaid">
flowchart LR
    HEAD["HEAD"]
    main["refs/heads/main"]
    commit["d1f4e8b..."]
    
    HEAD -->|ref: refs/heads/main| main
    main -->|d1f4e8b...| commit
</pre>

### Checkout의 진짜 의미

```bash
git checkout feature
```

이 명령이 하는 일:

1. `.git/HEAD` 파일을 `ref: refs/heads/feature`로 수정
2. feature가 가리키는 commit의 tree를 working directory에 반영

**Branch를 바꾼다 = 텍스트 파일 한 줄 수정**

### Commit하면 무슨 일이?

```bash
git commit -m "new feature"
```

1. 새 commit 객체 생성 → 새 hash
2. HEAD가 가리키는 branch 파일에 새 hash 기록

```bash
# HEAD → refs/heads/feature → (old hash)
# commit 후
# HEAD → refs/heads/feature → (new hash)
```

Branch가 "앞으로 이동"하는 것처럼 보이지만, 실제로는 **파일 내용이 업데이트**될 뿐이다.

---

## 실제로 보자

현재 디렉토리에서 직접 확인할 수 있다:

```bash
# 1. refs 구조 확인
$ find .git/refs -type f
.git/refs/heads/main
.git/refs/heads/feature

# 2. 각 branch가 가리키는 commit
$ cat .git/refs/heads/main
d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd

# 3. HEAD 확인
$ cat .git/HEAD
ref: refs/heads/main

# 4. 수동으로 branch 만들기 (git branch와 동일)
$ echo "a1b2c3d4..." > .git/refs/heads/experiment
$ git branch
  experiment  # 생겼다!
  feature
* main
```

Git의 "마법"은 없다. 전부 파일이다.

---

## Detached HEAD

가끔 이런 경고를 본다:

```
You are in 'detached HEAD' state.
```

이건 HEAD가 branch가 아니라 **직접 commit을 가리킬 때** 발생한다:

```bash
$ git checkout d1f4e8b7
$ cat .git/HEAD
d1f4e8b7c9a0f2e3d4c5b6a7890123456789abcd  # ref:가 없다!
```

<pre class="mermaid">
flowchart LR
    subgraph normal["일반 상태"]
        H1["HEAD"] --> B1["main"] --> C1["commit"]
    end
    
    subgraph detached["Detached HEAD"]
        H2["HEAD"] --> C2["commit"]
    end
</pre>

왜 위험한가? 이 상태에서 commit하면:

1. 새 commit 생성
2. HEAD가 새 commit 가리킴
3. **하지만 어떤 branch도 이 commit을 모른다**

나중에 다른 branch로 checkout하면? 그 commit은 미아가 된다.

---

## 초기 Git은 어땠을까?

첫 커밋에는 refs 디렉토리도, HEAD 파일도 없었다.

```
# 2005년 4월 7일 (Day 1)
.dircache/
└── objects/
    ├── 00/
    ├── 01/
    ...
    └── ff/
```

### Day 53: refs의 탄생

```
commit cad88fdf8d
Date: Mon May 30 10:20:44 2005 -0700

git-init-db: set up the full default environment

Create .git/refs/{heads,tags} and make .git/HEAD be a symlink to
(the as yet non-existent) .git/refs/heads/master.
```

첫 커밋으로부터 **7주 후**, Linus가 refs 시스템을 추가했다:

```c
// refs 디렉토리 생성
strcpy(path + len, "refs");
safe_create_dir(path);
strcpy(path + len, "refs/heads");
safe_create_dir(path);
strcpy(path + len, "refs/tags");
safe_create_dir(path);

// HEAD → refs/heads/master 심볼릭 링크
strcpy(path + len, "HEAD");
symlink("refs/heads/master", path);
```

이 한 커밋으로:
- `refs/heads/` - 브랜치용
- `refs/tags/` - 태그용
- `HEAD` - 현재 브랜치 포인터

**이 구조는 20년이 지난 지금도 동일하다.**

---

## 정리: Branch의 본질

| 개념 | 실체 |
|-----|------|
| Branch | `.git/refs/heads/이름` 파일 (41바이트) |
| HEAD | `.git/HEAD` 파일 (branch 또는 commit 가리킴) |
| Checkout | HEAD 파일 수정 + working directory 업데이트 |
| Commit | 새 hash 생성 + branch 파일 업데이트 |

Branch는 **commit에 붙인 이름표**다. 그 이상도 이하도 아니다.

---

## 다음 글 예고

Branch가 생겼으니 이제 **공유**할 차례다.

다음 글에서는:
- rsync에서 git 프로토콜까지
- fetch, pull, push의 등장
- remote와 origin의 탄생

[해체분석기 #10: Remote는 어떻게 탄생했나](/posts/git-remote-evolution/)에서 계속.

---

## 참고 자료

- [GitLab: Journey through Git's 20-year history](https://about.gitlab.com/blog/journey-through-gits-20-year-history/)
- [Git Book: Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References)
- [GitButler: 20 years of Git](https://blog.gitbutler.com/20-years-of-git)
