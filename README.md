# [feature/info] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. 바이탈 수집과 병원 매칭 로직 중 어디까지를 이 브랜치가
> 계속 담당할지, 아니면 신설된 `feature/hub`로 옮길지는 아직 팀 내부에서
> **역할 분담 확정 필요** 상태입니다. 아래 기존 서술(바이탈 수집, 존 기반
> 매칭 관련 내용)은 삭제하지 않고 그대로 남겨두었으니, 역할 조정이 확정되면
> 그에 맞춰 갱신해주세요.

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

> 실제 구급차 바이탈 체크 기기 스펙이 확정되지 않아, 아래는 우선 약식으로 정한 포맷이다. 기기 데이터 형태가 확인되면 갱신 예정.

### 1. 바이탈 스트림 → dashboard

**출력**
```json
{
  "vitals": {
    "bp_systolic": 90,
    "bp_diastolic": 60,
    "pulse": 102,
    "spo2": 92,
    "gcs": 13,
    "temperature": 36.4,
    "resp_rate": 24
  },
  "timestamp": "2026-07-28T14:33:10Z",
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `vitals.bp_systolic` / `bp_diastolic` | number | 수축기/이완기 혈압 (mmHg) |
| `vitals.pulse` | number | 맥박 (bpm) |
| `vitals.spo2` | number | 산소포화도 (%) |
| `vitals.gcs` | number | 의식 수준 (GCS, 3~15) |
| `vitals.temperature` | number | 체온 (℃) |
| `vitals.resp_rate` | number | 호흡수 (회/분) |
| `timestamp` | string (ISO 8601) | 측정 시각 |
| `source` | `"rule"` | 센서 직결, AI 미사용을 나타내는 고정값 |

### 2. 존 기반 병원 매칭 결과 → dashboard

**출력**
```json
{
  "zone_active": [1, 2],
  "hospitals": [
    {
      "hospital_id": "C",
      "name": "C병원",
      "distance_km": 2.1,
      "status": "confirmed",
      "eta_min": 6
    },
    {
      "hospital_id": "D",
      "name": "D병원",
      "distance_km": 2.6,
      "status": "rejected"
    }
  ],
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `zone_active` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospital_id` | string | 병원 식별자 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].distance_km` | number | GPS 기준 거리 |
| `hospitals[].eta_min` | number | 도착 예상 시간(분), 확정 병원만 필요 |

### 3. 승인 액션 ← dashboard (입력, 역방향)

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

### 4. 병원 정보 → feature/hub (신규, 가안)

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
