# Git Stash 리서치 노트

## 주제: "Stash - 작업을 잠시 숨기는 마법"

작성일: 2026-02-17

---

## 1. Stash란 무엇인가?

### 핵심 개념
- **Stash = 임시 저장소**: 커밋하지 않은 변경사항(staged + unstaged)을 임시로 저장하고 working tree를 깨끗하게 만드는 기능
- 핵심: "나중에 돌아올게, 잠깐만"을 Git에게 말하는 방법
- 내부적으로는 특수한 커밋 구조로 저장됨 (단순 임시 파일이 아님!)

### 사용 시나리오
1. 급한 버그 수정 요청 → 현재 작업을 stash → 버그 수정 → stash pop
2. 브랜치 전환 시 uncommitted 변경사항 충돌 방지
3. 실험적 코드를 잠시 치워두고 싶을 때

---

## 2. .git/refs/stash 구조 분석 (실험 결과)

### 파일 구조
```
.git/
├── refs/
│   └── stash          ← stash@{0}의 SHA 저장 (단순 텍스트 파일)
└── logs/
    └── refs/
        └── stash      ← stash 스택 순서를 관리하는 reflog
```

### 실험 결과

```bash
$ cat .git/refs/stash
3b3b1c9d11476f2bf218fbb41afcfaa8f98ff499  ← stash@{0}의 SHA

$ cat .git/logs/refs/stash
0000... 90b0b10... Test <test@test.com> 1771317412 +0900  On master: Stash A
90b0b10... fc93f2d... Test <test@test.com> 1771317412 +0900  On master: Stash B
fc93f2d... 3b3b1c9... Test <test@test.com> 1771317412 +0900  On master: Stash C
```

### 핵심 발견: stash 스택 = reflog!
- `.git/refs/stash`는 항상 stash@{0}만 가리킴
- stash 순서(스택)는 `.git/logs/refs/stash`(reflog)가 관리
- `stash@{N}` 표기 = reflog의 N번째 항목
- stash drop시: reflog에서 해당 항목만 제거, 나머지 순서 재조정

**중요한 점**: 각 stash 커밋의 parent[0]은 모두 동일한 HEAD를 가리킴
→ stash들 사이에는 연결고리가 없음! 오직 reflog가 스택 순서를 관리

---

## 3. Stash가 만드는 특별한 커밋 구조 (WIP commit)

### 기본 구조 (2 parents)
```
git stash push 실행 후:

stash commit (WIP)
├── tree: working directory 상태
├── parent[0]: HEAD at stash time
└── parent[1]: index state commit
                ├── tree: staged 변경사항
                └── parent: HEAD at stash time
```

### 실험으로 확인한 실제 데이터
```bash
$ git cat-file -p refs/stash
tree e8c86e38...   ← working directory 전체 트리
parent 59b1d8c9... ← HEAD (stash 당시 커밋)
parent 077d6d8f... ← index state commit
author Test <test@test.com> 1771317389 +0900
committer Test <test@test.com> 1771317389 +0900

On master: WIP: feature work

$ git cat-file -p 077d6d8f  # index state
tree a05f42ad...   ← staged 파일들의 트리
parent 59b1d8c9... ← HEAD
author Test <test@test.com> 1771317389 +0900
committer Test <test@test.com> 1771317389 +0900

index on master: 59b1d8c Initial commit
```

### -u (--include-untracked) 옵션: 3 parents!
```bash
$ git stash push -u -m "With untracked"
$ git cat-file -p stash@{0}
tree 0571cb4f...
parent 86a87910... ← HEAD
parent 783a16f3... ← index state
parent cb424f38... ← untracked files commit (세 번째!)
author Test <test@test.com> 1771317447 +0900

On feature-branch: With untracked

$ git cat-file -p cb424f38  # untracked files commit
tree 4822b7ee...
(no parent!)  ← 부모 없음, 완전 독립 커밋
author Test <test@test.com> 1771317447 +0900

untracked files on feature-branch: 86a8791 Initial
```

### 구조 요약 다이어그램
```
일반 stash:
WIP commit → [HEAD, index_commit]
index_commit → [HEAD]

-u stash:
WIP commit → [HEAD, index_commit, untracked_commit]
index_commit → [HEAD]
untracked_commit → [] (부모 없음)
```

---

## 4. stash 명령어 분석

### stash push
1. HEAD 현재 상태 기억
2. index state 커밋 생성 (staged 변경사항 보존)
3. WIP 커밋 생성 (working directory 보존)  
4. stash@{0}으로 설정 (refs/stash 업데이트)
5. working directory & index를 HEAD 상태로 복원

### stash pop = apply + drop
- `git stash pop` = `git stash apply` + `git stash drop`
- apply: 3-way merge로 변경사항 재적용 (충돌 가능)
- drop: reflog에서 해당 항목 제거

### stash apply 내부
- 3-way merge 사용:
  - base: stash의 HEAD(^1) 트리
  - ours: 현재 HEAD 트리  
  - theirs: stash WIP 트리
- 충돌 시: stash 항목 유지됨 (안전장치)

```bash
# pop 충돌 시 메시지:
error: Your local changes to the following files would be overwritten by merge
The stash entry is kept in case you need it again.
```

### stash list
- 실제로는 `git log --oneline refs/stash` 같은 동작
- reflog 기반으로 순서 표시

---

## 5. stash와 worktree의 관계

### 핵심: stash는 전체 리포지토리 범위에서 공유됨

```bash
# main worktree에서 stash 생성
$ git stash push -m "Main stash"

# 다른 worktree에서도 동일하게 보임
$ cd /path/to/worktree
$ git stash list
stash@{0}: On master: Main stash  ← 보임!
```

