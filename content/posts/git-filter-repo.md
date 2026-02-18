---
title: "Git 해체분석기 #24: filter-repo - 히스토리 재작성의 끝판왕"
date: 2026-02-18T14:28:00+09:00
tags: ["git", "internals", "filter-repo", "history-rewriting", "security", "bfg"]
series: ["해체분석기"]
series_order: 24
---

## 들어가며

실수는 누구나 한다. API 키를 `.env`에 넣어놓고 커밋했다. 수백 MB짜리 바이너리를 실수로 추가했다. 그리고 나서 `git rm`으로 삭제하고 다시 커밋했다. 이걸로 끝났다고 생각했다면, 착각이다.

```bash
$ git log --all --full-history -- secrets.txt
commit 3a7f2b1
Author: You <you@example.com>
Date:   Mon Feb 10 14:23:11 2026

    feat: add configuration

+DATABASE_PASSWORD=super_secret_123
+AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
```

Git 히스토리는 불변이다 — 아무도 손대지 않는 한. 그리고 "손대는" 방법이 바로 히스토리 재작성(history rewriting)이다.

오래전부터 Git에는 `filter-branch`라는 강력한 도구가 있었다. 하지만 이 도구는 속도가 느리고, API가 난해하며, 자잘한 함정이 너무 많다. 이 문제를 근본부터 다시 설계한 것이 `git filter-repo`다. Git 공식 문서조차 `filter-branch` 대신 `filter-repo` 사용을 권장하는 시대가 됐다.

오늘은 `git filter-repo`의 내부를 완전히 해부하고, 실전에서 어떻게 써야 하는지 파헤쳐본다.

---

## filter-branch의 원죄

`git filter-branch`가 왜 문제였는지 먼저 이해해야 `filter-repo`의 존재 이유가 명확해진다.

### 느림의 구조적 원인

`filter-branch`는 각 커밋마다 **bash 서브쉘**을 하나씩 spawn한다. 커밋이 10,000개면 bash 프로세스가 10,000번 실행된다. Python의 subprocess 오버헤드가 아니라, 진짜 OS 레벨의 fork/exec가 매 커밋마다 발생한다.

```bash
# filter-branch: 10,000 커밋 재작성
$ time git filter-branch --tree-filter 'rm -f secrets.txt' HEAD
# real 47m23s  ← 거의 50분

# filter-repo: 동일 작업
$ time git filter-repo --path secrets.txt --invert-paths
# real 0m8s   ← 8초
```

실제 벤치마크에서 `filter-repo`는 `filter-branch`보다 **수십 배 ~ 수백 배** 빠르다. CPython으로 작성됐음에도 불구하고.

### 참조 처리의 함정

`filter-branch`는 기본적으로 `refs/original/`에 원본 참조를 백업한다. 이걸 지우지 않으면 민감 정보가 **여전히 저장소에 남아있다**. 이 사실을 모르는 개발자들이 `filter-branch` 실행 후 "정리됐다"고 착각하고 push한다.

```bash
# filter-branch 실행 후 잔존 참조
$ git for-each-ref --format='%(refname)' refs/original/
refs/original/refs/heads/main
refs/original/refs/heads/feature/payments

# 이 참조들을 통해 민감 정보에 여전히 접근 가능!
$ git show refs/original/refs/heads/main:secrets.txt
DATABASE_PASSWORD=super_secret_123
```

### API의 복잡성

`filter-branch`의 필터 옵션들 — `--tree-filter`, `--index-filter`, `--msg-filter`, `--commit-filter` — 은 각각 셸 스크립트를 인자로 받는다. 강력하지만 그만큼 오류 가능성이 높고, 조합이 어렵다.

---

## filter-repo의 설계

`filter-repo`는 Git 기여자 Elijah Newren이 설계했다. 핵심 철학은 단순하다: **Python 스크립트 하나에 모든 것을 담되, Git의 내부 데이터 포맷을 직접 처리한다.**

