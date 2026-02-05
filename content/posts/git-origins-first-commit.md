---
title: "해체분석기 #6: Git의 탄생 - 첫 커밋을 열어보다"
date: 2026-02-05T20:35:00+09:00
summary: "2005년 4월, Linus Torvalds는 10일 만에 Git을 만들었다. 왜 만들었고, 첫 버전은 어떻게 생겼을까?"
tags: ["git", "해체분석기", "history", "linus-torvalds"]
categories: ["개발"]
series: ["해체분석기"]
draft: false
mermaid: true
---

> 2005년 4월 7일, Linus Torvalds가 올린 커밋 메시지:
> **"Initial revision of 'git', the information manager from hell"**

## 들어가며

Git은 이제 개발자의 필수 도구다. 하지만 Git이 왜, 어떻게 만들어졌는지 아는 사람은 많지 않다.

2005년 4월, Linus Torvalds는 **10일 만에** 동작하는 버전 관리 시스템을 만들었다. Linux 커널 개발이 중단될 위기에서.

오늘은 Git의 탄생 배경과 첫 커밋(`e83c5163`)을 직접 열어본다.

---

## 1. 왜 Git을 만들었나?

### 1.1 BitKeeper 사건

2005년 이전, Linux 커널 개발의 역사:

```
1991~2002: tarball + 이메일 패치
           Linus가 모든 패치를 직접 검토
           → 심각한 병목

2002~2005: BitKeeper 도입
           상용 분산 VCS의 무료 버전 사용
           → 개발 속도 폭발적 증가 🚀
```

BitKeeper는 혁신적이었다. 분산 버전 관리, 효율적인 머지, 빠른 속도. Linux 커널 개발에 날개를 달아줬다.

**그러나 2005년 4월, 사건이 터진다.**

Andrew Tridgell(Samba 창시자)이 BitKeeper의 프로토콜을 리버스 엔지니어링했다. 오픈소스 대안을 만들기 위해서. BitMover(BitKeeper 개발사)는 이를 라이선스 위반으로 보고, **Linux 커널 팀의 무료 사용권을 철회**했다.

### 1.2 Linus의 선택지

Linux 커널 개발이 멈출 위기. Linus 앞에 놓인 선택지:

| 선택지 | Linus의 평가 |
|-------|-------------|
| **CVS** | "역사상 가장 멍청한 프로그램" |
| **Subversion** | "CVS를 제대로 만들려다 실패한 것" |
| **직접 만든다** | ✅ |

Linus는 기존 도구들이 마음에 들지 않았다. 특히 **중앙 집중식** 구조와 **느린 브랜치/머지**가 문제였다.

### 1.3 10일의 기적

```
2005년 4월 3일: 마지막 BitKeeper 기반 릴리즈 (2.6.12-rc2)
2005년 4월 6일: Linus, Git 개발 시작 발표
2005년 4월 7일: Git 첫 커밋 🎉
2005년 4월 17일: 첫 Linux 커널 머지 성공
```

**10일 만에 동작하는 버전 관리 시스템**을 만들었다. 물론 기능은 최소한이었지만, 핵심 설계는 지금과 거의 같다.

---

## 2. 기존 도구들의 문제점

Git이 해결하려 한 문제를 이해하려면, 당시 도구들의 한계를 알아야 한다.

### 2.1 CVS/SVN의 구조

<pre class="mermaid">
flowchart TB
    subgraph server[Central Server]
        REPO[(Repository)]
    end
    
    subgraph clients[Developers]
        D1[Dev 1<br/>Working Copy]
        D2[Dev 2<br/>Working Copy]
        D3[Dev 3<br/>Working Copy]
    end
    
    D1 <-->|commit/update| REPO
    D2 <-->|commit/update| REPO
    D3 <-->|commit/update| REPO
    
    style REPO fill:#ffcdd2,stroke:#c62828,stroke-width:2px
    style D1 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style D2 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style D3 fill:#bbdefb,stroke:#1976d2,stroke-width:2px
</pre>

**중앙 집중식**. 모든 작업이 서버를 거쳐야 했다.

### 2.2 문제점들

