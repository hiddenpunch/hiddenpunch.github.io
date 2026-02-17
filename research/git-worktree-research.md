# Git Worktree 리서치 노트

## 주제: "Worktree - 하나의 저장소, 여러 작업 디렉토리"

작성일: 2026-02-17

---

## 1. Worktree란 무엇인가?

### 핵심 개념
- **Worktree = 하나의 `.git` 저장소에 연결된 여러 작업 디렉토리**
- 기존 문제: 두 브랜치를 동시에 열어두려면 → 저장소를 통째로 clone 해야 했음
- Worktree 해결책: clone 없이 같은 `.git`을 공유하면서 다른 브랜치를 각자 다른 디렉토리에서 checkout

### 주요 용어
- **Main worktree**: `git init` 또는 `git clone`으로 만들어진 기본 작업 디렉토리
- **Linked worktree**: `git worktree add`로 추가한 연결된 작업 디렉토리
- **Bare repository worktree**: bare repo에서도 worktree add 가능

---

## 2. 명령어 정리

### git worktree add
```bash
# 새 브랜치 만들면서 추가
git worktree add <path> -b <branch>

# 기존 브랜치로 추가
git worktree add <path> <branch>

# detached HEAD 상태로 추가 (특정 커밋)
git worktree add --detach <path> <commit>

# orphan 브랜치 (히스토리 없는 새 브랜치)
git worktree add --orphan -b <branch> <path>
```

### git worktree list
```bash
git worktree list
# /path/to/main   abc1234 [main]
# /path/to/hotfix def5678 [hotfix/urgent]

git worktree list --porcelain  # 기계가 읽기 좋은 포맷
```

### git worktree remove
```bash
git worktree remove <path>
# 조건: 변경사항이 없어야 함 (clean)
git worktree remove -f <path>  # 강제 (변경사항 있어도)
```

### 기타
```bash
git worktree lock --reason "CI 빌드 중" <path>
git worktree unlock <path>
git worktree move <old-path> <new-path>
git worktree prune  # 삭제된 worktree 메타데이터 정리
git worktree repair  # 이동된 worktree 링크 복구
```

---

## 3. .git 내부 구조 실험 결과

### 실험 환경
```bash
git init wt-test && cd wt-test
git commit -m "Initial"
git worktree add ../wt-hotfix -b hotfix/urgent
git worktree add ../wt-review feature/login
```

### 발견 1: linked worktree의 .git은 "파일"
```
/tmp/wt-hotfix/.git  ← 디렉토리가 아니라 텍스트 파일!
내용: "gitdir: /private/tmp/wt-test/.git/worktrees/wt-hotfix"
```

### 발견 2: .git/worktrees/ 구조
```
.git/worktrees/wt-hotfix/
├── HEAD         ← "ref: refs/heads/hotfix/urgent" (worktree 독립)
├── commondir    ← "../.." (공유 .git 위치)
├── gitdir       ← "/private/tmp/wt-hotfix/.git" (역방향 링크)
├── index        ← worktree 독립 staging area
├── locked       ← lock reason (lock 시 생성)
├── ORIG_HEAD    ← worktree 독립
└── logs/
    └── HEAD     ← worktree 독립 HEAD reflog
```

### 공유되는 것 vs 독립적인 것

**공유 (main .git/):**
- `objects/` - 모든 커밋, 트리, 블롭 공유
- `refs/` - 브랜치, 태그 공유
- `config` - 저장소 설정
- `hooks/` - Git 훅
- `packed-refs` - packed refs

**독립 (worktrees/<name>/):**
- `HEAD` - 어떤 브랜치/커밋을 가리키는지
- `index` - staging area (staged 파일 목록)
- `logs/HEAD` - 해당 worktree의 HEAD 이동 기록
- `ORIG_HEAD`, `MERGE_HEAD` 등 임시 ref들
- `locked` (optional)

### 발견 3: 브랜치 잠금
```bash
# hotfix worktree에서 이미 main이 사용 중인 master로 checkout 시도
git checkout master
# fatal: 'master' is already used by worktree at '/private/tmp/wt-test'
```
→ 같은 브랜치를 두 worktree에서 동시에 사용 불가

### 발견 4: GIT_COMMON_DIR 환경변수
- Git이 내부적으로 `GIT_DIR` (worktree 전용 .git) 와 `GIT_COMMON_DIR` (공유 .git) 구분
- path 해석 시 HEAD, index → GIT_DIR 사용
- objects, refs, config → GIT_COMMON_DIR 사용