### fast-export / fast-import 파이프라인

`filter-repo`의 동작 원리는 Git의 두 명령을 연결하는 파이프다.

```mermaid
flowchart LR
    A[".git 저장소"] -->|git fast-export| B["커밋 스트림\n(텍스트 포맷)"]
    B -->|filter-repo 처리| C["변환된 스트림"]
    C -->|git fast-import| D["새 .git 저장소"]

    style B fill:#f9f,stroke:#333
    style C fill:#9f9,stroke:#333
```

`git fast-export`는 저장소 전체를 **텍스트 스트림**으로 직렬화한다. 각 커밋, 트리, 블롭이 순서대로 흘러나온다. `filter-repo`는 이 스트림을 Python으로 읽고 변환한 뒤, `git fast-import`로 새 저장소를 구성한다.

실제 fast-export 스트림의 생김새:

```
blob
mark :1
data 42
DATABASE_PASSWORD=super_secret_123

blob
mark :2
data 156
# Application Config
LOG_LEVEL=INFO
MAX_CONNECTIONS=100

commit refs/heads/main
mark :3
author Dev <dev@example.com> 1707541391 +0900
committer Dev <dev@example.com> 1707541391 +0900
data 26
feat: add app configuration
M 100644 :1 .env
M 100644 :2 config.txt
```

`filter-repo`는 이 텍스트 스트림을 **한 번** 순회하면서 모든 변환을 적용한다. 커밋마다 서브쉘을 띄우지 않는다. 이것이 속도의 비밀이다.

### 아키텍처 다이어그램

```mermaid
graph TD
    A[git fast-export] --> B[Parser]
    B --> C{Callback 적용}
    C --> D[blob_callback]
    C --> E[commit_callback]
    C --> F[tag_callback]
    D --> G[Writer]
    E --> G
    F --> G
    G --> H[git fast-import]

    style C fill:#ff9,stroke:#333
    style G fill:#9ff,stroke:#333
```

각 오브젝트 타입마다 콜백이 호출된다. 내장 필터(경로 필터, 내용 교체 등)도, 사용자 정의 Python 콜백도 이 구조 안에서 동작한다.

---

## 실전: 민감 정보 제거

### 시나리오 1 - 파일 전체 제거

`.env` 파일이 커밋에 포함됐다. 파일 자체를 히스토리에서 완전히 제거한다.

```bash
# 설치
pip install git-filter-repo

# 또는 Homebrew
brew install git-filter-repo

# .env 파일을 히스토리 전체에서 제거
git filter-repo --path .env --invert-paths

# 여러 파일 동시 제거
git filter-repo \
  --path .env \
  --path secrets.yml \
  --path config/database.yml \
  --invert-paths
```

`--invert-paths`가 핵심이다. 이 플래그 없이 `--path .env`를 쓰면 `.env`만 **남기고** 나머지를 다 지운다.

### 시나리오 2 - 파일 내 특정 문자열 교체

파일은 남기되, 파일 안의 민감한 값만 교체한다.

```bash
# 특정 문자열을 ***REMOVED***로 교체
git filter-repo --replace-text <(echo "super_secret_123==>***REMOVED***")

# 파일에서 여러 패턴을 한 번에 교체
cat > replacements.txt << 'EOF'
super_secret_123==>***REMOVED***
AKIAIOSFODNN7EXAMPLE==>***AWS_KEY_REMOVED***
regex:password=\w+==>password=***REMOVED***
EOF

git filter-repo --replace-text replacements.txt
```

교체 파일 포맷은 `원본==>교체값` 형식이며, `regex:` 접두사로 정규식도 사용 가능하다.

### 시나리오 3 - 경로 패턴으로 제거

특정 디렉토리나 확장자를 가진 파일들을 모두 제거한다.

