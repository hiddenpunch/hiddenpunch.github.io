# Git Cherry-pick 리서치 노트

## 목표
Git 해체분석기 #13: "Cherry-pick - 커밋 하나만 골라담기"

---

## 1. Cherry-pick이란 무엇인가

### 정의
- 다른 브랜치(또는 같은 브랜치)에 있는 **특정 커밋 하나(혹은 여러 개)의 변경사항**을 현재 브랜치에 적용
- 브랜치 전체를 merge하는 게 아니라 **원하는 커밋만 쏙 뽑아** 새 커밋으로 만든다
- 새 커밋이 생기므로 **hash가 다르다** (내용은 같아도 부모가 다르기 때문)

### 기본 사용법
```bash
git cherry-pick <commit-hash>          # 단일 커밋
git cherry-pick <hash1> <hash2>        # 여러 커밋 (비연속)
git cherry-pick <hash1>^..<hash2>      # 범위 (hash1 포함)
git cherry-pick <hash1>..<hash2>       # 범위 (hash1 미포함)
```

### 커밋 그래프
```
Before:
A---B (main)
 \
  C---D---E (feature)

git cherry-pick D  (on main)

After:
A---B---D' (main)
 \
  C---D---E (feature)
```
D'는 D와 내용이 같지만 부모가 B이므로 완전히 다른 커밋.

---

## 2. Cherry-pick vs Merge vs Rebase

### 비교표

| 특성 | Cherry-pick | Merge | Rebase |
|------|------------|-------|--------|
| 대상 | 커밋 하나 | 브랜치 전체 | 커밋 시퀀스 |
| 히스토리 | 새 커밋 생성 | merge commit 생성 | 커밋 재작성 |
| 원본 유지 | 원본 그대로 | 원본 그대로 | 원본 사라짐 |
| hash 변경 | O (새 hash) | 부분적 | O (전부 새 hash) |
| 관계 | 독립 | 연결됨 | 선형화 |

### 언제 쓰나?
- **Cherry-pick**: hotfix를 특정 브랜치에만 backport, 실수로 잘못된 브랜치에 커밋한 것 옮기기
- **Merge**: 브랜치 전체 통합 (PR merge)
- **Rebase**: 로컬 브랜치 히스토리 정리, main 최신화

### Rebase와의 관계
**Rebase는 내부적으로 Cherry-pick의 연속이다!**
```c
// builtin/rebase.c
static int run_sequencer_rebase(struct rebase_options *opts) {
    replay.action = REPLAY_PICK;  // cherry-pick 모드
    return sequencer_continue(&replay);
}
```

---

## 3. 내부 동작 원리 - Three-way Merge

### 핵심 오해: "패치를 적용한다"가 아니다

많은 사람들이 cherry-pick을 이렇게 생각:
```
git show <commit> > patch.diff
git apply patch.diff
```

**하지만 이건 틀렸다!** `git apply`는 컨텍스트가 맞지 않으면 그냥 실패.
Cherry-pick은 **Three-way Merge**를 사용한다.

### Three-way Merge 원리

3개의 파일 버전을 비교:
- **BASE**: 복사할 커밋의 부모 (변경 이전 상태)
- **OURS**: 현재 브랜치 HEAD (내 버전)
- **THEIRS**: 복사할 커밋 (변경 후 상태)

```
커밋 그래프:
A---B (main, HEAD = OURS)
 \
  X---Y (Y를 cherry-pick할 것)
  ↑
 BASE      THEIRS = Y

Three-way merge: merge(OURS=B, BASE=X, THEIRS=Y)
```

### 의사결정 로직

| BASE | OURS | THEIRS | 결과 |
|------|------|--------|------|
| 동일 | 동일 | 동일 | 그대로 |
| 동일 | 변경됨 | 동일 | OURS 채택 |
| 동일 | 동일 | 변경됨 | THEIRS 채택 (패치 적용) |
| 동일 | 변경됨 | 변경됨 | **CONFLICT** |

### 소스코드 레퍼런스 (sequencer.c)

```c
// https://github.com/git/git/blob/master/sequencer.c
// do_pick_commit() 함수 핵심 부분

res = do_recursive_merge(r,
    base,        // 원본 커밋의 부모
    next,        // 원본 커밋 (THEIRS)
    base_label,
    next_label,
    &head,       // 현재 HEAD (OURS)
    &msgbuf,
    opts);
```

**Cherry-pick = `do_recursive_merge()` = Three-way merge**

### git apply와의 차이

```bash
# 단순 patch 적용 (컨텍스트 불일치 시 실패)
git show abc1234 > out.patch
git apply out.patch
# → error: patch failed: file.txt:17

# cherry-pick (three-way merge, 충돌 해결 가능)
git cherry-pick abc1234
# → CONFLICT 마커와 함께 충돌 해결 옵션 제공
```

### 왜 Three-way가 더 강력한가?

일반 patch는 컨텍스트(주변 줄)가 맞지 않으면 실패.
Three-way merge는 파일 **전체**를 기준으로 비교하므로:
- 주변 코드가 바뀌어도 의도한 변경을 추적
- 충돌 시 마커로 표시하고 해결 가능

---

## 4. Cherry-pick Conflict 해결

### 충돌 시나리오

```
BASE (X): authenticate(user, password)
OURS (main에서 변경): authenticate(user, password, mfa_token=None)
THEIRS (hotfix): authenticate(user, password) + log_attempt()
```

OURS와 THEIRS가 같은 줄을 다르게 수정 → CONFLICT

### 실제 충돌 마커

```python
<<<<<<< HEAD
def authenticate(user, password, mfa_token=None):
    if not check_db(user, password):
        return False
    return True
=======
def authenticate(user, password):
    log_attempt(user)
    return check_db(user, password)
>>>>>>> cf672dc (fix: add audit logging to auth)
```

