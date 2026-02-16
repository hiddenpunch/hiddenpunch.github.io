# Git Rebase 리서치 노트

## 목표
Git 해체분석기 #9: "Rebase의 비밀 - 히스토리는 어떻게 재작성되나"

## 1. Rebase vs Merge 차이

### Merge
- 두 브랜치를 합쳐서 새로운 merge commit 생성
- 히스토리가 분기되고 다시 합쳐지는 형태
- 모든 히스토리 보존
- 안전하지만 복잡한 그래프

```
    A---B---C (feature)
   /         \
  D---E---F---M (main) ← merge commit
```

### Rebase
- 커밋들을 다른 base 위로 "재배치"
- 선형적인 히스토리
- 커밋을 새로 만듦 (새 hash)
- 깔끔하지만 히스토리 재작성

```
Before:
  D---E---F (main)
   \
    A---B---C (feature)

After rebase:
  D---E---F (main)
           \
            A'---B'---C' (feature)
```

## 2. Rebase 내부 동작

### 핵심: Cherry-pick의 연속
Rebase는 내부적으로 다음과 같이 동작:

1. **공통 조상 찾기**: `git merge-base`로 upstream과 현재 브랜치의 공통 조상 찾기
2. **커밋 목록 생성**: 공통 조상 이후의 커밋들 나열
3. **패치 생성**: 각 커밋의 diff를 패치로 저장
4. **Reset**: 현재 브랜치를 새로운 base로 reset
5. **Cherry-pick 반복**: 각 패치를 순차적으로 cherry-pick
6. **브랜치 ref 업데이트**: 최종 커밋으로 브랜치 포인터 이동

### 소스코드 확인
- `builtin/rebase.c`: 메인 rebase 로직 (약 1900줄)
- `sequencer.c`: cherry-pick 구현
- `rebase-interactive.h`: interactive rebase 헤더

### 내부 프로세스
```c
// 의사코드
commits = find_commits_to_replay(current_branch, upstream);
reset_to(upstream);
for (commit in commits) {
    cherry_pick(commit);  // Three-way merge 사용
    if (conflict) {
        pause_and_wait_for_resolution();
    }
}
update_branch_ref(current_branch, final_commit);
```

## 3. Interactive Rebase

### 기본 사용법
```bash
git rebase -i HEAD~3
```

에디터가 열리고 커밋 목록 표시:
```
pick abc1234 Add feature
pick def5678 Fix bug
pick ghi9012 Update tests
```

### 주요 명령어

| 명령 | 약자 | 설명 |
|------|------|------|
| pick | p | 커밋을 그대로 사용 |
| reword | r | 커밋 메시지만 수정 |
| edit | e | 커밋을 수정하고 일시정지 |
| squash | s | 이전 커밋과 합치고 메시지 편집 |
| fixup | f | 이전 커밋과 합치고 메시지 버림 |
| drop | d | 커밋 제거 |

### Squash vs Fixup
```
Before:
pick abc1234 Add feature
pick def5678 Fix typo
pick ghi9012 Fix another typo

After (squash):
pick abc1234 Add feature
squash def5678 Fix typo
squash ghi9012 Fix another typo
→ 하나로 합쳐지고 메시지 편집 가능

After (fixup):
pick abc1234 Add feature
fixup def5678 Fix typo
fixup ghi9012 Fix another typo
→ 하나로 합쳐지고 첫 메시지만 유지
```

### 내부 구현
- `.git/rebase-merge/git-rebase-todo`: 편집 가능한 todo 리스트
- 순차적으로 명령 실행
- 각 단계마다 상태 저장

## 4. Rebase --onto 활용

### 기본 형태
```bash
git rebase --onto <newbase> <upstream> <branch>
```

### 사용 케이스

#### Case 1: 특정 커밋 범위만 이동
```
Before:
  A---B---C---D (main)
       \
        E---F---G (feature)

git rebase --onto D B feature

After:
  A---B---C---D (main)
               \
                E'---F'---G' (feature)
```

B 이후의 커밋들(E, F, G)만 D 위로 이동

#### Case 2: 브랜치 분리
```
Before:
  A---B---C (main)
       \
        D---E---F (server)
             \
              G---H (client)

git rebase --onto main server client

After:
  A---B---C (main)
       |   \
       |    D---E---F (server)
       \
        G'---H' (client)
```

client의 커밋만 main 위로 직접 이동

## 5. 위험성: Force Push와 히스토리 손상