```bash
# 특정 디렉토리 제거
git filter-repo --path-glob 'config/secrets/*' --invert-paths

# 특정 확장자 파일 제거  
git filter-repo --path-regex '.*\.(pem|key|pfx|p12)$' --invert-paths

# 여러 조건 조합 (OR 조건)
git filter-repo \
  --path-glob '*.pem' \
  --path-glob '*.key' \
  --path 'credentials.json' \
  --invert-paths
```

---

## 실전: 대용량 파일 제거

저장소가 비정상적으로 크다면, 히스토리 어딘가에 큰 파일이 숨어있다.

### 큰 파일 찾기

```bash
# 히스토리에서 가장 큰 파일 top 10 찾기
git filter-repo --analyze

# 결과는 .git/filter-repo/analysis/ 에 저장
cat .git/filter-repo/analysis/path-all-sizes.txt | head -20

# 혹은 git으로 직접
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | grep '^blob' \
  | sort -k3 -rn \
  | head -20 \
  | awk '{print $3, $4}'
```

`--analyze` 플래그는 실제로 파일을 변경하지 않고, 저장소 분석 리포트만 생성한다. 어떤 파일이 용량을 차지하는지 확인하기 위한 첫 단계다.

### 특정 크기 이상 파일 제거

```bash
# 10MB 이상 파일을 히스토리에서 제거
git filter-repo --strip-blobs-bigger-than 10M

# 특정 파일 이름으로 제거
git filter-repo --path 'assets/video.mp4' --invert-paths

# 여러 큰 파일 목록으로 제거
git filter-repo --paths-from-file big-files.txt --invert-paths
```

`big-files.txt` 파일은 한 줄에 경로 하나씩 적으면 된다:

```
assets/video.mp4
dist/bundle.js.map
data/training-set.bin
```

### 제거 후 저장소 정리

히스토리 재작성만으로는 `.git/objects/`에서 실제로 공간이 회수되지 않는다. 참조가 정리되어야 GC가 오브젝트를 수집한다.

```bash
# filter-repo는 자동으로 대부분의 참조를 정리하지만
# 명시적으로 확인하고 싶다면
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 저장소 크기 확인
git count-objects -vH
```

---

## 실전: 저장소 분할

대형 모노리포를 여러 개의 독립 저장소로 분리하는 경우다.

### 하위 디렉토리를 새 저장소로

```
monorepo/
├── frontend/
├── backend/
└── shared/
```

이걸 `frontend/`, `backend/` 두 개의 독립 저장소로 분리한다.

```bash
# monorepo 복제 (원본 보존)
git clone --no-local monorepo frontend-repo
cd frontend-repo

# frontend/ 디렉토리만 남기고 나머지 제거
# --subdirectory-filter는 해당 디렉토리를 루트로 올림
git filter-repo --subdirectory-filter frontend

# 결과: frontend/ 아래 파일들이 루트로 이동
# 히스토리는 frontend/ 관련 커밋만 남음
ls
# src/  public/  package.json  ...

# backend도 동일하게
cd ..
git clone --no-local monorepo backend-repo
cd backend-repo
git filter-repo --subdirectory-filter backend
```

`--subdirectory-filter`는 단순히 해당 디렉토리의 파일만 남기는 것이 아니라, **해당 디렉토리가 저장소 루트가 되도록** 경로를 재구성한다.

### 경로 재배치

분리 후 파일 경로를 재구성할 수도 있다.

```bash
# src/ 디렉토리를 lib/로 이름 변경 (히스토리 전체 반영)
git filter-repo --path-rename src/:lib/

# 여러 경로 동시 재배치
git filter-repo \
  --path-rename old-src/:src/ \
  --path-rename old-tests/:tests/
```

---

## 실전: 저장소 병합

두 개의 저장소를 하나로 합치는 경우다. 각 저장소의 히스토리를 모두 보존한다.

