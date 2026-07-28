# 골든링크 — 응급 이송 골든타임 단축을 위한 실시간 병원 매칭 시스템

2026 AI ROOKIE 대회 출품작입니다.

---

## 팀 구성

| 역할 | 이름 |
|------|------|
| PM | 이승주 |
| 리드 개발자 | 이승주 |
| 리드 개발자 | 곽호영 |
| 서브 개발자 | 김태우 |

---

## 기술 스택

> 추후 작성

---

## 브랜치 전략

| 브랜치 | 역할 | 직접 Push |
|--------|------|-----------|
| `main` | 배포 브랜치 | 금지 |
| `develop` | 통합 테스트 브랜치 | 금지 |
| `feature/voice` | 음성 STT + 요약 기능 개발 | 가능 |
| `feature/vital` | 바이탈 데이터 처리 기능 개발 | 가능 |
| `feature/dashboard` | 대시보드 UI 개발 | 가능 |

**브랜치 흐름:**
```
feature/*  →  develop  →  (배포 준비 완료 시)  →  main
```

---

## 협업 시작하기

### 1. 저장소 클론 — 최초 1회
```bash
git clone https://github.com/podongchip-stack/AIRookie.git
cd AIRookie
```

### 2. develop 최신 코드 반영
```bash
git checkout develop
git pull origin develop
```

### 3. 본인 feature 브랜치로 이동
```bash
git checkout feature/voice   # 또는 feature/vital, feature/dashboard
```

---

## Push & Pull Request 절차

### 1. 작업 완료 후 Push
```bash
# 변경 파일 스테이징
git add .

# 커밋 (아래 커밋 메시지 양식 참고)
git commit -m "feat: 기능 설명"

# 본인 브랜치에 Push
git push origin feature/본인브랜치
```

### 2. Pull Request 생성
- GitHub에서 `feature/* → develop` 방향으로 PR 생성
- PR 템플릿에 맞게 작성
- **`develop → main` PR은 PM 승인 후에만 머지**

### 3. 리뷰 및 머지
- `feature → develop` PR: 팀원 전원 머지 가능
- `develop → main` PR: PM 지정 인원만 머지

---

## 커밋 메시지 양식

```
타입: 작업 내용 요약
```

| 타입 | 사용 상황 |
|------|-----------|
| `feat` | 새 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서 수정 |
| `refactor` | 코드 리팩토링 (기능 변화 없음) |
| `chore` | 설정, 패키지 등 기타 작업 |

**예시:**
```
feat: 음성 파일 STT 변환 기능 추가
fix: Whisper 모델 로딩 오류 수정
docs: README 실행 방법 보완
```

---

## 다른 팀원 변경사항 가져오기

PR이 develop에 머지된 후, 아래 명령어로 최신 코드를 로컬에 반영합니다.

```bash
git checkout develop
git pull origin develop

# 이후 본인 브랜치에 develop 내용 반영
git checkout feature/본인브랜치
git merge develop
```
