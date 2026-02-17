# Git Hooks 리서치 노트

## 주제: "Hooks - Git의 자동화 시스템"

작성일: 2026-02-17

---

## 1. Git Hooks란 무엇인가?

### 핵심 개념

- **Git Hooks**: Git 이벤트(commit, push, receive 등)가 발생할 때 자동으로 실행되는 스크립트
- 위치: `.git/hooks/` 디렉토리 (기본값)
- **실행 파일이면 어떤 언어든 OK**: sh, bash, Python, Ruby, Node.js...
- exit 0 = 성공(계속 진행), exit non-zero = 실패(작업 중단)
- `.sample` 확장자 제거 + 실행 권한 부여 시 활성화

### .git/hooks 기본 구조

```
.git/hooks/
├── applypatch-msg.sample
├── commit-msg.sample
├── fsmonitor-watchman.sample
├── post-update.sample
├── pre-applypatch.sample
├── pre-commit.sample
├── pre-merge-commit.sample
├── pre-push.sample
├── pre-rebase.sample
├── pre-receive.sample
├── prepare-commit-msg.sample
├── push-to-checkout.sample
├── sendemail-validate.sample
└── update.sample
```

### core.hooksPath (중요!)

Git 2.9+ 에서 추가된 설정:
```bash
git config core.hooksPath .husky
# 또는 전역 설정
git config --global core.hooksPath ~/.git-hooks
```

이게 Husky v5+의 핵심 메커니즘! `.git/hooks/` 대신 `.husky/` 디렉토리를 훅 디렉토리로 지정.

---

## 2. 클라이언트 훅 (Client-side Hooks)

### 커밋 관련 훅

#### pre-commit
- **언제**: `git commit` 실행 직후, 커밋 메시지 입력 전
- **인자**: 없음
- **stdin**: 없음
- **용도**: staged 변경사항 검사 (린트, 테스트 등)
- **git commit --no-verify**: 건너뛸 수 있음

실제 `.git/hooks/pre-commit.sample` 내용:
```sh
#!/bin/sh
# 비ASCII 파일명 감지, whitespace 오류 감지
if git rev-parse --verify HEAD >/dev/null 2>&1; then
    against=HEAD
else
    against=$(git hash-object -t tree /dev/null)
fi
exec git diff-index --check --cached $against --
```

#### prepare-commit-msg
- **언제**: 기본 커밋 메시지 생성 후, 에디터 실행 전
- **인자**: 메시지 파일, 커밋 타입, SHA (선택)
- **용도**: 자동 메시지 삽입 (브랜치명, 티켓번호 등)

#### commit-msg
- **언제**: 사용자가 메시지 입력 후
- **인자**: 커밋 메시지가 담긴 임시 파일 경로
- **용도**: 커밋 메시지 형식 검증 (Conventional Commits 등)

실제 `.git/hooks/commit-msg.sample`:
```sh
#!/bin/sh
# Duplicate Signed-off-by 라인 검사
test "" = "$(grep '^Signed-off-by: ' "$1" | sort | uniq -c | sed -e '/^[ \t]*1[ \t]/d')" || {
    echo >&2 Duplicate Signed-off-by lines.
    exit 1
}
```

#### post-commit
- **언제**: 커밋 완료 후
- **인자**: 없음
- **용도**: 알림, 로깅 (실패해도 커밋은 취소되지 않음)

### 기타 클라이언트 훅

| 훅 | 타이밍 | 용도 |
|----|--------|------|
| pre-push | push 전 | 리모트로 보내기 전 검사 |
| pre-rebase | rebase 전 | 위험한 rebase 방지 |
| post-checkout | checkout 후 | 환경 설정 |
| post-merge | merge 후 | 의존성 업데이트 |
| pre-merge-commit | merge commit 전 | merge 전 검사 |

---

## 3. 서버 훅 (Server-side Hooks)

### 서버 훅이 중요한 이유

클라이언트 훅은 `--no-verify`로 우회 가능.
서버 훅은 **우회 불가능** (push 자체를 거부).

### pre-receive

- **언제**: push를 받는 순간, ref 업데이트 전
- **인자**: 없음
- **stdin**: `<old-value> <new-value> <refname>` 형식 라인들
- **전략**: exit 1 → 전체 push 거부

