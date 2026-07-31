# Hospital_inform — 병원 정보 정규화 (feature/info)

**골든링크(GoldenLink)** — 2026 AI ROOKIE 대회 출품작의 `feature/info` 파트 중
**E-Gen 공개 API → `HospitalInfo` 정규화** 영역이다.

개인 작업 공간에서 개발하던 것을 팀 저장소(`podongchip-stack/AIRookie`)의
`feature/info` 브랜치로 옮겨온 것으로, **아직 브랜치 최상위 구조에 통합하지 않고
`Hospital_inform/` 아래에 그대로 둔 상태**다. 브랜치 README의 폴더 구조(서버 +
`ocr/`)와 합치는 작업은 hub 연동 검증(④-b)이 끝난 뒤에 한다.

---

## feature/info 가 하는 일

응급의료기관의 상태를 모아 **표준 형식(`HospitalInfo`)으로 정규화해
`feature/hub`에 공급**한다. 환자에게 어느 병원이 적합한지는 판정하지 않는다 —
그건 `feature/hub`의 몫이다.

데이터 소스가 둘이고 성격이 정반대인 것이 이 파트의 특징이다.

| 소스 | 범위 | 실시간성 | 깊이 | 위치 |
|---|---|---|---|---|
| **E-Gen 공개 API** | 전국 전 기관 | 실시간 | 얕음 (병상 수) | **이 폴더** (`Hospital_inform/`) |
| **병원 서류 OCR** | 소수 기관 | 정적 | 깊음 (당직·인력) | 같은 브랜치 [`ocr/`](../ocr/README.md) |

둘 다 `feature/info`가 담당하며 최종적으로 같은 `HospitalInfo`로 합류한다.
현재는 서로 독립적으로 개발 중이고, 합류 지점(OCR 텍스트 → `HospitalInfo` 필드
구조화)은 아직 미구현이다.

당직 전문의 정보는 공개 API로 나오지 않는다. 그 공백을 서류 OCR로 메우는 것이
info의 고유 가치인데, **E-Gen의 "중증질환 수용가능 정보"가 그 상당 부분을
대체할 수 있는지가 아직 미검증**이다. 서비스키 승인 후 실측으로 판단한다
(아래 "미해결 항목" 참고).

---

## 현재 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| ① `schema.py` | 출력 형식 정의 + 검사기 | ✅ 완료 |
| ② fixture + client | 데이터 통로, API 없이 개발 가능하게 | ✅ 완료 |
| ③ 정규화 매퍼 | E-Gen 원본 → `HospitalInfo` | ✅ 완료 |
| ④-a 계약 검증 | hub의 실제 모델로 파싱되는지 | ✅ 통과 (4/4) |
| ④-b 매칭 검증 | hub 엔진에 넣어 순위 확인 | ⏳ 실행 대기 |
| ⑤ 시연 데이터 | 시나리오 3종용 값 설계 | ⏳ ④-b 이후 |
| ⑥ 브랜치 구조 통합 | `Hospital_inform/` → 브랜치 폴더 구조에 편입 | ⏳ ④-b 이후 |

---

## 구조

```
Hospital_inform/
├── README.md                            이 문서
├── hospital-info-interface-proposal.md  hub·voice에 보내는 인터페이스 변경 제안
└── info/
    ├── schema.py            출력 형식 정의 + 검사기 (가장 아래 계층, 아무것도 import 안 함)
    ├── egen/
    │   ├── client.py        데이터를 어디서 가져오나 (Fixture / Http 두 구현)
    │   └── mapper.py        가져온 걸 어떻게 바꾸나  ★본체
    ├── build_hospitals.py   실행 진입점
    ├── verify_with_hub.py   hub 엔진 연동 검증 (검증 전용, 프로덕션 아님)
    └── data/
        ├── fixtures/        E-Gen 응답을 흉내낸 가상 데이터 (커밋 안 함)
        └── output/          변환 결과 JSON (커밋 안 함)
```

의존 관계는 `build_hospitals.py → {client, mapper} → schema` 한 방향이다.
`schema.py`가 아무것도 import하지 않는 것은 `feature/hub`의 구조를 그대로 맞춘
것으로, 팀원이 우리 코드를 볼 때 익숙한 배치가 되도록 한 의도다.

