---
title: "Git 해체분석기 #18: Cherry-pick - 커밋 하나만 골라담기"
date: 2026-02-17T18:00:00+09:00
draft: false
tags: ["git", "해체분석기", "cherry-pick", "rebase"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 18
weight: -18
mermaid: true
toc: true
---

> "Merge는 브랜치 전체를 데려온다. Cherry-pick은 원하는 것만 고른다."

## 들어가며

팀에서 이런 상황을 겪어본 적 있을 것입니다.

```
main 브랜치에서 치명적 버그 발견.
이미 패치를 만들어서 main에 올렸는데...
release/v1.x 브랜치에도 같은 버그가 있다!
```

`release/v1.x`를 `main`에 merge? 그러면 아직 검증 안 된 신기능이 함께 딸려온다.  
새로 패치를 작성? 귀찮고 실수할 가능성도 있다.

이럴 때 쓰는 것이 **Cherry-pick**이다.

```bash
git checkout release/v1.x
git cherry-pick -x abc1234  # main의 패치 커밋 딱 하나만
```

끝이다. **원하는 커밋만 골라서 다른 브랜치에 이식한다.**

---

## 1. Cherry-pick이란?

Cherry-pick은 특정 커밋의 변경사항을 현재 브랜치에 **새 커밋으로 복사**한다.

```
Before:
A---B (main) ← HEAD
 \
  C---D---E (feature)
      ↑
  이것만 가져오고 싶다

git cherry-pick D

After:
A---B---D' (main)
 \
  C---D---E (feature)
```

D'와 D는 **내용은 같지만 완전히 다른 커밋**이다. 부모가 B이기 때문에 hash가 달라진다.

<pre class="mermaid">
%%{init: {'theme':'base'}}%%
gitGraph
    commit id: "A"
    commit id: "B"
    branch feature
    commit id: "C"
    commit id: "D"
    commit id: "E"
    checkout main
    commit id: "D' (cherry-pick)"
</pre>

### Merge, Rebase와 뭐가 다른가?

| | Cherry-pick | Merge | Rebase |
|---|---|---|---|
| 단위 | 커밋 하나 | 브랜치 전체 | 커밋 시퀀스 |
| 원본 커밋 | 그대로 남음 | 그대로 남음 | 사라짐 |
| 히스토리 | 새 커밋 추가 | merge commit | 커밋 재작성 |
| 용도 | 골라서 가져오기 | 통합 | 정리/선형화 |

그리고 흥미로운 사실: **Rebase는 내부적으로 Cherry-pick의 반복이다.**

```c
// builtin/rebase.c
static int run_sequencer_rebase(struct rebase_options *opts) {
    replay.action = REPLAY_PICK;  // ← cherry-pick 모드!
    return sequencer_continue(&replay);
}
```

Rebase = "각 커밋을 새 base 위에 cherry-pick".

---

## 2. 내부 동작: patch가 아니라 Three-way Merge다

이게 오늘 가장 중요한 부분이다.

많은 사람이 cherry-pick을 이렇게 상상한다:

```bash
git show <commit> > patch.diff
git apply patch.diff
```

**틀렸다.** 이렇게 구현하면 코드가 살짝 달라진 경우 그냥 실패한다.

```bash
$ git show 10e96e46 --patch > out.patch
$ git apply out.patch
error: patch failed: content/post/auth.py:17
error: patch does not apply
```

Cherry-pick은 **Three-way Merge**를 사용한다.

### Three-way Merge 원리

Git은 세 개의 버전을 비교한다:

```
복사할 커밋 그래프:
... X --- Y (Y를 cherry-pick)
    ↑     ↑
   BASE  THEIRS

현재 브랜치:
... A --- B (HEAD)
          ↑
         OURS

three-way merge(OURS=B, BASE=X, THEIRS=Y)
```

- **BASE**: 복사할 커밋(Y)의 **부모**(X). "Y 이전 상태"
- **OURS**: 현재 브랜치 HEAD(B)
- **THEIRS**: 복사할 커밋(Y). "X에서 이 변경을 가함"

### 의사결정 테이블

| BASE | OURS | THEIRS | 결과 |
|------|------|--------|------|
| `x=1` | `x=1` | `x=3` | `x=3` ✅ (패치 적용) |
| `x=1` | `x=2` | `x=1` | `x=2` ✅ (내 변경 유지) |
| `x=1` | `x=2` | `x=3` | **CONFLICT** ❌ |

BASE, OURS, THEIRS **세 버전을 다 아는 덕분에** "누가 뭘 바꿨는지"를 추론할 수 있다.

단순 patch는 OURS만 알고 diff만 안다. 그래서 컨텍스트가 조금 달라지면 적용 실패.

### 소스코드 확인

Git 소스 `sequencer.c`의 핵심:

```c
// do_pick_commit() 함수
res = do_recursive_merge(r,
    base,        // X: 복사할 커밋의 부모
    next,        // Y: 복사할 커밋
    base_label,
    next_label,
    &head,       // B: 현재 HEAD
    &msgbuf,
    opts);
```

`do_recursive_merge()` = Git의 표준 three-way merge 엔진.  
Cherry-pick은 이걸 "한 커밋짜리 merge"로 쓰는 것이다.

---

## 3. Conflict가 나면?

### 충돌 시나리오

인증 모듈에서 충돌이 났다고 하자.

**BASE** (hotfix 커밋의 부모):
```python
def authenticate(user, password):
    return check_db(user, password)
```

**OURS** (main이 이미 수정해놓은 상태):
```python
def authenticate(user, password, mfa_token=None):
    if not check_db(user, password):
        return False
    return True
```

**THEIRS** (가져오려는 hotfix):
```python
def authenticate(user, password):
    log_attempt(user)  # ← 이 변경만 가져오고 싶다
    return check_db(user, password)
```

같은 함수 시그니처를 OURS와 THEIRS가 다르게 바꿨다 → **CONFLICT!**

```bash
$ git cherry-pick cf672dc
Auto-merging server.py
CONFLICT (content): Merge conflict in server.py
error: could not apply cf672dc... fix: add audit logging to auth
hint: After resolving the conflicts, mark them with
hint: "git add/rm <pathspec>", then run
hint: "git cherry-pick --continue".
```

### 충돌 중 Git의 상태

```
.git/
├── CHERRY_PICK_HEAD   # cf672dc... (진행 중인 커밋)
├── MERGE_MSG          # 커밋 메시지 후보
└── index              # 3개 버전 모두 저장됨 (stage 1/2/3)
```

`CHERRY_PICK_HEAD`가 존재하는 동안은 cherry-pick 진행 중.

### 충돌 파일

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

### 해결 절차

```bash
# 1. 충돌 파일 수정 (원하는 최종 코드 작성)
vim server.py
# → MFA + audit logging 둘 다 포함하도록

# 2. 해결 완료 표시
git add server.py

# 3. cherry-pick 완료
git cherry-pick --continue

# --- 대안들 ---
git cherry-pick --skip    # 이 커밋 건너뛰기
git cherry-pick --abort   # 전체 취소 (원래 상태로)
```

---

## 4. -x 옵션: 출처를 남겨라

### 왜 필요한가?

cherry-pick한 커밋은 새 hash를 갖는다. 나중에 히스토리를 보면:

```
release/v1.x:
* 3f4a5b6 fix: CVE-2026-1234 security vulnerability
* ...
```

"이게 main에서 backport한 건지, 여기서 직접 만든 건지" 알 수가 없다.

### -x 옵션 사용

```bash
git cherry-pick -x abc1234
```

생성된 커밋 메시지:

```
fix: CVE-2026-1234 security vulnerability

(cherry picked from commit abc1234abcdefgh1234567890abcdef123456789)
```

한 줄이 자동으로 추가된다.

이제 히스토리를 보면 출처가 명확하다:

```bash
$ git log --oneline release/v1.x
3f4a5b6 fix: CVE-2026-1234 security vulnerability
# git show 3f4a5b6 에서 "(cherry picked from commit abc1234...)" 확인 가능
```

**Backport 작업에서는 `-x`를 습관적으로 쓰자.**

단, 충돌이 나서 수동으로 수정한 경우는 원본과 완전히 같지 않을 수 있으므로 **자동으로 추가되지 않는다.**

---

## 5. 실전 활용 패턴

### 5.1 Hotfix Backport (가장 흔한 케이스)

```
main:        A---B---C---[fix]---D
                         ↑
              release/v1.x에도 필요!

release/v1.x: E---F---G
```

```bash
# 1. fix 커밋 hash 찾기
git log main --oneline --grep="CVE-2026"
# → abc1234 fix: CVE-2026-1234 security vulnerability

# 2. backport
git checkout release/v1.x
git cherry-pick -x abc1234

# 3. push
git push origin release/v1.x
```

**결과:**
```
release/v1.x: E---F---G---[fix']
```

### 5.2 잘못된 브랜치에 커밋한 경우

```bash
# main에 실수로 feature 코드를 커밋함
git log --oneline
# abc1234 feat: new search feature  ← 이거 feature 브랜치로 가야 함!

# feature 브랜치에서 cherry-pick
git checkout feature
git cherry-pick abc1234

# main에서 실수 커밋 제거
git checkout main
git reset --hard HEAD~1
```

### 5.3 여러 커밋 범위 지정

```bash
# A 미포함, B 포함 (A..B)
git cherry-pick abc123..def456

# A 포함, B 포함 (A^..B)
git cherry-pick abc123^..def456

# 비연속 커밋
git cherry-pick abc123 def456 ghi789
```

### 5.4 Staged만 하고 커밋은 나중에 (-n)

여러 cherry-pick을 하나의 커밋으로 합치고 싶을 때:

```bash
git cherry-pick -n abc123
git cherry-pick -n def456
git cherry-pick -n ghi789

# 세 커밋의 변경사항이 모두 staged됨
git commit -m "Consolidated fixes from release/v1.x"
```

### 5.5 Merge commit cherry-pick (-m)

```bash
# merge commit을 cherry-pick할 때
git cherry-pick -m 1 <merge-commit-hash>
# -m 1: 첫 번째 부모(보통 main)를 기준으로 diff 계산
```

---

## 6. Cherry-pick과 Revert: 쌍둥이 구현

재밌는 사실: `cherry-pick`과 `revert`는 **같은 파일에 구현되어 있다.**

```
builtin/revert.c
├── git cherry-pick  (REPLAY_PICK)
└── git revert       (REPLAY_REVERT)
```

원리가 같기 때문이다:

```
cherry-pick Y:
  BASE = X (Y의 부모)
  THEIRS = Y
  → "X→Y 변경을 현재에 적용"

revert Y:
  BASE = Y
  THEIRS = X (Y의 부모)
  → "X→Y 변경을 현재에 역적용"
```

방향만 반대인 Three-way merge. **같은 엔진, 다른 방향.**

---

## 마무리

### Cherry-pick의 본질

1. **골라담기**: 브랜치 전체가 아닌 커밋 단위로 이식
2. **새 커밋 생성**: 내용은 같아도 hash가 다름 (부모가 다름)
3. **Three-way Merge**: 단순 patch가 아닌 지능적 병합
4. **충돌 해결 가능**: patch apply와 달리 충돌 정보를 제공
5. **Rebase의 기반**: Rebase = cherry-pick × n

### 언제 써야 하나

| 상황 | 권장 |
|------|------|
| hotfix backport | ✅ cherry-pick -x |
| 잘못된 브랜치 커밋 이동 | ✅ cherry-pick |
| 기능 브랜치 전체 통합 | ❌ merge 사용 |
| 특정 커밋만 필요 | ✅ cherry-pick |
| 선형 히스토리 원할 때 | ❌ rebase 사용 |

### 기억할 것

> **Cherry-pick은 "복사"가 아니라 "이식"이다.**
> 
> 패치를 기계적으로 붙이는 게 아니라,  
> 원본의 의도를 이해하고 새로운 컨텍스트에 녹여낸다.  
> 
> 그래서 충돌이 생겨도 포기하지 않고 대화를 걸어온다.

---

## 참고 자료

- [Git 공식 문서: git-cherry-pick](https://git-scm.com/docs/git-cherry-pick)
- [Git 소스코드: sequencer.c](https://github.com/git/git/blob/master/sequencer.c)
- [Julia Evans: How cherry-pick and revert use 3-way merge](https://jvns.ca/blog/2023/11/10/how-cherry-pick-and-revert-work/)
- [Atlassian: git cherry-pick](https://www.atlassian.com/git/tutorials/cherry-pick)
