# Git Merge 리서치 노트

## 리서치 목적
Git 해체분석기 #8 "Merge의 비밀 - 두 브랜치는 어떻게 합쳐지나" 작성을 위한 사전 조사

## 1. Fast-forward Merge vs 3-way Merge

### Fast-forward Merge
- **조건**: 대상 브랜치가 소스 브랜치와 분기한 이후 변경사항이 없을 때
- **동작**: 브랜치 포인터만 이동, 새 커밋 생성 안 함
- **특징**: 선형 히스토리 유지, 깔끔한 로그

```
Before:
main:    A → B
feature:     B → C → D

After (git merge feature):
main:    A → B → C → D
```

### 3-way Merge
- **조건**: 두 브랜치 모두 독립적인 커밋이 있을 때
- **동작**: 
  1. Merge base (공통 조상) 찾기
  2. Base → tip1 diff 계산
  3. Base → tip2 diff 계산
  4. 두 diff를 base tree에 적용
  5. 두 부모를 가진 merge commit 생성
- **전략**: 기본적으로 recursive strategy 사용

```
Before:
main:    A → B → D
feature:     B → C

After (git merge feature):
main:    A → B → D → M
feature:     B → C ↗
```

### 비교

| 측면 | Fast-forward | 3-way Merge |
|------|--------------|-------------|
| 조건 | 선형 히스토리 | 분기된 히스토리 |
| 커밋 생성 | X | O (merge commit) |
| 히스토리 | 단순 | 분기 보존 |
| 강제 방법 | (불가능) | --no-ff |

## 2. Merge Commit 생성 과정

1. **Merge base 찾기** (LCA 알고리즘)
2. **3-way diff 계산**
   - Base → HEAD diff
   - Base → MERGE_HEAD diff
3. **Diff 적용 및 충돌 감지**
   - 겹치지 않는 변경: 자동 병합
   - 겹치는 변경: conflict
4. **Merge commit 생성**
   - Parent 1: HEAD (현재 브랜치)
   - Parent 2: MERGE_HEAD (병합 대상)
   - Tree: 병합된 결과

## 3. Merge Base 찾기 알고리즘

### LCA (Lowest Common Ancestor) 알고리즘
- Git의 커밋 히스토리 = DAG (Directed Acyclic Graph)
- 두 커밋에서 동시에 부모 방향으로 탐색
- 양쪽에서 도달 가능한 공통 조상 찾기
- 다른 공통 조상의 조상이 아닌 "가장 가까운" 조상 선택

### git merge-base 명령
```bash
git merge-base branch1 branch2
# → 공통 조상 SHA-1 반환

git merge-base --all branch1 branch2
# → 모든 merge base 목록 (여러 개 가능)
```

### Recursive Strategy
- 여러 merge base가 있을 경우
- Merge base들을 먼저 병합하여 가상의 base 생성
- 그 가상 base를 사용하여 최종 병합

## 4. Conflict 발생 원리와 해결

### Conflict 발생 조건
- 같은 파일의 같은 위치를 두 브랜치가 다르게 수정
- Base에서의 내용과 둘 다 다를 때

### diff3 알고리즘
기본 conflict 마커:
```
<<<<<<< HEAD
내 변경사항
=======
상대방 변경사항
>>>>>>> branch-name
```

diff3 스타일 (더 많은 정보):
```
<<<<<<< HEAD
내 변경사항
||||||| merged common ancestor
원본 내용
=======
상대방 변경사항
>>>>>>> branch-name
```

설정:
```bash
git config --global merge.conflictstyle diff3
```

### 해결 패턴
1. 각 변경사항과 원본 비교
2. 각 브랜치의 의도 파악
3. 두 의도를 모두 반영한 결과 작성

## 5. Octopus Merge

### 개념
- 2개 이상의 브랜치를 동시에 병합
- 하나의 merge commit에 여러 parent

### 사용법
```bash
git merge branch1 branch2 branch3
# → "Merge made by the 'octopus' strategy"
```