| 문제 | 설명 |
|-----|------|
| 🔴 **서버 의존** | 커밋하려면 네트워크 연결 필수 |
| 🔴 **오프라인 불가** | 비행기에서 코딩? 커밋 못함 |
| 🔴 **느린 브랜치** | SVN의 브랜치 = 전체 복사 (느림) |
| 🔴 **단일 장애점** | 서버 죽으면 모든 히스토리 손실 위험 |
| 🔴 **느린 히스토리** | 로그 보려면 서버에 요청해야 함 |

Linux 커널처럼 **전 세계 수천 명이 동시에 개발**하는 프로젝트에서 이런 구조는 치명적이었다.

### 2.3 Git의 해결책

<pre class="mermaid">
flowchart TB
    subgraph d1[Developer 1]
        R1[(Full Repo)]
        W1[Working Dir]
    end
    
    subgraph d2[Developer 2]
        R2[(Full Repo)]
        W2[Working Dir]
    end
    
    subgraph d3[Developer 3]
        R3[(Full Repo)]
        W3[Working Dir]
    end
    
    R1 <-->|push/pull| R2
    R2 <-->|push/pull| R3
    R1 <-->|push/pull| R3
    
    style R1 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style R2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style R3 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

**분산형**. 모든 개발자가 전체 히스토리를 가진다.

| 해결책 | 효과 |
|-------|-----|
| 🟢 **로컬 저장소** | 서버 없이 커밋 가능 |
| 🟢 **오프라인 작업** | 나중에 동기화하면 됨 |
| 🟢 **빠른 브랜치** | 브랜치 = 포인터 (즉시 생성) |
| 🟢 **모든 클론이 백업** | 서버 죽어도 복구 가능 |
| 🟢 **로컬 히스토리** | 네트워크 없이 로그 조회 |

---

## 3. Git 첫 커밋 열어보기

실제로 첫 커밋을 열어보자. 커밋 해시는 `e83c5163316f89bfbde7d9ab23ca2e25604af290`.

### 3.1 파일 목록

```
git/
├── Makefile         ← 빌드 스크립트
├── README           ← Linus가 쓴 설명서
├── cache.h          ← 핵심 자료구조 정의
├── read-cache.c     ← 캐시 읽기 공통 코드
├── init-db.c        ← 저장소 초기화
├── update-cache.c   ← 파일 스테이징
├── write-tree.c     ← 트리 객체 생성
├── commit-tree.c    ← 커밋 객체 생성
├── read-tree.c      ← 트리 객체 읽기
├── show-diff.c      ← diff 출력
└── cat-file.c       ← 객체 내용 출력
```

**10개 파일, 약 1000줄**. 이게 Git의 시작이다.

### 3.2 README: Linus의 설계 철학

README 파일 첫 부분:

```
GIT - the stupid content tracker

"git" can mean anything, depending on your mood.

 - "global information tracker": you're in a good mood, 
   and it actually works for you. Angels sing, and a 
   light suddenly fills the room.
   
 - "goddamn idiotic truckload of sh*t": when it breaks
```

Linus 특유의 유머. 하지만 핵심 설계 철학도 담겨있다:

> "This is a stupid (but extremely fast) directory content manager."

**멍청하지만 극도로 빠른**. 복잡한 기능 대신 단순하고 빠른 핵심에 집중했다.

### 3.3 두 가지 핵심 추상화

README에서 Linus는 Git의 핵심을 두 가지로 설명한다:

```
There are two object abstractions:
1. The "object database"
2. The "current directory cache"
```

**Object Database**와 **Directory Cache**. 지금의 `.git/objects`와 `.git/index`의 원형이다.

---

## 4. Object Database: 내용 주소 저장소

### 4.1 핵심 아이디어

README에서:

> "The object database is literally just a content-addressable 
> collection of objects. All objects are named by their content, 
> which is approximated by the SHA1 hash of the object itself."

**Content-addressable**: 내용이 곧 주소다. 파일 내용의 SHA1 해시가 파일명이 된다.

```
"Hello, Git!" → SHA1 → 557db03de997c86a4a028e1ebd3a1ceb225be238
                              ↓
               저장 위치: .dircache/objects/55/7db03...
```

### 4.2 세 가지 객체 타입

