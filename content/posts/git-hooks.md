---
title: "Git 해체분석기 #11: Hooks - Git의 자동화 시스템"
date: 2026-02-17
draft: false
summary: "git commit을 실행하는 순간 뒤에서 조용히 실행되는 스크립트들. .git/hooks의 정체를 파헤친다."
tags: ["git", "해체분석기", "hooks", "automation", "husky"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 11
mermaid: true
toc: true
---

> `git commit`을 실행했는데 뭔가가 실행되고, 테스트가 돌아가고, 린트가 검사를 한다.  
> `.git/hooks` 폴더에 숨겨진 **Git의 자동화 엔진**을 해체해봅니다.

## 들어가며

Git을 쓰다 보면 이런 경험을 합니다.

```bash
$ git commit -m "feat: add login"
Running pre-commit checks...
✖ ESLint: 3 errors found
  src/auth.ts:42  Missing semicolon
  src/auth.ts:87  Unused variable 'token'
husky - pre-commit hook exited with code 1 (error)
```

커밋이 거부됐습니다. 누가 막은 걸까요?

오늘은 `git commit`이 실행되는 순간 뒤에서 조용히 움직이는 **Git Hooks** 시스템을 해체합니다.

---

## 1. Hooks란 무엇인가?

**Git Hook = 특정 Git 이벤트가 발생할 때 자동으로 실행되는 스크립트.**

Git은 커밋, 푸시, 머지 등 주요 작업마다 "이 시점에 뭔가 실행하고 싶으면 여기 스크립트를 놔라"라고 약속된 위치를 제공합니다. 그 위치가 `.git/hooks/`입니다.

```bash
$ git init test-repo
$ ls test-repo/.git/hooks/
aplypatch-msg.sample    pre-applypatch.sample
commit-msg.sample        pre-commit.sample
fsmonitor-watchman.sample pre-merge-commit.sample
post-update.sample       pre-push.sample
prepare-commit-msg.sample pre-rebase.sample
pre-receive.sample       push-to-checkout.sample
sendemail-validate.sample update.sample
```

모두 `.sample` 확장자를 달고 잠들어 있습니다. 활성화 방법은 간단합니다:

```bash
# 1. 확장자 제거
mv .git/hooks/pre-commit.sample .git/hooks/pre-commit

# 2. 실행 권한 부여
chmod +x .git/hooks/pre-commit
```

**끝입니다.** 이제 `git commit` 때마다 이 스크립트가 실행됩니다.

### 규칙: exit code가 전부다

```
exit 0   → 성공. Git 작업 계속 진행.
exit 1   → 실패. Git 작업 중단.
```

단 두 가지 규칙으로 모든 자동화가 가능합니다.

---

## 2. 클라이언트 훅: 내 컴퓨터에서 실행되는 것들

### 커밋의 여정

`git commit -m "message"`를 실행하면 실제로는 이런 일이 벌어집니다:

<pre class="mermaid">
flowchart TD
    A["git commit 실행"]
    B["pre-commit\n(staged 파일 검사)"]
    C{"exit 0?"}
    D["prepare-commit-msg\n(메시지 자동 생성)"]
    E["에디터 열림\n사용자 메시지 입력"]
    F["commit-msg\n(메시지 형식 검증)"]
    G{"exit 0?"}
    H["커밋 생성 완료"]
    I["post-commit\n(알림/로깅)"]
    FAIL1["❌ 커밋 중단"]
    FAIL2["❌ 커밋 중단"]

    A --> B --> C
    C -->|"Yes"| D --> E --> F --> G
    C -->|"No"| FAIL1
    G -->|"Yes"| H --> I
    G -->|"No"| FAIL2

    style FAIL1 fill:#ffcdd2,stroke:#c62828
    style FAIL2 fill:#ffcdd2,stroke:#c62828
    style H fill:#c8e6c9,stroke:#388e3c
</pre>

### pre-commit: 첫 번째 문지기

- **타이밍**: 커밋 전, 스테이징 영역 검사
- **인자**: 없음
- **대표 용도**: 린트, 타입 체크, 간단한 테스트

```sh
#!/bin/sh
# .git/hooks/pre-commit

# 스테이징된 TypeScript 파일만 린트
STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.tsx?$')

if [ -n "$STAGED_TS" ]; then
    npx tsc --noEmit
    if [ $? -ne 0 ]; then
        echo "❌ TypeScript 타입 오류가 있습니다. 수정 후 다시 커밋하세요."
        exit 1
    fi
fi

exit 0
```

### commit-msg: 메시지 경찰

- **타이밍**: 사용자가 메시지를 입력한 직후
- **인자**: 커밋 메시지가 담긴 **임시 파일 경로**
- **대표 용도**: Conventional Commits 형식 강제

```sh
#!/bin/sh
# .git/hooks/commit-msg
# $1 = 커밋 메시지 파일 경로

commit_msg=$(cat "$1")

# Conventional Commits: feat(scope): description
pattern="^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?: .{1,72}"

if ! echo "$commit_msg" | grep -qE "$pattern"; then
    echo "❌ 커밋 메시지 형식이 잘못됐습니다."
    echo "   올바른 형식: feat(auth): add OAuth2 login"
    echo "   허용 타입: feat, fix, docs, style, refactor, test, chore"
    exit 1
fi
```

실제 Git이 제공하는 `commit-msg.sample`도 비슷한 방식으로 `Signed-off-by` 중복을 검사합니다:

```sh
test "" = ""
$(grep '^Signed-off-by: ' "$1" | sort | uniq -c | sed -e '/^[[:space:]]*1[[:space:]]/d')" || {
    echo >&2 "Duplicate Signed-off-by lines."
    exit 1
}
```

### post-commit: 커밋 후 알림

- **타이밍**: 커밋 완료 직후
- **인자**: 없음
- **중요**: 실패(exit 1)해도 커밋이 취소되지 않음

```sh
#!/bin/sh
# .git/hooks/post-commit
# 마지막 커밋 정보 Slack으로 알림
BRANCH=$(git branch --show-current)
COMMIT_MSG=$(git log -1 --pretty=format:"%s")
curl -s -X POST "$SLACK_WEBHOOK" \
    -d "{\"text\": \"✅ [$BRANCH] $COMMIT_MSG\"}" > /dev/null
```

---

## 3. 서버 훅: 우회 불가능한 문지기

### 클라이언트 훅의 치명적 약점

```bash
# 이 한 줄로 모든 클라이언트 훅을 무시할 수 있다
$ git commit --no-verify -m "린트 무시하고 커밋"
$ git push --no-verify
```

**`--no-verify`** 플래그 앞에서 pre-commit, commit-msg는 무력합니다.

서버 훅은 다릅니다. **push 자체를 서버에서 거부**하기 때문에, 우회할 방법이 없습니다.

### push의 여정 (서버 입장)

<pre class="mermaid">
flowchart TD
    PUSH["git push 실행"]
    PRE["pre-receive\n(전체 push 일괄 검사)"]
    C1{"exit 0?"}
    UPD["update\n(각 브랜치/태그별 검사)"]
    C2{"exit 0?"}
    REFS["refs 업데이트 완료"]
    POST["post-receive\n(배포, 알림 트리거)"]
    FAIL_ALL["❌ 전체 push 거부"]
    FAIL_REF["❌ 해당 ref만 거부"]

    PUSH --> PRE --> C1
    C1 -->|"Yes"| UPD --> C2
    C1 -->|"No"| FAIL_ALL
    C2 -->|"Yes"| REFS --> POST
    C2 -->|"No"| FAIL_REF

    style FAIL_ALL fill:#ffcdd2,stroke:#c62828
    style FAIL_REF fill:#ffe0b2,stroke:#e65100
    style POST fill:#c8e6c9,stroke:#388e3c
</pre>

### pre-receive: 전체 push의 심판

- **stdin**: `<old-sha> <new-sha> <refname>` 형식의 라인들
- **exit 1**: 전체 push 거부

```sh
#!/bin/bash
# .git/hooks/pre-receive
# main 브랜치 force push 방지

while read oldrev newrev refname; do
    if [ "$refname" = "refs/heads/main" ]; then
        # old가 new의 조상이 아니면 force push
        if ! git merge-base --is-ancestor "$oldrev" "$newrev" 2>/dev/null; then
            echo "❌ main 브랜치에 force push는 허용되지 않습니다."
            exit 1
        fi
    fi
done
```

### update: 브랜치별 심판

pre-receive와 달리 **각 ref(브랜치/태그)마다 별도 실행**됩니다.

- **인자 1**: refname (브랜치/태그 이름)
- **인자 2**: old SHA
- **인자 3**: new SHA

```sh
#!/bin/bash
# .git/hooks/update
# 보호된 브랜치에 직접 push 방지 (PR 필수)

refname="$1"
protected_branches="refs/heads/main refs/heads/develop"

for protected in $protected_branches; do
    if [ "$refname" = "$protected" ]; then
        echo "❌ $refname 에는 직접 push할 수 없습니다. PR을 사용하세요."
        exit 1
    fi
done
```

### post-receive: 배포 자동화의 심장

- **성공 여부와 무관**: exit 1해도 push는 이미 완료됨
- **stdin**: pre-receive와 동일
- **대표 용도**: 배포, Slack 알림, CI 트리거

```sh
#!/bin/bash
# .git/hooks/post-receive
# main 브랜치 push 시 자동 배포

while read oldrev newrev refname; do
    if [ "$refname" = "refs/heads/main" ]; then
        echo "🚀 main 브랜치 push 감지. 배포를 시작합니다..."
        cd /var/www/myapp
        git --work-tree=/var/www/myapp --git-dir=/var/repo/myapp.git checkout -f
        npm install --production
        pm2 restart myapp
        echo "✅ 배포 완료!"
    fi
done
```

---

## 4. 충격적인 사실들

### 🤯 훅은 버전 관리가 안 된다

`.git/` 폴더는 Git이 추적하지 않습니다.

```
내 컴퓨터: .git/hooks/pre-commit ← 존재
동료 컴퓨터: .git/hooks/pre-commit ← 없음!
```

`git clone`해도 훅은 복사되지 않습니다. 이게 Husky 같은 도구가 탄생한 이유입니다.

### 🤯 어떤 언어로도 쓸 수 있다

첫 줄 shebang만 맞으면 됩니다.

```python
#!/usr/bin/env python3
# .git/hooks/pre-commit
import subprocess
import sys

result = subprocess.run(["pytest", "tests/", "-q"], capture_output=True)
if result.returncode != 0:
    print(result.stdout.decode())
    sys.exit(1)
```

```ruby
#!/usr/bin/env ruby
# .git/hooks/commit-msg
msg = File.read(ARGV[0]).strip
unless msg.match?(/^(feat|fix|docs|chore):.+/)
  puts "❌ Conventional Commits 형식을 따르세요"
  exit 1
end
```

### 🤯 GitHub은 서버 훅을 직접 지원 안 한다

GitHub, GitLab Free 플랜에서는 서버 훅을 직접 설정할 수 없습니다. 대신:

| 플랫폼 | 대안 |
|--------|------|
| GitHub | GitHub Actions, Branch Protection Rules |
| GitLab (Free) | CI/CD Pipeline, Push Rules |
| GitLab (Premium) | Server Hooks (직접 지원) |
| 자체 서버 (Gitea 등) | 직접 서버 훅 설정 가능 |

---

## 5. 도구들: 훅을 팀과 공유하는 법

### Husky: Node.js 생태계의 표준

**핵심 아이디어**: `core.hooksPath`를 버전 관리되는 디렉토리로 설정

```bash
# Git 2.9+에 추가된 설정
git config core.hooksPath .husky
```

이제 `.husky/`가 `.git/hooks/`를 대체합니다. `.husky/`는 버전 관리됩니다!

```bash
# 설치
npm install husky --save-dev
npx husky init  # .husky/pre-commit 생성, package.json에 prepare 추가
```

```sh
# .husky/pre-commit (버전 관리됨!)
npx lint-staged
```

<pre class="mermaid">
flowchart LR
    subgraph "전통 방식"
        A[".git/hooks/pre-commit"]
        B["❌ git이 추적 안 함"]
        A --- B
    end
    subgraph "Husky 방식"
        C[".husky/pre-commit"]
        D["git add ✅"]
        E["core.hooksPath = .husky"]
        C --> D
        C --> E
    end

    style A fill:#ffcdd2,stroke:#c62828
    style C fill:#c8e6c9,stroke:#388e3c
</pre>

Husky v4(구버전)와 v9(현재)의 설정 방식 변화:

| 버전 | 설정 위치 | 방식 |
|------|-----------|------|
| v4 이하 | `package.json` → `"husky"` 키 | JSON 설정 |
| v9 현재 | `.husky/pre-commit` 파일 | 직접 스크립트 |

### pre-commit: Python 생태계의 표준

`.pre-commit-config.yaml`로 훅을 선언적으로 관리합니다.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: no-commit-to-branch
        args: ['--branch', 'main']
```

```bash
pip install pre-commit
pre-commit install         # .git/hooks/pre-commit 설치
pre-commit run --all-files # 전체 파일 검사 (CI에서 유용)
```

**강점**: 각 훅이 격리된 가상환경에서 실행 → 의존성 충돌 없음

### lint-staged: 스테이징된 파일만 검사

전체 프로젝트를 린트하면 너무 느립니다. Husky + lint-staged 조합이 답입니다:

```json
// package.json
{
  "lint-staged": {
    "*.{ts,tsx}": ["eslint --fix", "prettier --write", "git add"],
    "*.{css,scss}": ["stylelint --fix", "prettier --write", "git add"],
    "*.py": ["black", "flake8"]
  }
}
```

```sh
# .husky/pre-commit
npx lint-staged
```

커밋하는 파일만 검사하므로 속도가 훨씬 빠릅니다.

---

## 6. 내부를 들여다보면

### core.hooksPath의 등장 (Git 2.9, 2016)

Git 1.0 (2005년 12월)부터 `.git/hooks/`는 존재했습니다. 하지만 버전 관리 불가 문제는 오래된 숙제였습니다.

초기 해결책은 symlink였습니다:

```bash
# 옛날 방식 (지저분하다)
mkdir .githooks
cp .git/hooks/pre-commit .githooks/pre-commit
git add .githooks
# 팀원이 clone 후 직접 설정해야...
ln -s ../../.githooks/pre-commit .git/hooks/pre-commit
```

2016년 Git 2.9에서 `core.hooksPath`가 추가되며 이 모든 번거로움이 해결됐습니다. Husky v5+의 현대적 방식은 이 기능 위에 서 있습니다.

---

## 7. 정리

<pre class="mermaid">
flowchart TB
    subgraph CLIENT ["클라이언트 훅 (로컬)"]
        PC["pre-commit\n코드 품질 검사"]
        CM["commit-msg\n메시지 형식 검증"]
        POSH["post-commit\n알림/로깅"]
        PP["pre-push\npush 전 테스트"]
    end

    subgraph SERVER ["서버 훅 (우회 불가)"]
        PR["pre-receive\n전체 push 검사"]
        UPD["update\nbranch별 권한 검사"]
        POSR["post-receive\n배포/알림 트리거"]
    end

    subgraph TOOLS ["도구"]
        HUS["Husky (Node.js)"]
        PREC["pre-commit (Python)"]
        LS["lint-staged"]
    end

    CLIENT -->|"--no-verify로 우회 가능"| SERVER
    TOOLS -->|"버전 관리 + 팀 공유"| CLIENT

    style CLIENT fill:#e3f2fd,stroke:#1565c0
    style SERVER fill:#fce4ec,stroke:#c62828
    style TOOLS fill:#e8f5e9,stroke:#2e7d32
</pre>

| 항목 | 클라이언트 훅 | 서버 훅 |
|------|--------------|---------|
| **실행 위치** | 개발자 로컬 | Git 서버 |
| **우회 가능?** | Yes (`--no-verify`) | No |
| **대표 훅** | pre-commit, commit-msg | pre-receive, update, post-receive |
| **주요 용도** | 린트, 타입 체크, 메시지 검증 | 권한 제어, 배포, 알림 |
| **공유 방법** | Husky, pre-commit 도구 | 서버 설정 (또는 GitLab Premium) |

**Git Hooks의 본질:**
> 훅은 단순한 스크립트입니다. `.git/hooks/`라는 약속된 장소에,  
> 올바른 이름으로, 실행 권한을 주면 됩니다.  
> 나머지는 exit 0과 exit 1이 결정합니다.

---

## 8. 직접 해보기

팀 전체에 적용되는 린트 훅을 3분 안에 만들어봅시다.

```bash
# 1. Node.js 프로젝트 기준 (Husky + lint-staged)
npm install --save-dev husky lint-staged
npx husky init

# 2. pre-commit 훅 작성
echo "npx lint-staged" > .husky/pre-commit

# 3. package.json에 lint-staged 설정 추가
# (package.json 직접 편집)
# "lint-staged": {
#   "*.{js,ts}": ["eslint --fix", "prettier --write"]
# }

# 4. git에 추가하면 팀 전체에 공유
git add .husky package.json
git commit -m "chore: add git hooks with Husky"
```

이제 팀 모든 구성원이 `npm install` 한 번으로 동일한 훅을 갖게 됩니다.

---

## 다음 편 예고

> **해체분석기 #12: Git Stash - 임시 저장의 비밀**
> 
> - Stash는 사실 commit이다?
> - `refs/stash`의 정체
> - stash apply vs pop의 내부 차이

---

## 참고 자료

- [Git Official Docs - githooks](https://git-scm.com/docs/githooks)
- [Pro Git Book - Git Hooks](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks)
- [Husky Documentation](https://typicode.github.io/husky/)
- [pre-commit Framework](https://pre-commit.com)
- [Atlassian - Git Hooks Tutorial](https://www.atlassian.com/git/tutorials/git-hooks)
