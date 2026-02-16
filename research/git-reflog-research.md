# Git Reflog 리서치 노트

## 주제: "Reflog - Git의 타임머신"

작성일: 2026-02-16

---

## 1. Reflog란 무엇인가?

### 핵심 개념
- **Reflog = Reference Log**: Git 참조(HEAD, 브랜치)의 이동 기록을 추적하는 로컬 히스토리
- `git log`는 커밋 히스토리를 보여주지만, **reflog는 "내가 어디로 이동했는가"의 히스토리**
- **완전히 로컬**: 원격 저장소와 공유되지 않음 (Linus Torvalds의 reflog을 볼 수 없는 이유)
- **안전망 역할**: reset --hard, 브랜치 삭제 등의 실수를 복구할 수 있는 최후의 보루

### 실험 결과

```bash
# 테스트 시나리오
$ git init test-reflog
$ echo "First" > file1.txt && git add . && git commit -m "Initial"
$ echo "Second" > file2.txt && git add . && git commit -m "Add file2"
$ git reset --hard HEAD~1  # 커밋 "삭제"
$ git reflog

# 결과
044ec5f HEAD@{0}: reset: moving to HEAD~1       ← 방금 한 reset
dfde2c2 HEAD@{1}: commit: Add file2             ← "삭제된" 커밋이 여전히 존재!
044ec5f HEAD@{2}: commit (initial): Initial commit
```

**핵심 발견**: `git log`에서는 사라진 커밋이 reflog에는 남아있음!

---

## 2. .git/logs 구조 분석

### 디렉토리 구조

```
.git/logs/
├── HEAD                    ← 모든 HEAD 이동 기록
└── refs/
    ├── heads/
    │   └── master         ← master 브랜치 reflog
    │   └── feature        ← feature 브랜치 reflog
    └── remotes/
        └── origin/
            └── main       ← origin/main 추적 브랜치 reflog
```

### 파일 포맷 분석

`.git/logs/HEAD` 내용:

```
0000000000000000000000000000000000000000 044ec5fa9a394b2abc825f4c2fc165e375fa5359 Test <test@test.com> 1771240678 +0900	commit (initial): Initial commit
044ec5fa9a394b2abc825f4c2fc165e375fa5359 dfde2c229ec432736bba63e4782fe16e3aba3223 Test <test@test.com> 1771240678 +0900	commit: Add file2
dfde2c229ec432736bba63e4782fe16e3aba3223 044ec5fa9a394b2abc825f4c2fc165e375fa5359 Test <test@test.com> 1771240678 +0900	reset: moving to HEAD~1
```

**포맷 구조:**
```
[old_sha1] [new_sha1] [author] [timestamp] [timezone] [tab] [action]: [message]
```

- **old_sha1**: 이전 위치 (첫 커밋은 00000...)
- **new_sha1**: 새로운 위치
- **timestamp**: Unix epoch time
- **action**: commit, reset, checkout, merge, rebase 등
- **message**: 사용자 커밋 메시지 또는 Git 액션 설명

### 중요한 발견

1. **단순 텍스트 파일**: 복잡한 데이터베이스가 아니라 그냥 append-only 텍스트 파일
2. **브랜치별 독립**: 각 브랜치마다 독립적인 reflog 보유
3. **HEAD는 통합 뷰**: 모든 브랜치 이동을 포함한 전체 히스토리

---

## 3. Git 소스코드 분석

### reflog.c (git/git 공식 저장소)

출처: https://github.com/git/git/blob/master/reflog.c

**핵심 함수들:**

```c
// 설정 파싱: gc.reflogExpire, gc.reflogExpireUnreachable
int reflog_expire_config(const char *var, const char *value, ...) {
    // 패턴별 만료 설정 적용
    // 예: gc.refs/stash.reflogExpire = never
}

// Tree 완전성 체크
static int tree_is_complete(struct object_id *oid) {
    // Tree 로드 후 재귀적으로 모든 항목 체크
    // SEEN, INCOMPLETE 플래그 사용
}

// Reflog 항목 유지 여부 결정
static int keep_entry(struct commit **it, struct object_id *oid) {
    // 커밋이 reachable하고 객체가 존재하는지 검증
    // REACHABLE 플래그 마킹
}
```

**설계 철학:**
- 객체 존재성(existence)과 도달가능성(reachability)을 분리
- Flag 기반 상태 관리 (SEEN, INCOMPLETE, REACHABLE)
- 패턴 매칭으로 유연한 만료 정책

---

## 4. Reflog Expire와 GC

### 기본 만료 정책

```bash
# 기본 설정 (git help config에서 확인)
gc.reflogExpire = 90.days.ago              # 모든 reflog 항목
gc.reflogExpireUnreachable = 30.days.ago   # unreachable 항목만
```

**차이점:**
- **reachable**: 현재 브랜치에서 도달 가능한 커밋 (90일)
- **unreachable**: 고아 커밋, 삭제된 브랜치 커밋 (30일)

### 수동 제어

```bash
# 즉시 만료
git reflog expire --expire=now --all

# 절대 만료 안 함 (주의!)
git config gc.reflogExpire never

# stash는 보존, 나머지는 기본값
git config gc.refs/stash.reflogExpire never
```

### gc와의 관계

```bash
# git gc 실행 시:
# 1. reflog expire 실행 → 오래된 reflog 항목 제거
# 2. unreachable 객체 제거 → reflog에 없으면 진짜 삭제
# 3. pack 파일 생성
```

