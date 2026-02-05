---
title: "해체분석기 #7: 초창기 Git은 어떻게 사용했을까?"
date: 2026-02-05T21:15:00+09:00
summary: "2005년 첫 버전 Git의 실제 사용법. init-db부터 commit-tree까지, 수동으로 버전 관리하기"
tags: ["git", "해체분석기", "history", "linus-torvalds"]
categories: ["개발"]
series: ["해체분석기"]
draft: false
mermaid: true
---

> 이전 글 [Git의 탄생](/posts/git-origins-first-commit/)에서 첫 커밋의 구조를 살펴봤다.
> 이번엔 실제로 **어떻게 사용하는지** 알아보자.

## 들어가며

2005년 4월의 Git에는 `git add`, `git commit` 같은 편리한 명령어가 없었다.

있는 건 이것뿐:
- `init-db`
- `update-cache`
- `write-tree`
- `commit-tree`
- `cat-file`
- `show-diff`
- `read-tree`

이걸로 어떻게 버전 관리를 했을까?

---

## 1. 저장소 만들기: init-db

```bash
$ init-db
defaulting to private storage area
```

실행하면 `.dircache/` 디렉토리가 생긴다:

```
.dircache/
└── objects/
    ├── 00/
    ├── 01/
    ├── ...
    └── ff/
```

**256개의 하위 디렉토리**. SHA1 해시의 첫 2자리로 객체를 분류하기 위해서다.

### init-db.c 코드

```c
int main(int argc, char **argv)
{
    // .dircache 생성
    mkdir(".dircache", 0700);
    
    // .dircache/objects/00 ~ ff 생성
    for (i = 0; i < 256; i++) {
        sprintf(path+len, "/%02x", i);
        mkdir(path, 0700);
    }
}
```

---

## 2. 파일 추가하기: update-cache

파일을 만들고 캐시에 등록한다:

```bash
$ echo "Hello, Git!" > hello.txt
$ update-cache hello.txt
```

이 명령이 하는 일:

1. `hello.txt` 내용을 읽는다
2. SHA1 해시를 계산한다
3. `.dircache/objects/` 에 blob 객체로 저장한다
4. `.dircache/index` 캐시 파일에 등록한다

<pre class="mermaid">
flowchart LR
    F[hello.txt<br/>"Hello, Git!"]
    H[SHA1 계산]
    B[Blob 객체<br/>.dircache/objects/55/7db03...]
    I[Index 캐시<br/>.dircache/index]
    
    F --> H
    H --> B
    H --> I
    
    style F fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style B fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style I fill:#bbdefb,stroke:#1976d2,stroke-width:2px
</pre>

### update-cache.c 핵심 코드

```c
int main(int argc, char **argv)
{
    // 기존 캐시 읽기
    entries = read_cache();
    
    // 새 캐시 파일 생성 (락)
    newfd = open(".dircache/index.lock", O_RDWR | O_CREAT | O_EXCL, 0600);
    
    // 각 파일을 캐시에 추가
    for (i = 1; i < argc; i++) {
        char *path = argv[i];
        add_file_to_cache(path);  // blob 생성 + 캐시 등록
    }
    
    // 캐시 파일 저장
    write_cache(newfd, active_cache, active_nr);
    rename(".dircache/index.lock", ".dircache/index");
}
```

**락 파일**을 사용해서 동시 수정을 방지한다. `.dircache/index.lock` → `.dircache/index`로 atomic하게 교체.

---

## 3. 변경 확인하기: show-diff

파일을 수정하고 차이점을 본다:

```bash
$ echo "Hello, World!" > hello.txt
$ show-diff
hello.txt:  0644 -> 0644  (changed)
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-Hello, Git!
+Hello, World!
```

캐시에 저장된 버전과 현재 파일을 비교한다.

### 어떻게 빠르게 비교하나?

캐시 엔트리에는 파일의 메타데이터가 저장되어 있다:

```c
struct cache_entry {
    struct cache_time ctime;  // 생성 시간
    struct cache_time mtime;  // 수정 시간
    unsigned int st_size;     // 파일 크기
    unsigned char sha1[20];   // 내용 해시
    // ...
};
```

