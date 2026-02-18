---
title: "Git 해체분석기 #1: Git은 어떻게 파일을 저장할까?"
date: 2026-02-03
summary: ".git 폴더를 열어보며 Git의 Object Model을 이해합니다"
tags: ["git", "해체분석기"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 1
weight: -1
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

프로젝트 루트에 숨겨진 `.git` 폴더. 여기에 Git의 모든 비밀이 담겨 있습니다.

```
.git/
├── HEAD              ← 현재 브랜치를 가리키는 포인터
├── config            ← 이 저장소의 설정 파일
├── objects/          ← ⭐ 핵심! 모든 데이터가 여기 저장됨
│   ├── pack/         ← 압축된 객체들
│   └── info/
└── refs/             ← 브랜치와 태그 정보
    ├── heads/        ← 로컬 브랜치들
    └── tags/         ← 태그들
```

**핵심 포인트:** `objects/` 폴더가 Git의 심장입니다. 커밋, 파일 내용, 디렉토리 구조 전부 여기에 저장됩니다.

---

## 2. Git Object Model: 세 가지 객체

Git은 복잡해 보이지만, 내부적으로는 단 **세 가지 객체**만 사용합니다.

아래 그림은 이 세 객체가 어떻게 연결되는지 보여줍니다:

<pre class="mermaid">
flowchart LR
    C[COMMIT]
    T[TREE]
    B1[BLOB]
    B2[BLOB]
    
    C -->|tree| T
    T -->|README.md| B1
    T -->|main.py| B2
    
    style C fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style T fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B2 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
</pre>

| 색상 | 객체 | 역할 |
|------|------|------|
| 🔷 파랑 | **Commit** | "누가, 언제, 왜" + Tree 연결 |
| 🟢 초록 | **Tree** | 폴더 구조 (파일명 → Blob 매핑) |
| 🟡 노랑 | **Blob** | 실제 파일 내용 |

---

### 2.1 Blob: 파일 내용 저장소

**Blob**은 "Binary Large Object"의 약자로, **파일의 순수한 내용**만 저장합니다.

```bash
# "Hello, Git!" 이라는 내용을 Git에 저장하면?
$ echo "Hello, Git!" | git hash-object -w --stdin
557db03de997c86a4a028e1ebd3a1ceb225be238
```

이 과정을 그림으로 보면:

<pre class="mermaid">
flowchart LR
    A[File Content]
    B[SHA-1 Hash]
    C[.git/objects/55/7db03...]
    
    A --> B --> C
    
    style A fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
    style C fill:#e0e0e0,stroke:#616161,stroke-width:2px
</pre>

**왜 이렇게 설계했을까?**
- 🔸 **파일명은 저장 안 함** → 같은 내용이면 파일명이 달라도 하나만 저장 (용량 절약!)
- 🔸 **SHA-1 해시가 주소** → 내용이 같으면 해시도 같음 (중복 제거)
- 🔸 **변조 불가** → 내용이 바뀌면 해시도 바뀜 (무결성 보장)

---

### 2.2 Tree: 디렉토리 구조

**Tree**는 "이 폴더에 어떤 파일/폴더가 있는지"를 기록합니다.

<pre class="mermaid">
flowchart TB
    T1[TREE - root]
    B1[BLOB - README]
    B2[BLOB - main.py]
    T2[TREE - src]
    B3[BLOB - app.py]
    
    T1 -->|README.md| B1
    T1 -->|main.py| B2
    T1 -->|src| T2
    T2 -->|app.py| B3
    
    style T1 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style T2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B2 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B3 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
</pre>

**그림 설명:**
- 🟢 **초록 박스 (TREE)**: 디렉토리를 나타냄
- 🟡 **노란 박스 (BLOB)**: 실제 파일 내용
- **화살표**: 파일/폴더 이름 (Tree가 이름을 기억!)

---

### 2.3 Commit: 스냅샷 + 메타데이터

**Commit**은 "특정 시점의 프로젝트 전체 상태"를 저장합니다.

<pre class="mermaid">
flowchart TB
    C3[COMMIT 3 - latest]
    C2[COMMIT 2]
    C1[COMMIT 1 - initial]
    T3[TREE]
    T2[TREE]
    T1[TREE]
    
    C3 -->|parent| C2
    C2 -->|parent| C1
    C3 -->|tree| T3
    C2 -->|tree| T2
    C1 -->|tree| T1
    
    style C3 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style C2 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style C1 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style T3 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style T2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style T1 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

**그림 설명:**
- **세로 방향 (parent)**: 시간순 히스토리. 각 커밋은 이전 커밋을 가리킴
- **가로 방향 (tree)**: 그 시점의 전체 파일 상태. 커밋마다 다른 Tree를 가리킴

**Commit이 담고 있는 정보:**
```
commit e5f6g7...
├── tree      8a7b3c...     ← 이 시점의 파일 구조 (Tree 해시)
├── parent    a1b2c3...     ← 이전 커밋 (히스토리 연결)
├── author    Alice        ← 작성자
├── committer Alice        ← 커밋한 사람
└── message   "Add login"   ← 커밋 메시지
```

---

## 3. 전체 구조: HEAD → Branch → Commit → Tree → Blob

지금까지 배운 모든 것을 하나의 그림으로 연결하면:

<pre class="mermaid">
flowchart TB
    HEAD[HEAD]
    MAIN[main branch]
    C2[COMMIT 2]
    C1[COMMIT 1]
    T2[TREE]
    T1[TREE]
    B1[README]
    B2[main.py]
    B3[login.py]
    
    HEAD -->|ref| MAIN
    MAIN --> C2
    C2 -->|parent| C1
    C2 -->|tree| T2
    C1 -->|tree| T1
    T2 --> B1
    T2 --> B2
    T2 --> B3
    T1 --> B1
    T1 --> B2
    
    style HEAD fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style MAIN fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style C2 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style C1 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style T2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style T1 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B2 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B3 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
</pre>

**읽는 방법 (위에서 아래로):**

1. 🔴 **HEAD** → "지금 내가 어디 있지?" → `main` 브랜치
2. 🔴 **main** → "이 브랜치의 최신 커밋은?" → `COMMIT 2`
3. 🔷 **COMMIT** → "이 시점 파일들은?" → `TREE` 참조
4. 🟢 **TREE** → "어떤 파일들이 있지?" → `BLOB`들 나열
5. 🟡 **BLOB** → 실제 파일 내용!

**주목할 점:** `T1`과 `T2` 모두 같은 `README`, `main.py`를 가리킵니다. 파일이 안 바뀌면 같은 blob을 재사용!

---

## 4. 직접 해보기

이론은 충분합니다. 직접 까보죠!

```bash
# 1. 최근 커밋 해시 확인
$ git log -1 --format=%H
e5f6g7h8i9j0...

# 2. 커밋 내용 들여다보기
$ git cat-file -p e5f6g7
tree 8a7b3c4d5e6f...
parent a1b2c3d4e5f6...
author Alice <alice@example.com> 1706952000 +0900
committer Alice <alice@example.com> 1706952000 +0900

Add new feature

# 3. tree 내용 보기
$ git cat-file -p 8a7b3c
100644 blob abc123...    README.md
100644 blob def456...    main.py

# 4. blob 내용 보기 (실제 파일!)
$ git cat-file -p abc123
# README.md 파일 내용이 출력됨
```

---

## 5. 충격적인 사실들

### 🤯 브랜치는 그냥 40글자 텍스트 파일

"브랜치"라고 하면 뭔가 거창할 것 같지만...

<pre class="mermaid">
flowchart LR
    A[.git/refs/heads/main]
    B[e5f6g7h8i9j0...]
    
    A -->|contains| B
    
    style A fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style B fill:#e0e0e0,stroke:#616161,stroke-width:2px
</pre>

```bash
$ cat .git/refs/heads/main
e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4
```

**끝입니다.** 40글자 커밋 해시가 전부. 브랜치 생성 = 파일 하나 만들기!

---

### 🤯 같은 내용은 절대 두 번 저장 안 함

<pre class="mermaid">
flowchart TB
    F1[file1.txt]
    F2[file2.txt]
    F3[copy.txt]
    BLOB[Single BLOB]
    
    F1 -->|same hash| BLOB
    F2 -->|same hash| BLOB
    F3 -->|same hash| BLOB
    
    style F1 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style F2 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style F3 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style BLOB fill:#c8e6c9,stroke:#388e3c,stroke-width:3px
</pre>

**이게 왜 대단할까?**
- 대형 프로젝트에서 같은 라이선스 파일이 100개 폴더에 있어도 → **저장은 1번**
- 파일 복사해도 용량 증가 없음
- 이름 바꿔도 용량 증가 없음

---

## 6. 정리

<pre class="mermaid">
flowchart LR
    A1[Files]
    A2[Branches]
    A3[History]
    B1[BLOB]
    B2[TREE]
    B3[COMMIT]
    B4[REFS]
    
    A1 --> B1
    A1 --> B2
    A2 --> B4
    A3 --> B3
    
    style B1 fill:#ffecb3,stroke:#f57c00,stroke-width:2px
    style B2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B3 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style B4 fill:#ffcdd2,stroke:#c62828,stroke-width:2px
</pre>

| 우리가 아는 개념 | Git 내부 실체 | 역할 |
|-----------------|---------------|------|
| 파일 내용 | 🟡 Blob | 순수 데이터 저장 |
| 폴더 구조 | 🟢 Tree | 이름 + Blob/Tree 매핑 |
| 커밋 | 🔷 Commit | 스냅샷 + 메타데이터 |
| 브랜치/태그 | 🔴 Refs | 커밋을 가리키는 포인터 |

**Git의 본질:**
> 해시로 주소 지정되는 파일 시스템(Content-Addressable Storage) 위에  
> 커밋이라는 스냅샷을 쌓아가는 구조

---

---

## 참고 자료

- [Pro Git Book - Git Internals](https://git-scm.com/book/en/v2/Git-Internals-Plumbing-and-Porcelain)
- [Git from the inside out](https://codewords.recurse.com/issues/two/git-from-the-inside-out)