```mermaid
gitGraph
   commit id: "repo-a: init"
   commit id: "repo-a: feature 1"
   branch repo-b
   checkout repo-b
   commit id: "repo-b: init"
   commit id: "repo-b: feature A"
   checkout main
   merge repo-b id: "merge: both histories"
   commit id: "combined work"
```

```bash
# repo-a를 a/ 하위 디렉토리로, repo-b를 b/ 하위 디렉토리로 합침

# 각 저장소의 파일들을 하위 디렉토리로 이동 (경로 접두사 추가)
cd repo-a
git filter-repo --to-subdirectory-filter a/

cd ../repo-b  
git filter-repo --to-subdirectory-filter b/

# 새 통합 저장소 생성
mkdir combined && cd combined
git init

# 두 저장소를 리모트로 추가하고 가져오기
git remote add repo-a ../repo-a
git remote add repo-b ../repo-b
git fetch repo-a
git fetch repo-b

# 각각의 히스토리를 병합
git merge repo-a/main --allow-unrelated-histories -m "merge: repo-a"
git merge repo-b/main --allow-unrelated-histories -m "merge: repo-b"
```

---

## BFG Repo-Cleaner와 비교

`filter-repo` 이전에 `filter-branch`의 대안으로 인기를 끌었던 도구가 BFG Repo-Cleaner다. Java로 작성됐고, 특정 작업에서는 매우 빠르다.

| 항목 | `filter-branch` | BFG | `filter-repo` |
|------|----------------|-----|---------------|
| 속도 | 🐢 매우 느림 | ⚡ 빠름 | ⚡ 매우 빠름 |
| 설치 | Git 내장 | JVM 필요 | Python 필요 |
| 민감 정보 교체 | 가능 (복잡) | 가능 | 가능 |
| 대용량 파일 제거 | 가능 | ✅ 특화 | 가능 |
| 경로 필터 | 가능 | 제한적 | ✅ 강력 |
| 저장소 분할 | 가능 | ❌ 불가 | ✅ 가능 |
| 저장소 병합 | 가능 | ❌ 불가 | ✅ 가능 |
| 최신 커밋 보호 | ❌ 없음 | ✅ 기본 | 별도 옵션 |
| Python 콜백 | ❌ | ❌ | ✅ 가능 |
| Git 공식 권장 | ❌ | ❌ | ✅ |

BFG는 대용량 파일 제거와 비밀번호 교체라는 **특정 작업에 특화**됐다. 사용법이 단순하고 JVM 위에서 병렬 처리를 잘 한다.

```bash
# BFG: 100MB 이상 파일 제거
java -jar bfg.jar --strip-blobs-bigger-than 100M my-repo.git

# BFG: 비밀번호 교체
java -jar bfg.jar --replace-text passwords.txt my-repo.git
```

하지만 BFG는 **현재 HEAD의 최신 커밋은 수정하지 않는다**는 철학을 가진다. "가장 최근 버전은 건드리지 않는다"는 안전장치인데, 이 때문에 민감 정보가 최신 커밋에도 있다면 별도 처리가 필요하다.

반면 `filter-repo`는 **저장소 분할, 경로 재구성, Python 콜백** 같은 고급 작업이 필요할 때 유일한 선택지다.

---

## Python 콜백으로 고급 제어

`filter-repo`의 진정한 강점은 Python 콜백이다. 불가능해 보이는 변환도 코드로 구현할 수 있다.

### 커밋 메시지 일괄 수정

이슈 트래커가 Jira에서 GitHub Issues로 변경됐다. 커밋 메시지의 `PROJ-123` 형식을 `#123`으로 변환한다.

```python
# commit-message-filter.py
import re

def commit_callback(commit):
    # 커밋 메시지 디코딩 (bytes -> str)
    msg = commit.message.decode('utf-8')
    
    # PROJ-숫자 패턴을 #숫자로 교체
    msg = re.sub(r'PROJ-(\d+)', r'#\1', msg)
    
    commit.message = msg.encode('utf-8')

# 실행
git filter-repo --commit-callback "$(cat commit-message-filter.py)"
```