`verify_with_hub.py`는 성격이 다르다. 우리 산출물이 hub에서 실제로 도는지
확인하는 **검증 도구**이며, 구급차 GPS와 voice 요약 샘플처럼 info의 것이 아닌
데이터를 갖고 있다. 브랜치 구조에 편입할 때(⑥) 프로덕션 모듈과 분리한다.

---

## 실행

아래 명령은 전부 `Hospital_inform/`에서 실행한다.

### 변환 (일반 개발 환경)

```bash
cd Hospital_inform
conda activate dev          # Python 3.12, pydantic 설치돼 있음
python info/build_hospitals.py
```

`info/data/fixtures/`를 읽어 `info/data/output/`에 병원 1곳당 JSON 1개를 쓴다.
fixture는 커밋되지 않으므로 **처음 클론했다면 먼저 만들어야 한다** (아래 참고).

OCR 모듈(`ocr/`)과는 의존성이 겹치지 않는다. 여기서는 pydantic만 있으면 되고,
torch·onnxruntime은 필요 없다.

### hub 연동 검증 (임베딩 모델 필요)

```bash
conda create -n rookie_info python=3.11 -y
conda activate rookie_info
pip install pydantic==2.13.4 sentence-transformers==5.6.1 numpy
python info/verify_with_hub.py
```

첫 실행 때 임베딩 모델 약 500MB를 내려받는다. 이 스크립트는 실행할 때마다
`git show feature/hub:<모듈>`로 hub 최신 코드를 임시 폴더에 꺼내 쓰고 끝나면
지운다. 이제 같은 저장소 안에 있으므로 hub 브랜치를 로컬에 받아두기만 하면
바로 돌아가며, **작업 트리에는 파일을 하나도 만들지 않는다** (hub 모듈 사본을
두면 상대가 코드를 고쳤을 때 낡은 사본을 조용히 검증하게 되기 때문).

---

## 데이터 정책

### fixture를 커밋하지 않는 이유

`info/data/fixtures/`의 파일들은 **실재하는 병원 이름에 지어낸 좌표·병상 수를
붙인 것**이다. 공개 저장소에 두면 실제 병원 정보로 오인될 수 있어
`Hospital_inform/.gitignore`에 넣었다. `info/data/output/`도 fixture에서
파생되므로 함께 제외한다.

### fixture 구조

E-Gen 응답 봉투를 그대로 흉내내야 한다. 형태가 어긋나면 실제 API로 바꾸는 순간
매퍼를 다시 짜야 한다.

```
info/data/fixtures/
├── realtime_beds_<지역>.json    getEmrrmRltmUsefulSckbdInfoInqire  병상 수
├── list_info_<지역>.json        getEgytListInfoInqire              좌표·기관분류
└── severe_illness_<지역>.json   getSrsillDissAceptncPosblInfoInqire 시술 가능 여부
```

각 파일은 `response.body.items.item[]` 아래에 병원 목록을 담는다. 주요 필드:

| 오퍼레이션 | 필드 |
|---|---|
| 가용병상 | `hpid` `dutyName` `hvidate` `hvec`(응급실) `hvoc`(수술실) `hv2`(내과중환자실) `hv3`(외과중환자실) |
| 목록정보 | `hpid` `dutyName` `wgs84Lat` `wgs84Lon` `dutyAddr` `dgidIdName` |
| 중증질환 | `hpid` `dutyName` `MKioskTy1` `MKioskTy2` `MKioskTy3` … |

fixture를 새로 만들 때는 **정상 데이터만 넣지 말 것.** 병상 미입력(`-1`),
빈 문자열, 특정 병원이 한쪽 응답에만 있는 경우를 최소 1건씩 포함해야 결측 처리
코드가 실제로 검증된다.

### 결측 처리 규약

`0`과 "미상"을 절대 섞지 않는다. 이 구분이 무너지면 정보가 손실된다.

| 값 | 의미 | 표현 |
|---|---|---|
| `0` | 확인된 만실. 갈 수 없다 | `bedsByType`에 키가 있고 값이 `0` |
| 미상 | 병원이 입력 안 함. 알 수 없다 | `bedsByType`에 **키 자체가 없음** |

`availableBedCount`(hub의 기존 필드)는 정수여야 해서 미상일 때 `0`을 넣는다.
미상을 "가능"으로 취급하지 않는 보수적 선택이며, 원래 정보는 `bedsByType`의
키 유무로 보존된다.

---

## 브랜치 README와의 관계

