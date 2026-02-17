# Git Submodules 리서치 노트

## 주제: "Submodules - 저장소 안의 저장소"

작성일: 2026-02-17

---

## 1. Submodule이란 무엇인가?

### 핵심 개념
- **Submodule = 다른 Git 저장소를 현재 저장소의 특정 경로에 포함시키는 메커니즘**
- "저장소 안의 저장소": 외부 저장소를 내 저장소 하위 디렉토리에 삽입
- 포함된 저장소는 **특정 커밋(SHA-1)에 고정(pin)** 된다
- 핵심: submodule 디렉토리는 파일이 아니라 **gitlink 객체**로 저장됨

### 왜 필요한가?
1. **의존성 관리**: 외부 라이브러리를 소스 수준으로 포함할 때
2. **프로젝트 분리**: 공유 컴포넌트를 여러 저장소에서 재사용
3. **코드 재사용**: 설정, 스크립트, 공통 모듈 공유
4. **특정 버전 고정**: "이 프로젝트는 engine 라이브러리의 정확히 이 커밋을 사용한다"

### 사용 사례
- 게임 엔진이 여러 플랫폼별 라이브러리를 submodule로 관리
- 조직 공통 CI 스크립트를 모든 저장소에 submodule로 포함
- Linux 커널의 firmware, tools 등을 별도 저장소로 관리

---

## 2. .gitmodules 파일 구조

### 위치 및 역할
- **위치**: 저장소 루트의 `.gitmodules`
- **역할**: submodule 매핑 정보 저장 (버전 관리됨!)
- 형식: `.git/config`와 동일한 INI 스타일

### 파일 구조
```ini
[submodule "libs/engine"]
    path = libs/engine
    url = https://github.com/example/engine.git
    branch = main

[submodule "themes/default"]
    path = themes/default
    url = git@github.com:example/theme.git
    # branch 없으면 detached HEAD 상태
```

### 주요 필드
| 필드 | 설명 | 필수 |
|------|------|------|
| `path` | 로컬 파일시스템 경로 | Yes |
| `url` | 원격 저장소 URL | Yes |
| `branch` | 추적할 브랜치 | No (기본: HEAD) |
| `update` | update 전략 (checkout/rebase/merge/none) | No |
| `shallow` | shallow clone 여부 | No |

### .git/config와의 관계
- `.gitmodules`: 버전 관리되는 공개 정보 (팀 공유용)
- `.git/config`: 로컬 설정 (덮어쓰기 가능)
- `git submodule sync`: `.gitmodules` → `.git/config`로 URL 동기화

---

## 3. 내부 구조: gitlink 객체

### 핵심 발견: submodule은 파일이 아니다

```bash
$ git ls-tree HEAD
100644 blob abc123  README.md
100644 blob def456  package.json
160000 commit 7a8b9c  libs/engine   ← 이게 gitlink!
```

**160000**: 특수한 파일 모드 (gitlink)
- 100644 = 일반 파일
- 100755 = 실행 파일
- 120000 = 심볼릭 링크
- 160000 = gitlink (submodule)

### gitlink가 저장하는 것
```bash
$ git cat-file -p HEAD:libs/engine
# 출력 없음! gitlink는 내용이 없음

$ git rev-parse HEAD:libs/engine
7a8b9c1d2e3f...  ← 외부 저장소의 특정 커밋 SHA
```

**gitlink가 저장하는 유일한 정보: 외부 저장소의 커밋 SHA**

이것이 submodule의 본질이다. 부모 저장소는 submodule이 **어떤 커밋을 가리키는지만** 기억한다.

---

## 4. 주요 명령어 동작 분석

### git submodule add

```bash
git submodule add https://github.com/example/engine.git libs/engine
```

실행되는 작업:
1. `libs/engine`에 외부 저장소를 clone
2. `.gitmodules` 파일에 설정 추가 (없으면 생성)
3. `.git/config`에도 동일 설정 추가
4. `libs/engine`을 gitlink로 staging area에 추가
5. `.git/modules/libs/engine/`에 실제 git 데이터 저장

```bash
# 실행 후 파일 구조
.git/
├── config
├── modules/
│   └── libs/engine/    ← 여기에 실제 git 저장소 데이터가 있다!
│       ├── HEAD
│       ├── objects/
│       └── ...
libs/
└── engine/            ← 작업 디렉토리 (gitdir 파일이 있음)
    └── .git           ← 파일! (디렉토리가 아님)
```

```bash
$ cat libs/engine/.git
gitdir: ../../.git/modules/libs/engine
```

**중요**: submodule 안의 `.git`은 디렉토리가 아니라 **파일**이다. 실제 데이터는 부모 저장소의 `.git/modules/`에 있다.

### git submodule init

```bash
git submodule init
# 또는
git submodule init libs/engine
```

- `.gitmodules`의 정보를 `.git/config`에 복사
- 실제 파일을 가져오지는 않음 (체크아웃 X)
- URL을 로컬 설정으로 등록하는 단계

### git submodule update