**mtime이나 size가 다르면** 파일이 변경된 것. 전체 내용을 비교하지 않아도 빠르게 감지할 수 있다.

---

## 4. 트리 객체 만들기: write-tree

캐시의 현재 상태를 트리 객체로 저장한다:

```bash
$ write-tree
8b137891791fe96927ad78e64b0aad7bded08bdc
```

출력되는 건 **트리 객체의 SHA1 해시**.

### 트리 객체 구조

```
tree <size>\0
<mode> <filename>\0<sha1-bytes>
<mode> <filename>\0<sha1-bytes>
...
```

예를 들어:

```
tree 74
100644 hello.txt\0<20바이트 SHA1>
100644 world.txt\0<20바이트 SHA1>
```

### write-tree.c 핵심 코드

```c
int main(int argc, char **argv)
{
    entries = read_cache();
    
    // 각 캐시 엔트리를 트리 형식으로 변환
    for (i = 0; i < entries; i++) {
        struct cache_entry *ce = active_cache[i];
        
        // "<mode> <filename>\0<sha1>"
        offset += sprintf(buffer + offset, "%o %s", ce->st_mode, ce->name);
        buffer[offset++] = 0;
        memcpy(buffer + offset, ce->sha1, 20);
        offset += 20;
    }
    
    // "tree <size>" 헤더 추가 후 저장
    write_sha1_file(buffer, offset);
}
```

---

## 5. 커밋 만들기: commit-tree

트리 객체를 커밋으로 감싼다:

```bash
$ echo "Initial commit" | commit-tree 8b137891791fe96927ad78e64b0aad7bded08bdc
Committing initial tree 8b137891791fe96927ad78e64b0aad7bded08bdc
a1b2c3d4e5f6...
```

커밋 메시지는 **stdin으로** 받는다. 출력되는 건 커밋 객체의 SHA1.

### 커밋 객체 구조

```
commit <size>\0
tree <tree-sha1>
author <name> <<email>> <timestamp>
committer <name> <<email>> <timestamp>

<commit message>
```

### 부모 커밋 지정

두 번째 커밋부터는 `-p` 옵션으로 부모를 지정한다:

```bash
$ echo "Second commit" | commit-tree <tree-sha1> -p <parent-sha1>
```

여러 부모도 가능 (머지):

```bash
$ echo "Merge commit" | commit-tree <tree-sha1> -p <parent1> -p <parent2>
```

---

## 6. 객체 내용 보기: cat-file

저장된 객체의 내용을 확인한다:

```bash
$ cat-file <sha1>
temp_git_file_xxxxx: blob
```

임시 파일에 내용을 풀어준다. 압축(zlib)을 해제하고 내용을 보여주는 역할.

---

## 7. 전체 워크플로우

처음부터 끝까지 정리하면:

<pre class="mermaid">
flowchart TB
    subgraph init[1. 초기화]
        I[init-db]
    end
    
    subgraph add[2. 파일 추가]
        F1[파일 생성/수정]
        U[update-cache file1 file2]
    end
    
    subgraph check[3. 확인]
        D[show-diff]
    end
    
    subgraph save[4. 저장]
        W[write-tree]
        C[commit-tree tree-sha1]
    end
    
    I --> F1
    F1 --> U
    U --> D
    D --> W
    W --> C
    
    style I fill:#e1bee7,stroke:#7b1fa2,stroke-width:2px
    style U fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    style D fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    style W fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style C fill:#ffcdd2,stroke:#c62828,stroke-width:2px
</pre>

### 실제 세션 예시

