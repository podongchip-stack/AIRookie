# 개발 브랜치 가이드

## 브랜치 구조

```
main
 └── develop
       ├── feature/voice
       ├── feature/info        (기존 feature/vital 에서 이름 변경)
       ├── feature/hub
       └── feature/dashboard
```

## 작업 규칙

- 기능 개발은 각 feature 브랜치에서 진행
- feature → develop PR로 통합
- develop → main PR로 배포
