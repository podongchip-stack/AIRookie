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
| **E-Gen 공개 API** | 전국 전 기관 | 실시간 | 얕음 (병상 6종 · 시술/장비 역량) | **이 폴더** (`Hospital_inform/`) |
| **병원 서류 OCR** | 소수 기관 | 정적 | 깊음 (당직·인력) | 같은 브랜치 [`ocr/`](../ocr/README.md) |

둘 다 `feature/info`가 담당하며 최종적으로 같은 `HospitalInfo`로 합류한다.
현재는 서로 독립적으로 개발 중이다.

OCR 쪽은 텍스트에서 필드를 뽑는 데까지 구현됐다(`DocumentFields`). 다만 서류에는
좌표도 실시간 병상 수도 없어 그 자체로는 `HospitalInfo`가 될 수 없고, **합류
지점(`DocumentFields` → `HospitalInfo` 병합)은 아직 미구현**이다. 병합할 때
서류에서 온 정적인 값이 E-Gen의 실시간 값을 덮지 않게 하는 것이 핵심이다.
자세한 것은 [`ocr/README.md`](../ocr/README.md) 참고.

당직 전문의 정보는 공개 API로 나오지 않는다. 그 공백을 서류 OCR로 메우는 것이
info의 고유 가치인데, **E-Gen의 "중증질환 수용가능 정보"가 그 상당 부분을
대체할 수 있는지**를 서비스키 승인 후 실측했다. 결론은 **일부만 대체된다**이다 —
시술 역량은 상당히 덮이지만 **tPA(정맥 혈전용해술)는 `MKioskTy` 28항목 어디에도
없다.** 자세한 것은 아래 "실측으로 확인한 것" 참고.

> **정정 (2026-08-12)**: 여기 원래 "진료과별 의사 수도 공개 API에 항목 자체가 없다"고
> 적혀 있었는데 **틀렸다.** E-Gen에 없을 뿐 **심평원 의료기관별상세정보서비스(15001699)가
> 전문과목별 전문의 수를 준다.** 실제로 연동해 병원 518곳에서 받아 쓰고 있다
> ([`info/hospital_score/`](info/hospital_score/README.md) 참고). 따라서 OCR이 메워야 할
> 공백은 **tPA와 당직 편성** 쪽으로 좁혀졌다.

---

## 현재 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| ① `schema.py` | 출력 형식 정의 + 검사기 | ✅ 완료 |
| ② fixture + client | 데이터 통로, API 없이 개발 가능하게 | ✅ 완료 |
| ③ 정규화 매퍼 | E-Gen 원본 → `HospitalInfo` | ✅ 완료 |
| ④-a 계약 검증 | hub의 실제 모델로 파싱되는지 | ✅ 통과 (4/4) |
| **⑦ 실 API 연동** | `HttpEgenClient` + 매핑표 실측 확정 | ✅ **완료 (2026-08-10)** |
| **⑧ 시계열 축적** | `snapshot.py` — 원본 응답 주기 저장 | ✅ **가동 중** (전국 443곳 · 20분, 2026-08-12~) |
| **⑩ 신뢰도 진단·점수** | `hospital_score/` — 심평원 대조 + 계층 점수 | ✅ **구현 완료 · hub 연동 대기** |
| ④-b 매칭 검증 | hub 엔진에 넣어 순위 확인 | ⏳ 실행 대기 |
| ⑤ 시연 데이터 | 시나리오 3종용 값 설계 | ⏳ ④-b 이후 |
| ⑥ 브랜치 구조 통합 | `Hospital_inform/` → 브랜치 폴더 구조에 편입 | ⏳ ④-b 이후 |
| ~~⑨ 병상 추정 v1~~ | 스냅샷 → 중앙값 테이블 + 백테스트 | ❌ **폐기 (2026-08-12)** |

⑦·⑧이 번호상 뒤에 붙은 것은 서비스키가 늦게 승인돼 순서를 벗어나 들어왔기 때문이다.

**⑨는 만들기 전에 숫자로 접었다.** 서울 6,519쌍으로 잰 `P(만실 전환) = 0.568%`
(95% CI 0.41~0.78%, 10분 지평)가 **사전에 등록해둔 폐기 기준 2%**에 크게 못 미쳤다.
전국 50,133쌍(20분 지평)은 0.301%로 더 낮다. 병상은 움직이지만 0까지 가는 일이 거의
없어, 예측이 최대로 맞아도 얻는 이득이 모델 오차보다 작다. 그 대신 같은 스냅샷으로
**신고 자체의 신뢰도를 진단하는 쪽(⑩)**으로 방향을 틀었다.

