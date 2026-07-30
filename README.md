# [feature/info] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은 `feature/hub`로 이관하는 것으로
> 확정**되어 구 스키마(존 기반 병원 매칭 결과)는 이 문서에서 제거했습니다.
> 다만 dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/
> final_approval)을 이 브랜치와 `feature/hub` 중 어느 쪽이 수신할지는 아직
> 논의 중이라 **잠정 보류** 상태입니다.

## 담당자

- 이름: 김동현
- 역할: 리드 개발자
<!-- -->
- 이름: 최준혁
- 역할: 리드 개발자

## 이 브랜치가 하는 일

<!-- 이 기능이 전체 파이프라인에서 어떤 역할을 하는지 2~3문장 -->

## 사용한 AI / 모델

| 구분 | 모델명 | 용도 | 비고 |
|---|---|---|---|
| STT | | | |
| 정보 구조화 | | | |
| (필요 시 추가) | | | |

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [ ] AI 처리
> - [x] 규칙 기반

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 주요 라이브러리·프레임워크: Flask, Flask-SocketIO(WebSocket), requests(hv1/hvec/hv2 API 호출)
- 실행 환경: 로컬


## 입출력 데이터 포맷 (약식)

> 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어, 기존에 있던 "바이탈
> 스트림 → dashboard" 스키마는 이 문서에서 제거했습니다.

> 존 기반 병원 매칭 결과 스키마는 `feature/hub` 신설로 대체되어 이 문서에서
> 제거했습니다. 최신 스키마는 `feature/hub` README.md의 "입출력 데이터 포맷 >
> 출력 스키마 3"을 참고하세요.

### 1. 승인 액션 ← dashboard (입력, 역방향)

> `feature/info`와 `feature/hub` 중 어느 쪽이 이 액션을 수신할지 아직
> 확정되지 않았습니다 (잠정 보류). 확정 전까지는 스키마 자체만 유효합니다.

**입력**
```json
{
  "action": "final_approval",
  "hospital_id": "C",
  "actor": "paramedic",
  "timestamp": "2026-07-28T14:34:05Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `action` | `"hospital_approve"` \| `"hospital_reject"` \| `"final_approval"` | 어떤 승인 행위인지 |
| `hospital_id` | string | 대상 병원 |
| `actor` | `"hospital"` \| `"paramedic"` | 누가 누른 행위인지 |
| `timestamp` | string | 행위 발생 시각 |

### 2. 병원 정보 → feature/hub (신규, 가안)

> `feature/hub` 신설에 따라 추가된 스키마. `feature/hub`가 실제로 받는
> 입력 형태와 동일하다. 가안이며 팀 리뷰 후 확정 예정.

**출력**
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

## 실행 방법

```bash
conda create -n <가상환경명> python=3.11
conda activate <가상환경명>
pip install -r requirements.txt
```

`requirements.txt`는 직접 설치 대상(용도별 설명 포함)과 하위 의존성까지 모두 버전이
고정되어 있어, 위 명령 한 번으로 다른 팀원도 동일한 버전 조합을 그대로 재현할 수 있다.

## 폴더 구조

```
info/
├── .gitignore
├── README.md
└── requirements.txt
```

## 알려진 제약사항 / TODO

-

## 추가사항
