---
title: "Git 해체분석기 #10: Reflog - Git의 타임머신"
date: 2026-02-16
summary: "git reset --hard로 날린 커밋, 삭제한 브랜치... 정말 사라졌을까?"
tags: ["git", "해체분석기", "reflog"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 10
weight: -10
draft: false
mermaid: true
---

> `git reset --hard`를 실수로 눌렀을 때, 당신을 구해줄 마지막 안전망.

## 들어가며

Git을 쓰다 보면 누구나 한 번쯤 이런 공포를 느껴봤을 겁니다.

```bash
$ git reset --hard HEAD~3
$ git log
# 😱 3개 커밋이 증발...

$ git branch -D feature
# 😱 며칠 동안 작업한 브랜치가 사라짐...
```

**하지만 안심하세요.** Git에는 이런 순간을 위한 비밀 무기가 있습니다.  
오늘은 `.git/logs` 폴더에 숨겨진 **Git의 타임머신, Reflog**를 해체해봅니다.

---

## 1. Reflog가 뭐길래?

### git log vs git reflog

우리가 아는 `git log`는 **프로젝트의 역사**를 보여줍니다.  
하지만 `git reflog`는 **당신의 작업 기록**을 보여줍니다.

<pre class="mermaid">
flowchart LR
    A[git log]
    B[프로젝트 역사책]
    C[git reflog]
    D[개인 일기장]
    
    A -->|"무슨 일이?"| B
    C -->|"내가 뭐 했지?"| D
    
    style A fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style B fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
    style C fill:#ffccbc,stroke:#e64a19,stroke-width:2px
    style D fill:#ffe0b2,stroke:#f57c00,stroke-width:2px
</pre>

**차이를 실험으로 보면:**

```bash
# 커밋 3개 만들고 2개를 reset으로 "삭제"
$ git log --oneline
c3c3c3c Third commit
b2b2b2b Second commit
a1a1a1a Initial commit

$ git reset --hard a1a1a1a  # 2개 커밋 날림
$ git log --oneline
a1a1a1a Initial commit        # ← Second, Third가 사라짐

$ git reflog
a1a1a1a HEAD@{0}: reset: moving to a1a1a1a
c3c3c3c HEAD@{1}: commit: Third commit    # ← 여전히 있음! 🎉
b2b2b2b HEAD@{2}: commit: Second commit   # ← 여전히 있음! 🎉
a1a1a1a HEAD@{3}: commit (initial): Initial commit
```

**핵심 발견:** `git log`에서는 사라진 커밋이 `reflog`에는 남아있습니다!

---

## 2. .git/logs 까보기

Reflog는 복잡한 데이터베이스가 아닙니다. **그냥 텍스트 파일**입니다.

### 구조 한눈에 보기

```
.git/logs/
├── HEAD              ← 모든 HEAD 이동 기록
└── refs/
    ├── heads/
    │   ├── main     ← main 브랜치 전용 기록
    │   └── feature  ← feature 브랜치 전용 기록
    └── remotes/
        └── origin/
            └── main ← origin/main 추적 브랜치 기록
```

<pre class="mermaid">
flowchart TB
    HEAD[HEAD reflog]
    MAIN[refs/heads/main]
    FEATURE[refs/heads/feature]
    
    HEAD -->|"전체 이동 기록"| MAIN
    HEAD -->|"브랜치 전환까지 포함"| FEATURE
    
    style HEAD fill:#ffcdd2,stroke:#c62828,stroke-width:3px
    style MAIN fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style FEATURE fill:#b3e5fc,stroke:#0288d1,stroke-width:2px
</pre>

### 파일 내용 직접 보기

```bash
$ cat .git/logs/HEAD
0000000000000000000000000000000000000000 a1a1a1a... Test <test@test.com> 1771240678 +0900	commit (initial): Initial commit
a1a1a1a... b2b2b2b... Test <test@test.com> 1771240679 +0900	commit: Second commit
b2b2b2b... c3c3c3c... Test <test@test.com> 1771240680 +0900	commit: Third commit
c3c3c3c... a1a1a1a... Test <test@test.com> 1771240681 +0900	reset: moving to a1a1a1a
```

**포맷 분석:**
```
[old SHA] [new SHA] [작성자] [타임스탬프] [tab] [액션]: [메시지]
```

- 🔸 **old SHA**: 이전 위치 (첫 커밋은 `0000...`)
- 🔸 **new SHA**: 새로운 위치
- 🔸 **액션**: `commit`, `reset`, `checkout`, `merge`, `rebase` 등
- 🔸 **메시지**: 커밋 메시지 또는 Git 액션 설명

**중요한 점:** 이건 **append-only** 파일입니다. 한 번 쓰면 수정 없이 계속 추가됩니다.

---

## 3. 충격적인 사실들

### 🤯 Reflog는 완전히 로컬입니다

<pre class="mermaid">
flowchart LR
    LOCAL[내 컴퓨터]
    REMOTE[GitHub]
    
    LOCAL -->|"git push"| REMOTE
    REMOTE -.->|"reflog는 절대 공유 안 됨"| LOCAL
    
    style LOCAL fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style REMOTE fill:#e0e0e0,stroke:#616161,stroke-width:2px
</pre>

**의미:**
- Linus Torvalds의 reflog을 볼 수 없습니다. (로컬에만 존재!)
- 동료가 실수한 기록도 볼 수 없습니다.
- 당신의 실수도 절대 공유되지 않습니다. 😌

**왜 이렇게 설계했을까?**
1. **프라이버시**: 실험, 실수를 숨길 수 있음
2. **안전성**: 무엇을 push하든 로컬 복구 가능
3. **성능**: 원격 동기화 불필요 → 빠름

---

### 🤯 브랜치 삭제해도 reflog에는 남습니다

```bash
$ git checkout -b feature
$ echo "Feature" > feature.txt
$ git add . && git commit -m "Feature work"

$ git checkout main
$ git branch -D feature  # 브랜치 삭제! 😱

$ git log --all
# feature 커밋이 안 보임...

$ git reflog
1d21430 HEAD@{0}: checkout: moving from feature to main
ba2ad6e HEAD@{1}: commit: Feature work  # ← 여전히 있음! 🎉
```

**HEAD reflog는 모든 브랜치 이동을 기록**하기 때문에, 브랜치를 삭제해도 커밋은 살아있습니다!

---

## 4. 실전 복구 시나리오

### 시나리오 1: reset --hard 실수 복구

```bash
# 😱 문제 상황
$ git reset --hard HEAD~3  # 커밋 3개 날림
$ git log  # 텅 비어있음...

# 🔍 복구 시작
$ git reflog
a1b2c3d HEAD@{1}: commit: Important feature  # ← 이거다!
e4f5g6h HEAD@{2}: commit: Critical fix
i7j8k9l HEAD@{3}: commit: Performance boost

# ✅ 복구 완료
$ git reset --hard a1b2c3d
# 또는 상대 참조로
$ git reset --hard HEAD@{1}
```

<pre class="mermaid">
flowchart TB
    A[커밋 3개 작업]
    B[reset --hard 실수]
    C[reflog 확인]
    D[타임머신 복구]
    
    A --> B
    B --> C
    C --> D
    
    style B fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style D fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

---

### 시나리오 2: 삭제한 브랜치 복구

```bash
# 😱 문제 상황
$ git branch -D feature  # 실수로 삭제

# 🔍 복구 시작
$ git reflog | grep feature
ba2ad6e HEAD@{5}: commit: Feature commit

# ✅ 복구 완료
$ git checkout -b feature-recovered ba2ad6e
```

---

### 시나리오 3: 최후의 수단 - git fsck

Reflog도 만료된 경우 (90일 지남), **정말 최후의 수단**:

```bash
$ git fsck --lost-found
dangling commit dfde2c2...

$ git show dfde2c2  # 내용 확인
$ git merge dfde2c2  # 필요하면 복구
```

이건 **객체 데이터베이스를 전수 조사**하는 방법입니다. Reflog보다 느리지만, 완전히 잃어버린 커밋도 찾을 수 있습니다.

---

## 5. Reflog는 언제까지 살아있나?

### 만료 정책

```bash
# 기본 설정
gc.reflogExpire = 90 days             # reachable 항목
gc.reflogExpireUnreachable = 30 days  # unreachable 항목
```

<pre class="mermaid">
timeline
    title Reflog 생존 타임라인
    section Unreachable
        삭제된 브랜치 커밋 : 30일
    section Reachable
        현재 브랜치 히스토리 : 90일
    section Safe
        항상 안전 : 커밋 직후~30일
</pre>

**용어 정리:**
- **Reachable**: 현재 브랜치에서 도달 가능한 커밋 (90일 보관)
- **Unreachable**: 고아 커밋, 삭제된 브랜치의 커밋 (30일만 보관)

### 수동 제어

```bash
# stash는 영구 보존
$ git config gc.refs/stash.reflogExpire never

# 즉시 만료 (주의!)
$ git reflog expire --expire=now --all

# 절대 만료 안 함 (더 주의!)
$ git config gc.reflogExpire never
```

---

## 6. Git 소스코드에서 엿보기

Git 공식 저장소의 `reflog.c`를 보면, reflog의 핵심 로직이 드러납니다.

```c
// github.com/git/git/blob/master/reflog.c

// 설정 파싱: 패턴별 만료 정책
int reflog_expire_config(const char *var, const char *value, ...) {
    // gc.refs/stash.reflogExpire 같은 패턴 매칭
}

// Reflog 항목을 유지할지 결정
static int keep_entry(struct commit **it, struct object_id *oid) {
    // 1. 커밋이 존재하는가?
    // 2. 커밋이 reachable한가?
    // REACHABLE 플래그 마킹
}
```

**설계 철학:**
- 객체 **존재성**(existence)과 **도달가능성**(reachability)을 분리
- 플래그 기반 상태 관리 (`SEEN`, `INCOMPLETE`, `REACHABLE`)
- 패턴 매칭으로 유연한 만료 정책 (예: stash는 보존)

---

## 7. 정리

<pre class="mermaid">
flowchart TB
    A[Git 안전망]
    B[1차: Working Directory]
    C[2차: Staging Area]
    D[3차: Reflog]
    
    A --> B
    B --> C
    C --> D
    
    B -.->|git checkout| E[파일 복원]
    C -.->|git reset| F[스테이징 취소]
    D -.->|git reflog| G[커밋 복구]
    
    style D fill:#ffcdd2,stroke:#c62828,stroke-width:3px
    style G fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

| 항목 | git log | git reflog |
|------|---------|------------|
| **기록 대상** | 프로젝트 커밋 히스토리 | HEAD 이동 기록 |
| **범위** | 전역 (리포지토리 공유) | 로컬 (내 작업만) |
| **공유 여부** | Push/Pull로 공유됨 | 절대 공유 안 됨 |
| **삭제된 커밋** | 보이지 않음 | 보임 (만료 전) |
| **브랜치 전환** | 기록 안 함 | 기록함 |
| **생존 기간** | 영구 (reachable) | 기본 90일 |

**Git의 본질:**
> Reflog는 단순한 로그가 아닙니다.  
> 당신의 모든 작업을 기억하는 **타임머신**이자,  
> 실수를 용서해주는 **최후의 안전망**입니다.

---

## 8. 직접 해보기

한 번 실험해보세요! 두려워 마세요, reflog가 지켜줍니다.

```bash
# 1. 테스트 저장소 생성
$ mkdir reflog-test && cd reflog-test
$ git init

# 2. 커밋 3개 만들기
$ echo "First" > file1.txt && git add . && git commit -m "First"
$ echo "Second" > file2.txt && git add . && git commit -m "Second"
$ echo "Third" > file3.txt && git add . && git commit -m "Third"

# 3. "실수" 재현
$ git reset --hard HEAD~2  # 2개 커밋 날림
$ git log --oneline  # 하나만 남음...

# 4. reflog로 복구
$ git reflog  # 모든 기록 확인
$ git reset --hard HEAD@{1}  # 복구!

# 5. .git/logs 직접 열어보기
$ cat .git/logs/HEAD  # 모든 이동이 기록됨
```

---

## 다음 편 예고

> **해체분석기 #11: Git Stash - 임시 저장의 비밀**
>
> - Stash는 어디에 저장되나? (refs/stash의 정체)
> - 왜 stash는 reflog가 never expire일까?
> - stash apply vs pop, 내부적으로 무슨 차이?

---

## 참고 자료

- [Git Official Docs - git-reflog](https://git-scm.com/docs/git-reflog)
- [Git Source Code - reflog.c](https://github.com/git/git/blob/master/reflog.c)
- [Pro Git Book - Maintenance and Data Recovery](https://git-scm.com/book/en/v2/Git-Internals-Maintenance-and-Data-Recovery)