이 판정은 명령 하나로 재현된다 — `python -m hospital_score.discarded --seoul-only`
(API 호출 0회). 최초 분석(2026-08-11)이 적어둔 `0.618%`와 신뢰구간이 겹쳐, 다른
시점·다른 코드로 두 번 계산해 같은 결론이 나왔다.

**⑧은 전국 20분 주기로 돌고 있다** (`snapshot_nationwide.bat`, Windows 작업 스케줄러).
`--stage1`을 비우면 전국이 1회 호출로 오므로 **호출 횟수는 서울만 받을 때와 같다.**

---

## 구조

```
Hospital_inform/
├── README.md                            이 문서
├── hospital-info-interface-proposal.md  hub·voice에 보내는 인터페이스 변경 제안
├── snapshot.bat                         시계열 수집 1회 — 서울 (작업 스케줄러 등록용)
├── snapshot_nationwide.bat              시계열 수집 1회 — 전국 (현재 가동 중, 20분 주기)
└── info/
    ├── schema.py            출력 형식 정의 + 검사기 (가장 아래 계층, 아무것도 import 안 함)
    ├── egen/
    │   ├── client.py        데이터를 어디서 가져오나 (Fixture / Supabase / Http 세 구현)
    │   └── mapper.py        가져온 걸 어떻게 바꾸나  ★본체
    ├── build_hospitals.py   실행 진입점 — 변환해서 JSON으로 떨어뜨린다
    ├── snapshot.py          실행 진입점 — 원본 응답을 시계열로 쌓는다
    ├── verify_with_hub.py   hub 엔진 연동 검증 (검증 전용, 프로덕션 아님)
    ├── hospital_score/      신뢰도 진단·외부 대조·점수   (격리 폴더, 아래 참고)
    │   ├── README.md        상세 문서 + 팀 요청 사항
    │   ├── vocabulary.py    MKioskTy 28항목 · 15그룹 · 연령축
    │   ├── dataset.py       스냅샷 JSONL → 시각별 관측
    │   ├── report.py        신뢰도 진단 리포트 (API 호출 0회)
    │   ├── scoring.py       계층 기반 점수 · 불변식 · 전송 객체 조립  ★본체
    │   ├── hira.py          심평원 상세정보 2.8 · 병원정보 v2 · 좌표 조인
    │   ├── hira_files.py    심평원 파일데이터 (전문병원 지정 현황)
    │   ├── rejection.py     거절 이유 어휘 · 로그 · 축별 집계
    │   └── ingest.py        거절 로그 수신구 (POST /hub/rejection)
    └── data/                (전부 커밋 안 함 — .gitignore의 `data/`가 경로 무관으로 걸린다)
        ├── fixtures/            E-Gen 응답을 흉내낸 가상 데이터
        ├── output/              변환 결과 JSON
        ├── snapshots/           원본 응답 시계열 — 서울 55곳 (2026-08-12 중단)
        ├── snapshots_nationwide/ 원본 응답 시계열 — 전국 443곳 (가동 중)
        ├── hira/                심평원 캐시 (조인 518곳 · 전문의 518곳 · 전문병원 114곳)
        └── rejections/          거절 로그 JSONL (append-only)
```

의존 관계는 `{build_hospitals, snapshot} → {client, mapper} → schema` 한 방향이다.
`schema.py`가 아무것도 import하지 않는 것은 `feature/hub`의 구조를 그대로 맞춘
것으로, 팀원이 우리 코드를 볼 때 익숙한 배치가 되도록 한 의도다.

`hospital_score/`는 이 의존 그래프에 **들어오지 않는다.** 바깥 모듈을 import 하지 않고
바깥에서도 이 폴더를 import 하지 않아서, 폴더째 지워도 위 경로가 그대로 돈다(검증 전인
트랙을 기존 파이프라인과 섞지 않으려는 의도). 유일한 예외는 `scoring.py --payload`가
"합친 전송 객체가 실제로 어떻게 생겼는지" 보여주려고 `egen.mapper`를 **함수 안에서 지연
import** 하는 것이고, 라이브러리 본문은 여전히 격리돼 있다.

