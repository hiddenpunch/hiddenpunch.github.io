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

<div class="mermaid">
flowchart LR
    C[🔷 Commit<br/>스냅샷 메타데이터]
    T[🟢 Tree<br/>디렉토리 구조]
    B1[🟡 Blob<br/>파일 내용]
    B2[🟡 Blob<br/>파일 내용]
    
    C -->|"이 시점의<br/>파일 구조"| T
    T -->|"README.md"| B1
    T -->|"main.py"| B2
    
    style C fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style T fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B2 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
</div>

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

<div class="mermaid">
flowchart LR
    subgraph input[입력]
        A[파일 내용<br/>Hello Git!]
    end
    
    subgraph process[처리]
        B[SHA-1 해시 계산]
    end
    
    subgraph output[저장]
        C[.git/objects/55/7db03...]
    end
    
    A --> B --> C
    
    style A fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style C fill:#e0e0e0,stroke:#616161,stroke-width:2px
</div>

**왜 이렇게 설계했을까?**
- 🔸 **파일명은 저장 안 함** → 같은 내용이면 파일명이 달라도 하나만 저장 (용량 절약!)
- 🔸 **SHA-1 해시가 주소** → 내용이 같으면 해시도 같음 (중복 제거)
- 🔸 **변조 불가** → 내용이 바뀌면 해시도 바뀜 (무결성 보장)

---

### 2.2 Tree: 디렉토리 구조

**Tree**는 "이 폴더에 어떤 파일/폴더가 있는지"를 기록합니다.

<div class="mermaid">
flowchart TB
    subgraph root[루트 Tree]
        T1[🟢 tree a1b2c3<br/>프로젝트 루트]
    end
    
    subgraph files[파일들]
        B1[🟡 blob<br/>README.md 내용]
        B2[🟡 blob<br/>main.py 내용]
    end
    
    subgraph subdir[하위 디렉토리]
        T2[🟢 tree<br/>src 폴더]
        B3[🟡 blob<br/>app.py 내용]
    end
    
    T1 -->|"100644 README.md"| B1
    T1 -->|"100644 main.py"| B2
    T1 -->|"040000 src/"| T2
    T2 -->|"100644 app.py"| B3
    
    style T1 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style T2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B2 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B3 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
</div>

**그림 설명:**
- 🟢 **초록 박스(Tree)**: 디렉토리를 나타냄
- 🟡 **노란 박스(Blob)**: 실제 파일 내용
- **화살표 위 숫자**: Unix 파일 권한 (`100644`=일반 파일, `040000`=디렉토리)
- **화살표 위 이름**: 파일/폴더 이름 (Tree가 이름을 기억!)

---

### 2.3 Commit: 스냅샷 + 메타데이터

**Commit**은 "특정 시점의 프로젝트 전체 상태"를 저장합니다.

<div class="mermaid">
flowchart TB
    subgraph latest[최신 커밋]
        C3[🔷 commit c3<br/>Add login feature<br/>by Gideok, 2월 3일]
    end
    
    subgraph second[두번째 커밋]
        C2[🔷 commit c2<br/>Add README<br/>by Gideok, 2월 2일]
    end
    
    subgraph first[첫번째 커밋]
        C1[🔷 commit c1<br/>Initial commit<br/>by Gideok, 2월 1일]
    end
    
    subgraph trees[각 시점의 파일 상태]
        T3[🟢 tree]
        T2[🟢 tree]
        T1[🟢 tree]
    end
    
    C3 -->|"parent<br/>이전 커밋"| C2
    C2 -->|"parent"| C1
    
    C3 -->|"tree<br/>파일 상태"| T3
    C2 -->|"tree"| T2
    C1 -->|"tree"| T1
    
    style C3 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style C2 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style C1 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style T3 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style T2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style T1 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
</div>

**그림 설명:**
- **세로 방향 (parent)**: 시간순 히스토리. 각 커밋은 이전 커밋을 가리킴
- **가로 방향 (tree)**: 그 시점의 전체 파일 상태. 커밋마다 다른 Tree를 가리킴

**Commit이 담고 있는 정보:**
```
commit e5f6g7...
├── tree      8a7b3c...     ← 이 시점의 파일 구조 (Tree 해시)
├── parent    a1b2c3...     ← 이전 커밋 (히스토리 연결)
├── author    Gideok        ← 작성자
├── committer Gideok        ← 커밋한 사람
└── message   "Add login"   ← 커밋 메시지
```

---

## 3. 전체 구조: HEAD → Branch → Commit → Tree → Blob

지금까지 배운 모든 것을 하나의 그림으로 연결하면:

<div class="mermaid">
flowchart TB
    subgraph refs[References - 사람이 읽을 수 있는 이름]
        HEAD[📍 HEAD<br/>현재 위치]
        MAIN[🏷️ main<br/>브랜치]
    end
    
    subgraph commits[Commits - 히스토리]
        C2[🔷 commit<br/>feat: login]
        C1[🔷 commit<br/>init]
    end
    
    subgraph trees[Trees - 디렉토리]
        T2[🟢 tree]
        T1[🟢 tree]
    end
    
    subgraph blobs[Blobs - 파일 내용]
        B1[🟡 README]
        B2[🟡 main.py]
        B3[🟡 login.py]
    end
    
    HEAD -->|"ref: main"| MAIN
    MAIN -->|"커밋 해시"| C2
    C2 -->|"parent"| C1
    C2 -->|"tree"| T2
    C1 -->|"tree"| T1
    T2 --> B1
    T2 --> B2
    T2 --> B3
    T1 --> B1
    T1 --> B2
    
    style HEAD fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style MAIN fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style C2 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style C1 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style T2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style T1 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B2 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B3 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
</div>

**읽는 방법 (위에서 아래로):**

1. 🔴 **HEAD** → "지금 내가 어디 있지?" → `main` 브랜치
2. 🔴 **main** → "이 브랜치의 최신 커밋은?" → `commit c2`
3. 🔷 **commit** → "이 시점 파일들은?" → `tree` 참조
4. 🟢 **tree** → "어떤 파일들이 있지?" → `blob`들 나열
5. 🟡 **blob** → 실제 파일 내용!

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
author Gideok <gideok@example.com> 1706952000 +0900
committer Gideok <gideok@example.com> 1706952000 +0900

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

<div class="mermaid">
flowchart LR
    subgraph file[파일 시스템]
        A[.git/refs/heads/main]
    end
    
    subgraph content[파일 내용]
        B[e5f6g7h8i9j0k1l2...]
    end
    
    subgraph meaning[의미]
        C[이 커밋이<br/>main 브랜치의<br/>최신이야!]
    end
    
    A -->|cat| B
    B -->|해석| C
    
    style A fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style B fill:#e0e0e0,stroke:#616161,stroke-width:2px
    style C fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
</div>

```bash
$ cat .git/refs/heads/main
e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4
```

**끝입니다.** 40글자 커밋 해시가 전부. 브랜치 생성 = 파일 하나 만들기!

---

### 🤯 같은 내용은 절대 두 번 저장 안 함

<div class="mermaid">
flowchart TB
    subgraph files[서로 다른 파일]
        F1[📄 file1.txt<br/>내용: Hello]
        F2[📄 file2.txt<br/>내용: Hello]
        F3[📄 copy.txt<br/>내용: Hello]
    end
    
    subgraph storage[Git 저장소]
        BLOB[🟡 단 하나의 blob<br/>해시: aaf4c6...]
    end
    
    F1 -->|같은 해시| BLOB
    F2 -->|같은 해시| BLOB
    F3 -->|같은 해시| BLOB
    
    style F1 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style F2 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style F3 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style BLOB fill:#e8f5e9,stroke:#388e3c,stroke-width:3px
</div>

**이게 왜 대단할까?**
- 대형 프로젝트에서 같은 라이선스 파일이 100개 폴더에 있어도 → **저장은 1번**
- 파일 복사해도 용량 증가 없음
- 이름 바꿔도 용량 증가 없음

---

## 6. 정리

<div class="mermaid">
flowchart LR
    subgraph ui[우리가 보는 것]
        A1[📁 파일/폴더]
        A2[🌿 브랜치]
        A3[📜 커밋 로그]
    end
    
    subgraph internal[Git 내부]
        B1[🟡 Blob]
        B2[🟢 Tree]
        B3[🔷 Commit]
        B4[🔴 Refs]
    end
    
    A1 --> B1
    A1 --> B2
    A2 --> B4
    A3 --> B3
    
    style A1 fill:#fafafa,stroke:#9e9e9e,stroke-width:1px
    style A2 fill:#fafafa,stroke:#9e9e9e,stroke-width:1px
    style A3 fill:#fafafa,stroke:#9e9e9e,stroke-width:1px
    style B1 fill:#fff8e1,stroke:#f57c00,stroke-width:2px
    style B2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style B3 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B4 fill:#ffcdd2,stroke:#c62828,stroke-width:2px
</div>

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

## 다음 편 예고

> **해체분석기 #2: Git은 어떻게 변경사항을 추적할까?**
>
> - staging area(index)의 정체
> - `git diff`는 어떻게 동작하는가  
> - merge vs rebase, DAG 관점에서 이해하기

---

## 참고 자료

- [Pro Git Book - Git Internals](https://git-scm.com/book/en/v2/Git-Internals-Plumbing-and-Porcelain)
- [Git from the inside out](https://codewords.recurse.com/issues/two/git-from-the-inside-out)