### 왜 위험한가?

1. **히스토리 재작성**: Rebase는 새 커밋을 만듦 (새 hash)
2. **Remote와 불일치**: 이미 push한 커밋을 rebase하면 히스토리가 달라짐
3. **Force push 필요**: 일반 push 거부됨 → `--force` 필요
4. **협업자의 작업 손실**: 다른 사람이 그 커밋 기반으로 작업했다면 충돌

### 문제 시나리오

```
# 개발자 A
git commit -m "Feature"
git push origin feature  # abc1234

# 개발자 B (같은 브랜치)
git pull
git commit -m "Fix"      # def5678 (부모: abc1234)
git push

# 개발자 A
git rebase main          # abc1234 → xyz9999 (새 hash!)
git push --force         # B의 커밋(def5678) 삭제됨!

# 개발자 B
git pull                 # 에러! 히스토리 충돌
```

### 안전한 대안: --force-with-lease

```bash
git push --force-with-lease
```

- Remote가 예상한 상태인지 확인
- 다른 사람이 push했다면 거부
- `--force`보다 안전

### 더 안전한: --force-if-includes

```bash
git push --force-with-lease --force-if-includes
```

- 최신 fetch 이후 변경사항 확인
- 더욱 강력한 보호

### 황금률
**공유된 브랜치는 rebase하지 말 것!**

- Local 브랜치에서만 rebase
- PR 생성 전까지만
- Push 후에는 merge 사용

## 6. Git 초기 Rebase 구현 역사

### 타임라인
- **2005년 4월 7일**: Linus, Git 첫 커밋
- **2005년 8월 18일**: Junio Hamano, `git rebase` 구현 (v1.0.0rc3)
- 초기 버전: 쉘 스크립트로 구현
- Cherry-pick 기반 설계

### 설계 철학
- "stupid content tracker"의 연장선
- 복잡한 기능보다 단순한 조합
- Rebase = cherry-pick의 자동화

### 초기 구현 (추정)
```bash
# git-rebase.sh (의사코드)
find_merge_base $upstream $branch
list_commits $merge_base..$branch
reset --hard $upstream
for commit in $commits; do
    git-cherry-pick $commit
done
```

### 현재 구현
- C로 재작성 (`builtin/rebase.c`)
- Interactive mode 추가
- 다양한 옵션 지원
- 하지만 핵심 개념은 동일: **cherry-pick의 연속**

## 7. 실제 사용 예시

### 1. 깔끔한 히스토리 만들기
```bash
# 로컬에서 여러 번 커밋
git commit -m "WIP: feature"
git commit -m "Fix typo"
git commit -m "Fix another typo"
git commit -m "Feature complete"

# 정리
git rebase -i HEAD~4
# squash/fixup으로 하나로 합치기
```

### 2. 최신 main 반영
```bash
git checkout feature
git rebase main  # merge 대신
```

### 3. 커밋 순서 바꾸기
```bash
git rebase -i HEAD~3
# 에디터에서 줄 순서 변경
```

### 4. 커밋 분리
```bash
git rebase -i HEAD~1
# 'edit'으로 변경
# reset HEAD^
# git add -p (부분 스테이징)
# git commit (여러 번)
# git rebase --continue
```

## 주요 인사이트

1. **Rebase는 마법이 아니다**: Cherry-pick의 반복일 뿐
2. **새 커밋 = 새 hash**: 히스토리가 완전히 바뀜
3. **Three-way merge 사용**: 각 cherry-pick마다
4. **Interactive mode는 강력하다**: 히스토리 완전 제어
5. **--onto는 유연하다**: 정확한 커밋 범위 지정
6. **공유 브랜치는 금지**: 협업 파괴
7. **Force push 조심**: --force-with-lease 사용

## 다이어그램 아이디어

1. Merge vs Rebase 비교 (before/after)
2. Rebase 내부 프로세스 (flowchart)
3. Interactive rebase todo 흐름
4. --onto 시나리오 (여러 케이스)
5. Force push 문제 시나리오 (타임라인)

## 참고 자료

- Git 공식 문서: git-scm.com/docs/git-rebase
- Git 소스: github.com/git/git (builtin/rebase.c)
- Atlassian 튜토리얼: atlassian.com/git/tutorials/rewriting-history/git-rebase
- Julia Evans 블로그: jvns.ca/blog/2023/11/06/rebasing-what-can-go-wrong-/