`verify_with_hub.py`는 성격이 다르다. 우리 산출물이 hub에서 실제로 도는지
확인하는 **검증 도구**이며, 구급차 GPS와 voice 요약 샘플처럼 info의 것이 아닌
데이터를 갖고 있다. 브랜치 구조에 편입할 때(⑥) 프로덕션 모듈과 분리한다.

---

## 실행

아래 명령은 전부 `Hospital_inform/`에서 실행한다.

### 변환 (실제 E-Gen API) — 기본

```bash
cd Hospital_inform
conda activate dev          # Python 3.12
pip install pydantic requests python-dotenv

python info/build_hospitals.py --http                  # 서울 전체
python info/build_hospitals.py --http --stage2 강남구    # 시군구 한정
```

`Hospital_inform/.env`에 아래 한 줄이 있어야 한다 (`.gitignore`에 이미 등록돼 있다):

```
EGEN_SERVICE_KEY=발급받은키
```

서비스키는 **인코딩/디코딩 두 종류**로 발급된다. 둘 중 아무거나 넣어도 되게
`HttpEgenClient`가 알아서 정규화한다(`%`가 들어 있으면 인코딩된 것으로 보고 되돌린다).
그래도 인증이 안 되면 **키 반영 대기**일 수 있다 — 승인 직후 최대 24시간 걸린다.

`STAGE2`(시군구)를 비우면 **시도 전체가 1회 호출로** 온다. 자치구를 25번 나눠 부르면
개발계정 일일 한도가 금방 닳으므로 특별한 이유가 없으면 비워 둔다.

### 변환 (fixture — 키 없이 개발할 때)

```bash
python info/build_hospitals.py
```

`info/data/fixtures/`를 읽어 `info/data/output/`에 병원 1곳당 JSON 1개를 쓴다.
fixture는 커밋되지 않으므로 **처음 클론했다면 먼저 만들어야 한다** (아래 참고).

### 시계열 축적

```bash
python info/snapshot.py                   # 1회 — 서울 (기본값)
python info/snapshot.py --interval 600    # 600초마다 반복 (콘솔 상주)

# 전국 — 현재 상시 수집이 도는 형태 (snapshot_nationwide.bat이 이 명령을 부른다)
python info/snapshot.py --stage1 "" --dir "info\data\snapshots_nationwide"
```

`--stage1`을 비우면 **전국이 1회 호출로 온다.** 시도를 나눠 부를 필요가 없어서
전국 스냅샷의 호출 횟수가 서울만 받을 때와 **같다.** 저장 폴더를 `--dir`로 나눠
두는 이유는 파일 이름이 둘 다 `YYYY-MM-DD.jsonl`이라 섞이면 구분이 안 되기 때문이다
(전국이 서울을 포함하므로, 분석할 때 서울만 보려면 `hpid` 접두어 `A11`로 거른다).

E-Gen은 "지금 값"만 주고 **과거 이력을 주지 않는다.** 나중에 몰아서 받을 방법이 없어서
지금부터 직접 찍어 쌓는다. `data/snapshots/YYYY-MM-DD.jsonl`에 **가공하지 않은 원본
행**을 append한다 — `HospitalInfo`로 변환한 결과를 저장하지 않는 이유는, 매핑 해석이
나중에 또 바뀌더라도 과거 데이터를 다시 해석할 수 있어야 하기 때문이다.

호출 실패도 한 줄로 남긴다. 나중에 빈 구간을 볼 때 "그 시각에 데이터가 없었다"와
"그 시각에 호출이 실패했다"를 구분할 수 없으면 원인을 알 수 없다.

좌표·기관분류는 거의 안 바뀌므로 **하루 한 번만** 부르고 실시간 두 오퍼레이션만 매
주기 부른다. 10분 주기 기준 하루 289회(= 144 × 2 + 1), **20분 주기 기준 하루 145회**다.

상시 수집은 `.bat`을 Windows 작업 스케줄러에 등록해서 쓴다 (등록 방법은 파일 상단 주석
참고). 현재 도는 것은 **전국 20분 주기**(`snapshot_nationwide.bat`)이고, 서울 전용
(`snapshot.bat`, 10분)은 2026-08-12에 멈췄다 — 전국이 서울을 포함해서다.