```bash
# 1. 저장소 초기화
$ init-db
defaulting to private storage area

# 2. 파일 생성
$ echo "Hello" > hello.txt
$ echo "World" > world.txt

# 3. 캐시에 추가
$ update-cache hello.txt world.txt

# 4. 변경 확인 (아직 변경 없음)
$ show-diff
(출력 없음)

# 5. 트리 객체 생성
$ write-tree
abc123def456...

# 6. 첫 번째 커밋
$ echo "Initial commit" | commit-tree abc123def456...
Committing initial tree abc123def456...
111222333444...

# --- 수정 후 두 번째 커밋 ---

# 7. 파일 수정
$ echo "Hello, Git!" > hello.txt

# 8. 변경 확인
$ show-diff
hello.txt: changed
-Hello
+Hello, Git!

# 9. 캐시 업데이트
$ update-cache hello.txt

# 10. 새 트리 생성
$ write-tree
def789...

# 11. 두 번째 커밋 (부모 지정)
$ echo "Update hello.txt" | commit-tree def789... -p 111222333444...
555666777888...
```

---

## 8. 불편한 점들

2005년 첫 버전의 한계:

### 8.1 수동 조합

모든 걸 수동으로 해야 한다:

```bash
# 지금이라면:
git add . && git commit -m "message"

# 첫 버전에서는:
update-cache file1.txt file2.txt
TREE=$(write-tree)
echo "message" | commit-tree $TREE -p $PARENT
```

### 8.2 히스토리 조회 없음

`log` 명령어가 없다. 커밋 체인을 따라가려면 수동으로:

```bash
$ cat-file <commit-sha1>
# 출력에서 parent 확인
$ cat-file <parent-sha1>
# 반복...
```

### 8.3 브랜치 없음

브랜치 개념이 아예 없다. HEAD 포인터도 없다. 최신 커밋 SHA1을 직접 기억해야 한다.

### 8.4 체크아웃 없음

과거 버전으로 돌아가는 명령이 없다. `read-tree`로 트리를 읽을 수는 있지만, 파일로 복원하는 건 수동.

---

## 9. 그럼에도 핵심은 완성

불편하지만, **핵심 설계는 이미 완성**됐다:

| 개념 | 첫 버전 |
|-----|---------|
| Content-addressable 저장 | ✅ SHA1 해시로 객체 저장 |
| Blob/Tree/Commit 구조 | ✅ 세 가지 객체 타입 |
| 스테이징 영역 | ✅ `.dircache/index` |
| 데이터 무결성 | ✅ 모든 객체 SHA1 검증 |

편의 명령어들은 나중에 추가됐지만, 기반 구조는 이때 만들어진 그대로다.

---

## 10. README의 조언

Linus는 README에 이렇게 썼다:

> "If you blow the directory cache away entirely, you haven't 
> lost any information as long as you have the name of the 
> tree that it described."

캐시(index)를 날려도 **트리 객체의 SHA1만 알면 복구**할 수 있다. 모든 데이터는 objects에 있으니까.

> "In other words, you can easily validate a whole archive 
> by just sending out a single email that tells the people 
> the name (SHA1 hash) of the top changeset."

최상위 커밋의 SHA1 하나만 공유하면, 전체 히스토리를 검증할 수 있다. 각 커밋이 부모를 참조하고, 트리를 참조하고, 트리가 blob을 참조하니까. **체인 전체가 암호학적으로 연결**되어 있다.

---

## 마무리

초창기 Git은 불편했다. 모든 걸 수동으로 조합해야 했다.

하지만 그 덕분에 **내부 구조가 투명하게 보인다**:

- `update-cache`: 파일 → blob + 캐시
- `write-tree`: 캐시 → 트리 객체
- `commit-tree`: 트리 → 커밋 객체

지금의 `git add`와 `git commit`은 이 과정을 자동화한 것뿐이다.

핵심은 2005년 4월에 이미 완성됐다.

---

## 직접 해보기

첫 버전을 직접 빌드해서 사용해볼 수 있다:

```bash
# Git 소스 받기
git clone https://github.com/git/git
cd git

# 첫 커밋으로 이동
git checkout e83c5163316f89bfbde7d9ab23ca2e25604af290

# 빌드 (OpenSSL, zlib 필요)
make

# 사용해보기
./init-db
echo "test" > test.txt
./update-cache test.txt
./write-tree
```

---

## 참고 자료

- [Git 첫 커밋](https://github.com/git/git/commit/e83c5163316f89bfbde7d9ab23ca2e25604af290)
- [이전 글: Git의 탄생](/posts/git-origins-first-commit/)
