---
title: "Git 해체분석기 #3: Git 진화의 첫 2주"
date: 2026-02-06T15:00:00+09:00
summary: "2005년 4월, Git은 2주 만에 완전히 다른 도구가 됐다. 어떤 개념들이 언제, 왜 추가됐을까?"
tags: ["git", "해체분석기", "history", "linus-torvalds"]
categories: ["개발"]
series: ["Git 해체분석기"]
series_order: 3
weight: 3
draft: false
mermaid: true
---
> 이전 글: [Git 해체분석기 #2: 초창기 Git은 어떻게 사용했을까?](/posts/git-origins-how-to-use/)



## 들어가며

[지난 글](/posts/git-origins-first-commit/)에서 Git의 첫 커밋을 봤다. 10개 파일, 1000줄.

그런데 2주 후의 Git은 완전히 다른 도구였다.

첫 커밋에 없던 것들:
- ❌ `.git` 폴더 (`.dircache`였음)
- ❌ 브랜치 머지
- ❌ 히스토리 조회
- ❌ checkout

이것들이 **어떤 순서로, 왜** 추가됐을까?

실제 커밋 로그를 따라가보자.

---

## 1단계: 저장만 된다 (Day 1-4)

### Day 1: 뼈대

첫 커밋의 Git은 정말 단순했다.

```
파일 → blob으로 저장
blob들 → tree로 묶음
tree → commit으로 기록
```

끝. 저장만 된다. 꺼내는 건? 수동으로.

### Day 3: 꺼내기

Linus가 추가한 것:

```bash
checkout-cache  # 캐시에서 파일 복원
diff-tree       # 두 트리 비교
```

이제 저장한 걸 **꺼낼 수 있다**.

<pre class="mermaid">
flowchart LR
    subgraph day1[Day 1]
        A[저장만 가능]
    end
    
    subgraph day3[Day 3]
        B[저장 + 복원]
    end
    
    day1 --> day3
    
    style day1 fill:#ffcdd2,stroke:#c62828
    style day3 fill:#c8e6c9,stroke:#388e3c
</pre>

---

## 2단계: .git 탄생 (Day 5)

### 이름이 바뀌다

```
4bb04f2 Rename ".dircache" directory to ".git"
```

`.dircache`(캐시) → `.git`(프로젝트 저장소). 단순 캐시가 아니라 전체 역사를 담는 곳이 될 거라는 걸 알았기 때문.

### 히스토리 추적 시작

같은 날:

```
84fe972 Add a "rev-tree" helper
```

**rev-tree**: 커밋들의 관계를 추적하는 도구.

```
commit C
   ↓
commit B  
   ↓
commit A (최초)
```

이제 "이 커밋의 부모는 뭐지?"를 물을 수 있다.

---

## 3단계: 머지의 탄생 (Day 10-12)

### 문제: 두 사람이 동시에 작업하면?

Git을 만든 이유가 뭐였지? **Linux 커널 개발**.

수백 명이 동시에 코드를 수정한다. 이걸 합쳐야 한다.

### Day 10: 머지 준비

```
f5cabd1 Encode a few extra flags per index entry
```

Index(캐시)에 **stage 플래그**를 추가했다.

| Stage | 의미 |
|-------|-----|
| 0 | 정상 (충돌 없음) |
| 1 | 공통 조상 버전 |
| 2 | 현재 브랜치 버전 |
| 3 | 머지 대상 버전 |

같은 파일의 **세 가지 버전**을 동시에 저장할 수 있게 됐다.

### Day 11: 공통 조상 찾기

```
6683463 Do a very simple "merge-base" that finds the most recent common ancestor
```

**merge-base**: 두 커밋의 공통 조상을 찾는다.

```
      C---D  (feature)
     /
A---B---E---F  (main)

merge-base(D, F) = B
```

왜 필요할까?

**3-way merge**를 하려면 "원래 뭐였는지"를 알아야 한다.

```
Base (B):  Hello
Ours (F):  Hello, World
Theirs (D): Hello, Git

→ 둘 다 "Hello"를 바꿨네? 충돌!
→ 한쪽만 바꿨으면? 자동 머지!
```

### Day 12: 첫 머지

```
839a7a0 Add the simple scripts I used to do a merge with content conflicts
b51ad43 Merge the new object model thing from Daniel Barkalow
```

**Git 역사상 첫 머지**.

커밋 메시지를 보면 "Daniel Barkalow의 새 객체 모델"을 머지했다. 이미 다른 개발자가 Git 개발에 참여하고 있었다!

---

## 4단계: 원격의 시작 (Day 13)

### Pull 스크립트

```
8ccfbf3 Update "git-pull-script"
```

이 전까지 다른 사람 작업을 가져오려면?

```bash
# 수동으로 object 폴더 복사
cp -r /다른사람/repo/.git/objects/* .git/objects/
# 그리고 수동으로 머지...
```

`git-pull-script`가 이걸 **자동화**했다:

```bash
# 1) rsync로 상대방 objects 가져오기
rsync -avz remote:.git/objects/ .git/objects/

# 2) 상대방의 HEAD 커밋 확인
# 3) 내 HEAD와 머지
```

왜 의미있나?

- **분산 VCS의 핵심**: "각자 전체 히스토리를 갖고, 필요할 때 동기화"
- 중앙 서버 없이 **peer-to-peer**로 코드 공유 가능
- 아직 rsync 기반이지만, 이후 ssh/http/git 프로토콜로 발전

`git push`는? 아직 없다. 이때는 **pull만**. 상대방이 내 저장소에서 pull하는 방식으로 공유했다.

---

## 2주간의 진화 요약

<pre class="mermaid">
flowchart TB
    subgraph week1[Week 1]
        D1[Day 1<br/>저장만]
        D3[Day 3<br/>복원 추가]
        D5[Day 5<br/>.git 탄생<br/>히스토리 추적]
    end
    
    subgraph week2[Week 2]
        D10[Day 10<br/>Stage 플래그]
        D11[Day 11<br/>merge-base]
        D12[Day 12<br/>첫 머지!]
        D13[Day 13<br/>Pull 스크립트]
    end
    
    D1 --> D3 --> D5
    D5 --> D10 --> D11 --> D12 --> D13
    
    style D1 fill:#ffcdd2,stroke:#c62828
    style D5 fill:#fff3e0,stroke:#f57c00
    style D12 fill:#c8e6c9,stroke:#388e3c
</pre>

| 날짜 | 추가된 개념 | 왜 필요했나 |
|-----|-----------|-----------|
| Day 1 | Object Model | 파일을 저장해야 하니까 |
| Day 3 | checkout, diff | 저장한 걸 꺼내야 하니까 |
| Day 5 | .git, 히스토리 | 변경 이력을 봐야 하니까 |
| Day 10 | Stage 플래그 | 머지할 때 충돌을 표시해야 하니까 |
| Day 11 | merge-base | 3-way merge를 하려면 조상이 필요하니까 |
| Day 12 | 머지 | 여러 사람이 협업해야 하니까 |

---

## Linus의 설계 철학

커밋 로그를 보면 Linus의 접근 방식이 보인다:

### 1. 일단 동작하게 만든다

Day 1 커밋 메시지:
> "the information manager from hell"

완벽하지 않아도 된다. 일단 돌아가게.

### 2. 필요해지면 추가한다

checkout이 Day 1에 없던 이유? **아직 필요 없었으니까**.

저장만 하면 되는 상황에서 복원 기능은 사치다.

### 3. 단순하게 유지한다

merge-base 커밋 메시지:
> "Do a very simple merge-base"

복잡한 알고리즘 대신 **단순한 해결책**. 나중에 개선하면 된다.

---

## 남은 것들

2주 후에도 여전히 없던 것들:

- ❌ `git log` (히스토리 예쁘게 보기)
- ❌ `git branch` (브랜치 관리)
- ❌ `git push` (원격 저장소에 올리기)
- ❌ HEAD 파일 (현재 브랜치 표시)

이것들은 언제 추가됐을까? 

다음 글에서 계속.

---

## 마무리

Git은 2주 만에 **파일 저장 도구**에서 **분산 버전 관리 시스템**이 됐다.

하지만 무작정 기능을 추가한 게 아니다.

1. 저장 → 2. 복원 → 3. 비교 → 4. 히스토리 → 5. 머지 → 6. 원격

**각 단계가 다음 단계의 기반**이 됐다.

이런 점진적 발전이 Git을 단순하면서도 강력하게 만들었다.

---

## 참고 자료

- [Git 저장소 커밋 히스토리](https://github.com/git/git/commits/master?after=e83c5163316f89bfbde7d9ab23ca2e25604af290)