> ⚠️ `.bat` 파일은 **반드시 CRLF 줄바꿈으로 저장한다.** LF만 있으면 cmd가 줄을 제대로
> 끊지 못해 주석 조각이 명령으로 실행된다.

### 신뢰도 진단·점수 (`info/hospital_score/`)

쌓인 스냅샷을 읽어 신고의 신뢰도를 진단하고 병원별 수용가능성 점수를 낸다.
전부 `Hospital_inform/info`에서 `-m`으로 부른다 (패키지 상대 import를 쓴다).

```bash
cd info
python -m hospital_score.report              # 신뢰도 진단 리포트 (API 호출 0회)
python -m hospital_score.discarded           # 폐기 판정 근거 재계산 (API 호출 0회)
python -m hospital_score.scoring --check --validate   # 불변식 + 홀드아웃 검증
python -m hospital_score.scoring --payload 한강성심     # hub로 보낼 합친 객체 실물
```

**새 장비에서는 심평원 캐시를 먼저 한 번 만들어야 한다** — `data/`는 커밋되지 않는다.

```bash
python -m hospital_score.hira_files --fetch  # 전문병원 지정 현황 (API 2회)
python -m hospital_score.hira --build-join   # 조인 + 전문의 수 (API 약 520회)
```

캐시가 없어도 점수는 나오지만 **심평원 근거가 통째로 빠져 미상이 전부 `unknown_bare`로
떨어진다.** 자세한 것은 [`info/hospital_score/README.md`](info/hospital_score/README.md).

여기서는 pydantic만 있으면 되고 torch·onnxruntime은 필요 없다. `ocr/`의 무거운
스택(이미지 → 텍스트)은 이 경로와 무관하다 — 다만 `ocr/`의 필드 추출 패키지
(`goldenlink_extract`) 역시 pydantic 하나로 돌게 만들어져 있어, 그쪽도 GPU 없이
개발할 수 있다.

### 변환 (Supabase 대체 DB — 역할 종료, 대조용으로만 남김)

> 서비스키 승인 전까지 실제 API를 대신하던 경로다. 이제 `--http`가 있으므로 평소에는
> 쓸 일이 없고, 대체 DB와 실제 응답을 비교해 볼 때만 쓴다.

```bash
cd Hospital_inform
conda activate dev
pip install supabase python-dotenv   # 버전 고정은 설치 후 `pip freeze`로 확인해 채워 넣을 것
```

`Hospital_inform/.env`에 아래 두 값을 채운다 (이 파일은 `.gitignore`에 이미
등록되어 있어 커밋되지 않는다):
```
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_KEY=sb_secret_...
```

**반드시 secret key(`sb_secret_...`, 예전 이름 service_role key)를 써야 한다.**
`hospitals` 테이블은 RLS(Row Level Security)를 켜둔 상태라, publishable
key(예전 이름 anon key)로는 정책을 따로 만들지 않는 한 조회 결과가 조용히
0건으로 나온다 (에러 없이 빈 결과만 돌아오므로 헷갈리기 쉽다).

```bash
python info/build_hospitals.py --supabase
```

`supabase/schema.sql`을 Supabase 프로젝트의 SQL Editor에서 먼저 실행해 `hospitals`
테이블을 만들어둬야 한다. `SupabaseEgenClient`(`egen/client.py`)가 그 테이블을
읽어 E-Gen 원본 필드명으로 다시 포장해주므로, 매퍼(`mapper.py`)는 fixture를 쓸
때와 코드가 완전히 동일하다.

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

실응답은 필드가 115종이지만 매퍼가 실제로 읽는 것은 아래뿐이다 (이름은 활용가이드
V4로 대조 확인했다).

| 오퍼레이션 | 필드 |
|---|---|
| 가용병상 | `hpid` `dutyName` `hvidate` `hvs38`(총 병상)<br>병상: `hvec`(일반) `hv28`(소아) `hv29`(응급실 음압격리) `hvicc`([중환자실] 일반) `hv34`([중환자실] 심장내과) `hvoc`(수술실)<br>장비: `hvctayn`(CT) `hvangioayn`(혈관촬영기) |
| 목록정보 | `hpid` `dutyName` `wgs84Lat` `wgs84Lon` |
| 중증질환 | `hpid` `dutyName` `MKioskTy1`~`MKioskTy28` (매핑하는 것은 1·2·3·4·17) |