### .git/ 상태 (충돌 중)

```
.git/
├── CHERRY_PICK_HEAD    # cherry-pick 중인 커밋 hash
├── MERGE_MSG           # 커밋 메시지 후보
└── index               # 충돌 마커 포함 3가지 버전 저장
```

CHERRY_PICK_HEAD에 현재 apply 중인 커밋 hash가 저장됨.

### 해결 절차

```bash
# 1. 충돌 확인
git status
# both modified: server.py

# 2. 파일 수정 (충돌 마커 제거, 원하는 코드 작성)
vim server.py

# 3. 해결 완료 표시
git add server.py

# 4. 계속 진행
git cherry-pick --continue

# 또는 이 커밋 건너뛰기
git cherry-pick --skip

# 또는 전체 취소
git cherry-pick --abort
```

---

## 5. -x 옵션과 원본 추적

### -x 옵션이 하는 일

cherry-pick한 커밋의 **원본 추적 정보**를 커밋 메시지에 자동 첨부.

```bash
git cherry-pick -x abc1234
```

생성되는 커밋 메시지:
```
fix: critical security patch

(cherry picked from commit abc1234abcdefgh1234567890abcdef123456789)
```

### 왜 필요한가?

나중에 히스토리를 볼 때:
- 이 커밋이 어디서 왔는지 추적 가능
- 중복 cherry-pick 방지
- Backport 작업 추적에 필수

### 주의사항

`-x`는 **충돌 없이 clean하게 적용된 경우에만** 메시지를 추가.
충돌이 나서 수동으로 해결한 경우는 원본과 다를 수 있으므로 자동 추가 안 함.

### 관련 옵션들

```bash
git cherry-pick -e <hash>     # 커밋 메시지 편집
git cherry-pick -n <hash>     # 커밋 안 하고 staged만 (--no-commit)
git cherry-pick -s <hash>     # Signed-off-by 추가
git cherry-pick -m 1 <hash>   # merge commit cherry-pick시 mainline 지정
```

---

## 6. 실전 활용

### 6.1 Hotfix Backport (가장 흔한 케이스)

```
main (v2.0):  A---B---C---[fix]---D
                         ↑
              이 fix를 v1.x에도 적용!

release/v1.x: E---F---G
```

```bash
# fix 커밋 hash 확인
git log main --oneline | grep "fix"
# → abc1234 fix: CVE-2026-1234 security vulnerability

# v1.x에 backport
git checkout release/v1.x
git cherry-pick -x abc1234
```

결과:
```
release/v1.x: E---F---G---[fix']
```

### 6.2 잘못된 브랜치에 커밋한 경우

```bash
# main에 실수로 커밋함
git log --oneline
# abc1234 feat: new feature  ← 이걸 feature 브랜치로 옮겨야 해!

# feature 브랜치에서 cherry-pick
git checkout feature
git cherry-pick abc1234

# main에서 실수 커밋 제거
git checkout main
git reset --hard HEAD~1
```

### 6.3 여러 커밋 한 번에 (범위)

```bash
# A..B 범위 (A 미포함, B 포함)
git cherry-pick abc123..def456

# A..B 범위 (A 포함)
git cherry-pick abc123^..def456
```

### 6.4 No-commit 모드 (-n)

여러 커밋의 변경사항을 하나의 커밋으로 합치고 싶을 때:

```bash
git cherry-pick -n abc123
git cherry-pick -n def456
git cherry-pick -n ghi789
git commit -m "Consolidated fixes from release branch"
```

### 6.5 Merge commit cherry-pick (-m)

```bash
# merge commit에서 특정 parent 기준으로 diff 계산
git cherry-pick -m 1 <merge-commit-hash>
# -m 1: 첫 번째 부모(main) 기준
# -m 2: 두 번째 부모(feature) 기준
```

---

## 7. Cherry-pick과 Revert의 관계

**Revert는 Cherry-pick의 역방향**

```c
// builtin/revert.c
// cherry-pick과 revert는 같은 파일에 구현됨!

// cherry-pick: BASE=X(부모), THEIRS=Y(커밋)
// revert:      BASE=Y(커밋), THEIRS=X(부모)  ← 반전!
```

```bash
# cherry-pick: Y의 변경사항 적용
git cherry-pick Y

# revert: Y의 변경사항 되돌리기
git revert Y
```

같은 Three-way merge 엔진, 방향만 반대.

---

## 주요 인사이트

1. **Cherry-pick ≠ patch apply**: Three-way merge를 사용
2. **새 커밋 생성**: 내용 같아도 hash 다름 (부모 다름)
3. **Rebase의 기반**: Rebase는 cherry-pick의 자동 반복
4. **-x 옵션**: backport 추적에 필수
5. **충돌 해결 가능**: 단순 patch와 달리 충돌 정보 제공
6. **Revert와 쌍둥이**: 같은 엔진, 반대 방향

---

## 다이어그램 아이디어

1. Cherry-pick 전후 커밋 그래프 (before/after)
2. Three-way merge 원리 (BASE/OURS/THEIRS)
3. Cherry-pick vs Merge vs Rebase 비교
4. Hotfix backport 시나리오
5. 충돌 해결 플로우

---

## 참고 자료

- Git 공식 문서: https://git-scm.com/docs/git-cherry-pick
- Julia Evans 블로그: https://jvns.ca/blog/2023/11/10/how-cherry-pick-and-revert-work/
- Git 소스코드 (sequencer.c): https://github.com/git/git/blob/master/sequencer.c
- Git 소스코드 (revert.c): https://github.com/git/git/blob/master/builtin/revert.c
