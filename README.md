# [feature/info] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은 `feature/hub`로 이관하는 것으로
> 확정**되어 구 스키마(존 기반 병원 매칭 결과)는 이 문서에서 제거했습니다.
> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)의
> 수신 주체도 **`feature/hub`로 확정**되었습니다 (dashboard는 feature/hub와만
> 직접 통신하기 때문). 이 브랜치는 승인 액션을 직접 받지 않는 대신, hub가
> 확정 처리 후 내려주는 "병상 갱신 알림"을 받는다 (아래 참고).

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
> 출력 스키마 4"를 참고하세요.

### 통합 데이터 모델: HospitalInfo

`feature/info`와 `feature/hub` 사이를 오가는 두 메시지(아래 1·2번)는 서로 다른
스키마가 아니라, **같은 병원 레코드(HospitalInfo)를 서로 다른 크기로 주고받는
것**이다. info가 hub로는 전체 레코드를 보내고, hub가 info로는 병상 수만 담은
부분 갱신(patch)을 돌려준다 — 필드 집합은 아래 표 하나를 기준으로 통일한다.

| 필드 | 타입 | 설명 | 1번(info→hub 전체 전송) | 2번(hub→info 부분 갱신) |
|---|---|---|---|---|
| `hospitalId` | string | 병원 고유 식별자 | 포함 | 포함 (대상 식별용) |
| `name` | string | 병원명 | 포함 | 미포함 (안 바뀌는 값) |
| `gps.lat` / `gps.lng` | number | 병원 위치 좌표 (Hub의 거리 계산에 사용) | 포함 | 미포함 |
| `availableBedCount` | number | 실시간 가용 응급실 병상 수 | 포함 (현재값) | 포함 (hub가 확정 처리 후 계산한 최신값 — 이 값으로 덮어씀) |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 | 포함 | 미포함 |
| `specialties[].department` | string | 진료과명 | 포함 | 미포함 |
| `specialties[].doctorCount` | number | 해당 진료과 수술 가능 의사 수 | 포함 | 미포함 |
| `specialties[].recentProcedureTags` | string[] | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반) | 포함 | 미포함 |
| `status` | `"confirmed"` \| `"rejected"` | 이 갱신이 발생한 사유 | 미포함 (해당 없음) | 포함 |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 | 포함 | 포함 |
| `updatedAt` | string (ISO 8601) | 이 레코드/갱신이 마지막으로 발생한 시각 | 포함 | 포함 |

### 1. feature/info → feature/hub (HospitalInfo 전체 전송)

> `feature/hub` 신설에 따라 추가된 스키마. `feature/hub`가 실제로 받는
> 입력 형태와 동일하다. 가안이며 팀 리뷰 후 확정 예정.

**출력** (위 HospitalInfo 표의 "1번" 열에 해당하는 필드 전부)
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

### 2. feature/hub → feature/info (HospitalInfo 부분 갱신 — 병상 수만, 신규)

> dashboard의 승인 액션은 feature/hub가 직접 받는다 (feature/info는 받지 않음).
> 대신 `final_approval`로 이송이 확정되면, 같은 병상에 다른 구급차가 중복
> 매칭되는 걸 막기 위해 hub가 이 브랜치에 갱신된 병상 수를 알려준다. 동시에
> 여러 구급차가 매칭 중일 수 있어서 필요한 흐름이다 — hv1/hvec 같은 외부
> API의 갱신 주기만으로는 확정 시점에 바로 반영이 안 될 수 있기 때문. 위
> HospitalInfo의 다른 필드(name/gps/nightDutyAvailable/specialties)는 hub가
> 바꿀 이유가 없어서 이 메시지엔 담지 않는다 — 받은 쪽(info)은 `hospitalId`로
> 기존 레코드를 찾아 `availableBedCount`만 덮어쓰면 된다.

**입력** (위 HospitalInfo 표의 "2번" 열에 해당하는 필드만)
```json
{
  "hospitalId": "H001",
  "availableBedCount": 11,
  "status": "confirmed",
  "updatedAt": "2026-07-30T14:20:00Z",
  "source": "rule"
}
```

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