fixture를 새로 만들 때는 **정상 데이터만 넣지 말 것.** 아래를 최소 1건씩 넣어야
결측·이상 처리 코드가 실제로 검증된다. 전부 실제 응답에서 관측된 형태다.

- 미입력 `-1`
- **과밀(음수) `-24`** — 미입력이 아니라 관측값이다
- 필드 자체가 빠진 병원 (E-Gen은 미입력을 필드 누락으로도 표현한다)
- 병상 수 자리에 `Y`/`N`이 오는 필드 (`hv11` 등)
- 총 병상보다 큰 가용 병상 (입력 오류)
- 중증질환 값 `Y`(뒤에 공백 있음) / `불가능` / `정보미제공`
- 특정 병원이 한쪽 응답에만 있는 경우

### 결측 처리 규약

`0`과 "미상"을 절대 섞지 않는다. 이 구분이 무너지면 정보가 손실된다.

| 원본 값 | 의미 | 표현 |
|---|---|---|
| `5` | 관측된 가용 병상 | `bedsByType`에 키가 있고 값이 `5` |
| `0` | 확인된 만실. 갈 수 없다 | `bedsByType`에 키가 있고 값이 `0` |
| `-24` | **과밀.** 정원보다 24명 많다 | `0`으로 낮춰 담고, 원래 값은 리포트에 남긴다 |
| `-1` | 미입력. 알 수 없다 | `bedsByType`에 **키 자체가 없음** |
| 필드 누락 | 미입력. 알 수 없다 | `bedsByType`에 **키 자체가 없음** |
| 총 병상 초과 | 입력 오류. 값이 아니다 | `bedsByType`에 **키 자체가 없음** + 리포트 |

**`-1`만 미입력이다.** `-2` 이하는 미입력이 아니라 과밀이며, 둘을 뭉개면 가장 갈 수
없는 병원이 "모르는 병원"으로 남아 후보에 계속 오른다. 과밀을 `0`으로 낮추는 것은
스키마가 음수를 막기 때문인데(`schema.py`의 `ge=0`), `0`은 "확인된 만실"이라 거짓이
아니다 — 지금 갈 수 없다는 사실은 같고 미상과도 여전히 구분된다. 다만 **과밀의
정도(-24인지 -2인지)는 여기서 사라지므로**, 그 값이 필요하면 스냅샷 원본을 본다.

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

## 실측으로 확인한 것 (2026-08-10 · 서울특별시 전체)

서비스키가 승인되어 실제 응답을 처음 받았다. 활용가이드 V4로 필드 이름까지 대조해
`egen/mapper.py`의 `[추정]`·`[미확인]` 표시를 **전부 없앴다.**

### 틀렸던 가정 3개 — 셋 다 조용히 잘못된 값을 내보내고 있었다

| 가정 | 실제 | 무슨 일이 있었나 |
|---|---|---|
| `-1` 이하는 미입력 | **`-1`만 미입력.** `-2` 이하는 과밀(정원 초과) | 서울 55곳 중 6곳(전부 상급종합병원)의 과밀 상태가 "미상"으로 세탁되고 있었다. **가장 갈 수 없는 병원이 "모르는 병원"이 된다** |
| `hv11` = 소아 병상 | `hv11`은 **인큐베이터 보유 여부(Y/N)**. 소아 병상은 **`hv28`** | `int('Y')`가 실패해 소아 병상이 늘 미상이었다. **시연 시나리오 ②가 죽어 있었다** |
| 수용가능 값이 `Y`/`N` | `Y` / `불가능` / `정보미제공` 3종 (`Y`에 뒤쪽 공백) | `N`으로 시작하는 값만 불가로 봐서 `불가능`이 미상으로 처리됐다 |

맞았던 것: `MKioskTy1`=[재관류중재술] 심근경색, `2`=뇌경색, `3`=[뇌출혈수술]
거미막하출혈, `hvidate`=`yyyyMMddHHmmss`.

### 고친 뒤 — 어휘의 병상 코드 6개가 전부 채워졌다

3개는 정의만 있고 한 번도 쓰이지 않던 코드다.

