---
title: "Git 해체분석기 #2: Git의 탄생 - 첫 커밋을 열어보다"
date: 2026-02-05T20:35:00+09:00
summary: "2005년 4월, Linus Torvalds는 10일 만에 Git을 만들었다. 왜 만들었고, 첫 버전은 어떻게 생겼을까?"
tags: ["git", "해체분석기", "history", "linus-torvalds"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 2
weight: 2
draft: false
mermaid: true
---

> 2005년 4월 7일, Linus Torvalds가 올린 커밋 메시지:
> **"Initial revision of 'git', the information manager from hell"**

## 들어가며

2005년 4월, Linux 커널 개발이 멈출 위기에 처했다.

그리고 Linus Torvalds는 **10일 만에** 새로운 버전 관리 시스템을 만들어냈다.

오늘은 Git의 탄생 배경과 첫 커밋(`e83c5163`)을 직접 열어본다.

---

## 1. 2005년 4월, 무슨 일이 있었나?

### 1.1 Linux 커널 개발의 역사

```
1991~2002: tarball + 이메일 패치
           Linus가 모든 패치를 직접 검토
           → 심각한 병목

2002~2005: BitKeeper 도입
           상용 분산 VCS의 무료 버전 사용
           → 개발 속도 폭발적 증가 🚀
```

BitKeeper는 당시로서는 혁신적인 도구였다. **분산 버전 관리**, 효율적인 머지, 빠른 속도. Linux 커널처럼 전 세계에서 동시에 개발하는 프로젝트에 딱 맞았다.

문제는 BitKeeper가 **상용 소프트웨어**였다는 것. BitMover사가 오픈소스 프로젝트에 한해 무료로 제공하고 있었다.

### 1.2 BitKeeper 사건

2005년 4월, Andrew Tridgell(Samba 창시자)이 BitKeeper의 프로토콜을 리버스 엔지니어링했다. 오픈소스 대안을 만들기 위해서.

BitMover는 이를 라이선스 위반으로 보고, **Linux 커널 팀의 무료 사용권을 철회**했다.

**Linux 커널 개발이 멈출 위기.**

### 1.3 Linus의 선택

당시 존재하던 오픈소스 버전 관리 도구들:

| 도구 | Linus의 평가 |
|-----|-------------|
| **CVS** | "역사상 가장 멍청한 프로그램" |
| **Subversion** | "CVS를 제대로 만들려다 실패한 것" |

둘 다 **중앙 집중식**이었고, Linux 커널 규모의 프로젝트에는 맞지 않았다.

Linus의 결정: **직접 만든다.**

### 1.4 10일의 기록

```
4월 3일: 마지막 BitKeeper 기반 릴리즈 (2.6.12-rc2)
4월 6일: Linus, 새 버전 관리 시스템 개발 시작 발표
4월 7일: Git 첫 커밋 🎉
4월 17일: Git으로 첫 Linux 커널 머지 성공
```

---

## 2. 기존 도구들의 문제

Git이 해결하려 한 문제를 이해하려면, CVS/SVN의 한계를 알아야 한다.

### 2.1 중앙 집중식 구조

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

CVS와 SVN은 모든 작업이 **중앙 서버를 거쳐야** 했다.

### 2.2 구체적인 문제들

| 문제 | 설명 |
|-----|------|
| 🔴 **서버 의존** | 커밋하려면 네트워크 연결 필수 |
| 🔴 **오프라인 불가** | 비행기에서 코딩? 커밋 못함 |
| 🔴 **느린 브랜치** | SVN의 브랜치 = 전체 디렉토리 복사 |
| 🔴 **단일 장애점** | 서버 죽으면 히스토리 손실 위험 |
| 🔴 **느린 히스토리** | 로그 조회도 서버에 요청 |

Linux 커널은 **전 세계 수천 명**이 동시에 개발한다. 중앙 서버 하나로는 감당이 안 됐다.

### 2.3 Git의 접근: 분산형

<pre class="mermaid">
flowchart TB
    subgraph d1[Developer 1]
        R1[(Full Repo)]
    end
    
    subgraph d2[Developer 2]
        R2[(Full Repo)]
    end
    
    subgraph d3[Developer 3]
        R3[(Full Repo)]
    end
    
    R1 <-->|push/pull| R2
    R2 <-->|push/pull| R3
    R1 <-->|push/pull| R3
    
    style R1 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style R2 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style R3 fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
</pre>

**모든 개발자가 전체 히스토리를 가진다.**

- 서버 없이 로컬에서 커밋
- 오프라인 작업 가능
- 모든 클론이 백업
- 히스토리 조회도 로컬에서

---

## 3. Git 첫 커밋 분석

커밋 해시: `e83c5163316f89bfbde7d9ab23ca2e25604af290`

### 3.1 파일 구조

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

**10개 파일, 약 1000줄**. 이게 전부다.

### 3.2 Makefile

```makefile
CFLAGS=-g
CC=gcc

PROG=update-cache show-diff init-db write-tree read-tree commit-tree cat-file

all: $(PROG)

LIBS= -lssl
```

빌드하면 **7개의 실행 파일**이 만들어진다:
- `init-db`: 저장소 초기화
- `update-cache`: 파일을 캐시에 추가
- `write-tree`: 캐시에서 트리 객체 생성
- `commit-tree`: 커밋 객체 생성
- `read-tree`: 트리 객체 읽기
- `show-diff`: 차이점 보기
- `cat-file`: 객체 내용 출력

### 3.3 README: Linus의 설계 철학

```
GIT - the stupid content tracker

"git" can mean anything, depending on your mood.

 - "global information tracker": you're in a good mood, 
   and it actually works for you. Angels sing, and a 
   light suddenly fills the room.
   
 - "goddamn idiotic truckload of sh*t": when it breaks
```

Linus 특유의 유머. 핵심 설계 철학도 여기 있다:

> "This is a stupid (but extremely fast) directory content manager.
> It doesn't do a whole lot, but what it _does_ do is track 
> directory contents efficiently."

**멍청하지만 극도로 빠른**. 복잡한 기능 대신 단순하고 빠른 핵심에 집중.

---

## 4. 핵심 설계: 두 가지 추상화

README에서 Linus는 Git의 핵심을 두 가지로 설명한다:

```
There are two object abstractions: 
the "object database", and the "current directory cache".
```

### 4.1 Object Database

> "The object database is literally just a content-addressable 
> collection of objects. All objects are named by their content, 
> which is approximated by the SHA1 hash of the object itself."

**Content-addressable**: 내용이 곧 주소다.

```
파일 내용 "Hello" → SHA1 해시 계산 → aaf4c61d...
                                        ↓
                    저장 위치: .dircache/objects/aa/f4c61d...
```

### 4.2 세 가지 객체 타입

README에서 정의한 객체 타입:

**BLOB**:
> "A blob object is nothing but a binary blob of data, and doesn't
> refer to anything else. There is no signature or any other 
> verification of the data... No name associations, no permissions.
> It is purely a blob of data (ie normally 'file contents')."

**TREE**:
> "A tree object is a list of permission/name/blob data, sorted by name.
> In other words the tree object is uniquely determined by the set 
> contents, and so two separate but identical trees will always share 
> the exact same object."

**CHANGESET** (커밋):
> "The changeset object introduces the notion of history into the picture.
> In contrast to the other objects, it doesn't just describe the physical 
> state of a tree, it describes how we got there, and why."

<pre class="mermaid">
flowchart TB
    C[CHANGESET<br/>커밋 정보<br/>author, message]
    T[TREE<br/>디렉토리 구조<br/>name → blob 매핑]
    B1[BLOB<br/>파일 A 내용]
    B2[BLOB<br/>파일 B 내용]
    
    C -->|tree| T
    T -->|file_a| B1
    T -->|file_b| B2
    
    style C fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style T fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style B1 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style B2 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
</pre>

### 4.3 Directory Cache

> "The current directory cache is a simple binary file, which contains
> an efficient representation of a virtual directory content at some 
> random time."

작업 중인 파일들의 상태를 캐싱한다. 두 가지 목적:

1. **상태 복원**: 캐시된 상태를 완벽히 재생성할 수 있다
2. **변경 감지**: 현재 파일과의 차이를 빠르게 찾을 수 있다

---

## 5. 코드 살펴보기

### 5.1 cache.h: 핵심 자료구조

```c
#define CACHE_SIGNATURE 0x44495243	/* "DIRC" */

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

#define DB_ENVIRONMENT "SHA1_FILE_DIRECTORY"
#define DEFAULT_DB_ENVIRONMENT ".dircache/objects"
```

캐시 엔트리에는:
- 파일 메타데이터 (시간, 권한, 크기)
- 파일 내용의 SHA1 해시
- 파일명

이 정보로 파일이 변경됐는지 **빠르게 확인**할 수 있다.

### 5.2 init-db.c: 저장소 초기화

```c
int main(int argc, char **argv)
{
    // .dircache 디렉토리 생성
    if (mkdir(".dircache", 0700) < 0) {
        perror("unable to create .dircache");
        exit(1);
    }

    /*
     * If you want to, you can share the DB area with any 
     * number of branches. That has advantages: you can save 
     * space by sharing all the SHA1 objects.
     */
    sha1_dir = DEFAULT_DB_ENVIRONMENT;  // ".dircache/objects"
    
    // objects/00 ~ objects/ff (256개 디렉토리) 생성
    for (i = 0; i < 256; i++) {
        sprintf(path+len, "/%02x", i);
        mkdir(path, 0700);
    }
    return 0;
}
```

저장소를 초기화하면:
1. `.dircache/` 디렉토리 생성
2. `.dircache/objects/00` ~ `ff` (256개) 디렉토리 생성

SHA1 해시의 첫 2자리로 객체를 분류하기 위해서다.

### 5.3 commit-tree.c: 커밋 만들기

```c
int main(int argc, char **argv)
{
    // 사용자 정보 가져오기
    pw = getpwuid(getuid());
    if (!pw)
        usage("You don't exist. Go away!");
    
    // 커밋 내용 구성
    add_buffer(&buffer, &size, "tree %s\n", sha1_to_hex(tree_sha1));
    
    // 부모 커밋들 (머지의 경우 여러 개)
    for (i = 0; i < parents; i++)
        add_buffer(&buffer, &size, "parent %s\n", sha1_to_hex(parent_sha1[i]));
    
    // author와 committer 정보
    add_buffer(&buffer, &size, "author %s <%s> %s\n", gecos, email, date);
    add_buffer(&buffer, &size, "committer %s <%s> %s\n\n", realgecos, realemail, realdate);
    
    // 커밋 메시지 (stdin에서 읽음)
    while (fgets(comment, sizeof(comment), stdin) != NULL)
        add_buffer(&buffer, &size, "%s", comment);
    
    // SHA1 파일로 저장
    write_sha1_file(buffer, size);
}
```

커밋 객체의 구조가 보인다:
```
tree <tree-sha1>
parent <parent-sha1>
author <name> <email> <date>
committer <name> <email> <date>

<commit message>
```

**다중 부모**도 이미 지원한다:

```c
/*
 * Having more than two parents may be strange, but hey, there's
 * no conceptual reason why the file format couldn't accept multi-way
 * merges. It might be the "union" of several packages, for example.
 */
#define MAXPARENT (16)
```

Linux 커널처럼 여러 브랜치를 동시에 머지하는 상황을 고려한 것이다.

---

## 6. 아직 없는 것들

첫 버전에는 **최소한의 기능만** 있다:

✅ 있는 것:
- 저장소 초기화
- 파일을 객체로 저장
- 트리 구조 생성
- 커밋 생성
- diff 보기
- 객체 내용 확인

❌ 없는 것:
- 히스토리 조회 (log)
- 브랜치 관리
- 머지
- 원격 저장소 연동
- 체크아웃

**진짜 뼈대만** 있다. 하지만 핵심 설계 - Object Database와 content-addressable 저장 - 는 완성됐다.

---

## 7. 설계 목표 정리

Linus가 Git을 만들 때 세운 목표들:

### 7.1 속도

BitKeeper 수준의 속도. 초당 수 개의 패치를 처리할 수 있어야 한다.

### 7.2 데이터 무결성

README에서:
> "You _can_ trust that an object is intact and has not been 
> messed with by external sources. So the name of an object 
> uniquely identifies a known state."

모든 객체가 SHA1으로 검증된다. 내용이 조금이라도 바뀌면 해시가 달라지므로 **조작을 감지**할 수 있다.

### 7.3 단순함

> "This is a stupid (but extremely fast) directory content manager."

복잡한 기능 대신 **핵심에 집중**. 두 가지 추상화(Object Database, Directory Cache)만으로 버전 관리의 본질을 구현했다.

### 7.4 분산 개발 지원

중앙 서버 없이 각자 전체 히스토리를 가진다. 나중에 동기화하면 된다.

### 7.5 비선형 개발

처음부터 다중 부모 커밋을 고려했다. Linux 커널처럼 **수많은 브랜치가 동시에 개발**되는 환경을 위해서.

---

## 마무리

Git 첫 버전은 **10개 파일, 1000줄**이다.

하지만 핵심 아이디어는 명확하다:

1. **Content-addressable storage**: 내용의 SHA1 해시가 곧 주소
2. **세 가지 객체**: Blob(파일), Tree(디렉토리), Changeset(커밋)
3. **분산형**: 모든 클론이 전체 히스토리를 가짐
4. **단순함**: "stupid content tracker"

복잡한 기능은 없지만, **근본적인 설계가 탄탄**하다. 

Linus는 10일 만에 이걸 만들어냈다.

---

## 직접 확인해보기

첫 커밋을 직접 보고 싶다면:

```bash
git clone https://github.com/git/git
cd git
git checkout e83c5163316f89bfbde7d9ab23ca2e25604af290
ls                    # 10개 파일
cat README            # Linus의 설명
cat init-db.c         # 저장소 초기화 코드
```

---

## 참고 자료

- [Git 첫 커밋](https://github.com/git/git/commit/e83c5163316f89bfbde7d9ab23ca2e25604af290)
- [The Git Origin Story](https://www.linuxjournal.com/content/git-origin-story)
- [BitKeeper and Linux: The Story of Git's Creation](https://graphite.com/blog/bitkeeper-linux-story-of-git-creation)