**이유**: 모든 worktree는 동일한 `.git` 디렉토리(또는 `gitdir` 링크)를 공유
→ `.git/refs/stash`와 `.git/logs/refs/stash`가 공유됨

### 주의사항
- worktree A에서 stash push → worktree B에서도 stash list에 보임
- worktree B에서 stash pop → 다른 worktree에서도 사라짐
- 브랜치 잠금처럼 stash는 어느 worktree에 속하는지 구분 없음

---

## 6. Git stash 구현 역사

### 타임라인

**2007년 2월**: Shawn O. Pearce가 최초 구현
- 커밋: d5464c0 (git 공식 저장소)
- Git 1.5.3에서 정식 도입 (2007년 9월)
- 최초 구현은 **쉘 스크립트** (`git-stash.sh`)

**2007년 이전**: 공식 stash 없음
- `git diff`로 패치 파일 생성 후 수동 관리
- `git commit --no-commit` 등 우회 방법 사용

**2007년 이후 진화**:
- `git stash save` → deprecated (현재는 `git stash push` 권장)
- `--include-untracked` (-u) 옵션 추가
- `--all` (-a) 옵션 추가 (gitignore된 파일도 포함)
- `--patch` 옵션 (대화형 hunks 선택)
- 최종적으로 C 코드로 내장 (`builtin/stash.c`)

### 이름의 변화
- 원래: `git stash save "message"`
- 현재: `git stash push -m "message"` (save는 deprecated)
- 이유: push가 더 직관적이고 일관성 있음 (stash push → stash pop)

---

## 7. gc와 stash

### stash가 gc로 삭제되는 경우
- `git stash drop`으로 제거된 stash 커밋 → unreachable
- 30일 후 gc에 의해 정리

### stash 보존 방법
```bash
# 기본 설정 확인
git config gc.reflogExpire          # 기본: 90 days
git config gc.reflogExpireUnreachable # 기본: 30 days

# stash 영구 보존 (신중히!)
git config gc.refs/stash.reflogExpire never
```

### 중요한 설계 결정
`refs/stash`는 **reflog가 never expire**로 설정되지 않음 (기본값)
- stash list에 있는 항목 = referenced → gc가 지우지 않음
- stash drop된 항목 = unreachable → 30일 후 gc

---

## 8. 흥미로운 사실들

### 1. stash는 "진짜 커밋"이다
- `git log --all`에는 안 보이지만
- `git cat-file -p stash@{0}` 하면 완전한 커밋 객체
- object database에 존재하는 first-class 객체

### 2. stash의 index state 커밋은 "유령 커밋"
- 브랜치가 없음
- HEAD에 속하지 않음
- stash 커밋의 parent[1]로만 참조됨

### 3. stash pop은 merge다
- 단순 파일 복사가 아님
- 3-way merge 알고리즘 사용
- 그래서 충돌이 발생할 수 있음

### 4. stash 스택은 reflog다
- `stash@{0}`, `stash@{1}` 표기법이 reflog와 동일
- reflog가 곧 스택 자체
- 이 덕분에 stash 항목도 "날짜로" 조회 가능: `stash@{2.weeks.ago}`

### 5. 원래 `git stash`는 쉘 스크립트였다
- 2007년 Shawn O. Pearce가 처음 쓸 때는 `.sh` 파일
- 나중에 C로 내장 (`builtin/stash.c`)
- 이런 점에서 git은 "쉘 스크립트의 집합"에서 시작한 프로젝트

---

## 9. 실험 요약 (실제 데이터)

```bash
# 테스트 환경
git init stash-test
echo "base" > base.txt && git add . && git commit -m "Initial"

# staged + unstaged 상태 만들기
echo "Modified" >> base.txt          # unstaged
echo "staged" > staged.txt && git add staged.txt  # staged

# stash push
git stash push -m "WIP: my work"

# 구조 확인
cat .git/refs/stash
# → e8c86e38... (stash@{0} SHA)

git cat-file -p refs/stash
# → tree + parent x2 + "On master: WIP: my work"
```

---

## 10. 톤 & 다이어그램 계획

### 다이어그램 1: stash 커밋 구조 (Mermaid)
```
HEAD → commit_A
stash@{0} [WIP] 
  ├── parent: commit_A (HEAD)
  └── parent: index_commit
               └── parent: commit_A
```

### 다이어그램 2: stash 스택 = reflog 구조
```
.git/refs/stash → stash@{0} SHA
.git/logs/refs/stash:
  0000 → SHA_A  (Stash A)
  SHA_A → SHA_B (Stash B)
  SHA_B → SHA_C (Stash C = stash@{0})
```

### 다이어그램 3: stash pop = apply + drop 흐름

### 메타포 아이디어
- stash = "책상 서랍에 노트 넣기"
- stash@{0} = "가장 위 서랍"
- stash list = "서랍 목차"
- stash는 서랍이 전 직원 공용 (worktree 공유)

---

## 마무리 체크리스트

- [x] stash 개념 및 내부 구조 분석
- [x] .git/refs/stash 실험으로 확인
- [x] WIP 커밋 구조 (2-parent, 3-parent) 확인
- [x] stash 스택 = reflog 구조 확인
- [x] stash push/pop/apply/drop/list 분석
- [x] stash와 worktree 관계 실험
- [x] 역사: Shawn O. Pearce, 2007, 쉘 스크립트 → C
- [x] 흥미로운 사실들 정리
- [x] 다이어그램 계획 완료