**핵심**: reflog가 객체를 참조하고 있으면 gc가 삭제하지 않음!

---

## 5. 삭제된 커밋 복구하기

### 시나리오 1: Reset --hard 실수

```bash
# 문제 상황
$ git reset --hard HEAD~3  # 3개 커밋 날림
$ git log  # 커밋들이 사라짐...

# 복구
$ git reflog
a1b2c3d HEAD@{1}: commit: Important feature  ← 이거다!
$ git reset --hard a1b2c3d  # 복구 완료!

# 또는 상대 참조 사용
$ git reset --hard HEAD@{1}
```

### 시나리오 2: 브랜치 삭제 실수

```bash
# 문제 상황
$ git branch -D feature  # 브랜치 삭제
$ git log --all  # feature 커밋들이 안 보임

# 복구 (HEAD reflog에는 남아있음!)
$ git reflog | grep feature
ba2ad6e HEAD@{1}: commit: Feature commit

$ git checkout -b feature-recovered ba2ad6e
```

### 시나리오 3: fsck로 완전히 잃어버린 커밋 찾기

```bash
# reflog도 만료된 경우 (최후의 수단)
$ git fsck --lost-found
dangling commit dfde2c229ec432736bba63e4782fe16e3aba3223

$ git show dfde2c2  # 내용 확인
$ git merge dfde2c2  # 복구
```

---

## 6. Reflog vs Log 차이

| 항목 | git log | git reflog |
|------|---------|------------|
| **무엇을 기록?** | 커밋 히스토리 (프로젝트 역사) | 참조 이동 기록 (내 작업 기록) |
| **범위** | 전역 (리포지토리 전체) | 로컬 (내 워크스페이스만) |
| **공유 여부** | Push/Pull로 공유됨 | 절대 공유 안 됨 |
| **삭제된 커밋** | 보이지 않음 | 보임 (만료 전까지) |
| **브랜치 전환** | 기록 안 함 | 기록함 |
| **목적** | "프로젝트 무슨 일이?" | "내가 뭐 했지?" |
| **생존 기간** | 영구 (reachable하면) | 기본 90일 (설정 가능) |

### 메타포

- **git log**: 공식 역사책 (History book)
- **git reflog**: 개인 일기장 (Personal diary)

---

## 7. 흥미로운 사실들 & 인용구

### 로컬 전용의 의미

> Linus Torvalds의 reflog을 볼 수 없는 이유는 간단합니다.  
> Reflog는 **당신의 로컬 작업 기록**이지, 프로젝트 역사가 아니기 때문입니다.

### 왜 이렇게 설계했을까?

1. **프라이버시**: 실수, 실험, 삭제된 브랜치를 공유하지 않음
2. **안전성**: 무엇을 push하든 로컬에서는 복구 가능
3. **성능**: 원격과 동기화할 필요 없음 → 빠름
4. **단순성**: append-only 텍스트 파일 → 구현 간단

### 설계 통찰

Git의 3단계 안전망:
```
1차: Working Directory (git checkout)
2차: Staging Area (git reset)
3차: Reflog (git reflog → reset/checkout)
```

---

## 8. 다이어그램 아이디어

### 다이어그램 1: git log vs git reflog

```
[git log]
A ← B ← C (master)

[git reset --hard A]
A (master)

[git log] → A만 보임
[git reflog] → A, B, C 모두 기록됨!
```

### 다이어그램 2: .git/logs 구조

```
.git/logs/
├── HEAD (전체 이동 기록)
│   └── 모든 checkout, commit, reset 기록
└── refs/
    └── heads/
        ├── main (main 브랜치 전용)
        └── feature (feature 브랜치 전용)
```

### 다이어그램 3: Reflog Expire 타임라인

```
← 90 days → ← 30 days → [NOW]
[reachable] [unreachable] [safe]
     ↓           ↓          ↓
   expire    expire+gc    keep
```

---

## 9. 다음 편 연결 포인트

- **Stash**: Reflog의 특수 케이스 (refs/stash는 never expire)
- **Git Gc**: Reflog와 객체 정리의 관계
- **Worktree**: 여러 worktree의 reflog는 어떻게 관리되나?

---

## 10. 톤 & 스타일 참고

기존 해체분석기 시리즈 (#1 Object Storage) 분석:
- ✅ "직접 해보기" 섹션으로 실습 유도
- ✅ Mermaid 다이어그램 적극 활용
- ✅ 이모지로 시각적 구분 (🔷🟢🟡🔴)
- ✅ "충격적인 사실들" 섹션으로 흥미 유발
- ✅ "왜 이렇게 설계했을까?" 사고 유도
- ✅ 표로 정보 정리
- ✅ 메타포 사용 (브랜치 = 40글자 텍스트 파일)
- ✅ 친근한 톤 ("끝입니다.", "직접 까보죠!")

---

## 마무리 체크리스트

- [x] Reflog 개념 명확화
- [x] .git/logs 구조 실험 및 파싱
- [x] Git 소스코드 참조 (reflog.c)
- [x] 만료 정책 (90일/30일) 확인
- [x] 복구 시나리오 3가지 작성
- [x] reflog vs log 비교표
- [x] 다이어그램 스케치
- [x] 기존 시리즈 톤 분석

**준비 완료! 이제 초안 작성으로 진행.**