### 특징
- Git의 기본 전략 (3개 이상 병합 시)
- **Conflict 거부**: 수동 해결 필요한 경우 abort
- 독립적인 topic branch들을 묶을 때 유용

### 제한사항
- Conflict 처리 불가
- Rename detection 없음
- 단순한 병합만 가능

### Linux 커널의 극단적 예시
- 최대 66개 parent를 가진 octopus merge 존재
- CI/CD에서 여러 feature/* 브랜치 통합에 활용

## 6. Git 초기 Merge 구현

### Timeline
- **Day 1 (2005-04-07)**: 첫 커밋, merge 기능 없음
- **Day 12**: 간단한 merge 추가
- **Day 53 (2005-05-30)**: refs 시스템 추가 (HEAD, refs/heads/)

### 초기 구현: read-tree -m
- `-m` 플래그: merge 모드
- Trivial 3-way merge 지원
- Index를 ancestor(stage 1)로 사용
- HEAD tree vs 주어진 tree 비교
- 간단한 케이스만 처리 (conflict 시 에러)

### Trivial Merge Table (초기 구현)
| Ancestor | HEAD | Remote | Result |
|----------|------|--------|--------|
| empty | empty | empty | empty |
| empty | empty | remote | remote |
| empty | head | empty | head |
| file1 | file1 | file1 | file1 |
| file1 | file1 | file2 | file2 |
| file1 | file2 | file1 | file2 |
| file1 | file2 | file3 | ERROR |

### 진화 과정
1. **read-tree -m**: Low-level plumbing, trivial merge만
2. **resolve strategy**: 초기 high-level merge
3. **recursive strategy**: 현재 기본 전략 (rename 감지, 복잡한 케이스)
4. **ort strategy**: Git 2.34+ 기본 (최적화된 버전)

## 주요 인용구

### Linus on Merge (2005)
> "There were no branches, tags, or even references. Users were expected to manually keep track of object IDs."

### Octopus Strategy Description
> "The strategy is designed for bundling topic branch heads together, but refuses to do a complex merge that needs manual resolution."

## 참고 자료
- Git Official Docs: merge strategies, merge-base
- Dev.to: Git Internals - How Git Merge Really Works
- Perplexity research: Fast-forward, 3-way merge, LCA algorithm
- Git source: trivial-merge.txt, git-read-tree.txt
- Blog posts: diff3 conflict resolution, octopus merge examples

## 글 작성 방향

### 핵심 메시지
1. Merge는 "두 커밋의 diff를 하나로 합치는 것"
2. Fast-forward는 merge가 아니라 "포인터 이동"
3. 진짜 merge는 3-way merge (base가 핵심)
4. Conflict는 "같은 곳을 다르게 고쳤을 때"
5. Octopus는 "여러 브랜치 한 번에"

### 톤 유지
- 기존 해체분석기 스타일 (친근, 직접적)
- 실제 명령어 예시
- 다이어그램 활용
- 초기 구현 코드/커밋 분석
- "왜?"에 대한 답

### 구성안
1. 이전 글 요약 (Branch 생성)
2. 문제: 브랜치를 만들었는데, 어떻게 합치지?
3. Fast-forward: 가장 간단한 경우
4. 3-way Merge: 진짜 병합
5. Merge Base 찾기 (LCA)
6. Conflict와 해결
7. Octopus (보너스)
8. 초기 Git의 merge (read-tree -m)
9. 정리
10. 다음 글 예고

### 다이어그램 아이디어
- Fast-forward 전/후
- 3-way merge 전/후 (다이아몬드 형태)
- Merge base 찾기 과정
- Octopus merge (여러 parent)

## 체크리스트
- [x] Fast-forward vs 3-way merge 조사
- [x] Merge base 알고리즘 (LCA) 조사
- [x] Conflict 원리 조사
- [x] Octopus merge 조사
- [x] 초기 Git merge 구현 조사
- [ ] 초안 작성
- [ ] 코드 예시 준비
- [ ] 다이어그램 작성
- [ ] 참고 자료 정리
