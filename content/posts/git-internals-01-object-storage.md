---
title: "해체분석기 #1: Git은 어떻게 파일을 저장할까?"
date: 2026-02-03
summary: ".git 폴더를 열어보며 Git의 Object Model을 이해합니다"
tags: ["git", "해체분석기"]
categories: ["개발"]
series: ["해체분석기"]
draft: false
mermaid: true
---

> 매일 쓰는 Git, 하지만 `.git` 폴더 안을 들여다본 적 있나요?

## 들어가며

Git을 처음 배울 때 우리는 `add`, `commit`, `push`를 외웁니다.  
하지만 이 명령어들이 실제로 무엇을 하는지, 파일이 어디에 어떻게 저장되는지는 잘 모릅니다.

오늘은 `.git` 폴더를 직접 열어보며 Git의 심장부를 해체해봅니다.

---

## 1. .git 폴더 구조 한눈에 보기

```
.git/
├── HEAD              ← 현재 브랜치
├── config            ← 저장소 설정
├── objects/          ← ⭐ 모든 데이터 저장
│   ├── pack/
│   └── info/
└── refs/             ← 브랜치/태그 정보
    ├── heads/
    └── tags/
```

핵심은 `objects/` 폴더입니다. **Git의 모든 것은 여기에 저장됩니다.**

---

## 2. Git Object Model: 세 가지 객체

Git은 모든 데이터를 **세 가지 객체**로 저장합니다:

<div class="mermaid">
flowchart LR
    C[Commit] -->|tree| T[Tree]
    T -->|file1| B1[Blob]
    T -->|file2| B2[Blob]
</div>

### 2.1 Blob (파일 내용)

```bash
# 파일 하나를 Git에 저장하면?
$ echo "Hello, Git!" | git hash-object -w --stdin
557db03de997c86a4a028e1ebd3a1ceb225be238
```

<div class="mermaid">
flowchart LR
    A[Hello Git!] -->|SHA-1| B[blob 557db03...]
    B -->|저장| C[.git/objects/55/7db03...]
</div>

- 파일 **내용**만 저장 (이름 없음!)
- SHA-1 해시가 파일명이 됨
- 같은 내용 = 같은 해시 = 한 번만 저장

### 2.2 Tree (디렉토리 구조)

<div class="mermaid">
flowchart TB
    T1[tree 8a7b3c] --> B1[blob - README.md]
    T1 --> B2[blob - main.py]
    T1 --> T2[tree - src/]
    T2 --> B3[blob - app.py]
</div>

- 파일명 + blob 해시 매핑
- 디렉토리는 또 다른 tree를 참조
- Unix 파일 권한도 저장 (100644, 040000 등)

### 2.3 Commit (스냅샷)

<div class="mermaid">
flowchart TB
    C3[commit - 최신] -->|parent| C2[commit]
    C2 -->|parent| C1[commit - 최초]
    C3 -->|tree| T3[tree]
    C2 -->|tree| T2[tree]
    C1 -->|tree| T1[tree]
</div>

```
commit e5f6g7...
├── tree      8a7b3c...     # 루트 tree (이 시점의 전체 파일들)
├── parent    a1b2c3...     # 이전 커밋 (히스토리 연결)
├── author    Gideok <...>
├── committer Gideok <...>
└── message   "첫 번째 커밋"
```

---

## 3. 전체 구조: 모든 것이 연결된다

<div class="mermaid">
flowchart TB
    HEAD[HEAD] -->|ref| MAIN[refs/heads/main]
    MAIN --> C2[commit 2]
    C2 -->|parent| C1[commit 1]
    C2 -->|tree| T2[tree]
    C1 -->|tree| T1[tree]
    T2 --> B1[README.md]
    T2 --> B2[main.py]
    T2 --> B3[login.py]
    T1 --> B1
    T1 --> B2
</div>

---

## 4. 직접 해보기: 커밋의 정체 파헤치기

```bash
# 최근 커밋 해시 확인
$ git log -1 --format=%H
e5f6g7h8i9j0...

# 커밋 내용 보기
$ git cat-file -p e5f6g7
tree 8a7b3c4d5e6f...
parent a1b2c3d4e5f6...
author Gideok <gideok@example.com> 1706952000 +0900
committer Gideok <gideok@example.com> 1706952000 +0900

Add new feature

# tree 내용 보기
$ git cat-file -p 8a7b3c
100644 blob abc123...    README.md
100644 blob def456...    main.py
```

---

## 5. 충격적인 사실들

### 🤯 브랜치는 그냥 텍스트 파일이다

<div class="mermaid">
flowchart LR
    A[.git/refs/heads/main] -->|내용| B[e5f6g7h8i9j0...]
</div>

```bash
$ cat .git/refs/heads/main
e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4
```

**40글자 커밋 해시가 끝.** 브랜치 생성 = 파일 하나 만들기!

### 🤯 같은 내용 = 같은 해시 = 저장 한 번

<div class="mermaid">
flowchart TB
    F1[file1.txt] -->|같은 해시| BLOB[blob abc123]
    F2[file2.txt] -->|같은 해시| BLOB
</div>

```bash
$ echo "동일한 내용" > file1.txt
$ echo "동일한 내용" > file2.txt
$ git add .
# objects/에는 blob 하나만 생성됨!
```

---

## 6. 정리: Git = Content-Addressable 파일 시스템

<div class="mermaid">
flowchart TB
    subgraph visible[우리가 보는 것]
        FILES[파일/폴더]
        BRANCH[브랜치]
        HISTORY[히스토리]
    end
    subgraph internal[Git 내부]
        BLOB[blob]
        TREE[tree]
        COMMIT[commit]
        REF[refs]
    end
    FILES --> BLOB
    FILES --> TREE
    BRANCH --> REF
    REF --> COMMIT
    HISTORY --> COMMIT
    COMMIT --> TREE
    TREE --> BLOB
</div>

| 우리가 아는 개념 | Git 내부 실체 |
|-----------------|---------------|
| 파일 | blob 객체 |
| 폴더 | tree 객체 |
| 커밋 | commit 객체 |
| 브랜치 | refs/heads/의 텍스트 파일 |
| HEAD | 현재 브랜치를 가리키는 포인터 |

Git은 결국 **해시로 주소 지정되는 파일 시스템** 위에  
**커밋이라는 스냅샷**을 쌓아가는 구조입니다.

---

## 다음 편 예고

> **해체분석기 #2: Git은 어떻게 변경사항을 추적할까?**
>
> - `git diff`는 어떻게 동작하는가
> - staging area(index)의 정체
> - merge와 rebase의 차이 (DAG 관점에서)

---

## 참고 자료

- [Pro Git Book - Git Internals](https://git-scm.com/book/en/v2/Git-Internals-Plumbing-and-Porcelain)
- [Git from the inside out](https://codewords.recurse.com/issues/two/git-from-the-inside-out)
