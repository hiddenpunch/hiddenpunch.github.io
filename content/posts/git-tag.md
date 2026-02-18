---
title: "Git 해체분석기 #8: Tag - 태그의 내부 구조와 서명"
date: 2026-02-18
summary: "Lightweight tag vs Annotated tag, .git/refs/tags/ 구조, GPG 서명까지 - git tag의 모든 것을 해체합니다"
tags: ["git", "해체분석기", "tag", "gpg"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 8
weight: -8
draft: false
mermaid: true
---

> `git tag v1.0.0` 한 줄로 태그를 달지만, 실제로 `.git` 폴더 안에서는 무슨 일이 일어날까요?

## 들어가며

릴리즈할 때마다 `git tag v1.0.0`을 치면서도, 태그가 커밋과 어떻게 다른지 깊이 생각해본 적 있으신가요?

사실 Git의 태그에는 두 가지 종류가 있습니다. 그리고 그 둘은 내부적으로 **완전히 다른 방식**으로 저장됩니다. 하나는 그냥 포인터고, 다른 하나는 GPG 서명까지 품을 수 있는 독립적인 객체입니다.

오늘은 `.git/refs/tags/` 폴더를 열어보고, `git cat-file`로 내장을 꺼내보면서 태그의 진짜 모습을 해체합니다.

---

## 1. 두 가지 태그: Lightweight vs Annotated

Git tag에는 두 가지 종류가 있습니다.

```bash
# Lightweight tag - 그냥 커밋에 이름표 붙이기
git tag v1.0.0

# Annotated tag - 메타데이터와 함께 (tagger, message, date)
git tag -a v1.0.0 -m "Release v1.0.0"

# GPG 서명 포함 annotated tag
git tag -s v1.0.0 -m "Signed Release v1.0.0"
```

겉으로 보면 비슷해 보이지만, 내부적으로는 전혀 다릅니다.

<pre class="mermaid">
flowchart TD
    subgraph Lightweight["Lightweight Tag"]
        LT["refs/tags/v1.0.0\n= commit SHA"]
        LC["Commit Object\nabc123"]
        LT -->|직접 참조| LC
    end

    subgraph Annotated["Annotated Tag"]
        AT["refs/tags/v1.0.0\n= tag object SHA"]
        TO["Tag Object\ntag type\ntagger info\nmessage\n(optional: PGP signature)"]
        AC["Commit Object\nabc123"]
        AT -->|참조| TO
        TO -->|object 필드| AC
    end

    style LT fill:#fff9c4,stroke:#f9a825
    style AT fill:#e8f5e9,stroke:#388e3c
    style TO fill:#c8e6c9,stroke:#2e7d32
    style LC fill:#bbdefb,stroke:#1976d2
    style AC fill:#bbdefb,stroke:#1976d2
</pre>

---

## 2. Lightweight Tag 해부

Lightweight tag는 가장 단순합니다. **커밋을 가리키는 포인터** 파일 하나가 전부입니다.

```bash
# 실습
git init demo-repo && cd demo-repo
echo "Hello" > README.md
git add . && git commit -m "Initial commit"

# Lightweight tag 생성
git tag v0.1.0
```

이제 `.git/refs/tags/`를 직접 열어봅시다:

```bash
cat .git/refs/tags/v0.1.0
# 출력: abc1234def5678... (커밋 SHA 그대로)

# 이 SHA가 정말 commit object인지 확인
git cat-file -t $(cat .git/refs/tags/v0.1.0)
# 출력: commit
```

바로 여기가 핵심입니다. **Lightweight tag는 별도의 tag object를 만들지 않습니다.** 단순히 커밋 SHA를 파일에 기록한 것뿐입니다.

```bash
# refs/tags/ 파일 내용 = 커밋 SHA
$ xxd .git/refs/tags/v0.1.0
00000000: 6162 6331 3233 3466 6566 3536 3738 2e2e  abc1234def5678..
```

그래서 lightweight tag에는 **tagger 정보도, 날짜도, 메시지도** 없습니다. 순수한 별명(alias)입니다.

---

## 3. Annotated Tag 해부

Annotated tag는 다릅니다. **독립적인 Tag Object**가 Object Storage에 저장됩니다.

```bash
# Annotated tag 생성
git tag -a v1.0.0 -m "First stable release

This version includes:
- Feature A
- Feature B
- Bug fixes"
```

### 3.1 refs/tags/ 파일 내용 확인

```bash
cat .git/refs/tags/v1.0.0
# 출력: def9876abc5432... (tag object의 SHA! commit SHA가 아님)

# type 확인
git cat-file -t $(cat .git/refs/tags/v1.0.0)
# 출력: tag  ← commit이 아니라 tag!
```

### 3.2 Tag Object 내부 구조

```bash
git cat-file -p $(cat .git/refs/tags/v1.0.0)
```

```
object abc1234def5678901234567890abcdef12345678
type commit
tag v1.0.0
tagger 홍길동 <hong@example.com> 1708222299 +0900

First stable release

This version includes:
- Feature A
- Feature B
- Bug fixes
```

이것이 **Tag Object의 실제 내용**입니다. 필드별로 뜯어봅시다:

| 필드 | 값 | 설명 |
|------|----|------|
| `object` | 커밋 SHA | 이 태그가 가리키는 커밋 |
| `type` | `commit` | 가리키는 객체 타입 (blob, tree도 가능) |
| `tag` | `v1.0.0` | 태그 이름 |
| `tagger` | 이름 + 이메일 + timestamp | 태그를 만든 사람과 시각 |
| (빈 줄 이후) | 메시지 | 태그 메시지 |

### 3.3 Object Storage에서 찾기

Tag object도 다른 Git object처럼 `.git/objects/`에 저장됩니다:

```bash
TAG_SHA=$(cat .git/refs/tags/v1.0.0)
echo ${TAG_SHA:0:2}   # 디렉토리명 (앞 2자)
echo ${TAG_SHA:2}     # 파일명 (나머지)

# 실제 파일 존재 확인
ls .git/objects/${TAG_SHA:0:2}/${TAG_SHA:2}
```

---

## 4. 전체 객체 관계도

Annotated tag는 commit, tree, blob과 함께 Object Storage의 4번째 객체 타입입니다.

<pre class="mermaid">
flowchart TB
    subgraph refs[".git/refs/tags/"]
        R1["v0.1.0\n(lightweight)"]
        R2["v1.0.0\n(annotated)"]
    end

    subgraph objects[".git/objects/"]
        TO["🏷️ Tag Object\ntype: tag\ntagger: ...\nmessage: ..."]
        CO1["📦 Commit Object\nauthor: ...\ncommitter: ...\ntree: ..."]
        CO2["📦 Commit Object\nauthor: ...\ncommitter: ...\ntree: ..."]
        TR["🌳 Tree Object"]
        BL["📄 Blob Object"]
    end

    R1 -->|직접| CO2
    R2 --> TO
    TO -->|object 필드| CO1
    CO1 -->|tree| TR
    TR -->|README.md| BL

    style TO fill:#c8e6c9,stroke:#2e7d32,stroke-width:2px
    style CO1 fill:#bbdefb,stroke:#1976d2
    style CO2 fill:#bbdefb,stroke:#1976d2
    style TR fill:#dcedc8,stroke:#558b2f
    style BL fill:#fff9c4,stroke:#f9a825
    style R1 fill:#fce4ec,stroke:#c62828
    style R2 fill:#fce4ec,stroke:#c62828
</pre>

---

## 5. GPG 서명 태그 (Signed Tag)

Annotated tag의 가장 강력한 기능은 **GPG 서명**입니다. 오픈소스 프로젝트의 공식 릴리즈에 자주 쓰입니다. Linux 커널, Git 자체도 이 방식을 사용합니다.

### 5.1 서명 태그 생성

```bash
# GPG 키가 설정되어 있다면
git tag -s v2.0.0 -m "Signed Release v2.0.0"

# 특정 GPG 키로 서명
git tag -u ABCD1234 -m "Signed with specific key" v2.0.1
```

### 5.2 서명된 Tag Object 내부

```bash
git cat-file -p v2.0.0
```

```
object abc1234def5678901234567890abcdef12345678
type commit
tag v2.0.0
tagger 홍길동 <hong@example.com> 1708222299 +0900

Signed Release v2.0.0
-----BEGIN PGP SIGNATURE-----

iQEzBAABCAAdFiEEXXXXXXXXXXXXXXXXXXXXXXXXXXXXFiEEXXXXXXXX
XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXx
XXXXXXXXx
=XXXX
-----END PGP SIGNATURE-----
```

GPG 서명이 태그 메시지 **뒤에** 붙습니다. 서명 대상은 `object`, `type`, `tag`, `tagger`, 메시지를 포함한 전체 헤더입니다.

### 5.3 서명 검증

```bash
# 태그 서명 검증
git tag -v v2.0.0

# 출력 (검증 성공 시):
# object abc1234def5678...
# type commit
# tag v2.0.0
# tagger 홍길동 <hong@example.com> ...
#
# Signed Release v2.0.0
# gpg: Signature made Wed 18 Feb 2026 10:30:00 AM KST
# gpg:                using RSA key ABCD1234EFGH5678
# gpg: Good signature from "홍길동 <hong@example.com>"
```

### 5.4 서명 검증 내부 동작

<pre class="mermaid">
sequenceDiagram
    participant User
    participant Git
    participant GPG

    User->>Git: git tag -v v2.0.0
    Git->>Git: refs/tags/v2.0.0 → Tag Object SHA 읽기
    Git->>Git: Tag Object 내용 파싱
    Git->>Git: PGP 서명 블록 분리
    Git->>GPG: 헤더+메시지와 PGP 서명 전달
    GPG->>GPG: 공개키로 서명 검증
    GPG-->>Git: 검증 결과 (Good/Bad signature)
    Git-->>User: 결과 출력
</pre>

---

## 6. Tag Object의 Raw 바이너리 구조

Git의 모든 object는 zlib 압축된 형태로 저장됩니다. Tag object도 마찬가지입니다.

```bash
# zlib 압축 전 실제 내용 형식:
# "tag {size}\0{content}"

# Python으로 직접 확인
python3 << 'EOF'
import zlib, sys

tag_sha = "def9876abc5432..."  # 실제 tag SHA
path = f".git/objects/{tag_sha[:2]}/{tag_sha[2:]}"

with open(path, 'rb') as f:
    raw = zlib.decompress(f.read())

# null byte 위치 찾기
null_pos = raw.index(b'\x00')
header = raw[:null_pos].decode()
content = raw[null_pos+1:].decode()

print(f"Header: {header}")
print(f"Content:\n{content}")
EOF
```

출력:
```
Header: tag 176
Content:
object abc1234def5678901234567890abcdef12345678
type commit
tag v1.0.0
tagger 홍길동 <hong@example.com> 1708222299 +0900

First stable release
```

형식이 blob, commit, tree와 완전히 동일합니다: `{type} {size}\0{content}`

---

## 7. 실전 팁: 태그 관련 유용한 명령들

### 7.1 태그 종류 구별하기

```bash
# 모든 태그의 type 확인
git for-each-ref refs/tags --format="%(refname:short) %(objecttype)"

# 출력 예시:
# v0.1.0 commit    ← lightweight (직접 commit 가리킴)
# v1.0.0 tag       ← annotated (tag object 가리킴)
# v2.0.0 tag       ← annotated + signed
```

### 7.2 Annotated tag에서 커밋 SHA 가져오기

```bash
# tag object를 거쳐서 commit SHA를 가져오려면
git rev-list -n 1 v1.0.0
# 또는
git rev-parse v1.0.0^{}  # ^{} = dereference tag object
```

### 7.3 태그 메시지만 보기

```bash
git tag -l -n9 v1.0.0   # 최대 9줄 메시지 출력
git show v1.0.0          # 태그 + 커밋 정보 전체
```

### 7.4 원격 태그 동기화

```bash
# 태그는 기본적으로 push 대상이 아님!
git push origin v1.0.0          # 특정 태그만
git push origin --tags           # 모든 태그
git push origin --follow-tags    # annotated tag만 (권장)
```

---

## 8. 왜 Annotated Tag를 써야 할까?

Lightweight tag는 "이 커밋에 별명 붙이기"이고, Annotated tag는 "릴리즈 이벤트 기록하기"입니다.

| 항목 | Lightweight | Annotated |
|------|-------------|-----------|
| 별도 객체 생성 | ❌ | ✅ |
| Tagger 정보 | ❌ | ✅ |
| 태그 날짜 | ❌ | ✅ |
| 태그 메시지 | ❌ | ✅ |
| GPG 서명 | ❌ | ✅ |
| `git describe` 대상 | ❌ | ✅ |
| 권장 용도 | 임시 북마크 | 공식 릴리즈 |

특히 `git describe`는 **annotated tag**만 참조합니다:

```bash
# annotated tag만 있을 때
git describe HEAD
# v1.0.0-3-gabc1234   (태그로부터 3커밋, 현재 SHA)

# lightweight tag는 무시됨
git describe HEAD --tags  # 이 옵션을 줘야 lightweight도 포함
```

---

## 마치며

Git tag는 단순해 보이지만, 내부를 들여다보면 두 가지 완전히 다른 메커니즘이 작동하고 있습니다.

- **Lightweight tag**: `.git/refs/tags/{name}` 파일에 커밋 SHA 한 줄. 끝.
- **Annotated tag**: 독립적인 Tag Object를 Object Storage에 생성. tagger, 날짜, 메시지, GPG 서명까지 품을 수 있는 완전한 엔티티.

공식 릴리즈에 annotated tag를 써야 하는 이유는 단순히 "관행"이 아닙니다. **누가, 언제, 왜** 이 릴리즈를 만들었는지를 Git history에 영구히 새기는 행위입니다. GPG 서명까지 더하면 그 릴리즈가 특정 사람의 손에서 나왔음을 암호학적으로 보증할 수 있습니다.

다음번에 `git tag -a v1.0.0 -m "..."` 을 칠 때, `.git/objects/` 어딘가에 새로운 tag object가 조용히 태어나고 있다는 걸 떠올려보세요.