| 병상 코드 | E-Gen 필드 | 신고 병원 (55곳 중) |
|---|---|---|
| `ER_ADULT` | `hvec` 일반 | 55 |
| `ER_PEDIATRIC` | `hv28` 소아 | 23 |
| `ER_NEGATIVE` | `hv29` 응급실 음압격리 | 37 |
| `ICU` | `hvicc` [중환자실] 일반 | 35 |
| `CCU` | `hv34` [중환자실] 심장내과 | 12 |
| `OR` | `hvoc` [기타] 수술실 | 54 |

`ICU`는 `hv2+hv3`(내과+외과) 합산에서 `hvicc`로 바꿨다. 어휘의 ICU 정의가 "일반
중환자실"이라 `hvicc`가 정확한 대응이고, 신고 병원 수도 22 → 36으로 넓다.

### 역량 — 장비 가용 여부가 가용병상 응답에 같이 온다

`hvctayn`·`hvangioayn`을 연결해 "역량 정보가 전혀 없는 병원"이 21곳 → 1곳이 됐다.

| 역량 코드 | 보유 병원 |
|---|---|
| `EQP_CT_24H` | 54 |
| `EQP_ANGIO_SUITE` | 38 |
| `PROC_PCI_EMERGENCY` | 33 |
| `PROC_CRANIOTOMY` | 31 |
| `PROC_EVT_THROMBECTOMY` | 29 |
| `PROC_CESAREAN_EMERGENCY` | 22 |
| `PROC_IV_THROMBOLYSIS` | **0** |

### 커버리지 실측 — OCR 존폐 질문의 답

**E-Gen이 시술 역량 상당 부분을 덮는다. 다만 E-Gen만으로는 못 덮는 것이 있다.**

- **`PROC_IV_THROMBOLYSIS`(tPA)** — `MKioskTy` 28개 항목 어디에도 없다.
  뇌경색은 재관류중재술(`MKioskTy2`)로만 묻고 정맥 혈전용해술은 따로 묻지 않는다.
  **다른 공개 API에도 없어서 서류로만 채울 수 있다**
- **진료과별 의사 수** — E-Gen에는 없다(`doctorCount`가 늘 `0`인 이유). 다만
  **2026-08-12에 심평원 의료기관별상세정보서비스로 해결됐다** — 전문과목별 전문의 수를
  병원 518곳에서 받아 `data/hira/specialists.json`에 캐시해 두고 있다.
  `mapper.build_specialties()`의 `doctorCount=0`은 아직 이 값과 배선되지 않은 상태다
- **당직 편성** — "그 과에 오늘 밤 누가 있는가"는 어느 공개 API에도 없다.
  현재 `nightDutyAvailable`은 중증질환 수용가능 신고를 **프록시**로 쓰고 있다

따라서 OCR을 동결하지 않는다. 다만 **무엇을 메워야 하는지가 tPA·당직 편성으로
구체적으로 좁혀졌다.**

### 그 밖에

- **병상 "미상"은 서울에 거의 없다** (55곳 중 0~1곳). 병원들이 병상 수는 성실히
  입력한다 → 미상 보간보다 **도착 시점 예측**이 실제 문제다
- **입력 오류가 있다** — 국립중앙의료원이 거의 전 필드에 `12312` 같은 시험값을
  넣어 뒀다. 임의의 상한 대신 그 병원이 신고한 총 병상(`hvs38`)을 넘으면 버린다
- **`STAGE2` 생략 시 시도 전체가 1회 호출로 온다** — 자치구 25번 호출이 불필요해져
  개발계정 트래픽 한도에 여유가 생겼다
- 값은 실제로 계속 변한다 — 14분 사이 과밀 병원 목록과 수치가 전부 바뀌었다

---

## 미해결 항목

### 1. ~~상시 수집이 안 돌고 있다~~ → **해결 (2026-08-12)**

`snapshot_nationwide.bat`을 작업 스케줄러에 등록해 **전국 443곳을 20분 주기로** 쌓고
있다. 이 데이터가 `hospital_score/`의 진단·점수 전부의 입력이 됐다.

남은 것은 **보존**이다. `data/`는 커밋되지 않으므로 이 장비의 폴더가 유일본이고,
E-Gen은 과거 이력을 안 줘서 **지우면 복구할 방법이 없다.**

### 2. 개발계정 일일 트래픽 한도 미확인

