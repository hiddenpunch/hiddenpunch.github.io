---
title: "Git 해체분석기 #17: Rebase의 비밀 - 히스토리는 어떻게 재작성되나"
date: 2026-02-17T09:00:00+09:00
draft: false
tags: ["git", "해체분석기", "rebase", "cherry-pick"]
series: ["Git 해체분석기"]
series_order: 17
weight: -17
mermaid: true
toc: true
---

> "Rebase는 마법이 아니다. 그저 cherry-pick의 반복일 뿐이다."

## 들어가며

Git을 쓰다 보면 이런 경고를 본다:

```
$ git push
To github.com:user/repo.git
 ! [rejected]        feature -> feature (non-fast-forward)
error: failed to push some refs
hint: Updates were rejected because the tip of your current branch is behind
hint: its remote counterpart. Merge the remote changes (e.g. 'git pull')
hint: before pushing again.
```

그래서 `git pull`을 했더니 merge commit이 생겼다.

```
*   a1b2c3d Merge branch 'feature' of github.com:user/repo
|\
| * d4e5f6g Fix typo
* | g7h8i9j Add new feature
|/
```

**아, 히스토리가 지저분하다.**

동료가 말한다: "Rebase 쓰면 깔끔해져요."

```bash
git pull --rebase
```

어, 됐다. Merge commit 없이 선형으로!

```
* g7h8i9j Add new feature
* d4e5f6g Fix typo
```

**근데 이게 어떻게 된 거지?**

오늘은 Rebase의 내부를 열어본다.

---

## 1. Merge vs Rebase: 근본적 차이

### 1.1 Merge의 방식

Merge는 **두 히스토리를 보존하며 합친다**.

```
Before merge:
      A---B---C (feature)
     /
D---E---F (main)

After git merge feature:
      A---B---C (feature)
     /         \
D---E---F-------M (main)
            ↑
        merge commit
```

<pre class="mermaid">
%%{init: {'theme':'base'}}%%
gitGraph
    commit id: "D"
    commit id: "E"
    branch feature
    checkout feature
    commit id: "A"
    commit id: "B"
    commit id: "C"
    checkout main
    commit id: "F"
    merge feature tag: "M"
</pre>

새로운 커밋 M이 생긴다. 두 부모를 가진 **merge commit**이다.

### 1.2 Rebase의 방식

Rebase는 **히스토리를 재작성한다**.

```
Before rebase:
      A---B---C (feature)
     /
D---E---F (main)

After git rebase main:
D---E---F (main)
         \
          A'---B'---C' (feature)
```

<pre class="mermaid">
%%{init: {'theme':'base'}}%%
gitGraph
    commit id: "D"
    commit id: "E"
    commit id: "F"
    branch feature
    commit id: "A'"
    commit id: "B'"
    commit id: "C'"
</pre>

커밋 A, B, C가 **복사**되어 A', B', C'로 만들어진다.