```bash
git submodule update          # init된 submodule 체크아웃
git submodule update --init   # init + update 한 번에
git submodule update --init --recursive  # 중첩 submodule까지
git submodule update --remote # .gitmodules의 branch 최신으로 업데이트
```

기본 update 동작:
1. 부모 저장소의 gitlink가 가리키는 SHA 확인
2. 해당 SHA를 submodule에서 체크아웃
3. submodule은 **detached HEAD 상태**가 됨

`--remote` 옵션:
- gitlink의 SHA가 아니라, 원격의 최신 브랜치로 업데이트
- 업데이트 후 부모 저장소에서 git add → git commit 필요

### git submodule sync

```bash
git submodule sync
git submodule sync --recursive
```

- `.gitmodules`의 URL을 `.git/config`에 동기화
- 원격 URL이 변경됐을 때 필수
- 파일 내용은 변경하지 않음

### clone 시 submodule 처리

```bash
# 방법 1: 따로따로
git clone https://example.com/main-repo.git
git submodule init
git submodule update

# 방법 2: 한 번에
git clone --recurse-submodules https://example.com/main-repo.git

# 방법 3: clone 후 한 번에
git submodule update --init --recursive
```

---

## 5. detached HEAD 문제

### 왜 submodule은 항상 detached HEAD인가?

```bash
$ cd libs/engine
$ git status
HEAD detached at 7a8b9c1
nothing to commit, working tree clean
```

**이유**: submodule은 "브랜치"가 아니라 **특정 커밋**에 고정되기 때문.

gitlink는 SHA를 저장한다. 브랜치 이름이 아니다.

### submodule 안에서 작업할 때의 위험

```bash
cd libs/engine
# 코드 수정
git add . && git commit -m "fix: something"  # OK, 새 커밋 생성

# 하지만!
cd ..  # 부모로 돌아오면
git submodule update  # 부모의 gitlink(SHA)로 되돌아감!
# 방금 만든 커밋이 "있긴 하지만 아무도 모르는" 상태가 됨
```

**해결책**: submodule 안에서 작업할 때는 반드시 브랜치를 만들거나, 작업 후 즉시 부모의 gitlink를 업데이트해야 함.

---

## 6. Submodule vs Subtree vs Monorepo

### git subtree

```bash
# subtree 추가
git subtree add --prefix=libs/engine https://github.com/example/engine.git main --squash

# subtree 업데이트
git subtree pull --prefix=libs/engine https://github.com/example/engine.git main --squash
```

**subtree의 특징**:
- 외부 저장소 내용을 현재 저장소 히스토리에 **병합**
- clone 후 별도 명령 없이 바로 사용 가능
- 별도 `.git` 없음, 일반 파일처럼 관리
- 기여하기(업스트림에 push) 복잡함

### 비교표

| 항목 | Submodule | Subtree | Monorepo |
|------|-----------|---------|----------|
| **개념** | 외부 저장소 참조 | 외부 저장소 병합 | 단일 저장소 통합 |
| **clone 복잡도** | 높음 (--recurse 필요) | 낮음 | 낮음 |
| **특정 버전 고정** | 쉬움 (SHA) | 가능하지만 복잡 | 브랜치로 관리 |
| **업스트림 기여** | 쉬움 | 복잡 | 해당 없음 |
| **히스토리** | 분리됨 | 병합됨 | 단일 |
| **팀 러닝 커브** | 높음 | 중간 | 낮음 |
| **저장소 크기** | 작음 | 큼 | 매우 큼 |
| **독립 배포** | 쉬움 | 가능 | 복잡 |

### Monorepo
- Google, Facebook, Twitter가 사용하는 방식
- 모든 코드를 단일 저장소에
- **장점**: 원자적 커밋, 의존성 관리 단순, 코드 재사용 쉬움
- **단점**: 저장소 크기, 빌드 시간, 권한 관리
- 도구: Bazel, Nx, Turborepo, Pants

### 선택 기준

```
Q: 외부 의존성을 특정 버전으로 고정해야 하나?
  → Yes: Submodule

Q: 외부 코드를 수정하고 upstream에 자주 기여하나?
  → Yes: Subtree 또는 Fork

Q: 동일 조직 내 여러 서비스가 강하게 결합되어 있나?
  → Yes: Monorepo

Q: 완전히 독립적인 라이브러리를 참조하나?
  → Submodule 또는 패키지 매니저 (npm, pip, etc.)
```

---

## 7. Submodule의 함정과 주의점

### 함정 1: 팀원이 --recurse-submodules를 까먹는다

```bash
git clone https://example.com/repo.git  # submodule 없이 clone
cd libs/engine  # 빈 디렉토리!
```

**해결**: `git config submodule.recurse true` (Git 2.15+)

### 함정 2: submodule 안에서 커밋하고 부모를 업데이트 안 함

```bash
# submodule에서 커밋
cd libs/engine && git commit -m "fix"
cd ..

# 부모가 이 커밋을 모름!
git status
# modified: libs/engine (new commits)
# 이걸 add + commit 해야 한다!
```

### 함정 3: submodule update가 변경사항을 날린다