```sh
#!/bin/bash
while read oldrev newrev refname; do
    # 보호된 브랜치에 force push 방지
    if [ "$refname" = "refs/heads/main" ] && [ "$oldrev" != "0000000000000000000000000000000000000000" ]; then
        echo "ERROR: Force push to main is not allowed"
        exit 1
    fi
done
```

### update

- **언제**: pre-receive 이후, 각 ref 업데이트마다
- **인자**: refname, old SHA, new SHA
- **차이**: pre-receive는 전체 push, update는 각 브랜치별 실행

실제 `.git/hooks/update.sample`:
```sh
#!/bin/sh
refname="$1"
oldrev="$2"
newrev="$3"
# annotated tag만 허용하는 로직...
```

### post-receive

- **언제**: 모든 ref 업데이트 완료 후
- **인자**: 없음
- **stdin**: pre-receive와 동일 형식
- **중요**: exit 1해도 push 취소 안 됨 (notification용)
- **용도**: CD 트리거, Slack 알림, 배포 등

---

## 4. 훅 활용 사례

### 린트 / 코드 품질

```sh
#!/bin/sh
# pre-commit: ESLint
npx eslint --ext .js,.ts $(git diff --cached --name-only --diff-filter=ACM | grep -E '\.ts?$')
```

### 테스트

```sh
#!/bin/sh
# pre-push: 테스트 실행
npm test || exit 1
```

### 커밋 메시지 검증 (Conventional Commits)

```sh
#!/bin/sh
# commit-msg
commit_msg=$(cat "$1")
pattern="^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?: .{1,72}"
if ! echo "$commit_msg" | grep -qP "$pattern"; then
    echo "ERROR: Commit message does not follow Conventional Commits format"
    echo "Example: feat(auth): add OAuth2 login"
    exit 1
fi
```

### CI/CD 배포 (post-receive)

```sh
#!/bin/bash
# post-receive: 배포 트리거
while read oldrev newrev refname; do
    if [ "$refname" = "refs/heads/main" ]; then
        echo "Deploying to production..."
        cd /var/www/myapp
        git --work-tree=/var/www/myapp --git-dir=/var/repo/myapp.git checkout -f
        systemctl restart myapp
    fi
done
```

---

## 5. Husky / pre-commit 도구들

### 핵심 문제: 훅은 .git에 있어 버전 관리가 안 됨

```
.git/hooks/pre-commit  ← git이 추적하지 않음!
```

팀에서 공유 불가. 그래서 도구가 등장.

### Husky (Node.js 생태계)

- **개발**: typicode, 2014년경 시작
- **핵심 메커니즘**: `core.hooksPath`를 `.husky/`로 설정

**v4 (구버전):**
```json
// package.json
{
  "husky": {
    "hooks": {
      "pre-commit": "npm run lint",
      "commit-msg": "commitlint --edit $HUSKY_GIT_PARAMS"
    }
  }
}
```

**v9 (현재):**
```bash
npx husky init
# .husky/pre-commit 파일 생성
# package.json에 "prepare": "husky" 추가
```

```sh
# .husky/pre-commit
npm run lint
npm test
```

**왜 빠른가?** core.hooksPath로 직접 연결 → 약 1ms 오버헤드

### pre-commit (Python 생태계)

