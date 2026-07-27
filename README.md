# 골든링크 (GoldenLink)

응급 이송 골든타임 단축을 위한 실시간 병원 매칭 시스템 — **2026 AI ROOKIE 대회** 팀 골든링크 프로젝트

구급대원이 여러 병원에 순차적으로 전화를 돌리는 "뺑뺑이" 문제를, 첫 병원과의 통화 내용을 텍스트로 요약해 존(Zone) 내 모든 후보 병원에 동시에 전달하는 방식으로 해결한다.

## 구성

이 저장소는 [`goldenLink/`](./goldenLink) 프로젝트 하나로 구성된다.

| 폴더 | 설명 |
|---|---|
| [`goldenLink/`](./goldenLink) | 병원 매칭 대시보드 시스템 기획 — 전체 흐름, 바이탈 전송 범위, 대시보드 구성 |
| [`goldenLink/voiceSummation/`](./goldenLink/voiceSummation) | 통화 음성 → 텍스트 변환 → 요약 파이프라인 (faster-whisper + 로컬 LLM) |

각 폴더의 README에서 세부 내용을 확인할 수 있다.

## 협업

브랜치 전략과 PR 규칙은 [`CONTRIBUTING.md`](./CONTRIBUTING.md)를 참고한다.