**주목**: 프라임(') 표시가 중요하다. 같은 내용이지만 **완전히 다른 커밋**이다.

```bash
$ git log --oneline
c'3c'3c' (feature) Add tests
b'2b'2b' Fix bug
a'1a'1a' Add feature
f6f6f6f (main) Update README

# A, B, C의 hash는?
# → 사라졌다. A', B', C'가 생긴 것이다.
```

### 1.3 Hash가 바뀐다는 것

Git에서 커밋 hash는 이렇게 계산된다:

```
SHA1(
  tree hash +
  parent hash +
  author + timestamp +
  committer + timestamp +
  message
)
```

Rebase는 **parent를 바꾼다**. 따라서 hash가 완전히 달라진다.

```
Before:
A (parent: E)  → hash: abc123...
B (parent: A)  → hash: def456...
C (parent: B)  → hash: ghi789...

After rebase onto F:
A' (parent: F)  → hash: xyz111...  ← 바뀌었다!
B' (parent: A') → hash: xyz222...
C' (parent: B') → hash: xyz333...
```

**이게 "히스토리 재작성"의 본질이다.**

---

## 2. Rebase는 Cherry-pick의 연속이다

### 2.1 Cherry-pick이란?

Cherry-pick은 **다른 브랜치의 커밋 하나를 복사**한다.

```bash
$ git checkout main
$ git cherry-pick abc123  # feature 브랜치의 커밋 하나
```

```
Before:
      A (abc123)
     /
D---E---F (main) ← HEAD

After cherry-pick:
      A (abc123)
     /
D---E---F---A' (xyz111) (main) ← HEAD
```

**A'는 A의 변경사항을 가진 새 커밋**이다. 부모가 F로 바뀌었다.

### 2.2 Rebase = 자동 Cherry-pick

Rebase를 실행하면 Git은 내부적으로 이렇게 동작한다:

```bash
# git rebase main의 내부 (의사코드)

# 1. 공통 조상 찾기
BASE=$(git merge-base HEAD main)  # E

# 2. 재작성할 커밋 목록
COMMITS=$(git rev-list $BASE..HEAD)  # A, B, C

# 3. 새 base로 reset
git reset --hard main  # HEAD → F

# 4. 순차적으로 cherry-pick
for commit in $COMMITS; do
    git cherry-pick $commit
done

# 결과: F---A'---B'---C'
```

**Rebase는 복잡한 마법이 아니다. Cherry-pick을 반복할 뿐이다.**

### 2.3 실제 소스코드 확인

Git 소스 `builtin/rebase.c`:

```c
// rebase 메인 로직 (간략화)
static int run_sequencer_rebase(struct rebase_options *opts) {
    struct replay_opts replay = REPLAY_OPTS_INIT;
    
    // Cherry-pick 시퀀스 준비
    replay.action = REPLAY_PICK;
    
    // 커밋 목록 순회하며 적용
    return sequencer_continue(&replay);
}
```

`sequencer.c`가 실제 cherry-pick을 수행한다:

```c
// Cherry-pick 구현 핵심
static int do_pick_commit(struct commit *commit) {
    // Three-way merge로 패치 적용
    res = do_recursive_merge(base, next, base_label, next_label, ...);
    
    if (res < 0) {
        // 충돌 발생
        return error(_("could not apply %s... %s"),
                     short_commit_name(commit), msg);
    }
    
    // 새 커밋 생성
    return write_commit_message(commit);
}
```

**핵심**: `do_recursive_merge` - 이게 cherry-pick의 본체다.

---

## 3. Conflict가 나면?

### 3.1 Three-way Merge

Cherry-pick(= rebase)은 **three-way merge**를 사용한다.

```
공통 조상 (BASE):
  x = 1

원본 (OURS):
  x = 2

적용할 커밋 (THEIRS):
  x = 3
```

Three-way merge 알고리즘:

| BASE | OURS | THEIRS | 결과 |
|------|------|--------|------|
| 1 | 1 | 1 | 1 (변화 없음) |
| 1 | 2 | 1 | 2 (OURS만 변경) |
| 1 | 1 | 3 | 3 (THEIRS만 변경) |
| 1 | 2 | 3 | **CONFLICT!** (둘 다 변경) |

마지막 케이스가 **충돌**이다.

### 3.2 Rebase 중 충돌

```bash
$ git rebase main
Applying: Add feature
error: Failed to merge in the changes.
hint: Use 'git am --show-current-patch' to see the failed patch
Resolve all conflicts manually, mark them as resolved with
"git add/rm <conflicted_files>", then run "git rebase --continue".
You can instead skip this commit: run "git rebase --skip".
To abort and get back to the state before "git rebase", run "git rebase --abort".
Could not apply a1b2c3d... Add feature
```

이 순간, Git의 상태:

```
.git/rebase-merge/
├── git-rebase-todo      # 남은 커밋 목록
├── stopped-sha          # 충돌 난 커밋 hash
├── author-script        # 작성자 정보
└── message              # 커밋 메시지
```

**Rebase가 중단되고 수동 해결을 기다린다.**

```bash
# 1. 충돌 파일 확인
$ git status
both modified:   file.txt

# 2. 수동 수정 후
$ git add file.txt

# 3. 계속 진행
$ git rebase --continue
```

이러면 다음 커밋(B)의 cherry-pick이 시작된다.

---

## 4. Interactive Rebase: 히스토리 편집

### 4.1 기본 사용법

```bash
$ git rebase -i HEAD~3
```

에디터가 열린다:

```
pick a1b2c3d Add feature
pick d4e5f6g Fix typo
pick g7h8i9j Update tests

# Rebase f0f0f0f..g7h8i9j onto f0f0f0f (3 commands)
#
# Commands:
# p, pick <commit> = use commit
# r, reword <commit> = use commit, but edit the commit message
# e, edit <commit> = use commit, but stop for amending
# s, squash <commit> = use commit, but meld into previous commit
# f, fixup <commit> = like "squash", but discard this commit's log message
# d, drop <commit> = remove commit
```

### 4.2 Squash: 커밋 합치기

```
Before:
* g7h8i9j Update tests
* d4e5f6g Fix typo
* a1b2c3d Add feature
```

Todo 수정:

```
pick a1b2c3d Add feature
squash d4e5f6g Fix typo
squash g7h8i9j Update tests
```

저장하면 Git이 메시지 편집기를 연다:

```
# This is a combination of 3 commits.
# This is the 1st commit message:

Add feature

# This is the commit message #2:

Fix typo

# This is the commit message #3:

Update tests
```

수정 후 저장:

```
Add feature with tests

- Implemented core logic
- Fixed typos
- Added comprehensive tests
```

결과:

```
After:
* xyz1234 Add feature with tests
```

**3개가 1개로!**

### 4.3 Fixup: 메시지 버리고 합치기

Squash와 비슷하지만 메시지 편집 없이 **첫 번째 메시지만 유지**한다.

```
pick a1b2c3d Add feature
fixup d4e5f6g Fix typo        ← 메시지 버림
fixup g7h8i9j Fix another typo ← 메시지 버림
```

결과:

```
* xyz1234 Add feature  ← 이 메시지만 남음
```

**WIP 커밋 정리할 때 유용하다.**

### 4.4 Reword: 메시지만 수정

```
reword a1b2c3d Add feature
pick d4e5f6g Fix typo
```

커밋 내용은 그대로, **메시지만 수정**한다.

### 4.5 Edit: 커밋 수정

```
edit a1b2c3d Add feature
pick d4e5f6g Fix typo
```

해당 커밋에서 **일시정지**한다.

```bash
Stopped at a1b2c3d...  Add feature
You can amend the commit now, with

  git commit --amend

Once you are satisfied with your changes, run

  git rebase --continue
```

이 상태에서 할 수 있는 일:

```bash
# 파일 수정
$ vim file.txt
$ git add file.txt
$ git commit --amend

# 또는 커밋 분리
$ git reset HEAD^
$ git add -p  # 부분 스테이징
$ git commit -m "Part 1"
$ git add -p
$ git commit -m "Part 2"

# 계속
$ git rebase --continue
```

**한 커밋을 여러 개로 쪼갤 수 있다.**

### 4.6 Drop: 커밋 제거

```
pick a1b2c3d Add feature
drop d4e5f6g Temporary debug code
pick g7h8i9j Update tests
```

또는 **그냥 줄을 삭제**해도 된다:

```
pick a1b2c3d Add feature
# d4e5f6g 줄을 지움
pick g7h8i9j Update tests
```

**히스토리에서 완전히 사라진다.**

---

## 5. Rebase --onto: 외과수술

### 5.1 기본 형태

```bash
git rebase --onto <newbase> <upstream> <branch>
```

**의미**: `<upstream>` 이후의 `<branch>` 커밋들을 `<newbase>` 위로 옮긴다.

### 5.2 케이스 1: 중간 커밋 버리기

```
Before:
A---B---C---D---E (feature)
```

C, D만 필요 없다면?

```bash
git rebase --onto B D feature
```

```
After:
A---B---E' (feature)
```

**C와 D가 사라졌다.**

### 5.3 케이스 2: 브랜치 기준 변경

```
Before:
      o---o---o (topic)
     /
o---o---o---o---o (next)
               /
o---o---o---o---o (master)
```

`topic`이 `next`에서 분기했는데, 사실 `master`에서 분기했어야 했다면?

```bash
git rebase --onto master next topic
```

```
After:
o---o---o---o---o (master)
 \
  o'--o'--o' (topic)
  
o---o---o---o---o (next)
```

**`next`에서 분기 → `master`에서 분기로 변경.**

### 5.4 케이스 3: 서브트리 이동

```
Before:
          H---I---J (topicB)
         /
    E---F---G (topicA)
   /
A---B---C---D (master)
```

`topicB`만 `master`로 직접 붙이고 싶다면?

```bash
git rebase --onto master topicA topicB
```

```
After:
    E---F---G (topicA)
   /
A---B---C---D (master)
             \
              H'--I'--J' (topicB)
```

**`topicA`를 건너뛰고 직접 연결.**

---

## 6. 위험: Force Push의 파괴력

### 6.1 문제 시나리오

```
# 개발자 A
git commit -m "Feature"     # abc123
git push origin feature

# 개발자 B (같은 브랜치)
git pull
git commit -m "Fix"         # def456 (부모: abc123)
git push

# 개발자 A (모르고...)
git rebase main             # abc123 → xyz789 (새 hash!)
git push origin feature
# → 거부됨! (non-fast-forward)

git push --force origin feature  # 강제로 푸시
# → 성공! 하지만...
```

<pre class="mermaid">
sequenceDiagram
    participant A as Dev A
    participant Remote
    participant B as Dev B
    
    A->>Remote: push abc123
    B->>Remote: pull (abc123)
    B->>B: commit def456
    B->>Remote: push def456
    Note over Remote: abc123→def456
    
    A->>A: rebase (abc123→xyz789)
    A->>Remote: push --force xyz789
    Note over Remote: abc123→def456 삭제됨!<br/>xyz789으로 대체
    
    B->>Remote: pull
    Note over B: 에러! 히스토리 충돌
</pre>

**개발자 B의 커밋(def456)이 사라졌다!**

### 6.2 왜 이런 일이?

```
Before A's force push:
o---o---abc123---def456 (remote/feature)
                  ↑
              B의 커밋

After A's force push:
o---o---xyz789 (remote/feature)
        ↑
    abc123의 rebase 버전

def456은? → 미아가 됨
```

개발자 B가 `git pull`하면:

```
error: Your local changes to the following files would be overwritten by merge:
...
```

또는:

```
! [rejected]        feature -> feature (non-fast-forward)
```

**히스토리가 갈라졌다.**

### 6.3 복구 방법?

```bash
# B의 작업 백업
git branch backup-feature

# Remote와 강제 동기화
git fetch origin
git reset --hard origin/feature

# B의 커밋을 다시 적용 (cherry-pick)
git cherry-pick backup-feature
```

**복구는 가능하지만 매우 번거롭다.**

### 6.4 안전장치: --force-with-lease

```bash
git push --force-with-lease origin feature
```

**동작**: Remote의 상태가 내가 **마지막으로 본 상태**와 같을 때만 push 허용.

```
# A가 fetch로 본 상태
origin/feature: abc123

# B가 push하여 변경
origin/feature: abc123---def456

# A가 force-with-lease로 push
git push --force-with-lease
# → 거부! "Expected abc123, but found def456"
```

**다른 사람의 push를 감지하고 보호한다.**

### 6.5 더 안전한: --force-if-includes

```bash
git push --force-with-lease --force-if-includes
```

추가 보호: **fetch 이후 내 변경사항만** push.

```bash
# 실수 방지
git fetch               # origin/feature 업데이트
git rebase main         # 하지만 fetch 전 상태 기반
git push --force-if-includes
# → 거부! "Fetch 이후 rebase하지 않았음"
```

### 6.6 황금률

> **공유된 브랜치는 rebase하지 말 것!**

| 상황 | Rebase OK? |
|------|-----------|
| 로컬 feature 브랜치 (push 전) | ✅ OK |
| PR용 브랜치 (혼자 작업) | ✅ OK |
| 여러 사람이 쓰는 브랜치 | ❌ NO |
| Main/master 브랜치 | ❌ NO |
| 이미 public에 push한 커밋 | ❌ NO |

---

## 7. 역사: Rebase의 탄생

### 7.1 타임라인

```
2005-04-07: Linus, Git 첫 커밋
            └─ cherry-pick 개념 존재 (patch 적용)

2005-08-18: Junio Hamano, git-rebase 첫 구현
            └─ v1.0.0rc3
            └─ 쉘 스크립트 형태

2006-07-10: Interactive rebase 추가
            └─ git rebase -i
            └─ todo list 편집

2018: C로 재작성
      └─ builtin/rebase.c
      └─ 성능 개선
```

### 7.2 초기 구현 (쉘 스크립트)

`git-rebase.sh` (2005년 버전, 의사코드):

```bash
#!/bin/sh

upstream=$1
branch=$2

# 공통 조상 찾기
merge_base=$(git-merge-base $upstream $branch)

# 커밋 목록
commits=$(git-rev-list $merge_base..$branch)

# 새 base로 reset
git-reset --hard $upstream

# Cherry-pick 반복
for commit in $commits; do
    if ! git-cherry-pick $commit; then
        echo "Conflict! Fix and run git rebase --continue"
        exit 1
    fi
done

echo "Rebase complete"
```

**단순하다!** 복잡한 로직 없이 cherry-pick의 반복.

### 7.3 설계 철학

Linus의 "stupid content tracker" 철학:

1. **복잡한 기능을 만들지 말라**
2. **단순한 도구를 조합하라**
3. **각 도구는 한 가지만 잘하라**

Rebase는 이 철학의 완벽한 예시다:
- Cherry-pick (이미 존재)
- Rev-list (이미 존재)
- Reset (이미 존재)

→ **조합하면 Rebase!**

---

## 8. 실전 팁

### 8.1 Commit 전 Rebase

```bash
# Main이 업데이트되었을 때
git fetch origin
git rebase origin/main
```

**Merge commit 없이 최신 상태 유지.**

### 8.2 PR 전 히스토리 정리

```bash
# WIP 커밋들 정리
git rebase -i HEAD~10

# Squash/fixup으로 의미 있는 단위로
pick a1b2c3d Implement user auth
fixup b2c3d4e Fix typo
fixup c3d4e5f Fix tests
pick d4e5f6g Add API endpoint
squash e5f6g7h Update docs
```

**리뷰어가 보기 좋은 히스토리.**

### 8.3 Autosquash

Fixup 커밋 이름을 특별히 짓기:

```bash
git commit -m "Add feature"
# ... 나중에 오타 발견
git commit -m "fixup! Add feature"
```

그리고:

```bash
git rebase -i --autosquash HEAD~2
```

자동으로 정리됨:

```
pick a1b2c3d Add feature
fixup b2c3d4e fixup! Add feature  ← 자동으로 배치됨
```

### 8.4 Rebase 중단

```bash
# 잘못됐다 싶으면
git rebase --abort

# 원래 상태로 복귀
```

### 8.5 Rebase 후 되돌리기

```bash
# 이미 rebase 완료했지만 후회...
git reflog
# 찾기: rebase 전 HEAD 위치
# a1b2c3d HEAD@{1}: rebase finished

git reset --hard HEAD@{1}
```

**Reflog는 구원자.**

---

## 마무리

### Rebase의 본질

1. **Cherry-pick의 자동화**: 복잡한 마법이 아니다
2. **히스토리 재작성**: 새 커밋 = 새 hash
3. **Three-way merge**: 각 커밋마다 적용
4. **Interactive mode**: 완전한 히스토리 제어
5. **--onto의 유연성**: 정밀한 외과수술
6. **위험성**: 공유 브랜치는 금지
7. **철학**: 단순한 도구의 조합

### 언제 쓸까?

| 상황 | 선택 |
|------|------|
| 로컬에서 히스토리 정리 | **Rebase** |
| PR 전 깔끔하게 | **Rebase** |
| Main 업데이트 반영 (혼자 작업) | **Rebase** |
| 팀 브랜치 | **Merge** |
| Public 히스토리 | **Merge** |
| 확신 없으면 | **Merge** |

### 기억할 것

> **Rebase는 날카로운 칼이다.**
> 
> 잘 쓰면 깔끔한 히스토리를 만든다.
> 잘못 쓰면 팀의 히스토리를 파괴한다.
> 
> 공유된 브랜치는 절대 rebase하지 말 것.

---

## 참고 자료

- [Git 공식 문서: git-rebase](https://git-scm.com/docs/git-rebase)
- [Git 소스코드: builtin/rebase.c](https://github.com/git/git/blob/master/builtin/rebase.c)
- [Julia Evans: Rebasing - what can go wrong?](https://jvns.ca/blog/2023/11/06/rebasing-what-can-go-wrong-/)
- [Atlassian: Merging vs. Rebasing](https://www.atlassian.com/git/tutorials/merging-vs-rebasing)
- [Git Book: Rewriting History](https://git-scm.com/book/en/v2/Git-Tools-Rewriting-History)
