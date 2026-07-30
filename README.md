# [feature/hub] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **신설 브랜치 안내**: `feature/hub`는 develop 기준으로 새로 만들어진 브랜치입니다.
> 아래 "입출력 데이터 포맷"에 정리된 세 가지 스키마(feature/voice 입력, feature/info
> 입력, feature/dashboard 출력)는 모두 **가안이며 팀 리뷰 후 확정 예정**입니다.

## 담당자

- 이름:
- 역할:

## 이 브랜치가 하는 일

feature/voice가 보내는 환자 정보(부상 상태, 예상 병명, 중증도)와 feature/info가
보내는 병원 정보(위치, 병상, 전문성)를 결합해 규칙 기반 스코어링으로 병원 후보를
매칭하고, 존(Zone) 로직과 병원/구급대원 승인 상태 관리까지 수행하는 브랜치입니다.
매칭 결과는 feature/dashboard로 전달됩니다.

## 사용한 AI / 모델

이 브랜치는 AI 모델을 사용하지 않는다. 규칙 기반 매칭 엔진으로 구현한다.

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [ ] AI 처리
> - [x] 규칙 기반

## 개발 환경 / 언어

- 언어: 미정
- 주요 라이브러리·프레임워크: 미정
- 실행 환경: 미정

## 입출력 데이터 포맷

> 아래 세 스키마 모두 가안이며 팀 리뷰 후 확정 예정.

### 입력 스키마 1: feature/voice로부터 (환자 정보)

기존 feature/voice README.md에 정의된 출력 스키마를 그대로 참조한다
(`transcript`, `summary.mechanism`, `summary.symptoms`, `summary.treatment`,
`summary.severity_tag` 등, 자세한 필드 설명은 feature/voice README.md 참고).
feature/hub는 이 중 `summary` 필드(부상 상태, 예상 병명, 중증도)만 매칭
스코어링에 사용한다.

### 입력 스키마 2: feature/info로부터 (병원 정보)

```json
{
  "hospitalId": "H001",
  "name": "○○병원",
  "gps": { "lat": 35.1795, "lng": 128.1076 },
  "availableBedCount": 12,
  "nightDutyAvailable": true,
  "specialties": [
    {
      "department": "흉부외과",
      "doctorCount": 3,
      "recentProcedureTags": ["기흉", "흉부외상"]
    }
  ],
  "source": "rule",
  "updatedAt": "2026-07-29T10:00:00Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `hospitalId` | string | 병원 고유 식별자 |
| `name` | string | 병원명 |
| `gps.lat` / `gps.lng` | number | 병원 위치 좌표 (Hub의 거리 계산에 사용) |
| `availableBedCount` | number | 현재 실시간 가용 응급실 병상 수 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[].department` | string | 진료과명 |
| `specialties[].doctorCount` | number | 해당 진료과 수술 가능 의사 수 |
| `specialties[].recentProcedureTags` | string[] | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반이며 향후 실제 데이터로 교체 예정) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 이 정보가 마지막으로 갱신된 시각 |

### 출력 스키마 3: feature/hub → feature/dashboard (통합 매칭 결과)

```json
{
  "patientInfo": {
    "injuryStatus": ["의식 저하", "호흡 곤란"],
    "expectedDiagnosis": "흉부 손상",
    "severityTag": "high"
  },
  "zoneActive": [1, 2],
  "hospitals": [
    {
      "hospitalId": "H001",
      "name": "○○병원",
      "gps": { "lat": 35.1795, "lng": 128.1076 },
      "distanceKm": 2.1,
      "specialtyMatch": {
        "department": "흉부외과",
        "score": 0.82
      },
      "availableBedCount": 12,
      "status": "confirmed",
      "etaMin": 6
    }
  ],
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `patientInfo.injuryStatus` | string[] | voice가 추출한 부상 상태 목록 (원본 `summary.symptoms` 기반) |
| `patientInfo.expectedDiagnosis` | string | voice가 추출한 예상 병명 (원본 `summary.mechanism` 기반) |
| `patientInfo.severityTag` | `"high"` \| `"medium"` \| `"low"` | 중증도 |
| `zoneActive` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospitalId` / `name` | string | 병원 식별자 및 병원명 |
| `hospitals[].gps` | object | 병원 위치 좌표 (대시보드 지도 표시용) |
| `hospitals[].distanceKm` | number | GPS 기준 거리 |
| `hospitals[].specialtyMatch.department` | string | 예상 병명에 매칭된 진료과 |
| `hospitals[].specialtyMatch.score` | number (0~1) | 해당 진료과의 수술 전문성 적합도 점수. `distanceKm`과 가중합되어 최종 순위 산출 |
| `hospitals[].availableBedCount` | number | 실시간 가용 병상 수 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].etaMin` | number | 도착 예상 시간(분), `confirmed` 병원만 필요 |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |

## 실행 방법

<!-- 아직 구현 코드가 없어 미정. 개발 환경 세팅 방법은 DEVELOPMENT.md 참고 -->

## 폴더 구조

```
hub/
├── .gitignore
├── CLAUDE.md
├── DEVELOPMENT.md
└── README.md
```

## 알려진 제약사항 / TODO

- 아직 실제 구현 코드가 없다 (README/CLAUDE.md/DEVELOPMENT.md/.gitignore만 존재)
- 개발 언어/프레임워크 미정
- 존(Zone) 확장 기준(명시적 거절 비율), 진료과 매칭 가중치 등 구체적인 스코어링 로직 미정
- 위 세 스키마 모두 가안이며 feature/voice, feature/info, feature/dashboard 팀과 리뷰 후 확정 필요

## 추가사항