---

## 4. Worktree vs Branch vs Clone 비교

| 구분 | Branch switch | Clone | Worktree |
|------|--------------|-------|---------|
| 별도 디렉토리 | ❌ | ✅ | ✅ |
| objects 공유 | ✅ | ❌ | ✅ |
| 디스크 사용 | 최소 | 2x | 최소 |
| 동시 체크아웃 | ❌ | ✅ | ✅ |
| stash 공유 | N/A | ❌ | ✅ |
| remote 공유 | N/A | ❌ | ✅ |
| 설정 공유 | N/A | ❌ | ✅ |

### Clone의 단점 (Worktree가 해결하는 것)
1. 전체 objects 복사 → 디스크 낭비 (대형 저장소에서 GB 단위)
2. remote tracking이 분리됨
3. `git fetch`를 각 clone마다 별도로 해야 함
4. stash 공유 불가

---

## 5. 실전 활용 패턴

### 패턴 1: 긴급 핫픽스
```bash
# 현재 feature/big-refactor에서 작업 중
git worktree add ../hotfix hotfix/critical-bug
cd ../hotfix
# 수정 및 커밋
# PR 올리고 merge
git worktree remove ../hotfix
```
→ stash 불필요, feature 작업 그대로 유지

### 패턴 2: 코드 리뷰
```bash
git worktree add ../review-pr-42 pr/42
cd ../review-pr-42
# 리뷰하면서 직접 실행/테스트
```

### 패턴 3: 동시 빌드
```bash
git worktree add ../build-v1.0 v1.0-branch
git worktree add ../build-main main
# 두 빌드를 병렬로 실행
```

### 패턴 4: Bare repo + worktree (고급)
```bash
# bare repo를 중앙으로
git clone --bare <url> repo.git
cd repo.git
git worktree add ../main main
git worktree add ../feature feature
```

---

## 6. Worktree 구현 역사

### 기원
- Git 2.5, **2015년 7월** 출시
- 이전: linked working trees 개념 없음
- 개발자들이 쓰던 방법: `git clone` 반복, 또는 `git diff > patch && apply` 방식

### 핵심 설계 결정
- `.git` 파일 (디렉토리 아님) 개념 도입 → linked worktree가 main `.git`을 가리킴
- `GIT_COMMON_DIR` 환경변수 추가 → 공유/독립 경로 구분
- `commondir` 파일 → 쉘 환경변수 없이도 공유 git dir 찾기 가능

### 버전별 발전
| 버전 | 기능 |
|------|------|
| Git 2.5 (2015.07) | `git worktree add`, `list`, `prune` 최초 도입 |
| Git 2.15 (2017.10) | `git worktree lock`, `unlock` 추가 |
| Git 2.17 (2018.04) | `git worktree list` 개선 |
| Git 2.17+ | `git bisect`의 worktree 지원 |
| Git 2.36 (2022.04) | `--reason` 옵션 개선 |
| Git 2.39 (2022.12) | `git worktree add --orphan` |
| Git 2.47 (2024) | `git worktree repair` 개선 |

---

## 7. 주의사항 및 엣지 케이스

### stash는 전체 저장소 공유
```bash
# main worktree에서 stash → 모든 worktree에서 보임
# (refs/stash가 공유 .git에 있기 때문)
```

### submodule 지원 제한
- worktree에서 submodule 동작이 제한적일 수 있음

### worktree 경로 이동 시
```bash
git worktree move <old> <new>  # 또는
# 직접 이동 후 git worktree repair
```

### prune vs remove
- `remove`: 실제 디렉토리도 삭제
- `prune`: 이미 삭제된 worktree의 .git/worktrees/ 메타데이터만 정리

---

## 8. 소스 코드 위치

- `builtin/worktree.c` - worktree 명령어 구현
- `worktree.c` / `worktree.h` - worktree 관련 공통 함수
- `Documentation/git-worktree.txt` - 공식 문서

---

## 참고 자료

- [Git Official Docs - git-worktree](https://git-scm.com/docs/git-worktree)
- [Git 2.5 Release Notes](https://github.com/git/git/blob/master/Documentation/RelNotes/2.5.0.txt)
- [Pro Git Book - Worktrees](https://git-scm.com/book/en/v2/Git-Tools-Worktrees)
- [Git Source - worktree.c](https://github.com/git/git/blob/master/worktree.c)