```bash
cd libs/engine
echo "my change" >> README.md
git add . && git commit -m "WIP"
cd ..

git submodule update  # 이전 SHA로 되돌림, 방금 커밋은 dangling
```

### 함정 4: 중첩 submodule

```
repo/
├── libs/engine/      ← submodule A
│   └── vendor/deps/  ← submodule B (engine의 submodule!)
└── ...
```

```bash
# --recursive 없이는 중첩 submodule을 초기화하지 않음
git submodule update --init              # libs/engine만
git submodule update --init --recursive  # vendor/deps도
```

### 함정 5: submodule URL 변경 후 sync 안 함

```bash
# .gitmodules URL 변경 후
git submodule sync  # 꼭 해야 함!
git submodule update
# sync 안 하면 이전 URL로 시도해서 오류
```

### 함정 6: 같은 브랜치를 여러 사람이 다른 SHA로 업데이트

```
Alice: libs/engine → sha_A
Bob:   libs/engine → sha_B
merge → 충돌!
```

gitlink도 충돌합니다. 충돌 해소:
```bash
git checkout --ours -- libs/engine    # Alice 버전 선택
git checkout --theirs -- libs/engine  # Bob 버전 선택
git add libs/engine
```

### 함정 7: git push 시 submodule 커밋을 push 안 함

```bash
# submodule에서 커밋 후 부모만 push
cd ..
git add libs/engine
git commit -m "update submodule"
git push  # 부모는 올라갔는데 submodule 커밋은 로컬에만!

# 팀원이 clone하면:
git submodule update  # 오류! 해당 SHA를 원격에서 찾을 수 없음
```

**해결**: `git push --recurse-submodules=on-demand`

---

## 8. 유용한 고급 명령어

```bash
# 모든 submodule에서 명령 실행
git submodule foreach 'git fetch && git status'
git submodule foreach --recursive 'git checkout main'

# submodule 상태 요약
git submodule status
# -abc123 libs/engine   ← 아직 init 안 됨
# +abc123 libs/engine   ← 부모의 gitlink와 다른 SHA로 체크아웃됨
# abc123 libs/engine    ← 정상
# Uabc123 libs/engine  ← 충돌 상태

# submodule 제거 (정석)
git submodule deinit libs/engine
git rm libs/engine
rm -rf .git/modules/libs/engine

# diff에서 submodule 변경사항 보기
git diff --submodule=diff
```

---

## 9. 역사 및 구현

### 등장 배경
- Git 초기에는 외부 코드 포함 방법이 없었음
- 2006년: 쉘 스크립트 형태로 `git-submodule.sh` 최초 도입
- Git 1.5.3 (2007)에서 정식 지원
- C 코드로 포팅: `builtin/submodule--helper.c`

### gitlink 타입의 역사
- tree 객체에서 160000 모드로 표현
- 초기에는 "commit type"이라고도 불렸음
- 외부 저장소의 커밋 SHA를 직접 tree에 저장하는 단순한 아이디어

---

## 10. 재미있는 사실들

### 1. .git이 디렉토리가 아니라 파일
submodule의 `.git`은 파일이다. `gitdir: ../../.git/modules/...` 형식의 포인터.

### 2. submodule 안에서 `git log`가 동작함
완전한 독립 저장소이기 때문에 모든 git 명령이 동작.

### 3. detached HEAD가 "정상"
submodule의 detached HEAD는 버그가 아니라 설계다. 특정 커밋에 고정되어야 하므로.

### 4. gitlink는 blob도 tree도 아님
git object 타입은 blob, tree, commit, tag 4가지인데, gitlink는 tree 안에 commit SHA를 직접 저장하는 특수 케이스.

### 5. 중첩 submodule 이론상 무한
submodule 안에 submodule, 그 안에 submodule... 이론상 깊이 제한 없음. 실용적으로는 지옥.

---

## 11. 다이어그램 계획

### 다이어그램 1: 저장소 구조
```
부모 repo .git/
├── objects/
├── modules/
│   └── libs/engine/    ← submodule git 데이터
│       ├── HEAD
│       └── objects/
libs/engine/             ← 작업 디렉토리
└── .git (파일, gitdir 포인터)
```

### 다이어그램 2: gitlink가 저장하는 것
```
tree (HEAD)
├── 100644 README.md → blob: "..."
├── 100644 package.json → blob: "..."
└── 160000 libs/engine → commit: 7a8b9c1  ← 외부 저장소의 커밋 SHA
```

### 다이어그램 3: submodule add 흐름 (Mermaid flowchart)
### 다이어그램 4: Submodule vs Subtree vs Monorepo 비교
### 다이어그램 5: 함정들 흐름도

---

## 마무리 체크리스트

- [x] Submodule 개념 및 내부 구조 (gitlink)
- [x] .gitmodules 파일 구조 및 필드
- [x] add, init, update, sync 동작 분석
- [x] .git/modules/ 구조
- [x] detached HEAD 이슈
- [x] Submodule vs Subtree vs Monorepo 비교
- [x] 주요 함정 7가지
- [x] 유용한 고급 명령어
- [x] 역사 및 구현 정보
- [x] 흥미로운 사실들
- [x] 다이어그램 계획