| 객체 | 역할 |
|-----|------|
| **BLOB** | 파일 내용 (이름/권한 없음) |
| **TREE** | 디렉토리 구조 (이름 → BLOB 매핑) |
| **CHANGESET** | 커밋 (나중에 "commit"으로 개명) |

<pre class="mermaid">
flowchart TB
    C[CHANGESET<br/>커밋 정보]
    T[TREE<br/>디렉토리 구조]
    B1[BLOB<br/>README 내용]
    B2[BLOB<br/>main.c 내용]
    
    C -->|tree| T
    T -->|README| B1
    T -->|main.c| B2
    
    style C fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style T fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style B2 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
</pre>

### 4.3 init-db.c: 저장소 초기화

첫 커밋의 `init-db.c`:

```c
int main(int argc, char **argv)
{
    // .dircache 디렉토리 생성 (지금의 .git)
    if (mkdir(".dircache", 0700) < 0) {
        perror("unable to create .dircache");
        exit(1);
    }

    // .dircache/objects/00 ~ ff (256개 디렉토리) 생성
    for (i = 0; i < 256; i++) {
        sprintf(path+len, "/%02x", i);
        mkdir(path, 0700);
    }
    return 0;
}
```

**`.git`이 아니라 `.dircache`였다!** 

256개의 하위 디렉토리(00~ff)를 미리 생성한다. SHA1 해시의 첫 2자리로 분류하기 위해서.

---

## 5. Directory Cache: 스테이징 영역

### 5.1 cache.h: 핵심 자료구조

```c
#define DEFAULT_DB_ENVIRONMENT ".dircache/objects"

struct cache_entry {
    struct cache_time ctime;
    struct cache_time mtime;
    unsigned int st_dev;
    unsigned int st_ino;
    unsigned int st_mode;
    unsigned int st_uid;
    unsigned int st_gid;
    unsigned int st_size;
    unsigned char sha1[20];      // 파일 내용의 SHA1
    unsigned short namelen;
    unsigned char name[0];       // 파일명 (가변 길이)
};
```

이게 지금의 **staging area** (`.git/index`)의 원형이다.

파일의 메타데이터(시간, 권한, 크기)와 SHA1 해시를 저장한다. **파일이 변경됐는지 빠르게 확인**하기 위해서.

### 5.2 캐시의 역할

README에서:

> "The current directory cache certainly does not need to be 
> consistent with the current directory contents, but it has 
> two very important attributes:
>
> (a) it can re-generate the full state it caches
> (b) it has efficient methods for finding inconsistencies"

두 가지 역할:
1. 캐시된 상태를 완벽히 복원할 수 있다
2. 현재 파일과의 차이를 빠르게 찾을 수 있다

---

## 6. 초창기 명령어

### 6.1 명령어 매핑

첫 버전의 명령어와 현재의 대응:

| 1차 버전 | 현재 | 역할 |
|---------|------|------|
| `init-db` | `git init` | 저장소 초기화 |
| `update-cache <file>` | `git add` | 스테이징 |
| `write-tree` | (내부) | 캐시 → 트리 객체 |
| `commit-tree <tree>` | (내부) | 트리 → 커밋 |
| `cat-file <sha1>` | `git cat-file` | 객체 내용 보기 |
| `show-diff` | `git diff` | 차이점 보기 |
| `read-tree <sha1>` | (내부) | 트리 객체 읽기 |

### 6.2 없었던 것들

첫 버전에는 **없었다**:

- ❌ `git log` - 히스토리 보기
- ❌ `git branch` - 브랜치 관리
- ❌ `git merge` - 머지
- ❌ `git clone` - 저장소 복제
- ❌ `git push / pull` - 원격 저장소
- ❌ `git checkout` - 브랜치 전환

**정말 최소한의 기능만** 있었다. 파일을 객체로 저장하고, 커밋을 만드는 것까지.

### 6.3 commit-tree.c: 커밋 만들기

커밋을 만드는 코드 일부:

```c
int main(int argc, char **argv)
{
    // 커밋 정보 수집
    pw = getpwuid(getuid());
    if (!pw)
        usage("You don't exist. Go away!");  // Linus식 에러 메시지 😂
    
    // 커밋 메시지 구성
    add_buffer(&buffer, &size, "tree %s\n", sha1_to_hex(tree_sha1));
    
    for (i = 0; i < parents; i++)
        add_buffer(&buffer, &size, "parent %s\n", sha1_to_hex(parent_sha1[i]));
    
    add_buffer(&buffer, &size, "author %s <%s> %s\n", gecos, email, date);
    add_buffer(&buffer, &size, "committer %s <%s> %s\n\n", realgecos, realemail, realdate);
    
    // stdin에서 커밋 메시지 읽기
    while (fgets(comment, sizeof(comment), stdin) != NULL)
        add_buffer(&buffer, &size, "%s", comment);
    
    // SHA1 파일로 저장
    write_sha1_file(buffer, size);
}
```

`"You don't exist. Go away!"` - 사용자 정보를 못 찾으면 나오는 에러 메시지. Linus의 유머가 코드 곳곳에 있다.

---

## 7. 설계 목표 정리

Linus가 Git을 만들 때 세운 목표:

### 7.1 속도

> 목표: 6.7 patches/second

기존 도구들이 느렸던 이유는 네트워크 의존과 비효율적인 자료구조. Git은 로컬 작업과 해시 기반 저장으로 극복했다.

### 7.2 데이터 무결성

> "You _can_ trust that an object is intact and has not been 
> messed with by external sources."

모든 객체가 SHA1으로 검증된다. 내용이 조금이라도 바뀌면 해시가 달라지므로 조작을 감지할 수 있다.

### 7.3 단순함

> "This is a stupid (but extremely fast) directory content manager."

복잡한 기능 대신 핵심에 집중. Object Database와 Directory Cache, 두 가지 추상화만으로 버전 관리의 본질을 구현했다.

### 7.4 비선형 개발 지원

README에서:

> "Having more than two parents may be strange, but hey, there's
> no conceptual reason why the file format couldn't accept multi-way
> merges."

처음부터 **다중 부모 커밋**(octopus merge)을 고려했다. Linux 커널처럼 수많은 브랜치가 동시에 개발되는 환경을 위해서.

---

## 8. 20년이 지난 지금

첫 커밋의 핵심 설계는 **20년이 지난 지금도 그대로**다:

| 2005년 | 2025년 |
|--------|--------|
| `.dircache/` | `.git/` |
| `changeset` | `commit` |
| `init-db` | `git init` |
| `update-cache` | `git add` |
| Object Database | Object Database (동일) |
| Directory Cache | Index / Staging Area |

물론 기능은 엄청나게 많아졌다. 브랜치, 머지, 리모트, 서브모듈, worktree, sparse checkout...

하지만 **핵심 구조는 10일 만에 만들어진 그 설계 그대로**다.

---

## 마무리

Git의 탄생은 여러 교훈을 준다:

1. **단순함의 힘**: 두 가지 추상화(Object Database, Directory Cache)로 버전 관리의 본질을 잡았다.

2. **좋은 설계는 오래 간다**: 20년 전 설계가 지금도 유효하다.

3. **제약이 혁신을 낳는다**: BitKeeper 사건이 없었다면 Git도 없었을지 모른다.

4. **Linus의 실력**: 10일 만에 동작하는 VCS를 만든 건 역시 천재의 영역이다.

다음에는 Git이 어떻게 진화했는지, 특히 브랜치와 머지가 어떻게 추가됐는지 살펴보자.

---

## 직접 확인해보기

첫 커밋을 직접 확인하고 싶다면:

```bash
git clone https://github.com/git/git
cd git
git log --oneline --reverse | head -1  # 첫 커밋 확인
git checkout e83c5163316f89bfbde7d9ab23ca2e25604af290
ls  # 10개 파일 확인
cat README  # Linus의 설명 읽기
```

---

## 참고 자료

- [Git 첫 커밋 (GitHub)](https://github.com/git/git/commit/e83c5163316f89bfbde7d9ab23ca2e25604af290)
- [The Git Origin Story (Linux Journal)](https://www.linuxjournal.com/content/git-origin-story)
- [BitKeeper and Linux: The Story of Git's Creation (Graphite)](https://graphite.com/blog/bitkeeper-linux-story-of-git-creation)
- [A Short History of Git (Git Book)](https://git-scm.com/book/en/v2/Getting-Started-A-Short-History-of-Git)
