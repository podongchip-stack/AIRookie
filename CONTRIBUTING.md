# 브랜치 전략 & 협업 규칙

## 브랜치 구조

- **`main`** — 항상 정상 동작하는 안정 버전. 직접 커밋 금지, `develop`에서 PR로만 병합.
- **`develop`** — 팀 통합 개발 브랜치. 평소 작업은 여기서 분기한다.
- **`feature/<작업내용>`** — 기능 단위 작업 브랜치. `develop`에서 분기해서 작업 후 `develop`으로 PR.

파트가 정해지면 필요에 따라 `feature/frontend-ambulance`, `feature/frontend-hospital`, `feature/backend-matching`, `feature/voice-summary`처럼 파트가 드러나는 이름을 사용한다.

## 작업 흐름

```bash
git clone https://github.com/podongchip-stack/AIRookie.git
cd AIRookie
git checkout develop
git checkout -b feature/작업내용

# 작업 후
git add .
git commit -m "설명"
git push origin feature/작업내용
```

이후 GitHub에서 `feature/작업내용` → `develop`으로 Pull Request를 생성한다.

## PR 규칙

- PR 제목은 무엇을 했는지 한 줄로 명확하게 작성한다.
- 최소 1인 리뷰 후 병합한다.
- `develop`이 충분히 안정화되면 `develop` → `main`으로 PR을 올려 병합한다.

## 커밋 메시지

- 무엇을 왜 바꿨는지 알 수 있게 간결하게 작성한다. (예: `병원 응답 상태 뱃지 UI 추가`)