브랜치 최상위 [`README.md`](../README.md)의 `HospitalInfo` 표가 팀 합의 기준이고,
이 폴더는 그 형식을 **그대로 지키면서 optional 필드 2개(`bedsByType`,
`capabilities`)를 덧붙여** 내보낸다. 기존 필드는 하나도 바꾸지 않았다.

> hub의 `HospitalInfo`는 pydantic 기본 설정이라 **모르는 필드를 무시한다.**
> 확장 필드를 지금 보내도 hub는 깨지지 않으며, 합의되면 읽기 시작하면 된다.

추가 배경은 [`hospital-info-interface-proposal.md`](hospital-info-interface-proposal.md) 참고.

---

## 미해결 항목

### 1. E-Gen 서비스키 미신청 — **최우선**

유일한 외부 대기 항목이다. 승인 전까지 아래 항목을 전부 확정할 수 없다.
신청: [공공데이터포털 15000563](https://www.data.go.kr/data/15000563/openapi.do)

### 2. 실측 전 가정 (`egen/mapper.py` 상단 매핑표에 모여 있음)

키가 나오면 **매핑표 3개만 고치면** 나머지 코드는 손대지 않아도 된다.

| 항목 | 현재 가정 | 위험도 |
|---|---|---|
| `hv11` = 소아 병상 | 추정 | **높음** — 시연 시나리오 ②가 여기 걸려 있음 |
| `MKioskTy1/2/3` 번호별 질환 | 추정 | 높음 |
| 결측 표현이 `-1` | 미확인 | 중간 |
| `hvidate` 형식 `yyyyMMddHHmmss` | 미확인 | 낮음 |

`PROC_IV_THROMBOLYSIS`(tPA)는 어휘에는 있으나 매퍼가 아직 만들지 않는다.
`MKioskTy2`(뇌경색 재관류)가 tPA까지 포함하는지 명세 확인이 필요하다.

### 3. 커버리지 실측 — OCR 존폐를 가르는 숫자

키 승인 후 1시간이면 확인된다. 이 두 숫자로 OCR 추가 작업 여부를 결정한다.

- 대상 지역 병원 중 **중증질환 수용가능 값을 채운 비율**
- 채운 병원들의 **마지막 갱신 시각**

커버리지가 높으면 E-Gen만으로 충분하니 OCR은 현 상태로 동결한다.
낮으면 공백이 실재하므로 OCR이 그것을 메운다.

---

## 팀 확인 요청

### 1. 명세 오류 (`CLAUDE.md` 정정 필요)

| 팀 문서 | 실제 |
|---|---|
| `hv1` = 별도 API, "전문의 보유 여부" | 가용병상 응답 안의 **필드**, **응급실 당직의 직통 전화번호** |
| `hv2` = 중증질환 수용 API | **내과중환자실 병상 수** |

중증질환 수용가능은 `getSrsillDissAceptncPosblInfoInqire`라는 별개 오퍼레이션이고
필드는 `MKioskTy*`다. 즉 "3개 API"가 아니라 **2개 오퍼레이션 + 필드명 혼동**이며,
호출 설계 자체가 달라진다.

### 2. `CLAUDE.md` 갱신 누락 — 승인 액션 수신 주체

브랜치 README에는 승인 액션 수신 주체가 **`feature/hub`로 확정**이라고 적혀
있는데, `CLAUDE.md`에는 아직 "논의 중 — 잠정 보류"로 남아 있다. 확정 내용이
공통 문서에 반영되지 않은 상태다.

### 3. hub의 병상 필터 부재

`hub_engine.process_voice_summary()`가 `availableBedCount`를 필터에도 스코어링에도
쓰지 않는다. 결과 JSON에 복사만 된다. **병상이 0인 병원도 1위가 될 수 있다.**

시연 시나리오 ③(만실 → 2순위 대체)이 성립하려면 병상 0 제외가 필요하다.
스키마 변경이 아니라 **이미 있는 필드를 쓰지 않던 것을 쓰는 것**이라 부담이 작다.

### 4. 인터페이스 변경 제안

`hospital-info-interface-proposal.md` 참고. 매칭 판정을 임베딩 유사도에서
표준 역량 코드 대조로 옮기고, 임베딩은 info의 정규화 단계로 이동시키는 안이다.
`bedsByType`·`capabilities` 확장 필드가 여기서 나왔다.