### 작성자 이메일 수정

회사 이메일로 커밋한 것을 개인 이메일로 바꿔야 할 때:

```python
# author-filter.py  
def commit_callback(commit):
    if commit.author_email == b'old@company.com':
        commit.author_email = b'personal@example.com'
        commit.author_name = b'Your Name'
    if commit.committer_email == b'old@company.com':
        commit.committer_email = b'personal@example.com'
```

```bash
git filter-repo --commit-callback "
if commit.author_email == b'old@company.com':
    commit.author_email = b'personal@example.com'
"
```

### 특정 조건의 커밋 제거

비어있는 커밋이나 특정 패턴의 커밋을 제거:

```python
# 빈 커밋 제거 (변경 사항이 없는 커밋)
def commit_callback(commit):
    if not commit.file_changes:
        commit.skip()
```

---

## 재작성 후 반드시 해야 하는 것들

히스토리 재작성은 저장소의 **모든 커밋 해시를 변경**한다. 협업 중인 저장소라면 심각한 혼란을 초래할 수 있다.

```mermaid
sequenceDiagram
    participant You
    participant Remote
    participant Teammate

    You->>You: git filter-repo 실행
    Note over You: 모든 커밋 해시 변경
    You->>Remote: git push --force
    Teammate->>Remote: git pull
    Note over Teammate: 충돌! 로컬 히스토리와 불일치
    Teammate->>Teammate: git fetch && git rebase
```

### 체크리스트

```bash
# 1. 팀 전체에 히스토리 재작성 공지 (먼저!)

# 2. force push (filter-repo는 자동으로 remote 설정 제거하므로 다시 추가)
git remote add origin https://github.com/your/repo.git
git push origin --force --all
git push origin --force --tags

# 3. 팀원들은 재작성 후 아래 중 하나를 실행
# 방법 A: 클린 클론 (권장)
rm -rf local-repo
git clone https://github.com/your/repo.git

# 방법 B: 리베이스로 로컬 작업 보존
git fetch origin
git rebase origin/main

# 4. 민감 정보가 있었다면 즉시 비밀번호/키 교체
# (히스토리 정리가 완료됐더라도 노출됐을 가능성 있음)
```

### GitHub에서 캐시 삭제 요청

GitHub은 삭제된 커밋도 일정 기간 캐시로 접근 가능하다. 민감 정보라면 GitHub 지원팀에 캐시 삭제를 요청해야 한다.

```
GitHub Support > Contact Support > 
"Cached views of deleted content" 항목 선택
```

---

## 마치며

`git filter-repo`는 Git 히스토리 재작성의 사실상 표준이 됐다. `filter-branch`의 고통스러운 경험을 겪어본 사람이라면, 이 도구의 등장이 얼마나 반가운 일인지 이해할 것이다.

핵심을 정리하면:

1. **속도**: fast-export/import 파이프라인을 Python으로 직접 제어 → bash 서브쉘 오버헤드 없음
2. **안전**: 작업 후 원본 참조가 남지 않아 실수로 민감 정보를 남길 가능성이 낮음
3. **표현력**: Python 콜백으로 어떤 변환도 구현 가능
4. **다목적**: 파일 제거, 문자열 교체, 저장소 분할/병합까지 하나로

하지만 히스토리 재작성은 **파괴적 작업**이다. 협업 저장소에서는 반드시 팀 전체 공지 후 진행하고, 재작성 완료 후 팀원 모두가 새 히스토리로 동기화해야 한다. 그리고 민감 정보가 노출됐다면 히스토리 정리와 무관하게 **즉시 자격증명을 교체**하는 것이 원칙이다. Git 히스토리는 이미 여러 곳에 복제됐을 수 있다.

도구는 강력하다. 사용하는 사람의 판단이 더 중요하다.