폴링 주기가 여기서 정해진다. 마이페이지 → 활용신청 상세에서 확인한다.
한도 1,000회 기준으로 20분 주기(하루 145회)면 여유가 크다.
(심평원 쪽은 일일 800,000회로 확인돼 사실상 제약이 없다.)

### 3. 과밀을 hub·dashboard에 어떻게 보여줄 것인가

지금은 `0`으로 낮춰 보내서 **"확인된 만실"과 구분되지 않는다.** 삼성서울 `-24`와
일반 만실 `0`은 구급대원에게 다른 정보다. 노출하려면 스키마에 필드를 더해야 하고
팀 합의가 필요하다 (`availableBedCount`는 `ge=0`이라 음수를 그대로 못 담는다).

---

## 팀 확인 요청

### 1. ~~명세 오류~~ → **정정 완료 (`CLAUDE.md`에 반영됨)**

활용가이드 V4와 실응답으로 확인해 아래 내용을 팀 문서에 반영했다. 기록으로 남긴다.

| 처음 적혀 있던 것 | 실제 |
|---|---|
| `hv1` = 별도 API, "전문의 보유 여부" | 가용병상 응답 안의 **필드**. 서울 실응답에는 등장하지 않았다 |
| `hvec` = "병상 현황" API | 가용병상 응답 안의 **필드**. 응급실 **일반** 병상 수 |
| `hv2` = 중증질환 수용 API | 가용병상 응답 안의 **필드**. **[중환자실] 내과** 병상 수 |

중증질환 수용가능은 `getSrsillDissAceptncPosblInfoInqire`라는 별개 오퍼레이션이고
필드는 `MKioskTy1`~`MKioskTy28`이다. 즉 "3개 API"가 아니라 **2개 오퍼레이션 +
필드명 혼동**이었고(좌표를 받는 `getEgytListInfoInqire`까지 합해 오퍼레이션 3개),
이 정정으로 호출 설계 자체가 달라졌다.

> `info/requirements.txt` 상단 주석에는 아직 옛 표기가 남아 있다. 정리 대상.

### 2. hub의 병상 필터 부재

`hub_engine.process_voice_summary()`가 `availableBedCount`를 필터에도 스코어링에도
쓰지 않는다. 결과 JSON에 복사만 된다. **병상이 0인 병원도 1위가 될 수 있다.**

시연 시나리오 ③(만실 → 2순위 대체)이 성립하려면 병상 0 제외가 필요하다.
스키마 변경이 아니라 **이미 있는 필드를 쓰지 않던 것을 쓰는 것**이라 부담이 작다.

> ⚠️ 다만 그냥 `availableBedCount`로 정렬하면 **곧바로 다른 문제가 생긴다.**
> 전국 가용병상 1위(한강성심병원 30병상)가 **2,457일 묵은 값**이고, 2위부터는 전부
> 10분 이내 갱신이라 오염된 것이 정확히 정렬 맨 윗칸 하나다. `bedsByType` 키 유무로
> "미상"을 가려내고, `assessment.conditions.stale`로 낡은 값을 함께 봐야 한다
> ([`info/hospital_score/README.md`](info/hospital_score/README.md) 참고).

### 3. 인터페이스 변경 제안 — 이 폴더 산출물의 근거

`hospital-info-interface-proposal.md` 참고. 매칭 판정을 임베딩 유사도에서
표준 역량 코드 대조로 옮기고, 임베딩은 info의 정규화 단계로 이동시키는 안이다.
`bedsByType`·`capabilities` 확장 필드가 여기서 나왔고, `hospital_score/`의
**15그룹 역량 벡터**도 같은 방향의 연장선이다 — 그룹 이름이 그 자체로 닫힌 enum이라
voice가 고르고 hub가 조회하면 유사도·임계값이 필요 없다.

### 4. `assessment` 필드 수용 — hub와 동시 배포 필요

`hospital_score/`가 만든 판정을 기존 `HospitalInfo`에 `assessment` 키 하나로 얹어
보낼 준비가 끝났다(superset, 병원당 약 5.1KB). **hub의 pydantic이 unknown 필드를
거부하면 보내는 순간 기존 연동이 깨지므로 info 혼자 배포할 수 없다.**
자세한 요청 사항은 [`info/hospital_score/README.md`](info/hospital_score/README.md)의
"팀에 요청하는 것".