- Python으로 작성된 프레임워크
- `.pre-commit-config.yaml`로 훅 공유
- 다양한 언어/도구를 지원하는 훅 레지스트리

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
```

```bash
pip install pre-commit
pre-commit install  # .git/hooks/pre-commit 설치
pre-commit run --all-files  # 전체 검사
```

### lint-staged (Node.js, 스테이징된 파일만)

```json
// package.json
{
  "lint-staged": {
    "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
    "*.{css,scss}": ["prettier --write"]
  }
}
```

Husky + lint-staged 조합이 가장 많이 쓰임.

---

## 6. Git 초기 Hooks 구현 역사

### 2005년 초기

- Git 첫 커밋: 2005년 4월 7일
- Git 1.0: 2005년 12월 21일
- `.dircache` → `.git` 디렉토리 이름 변경
- 초기부터 `.git/hooks/` 개념 존재 (단순 shell script)

### core.hooksPath의 추가 (Git 2.9, 2016)

버전 관리 가능한 훅 디렉토리를 위해 추가.
이게 Husky v5+, lefthook 등의 현대적 도구를 가능하게 함.

### 훅 도구 연대기

| 연도 | 도구 | 특징 |
|------|------|------|
| 2005 | Git 1.0 | .git/hooks/ 기본 제공 |
| 2014~ | Husky v1-4 | package.json에서 설정 |
| 2016 | Git 2.9 | core.hooksPath 추가 |
| 2016~ | pre-commit | Python, YAML 기반 |
| 2020~ | Husky v5+ | .husky/ 디렉토리 방식 |
| 현재 | lefthook | Go 기반, 병렬 실행 |

### Lefthook (최신 대안)

- Go로 작성 → 빠름
- 병렬 실행 지원
- 여러 언어 생태계 지원

```yaml
# lefthook.yml
pre-commit:
  parallel: true
  commands:
    lint:
      run: npm run lint
    test:
      run: npm test
```

---

## 7. 주요 다이어그램 아이디어

### 다이어그램 1: 커밋 훅 실행 순서

```
git commit 실행
    ↓
pre-commit (staged 검사) → 실패 시 중단
    ↓
prepare-commit-msg (메시지 생성/수정)
    ↓
[에디터 열림 → 사용자 메시지 입력]
    ↓
commit-msg (메시지 형식 검증) → 실패 시 중단
    ↓
post-commit (알림/로깅)
```

### 다이어그램 2: push 훅 실행 순서 (서버)

```
git push 실행
    ↓ (클라이언트)
pre-push → 실패 시 push 중단
    ↓ (서버)
pre-receive (전체 push 검사) → 실패 시 전체 거부
    ↓
update (각 ref마다 실행) → 실패 시 해당 ref만 거부
    ↓
post-receive (알림, 배포 트리거)
```

### 다이어그램 3: .git/hooks vs Husky 비교

```
[전통 방식]
개발자 A의 .git/hooks/pre-commit → 버전 관리 안 됨
개발자 B의 .git/hooks/pre-commit → 없음 (복사 안 됨)

[Husky 방식]
.husky/pre-commit → git add, git commit, 공유됨!
core.hooksPath = .husky → Git이 .husky를 훅 디렉토리로 사용
```

---

## 8. 재미있는 사실들

1. **--no-verify**: 클라이언트 훅을 완전히 건너뛰는 탈출구
   ```bash
   git commit --no-verify -m "규칙 무시하고 커밋"
   ```

2. **훅은 어떤 언어로도**: 첫 줄 shebang만 맞으면 됨
   ```python
   #!/usr/bin/env python3
   # .git/hooks/pre-commit
   import subprocess
   result = subprocess.run(["pytest"], capture_output=True)
   exit(result.returncode)
   ```

3. **서버 훅은 Git 호스팅 서비스마다 다름**:
   - GitHub: Webhooks로 대체 (pre-receive 직접 불가)
   - GitLab: Server Hooks 지원 (Premium)
   - Gitea/Gogs: 자체 서버 훅 지원

4. **core.hooksPath가 없었던 시절**: symlink 전략
   ```bash
   # 오래된 방법
   ln -s ../../.githooks/pre-commit .git/hooks/pre-commit
   ```

---

## 9. 다음 편 연결 포인트

- **Git Worktree**: 여러 worktree가 같은 .git/hooks를 공유하는가?
- **GitHub Actions vs 서버 훅**: 어느 것이 더 나은가?
- **보안**: 악의적인 훅 스크립트 (case-insensitive 파일시스템 공격)

---

## 마무리 체크리스트

- [x] .git/hooks 구조 직접 확인 (git init으로)
- [x] 클라이언트 훅 종류 및 인자 정리
- [x] 서버 훅 종류 및 사용법 정리
- [x] 실제 .sample 파일 내용 확인
- [x] Husky v4/v9 변화 추적
- [x] pre-commit 프레임워크 조사
- [x] core.hooksPath 메커니즘 확인
- [x] Git 초기 역사 조사
- [x] 다이어그램 스케치 완료

**준비 완료! 초안 작성으로 진행.**
