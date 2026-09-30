# feature/info — 작동 · 동작 방식

> 작성일: 2026-09-29 (develop `97182de` 기준)
> 정본 문서: `info/Hospital_inform/info/reliability/README.md`(신뢰도 트랙), `hospital_score/README.md`(수용가능성 트랙) · 공통: 저장소 루트 `CLAUDE.md`, `AIROOKIE-EGEN.md`

---

## 1. 역할과 위치

info는 **E-Gen 공공 API에서 병원 정보(목록·좌표·병상·중증질환 수용신고)를 읽어 구조화하고, 그 정보의 신뢰도 판정·확률까지 붙여 hub로 밀어주는 브랜치**다. 병원 매칭·존 로직은 hub 담당이고(이관 확정), 바이탈 수집은 폐기됐다.

```
E-Gen 실 API (3개 오퍼레이션) ─┐
심평원(HIRA) 3종 (로컬 캐시) ──┤→ send_to_hub.py (30분 상시 프로세스) ──→ hub POST /info/*
구급차 Supabase (별도 프로젝트)┘
스냅샷 축적 (20분 주기 .bat) ──→ reliability 엔진 워밍업 / 학습·재보정·probe 재료
hub ──(거절 로그 POST)──→ hospital_score/ingest.py (포트 5003, 선택적 별도 서버)
```

- **E-Gen 값을 참값으로 취급하지 않는다** — 전부 병원 자가 신고라 같은 소스 안에서 검증 불가. 실측된 구멍: 전국 25곳이 하루 넘게 방치된 병상 값을 실시간 송출(최고 8.6년), 전국 가용병상 1위가 2,457일 묵은 값, 중증질환 신고 "정보미제공" 70.8%, 화상 전문병원 5곳 중 E-Gen에 화상 역량이 보이는 곳 0곳.
- **hub→info 방향은 거절 로그 하나뿐** (병상 갱신 되쓰기는 2026-08-13 폐지 — E-Gen이 조회 전용이라 왕복 불가, hub의 TTL 오버레이로 대체).

## 2. 구성

```
info/send_to_hub.py                 30분 상시 프로세스 (진입점) — fetch → 판정/확률 첨부 → hub 전송
info/Hospital_inform/info/
├── egen/                            E-Gen 실 API 클라이언트(client.py) + HospitalInfo 매핑(mapper.py)
├── schema.py                        HospitalInfo 등 (hub schema.py와 계약)
├── snapshot.py + snapshot_nationwide.bat   E-Gen 원본 스냅샷 20분 축적 (전국 443곳, 가공 전 원본 저장)
├── hospital_score/                  수용가능성·신뢰도 판정 트랙 (HIRA 대조) + 거절 로그
│   ├── scoring.py                   5단계 판정 → HospitalInfo.assessment
│   ├── hira.py / hira_files.py      심평원 수집·조인 (좌표 최근접)
│   ├── ingest.py                    거절 로그 수신 서버 (POST /hub/rejection, 포트 5003)
│   ├── rejection.py                 4축 사유 어휘 (dashboard와 공유)
│   ├── demo_rejections.py           데모 주입기 (demo:true 마커 10건)
│   ├── rejection_report.py          집계 리포트 (--html 자기완결 단일 파일, --exclude-demo)
│   └── report.py / discarded.py     관측치·폐기 판정 재현 (API 호출 0회)
└── reliability/                     병상 정보 신뢰도 모델(infosurv) 서빙 트랙 (벤더링)
    ├── engine.py                    다필드 서빙 엔진 (model/ 자동 발견, 스냅샷 워밍업 60일)
    ├── features.py                  실시간 피처 빌더 (FULL9 — 학습 정의와 어긋나면 로드 시 실패)
    ├── serve.py / fit.py / evaluate.py   infosurv 벤더링 사본
    ├── calibrate.py                 잔차 재보정 (관문: ECE·Brier 둘 다 개선 시만 저장)
    ├── train_field.py               확장 필드 자급 학습 (관문: 이벤트≥2,000 + baseline 시드 3종 전승)
    ├── severe.py / probe_severe.py  중증신고 신선도 (규칙) / 타당성 실측 도구
    ├── selftest.py                  자체검증 (API 호출 0회)
    └── model/                       학습 모델 JSON·리듬 테이블·재보정 상수 (커밋됨)
```

## 3. 동작 방식 — 30분 사이클 (`send_to_hub.py`)

**상시 프로세스**다(1회성 스크립트 아님). hub는 받은 병원 정보를 메모리에 들고만 있고 스스로 재조회하지 않으므로, 이 프로세스가 주기적으로 재조회·재전송한다(`INFO_REFETCH_INTERVAL_SEC`, 기본 30분). hub가 안 떠 있어도 죽지 않고 다음 주기에 재시도.

한 사이클(`sync_once()`)의 순서:

1. **`fetch_hospitals()`** — E-Gen 실 API(`HttpEgenClient`) 3개 오퍼레이션 호출:
   - `getEgytListInfoInqire` (목록·좌표·응급의료기관 등급)
   - `getEmrrmRltmUsefulSckbdInfoInqire` (실시간 병상 6종·장비 — hvec 등)
   - `getSrsillDissAceptncPosblInfoInqire` (중증질환 수용가능 MKioskTy 28항목)
   - `egen/mapper.py`가 `HospitalInfo`로 조립. **병상 미상 표현 규칙**: 미상인 병상 종류는 `bedsByType`에 키를 아예 넣지 않는다 (`availableBedCount`엔 보수적으로 0 — hub가 키 유무로 "미상"과 "확인된 만실" 구분).
   - `hospitalId`는 실 E-Gen hpid (`A1100017` 등). E-Gen이 주는 병원 전체가 hub로 흐른다 (서울 실측 55곳, 전국 500여 곳).
2. **`_attach_assessments()`** — 병원마다 `hospital_score.scoring.score_hospital()`을 그 자리에서 호출해 `assessment` 첨부. 이번 사이클에 이미 받은 raw rows로 입력을 구성 (스냅샷 파일 의존 회피). **fail-soft**: try/except — hospital_score 폴더를 통째로 지워도 assessment 없이 원본 그대로 나감.
3. **`_attach_reliability()`** — reliability 엔진으로 `bedReliability`(hvec) + `bedReliabilityByType`(hvoc/hvgc/hv28) + `severeDeclarations` 첨부. 역시 **fail-soft** — reliability 폴더를 지워도 원본 그대로 나감.
4. **`fetch_ambulances()`** — 병원과는 **별도의 Supabase 프로젝트**(`ambulances` 테이블: apid/name/gps/voicePort)를 읽어 hub `POST /info/ambulances`로 전송. `AMBULANCE_SUPABASE_URL`/`KEY` 없으면 이 부분만 조용히 건너뜀. voice의 실제 IP는 여기 없다 (voice가 뜰 때 hub에 직접 자가등록).
5. **전송** — 병원·구급차를 hub로 POST.

## 4. 수용가능성 판정 트랙 (`hospital_score/`)

**질문: 이 병원의 수용 신고를 믿을 만한가.** 산출물은 `[여건 스칼라 + 15그룹 역량 벡터] + 신뢰도 + 근거` — 병원당 단일 점수는 만들지 않는다 (심근경색 환자와 화상 환자에게 같은 병원의 수용가능성이 다르므로).

- **판정은 최적화가 아니라 근거 강도의 계층 5단계 + 불변식**:
  `불가능 0.2 < 근거없는미상 0.4 < 전문의있는미상 0.6 < 전문병원지정미상 0.8 < 가능신고 1.0`
  **`score`와 `confidence`는 끝까지 곱하지 않는다** — 섞으면 "확실히 낮음"과 "모르겠음"이 구분 불가 (병상 미상 ↔ 확인된 만실 구분 원칙과 동일).
- **외부 대조는 심평원(HIRA) 3종**: 병원정보(getHospBasisList)·의료기관별상세(`MadmDtlInfoService2.8/` — ⚠ 구버전 2.7도 게이트웨이에 실재해 403을 돌려주므로 "경로 맞고 승인만 안 남"으로 오진 주의)·전문병원 지정 현황. 서비스키는 E-Gen과 같은 값 (`HIRA_SERVICE_KEY`).
- **E-Gen↔HIRA 조인은 좌표 최근접** (공통 식별자 없음, hpid↔ykiho): 533곳 중 518곳(97.2%)이 1.2km 이내, 오차 중앙값 11m.
- 홀드아웃 검증(전문병원 지정을 정답으로): **화상 후보 0곳 → 4곳**.
- **새 장비 필수 명령 2개** (HIRA 캐시는 `data/` 아래라 미커밋 — 없으면 미상이 전부 `unknown_bare`로 떨어짐):
  ```bash
  cd info/Hospital_inform/info
  python -m hospital_score.hira_files --fetch    # API 2회
  python -m hospital_score.hira --build-join     # API 약 520회, 이어받기 지원
  ```
- **폐기 판정 (되살리지 말 것, `python -m hospital_score.discarded`로 재현)**: ① 병상 수 예측 — P(만실 전환)=0.568%로 사전 등록 기준 2% 미달. ② 미상 추정 모델 — 관측 라벨 95.6%가 "가능"인 MNAR 편중이라 그대로 쓰면 "미신고 병원도 대부분 수용 가능"이라는 위험한 방향의 오류.

## 5. 병상 신뢰도 트랙 (`reliability/`) — infosurv 벤더링

**질문: 이 병상 숫자가 아직 유효한가.** XGBoost AFT 생존모델(연구 프로젝트 infosurv에서 학습)을 벤더링해 서빙한다. pip 로컬 경로 의존이면 팀원 장비에서 안 돌기 때문에 코드·모델 JSON·리듬 테이블을 저장소에 복사·커밋.

- **피처는 FULL9 고정** (`features.FEATURES`) — 값의 "의미"를 안 보고 변화 패턴만 보는 **내용맹** 설계. claim-version 규칙: 값 변화 = 새 버전, 공백 1시간 초과 = 세그먼트 리셋, 첫 버전 리듬 피처 NaN, 시각 피처 **UTC**(KST면 성능 하락 실측). 엔진이 로드 시 모델의 feature_names와 대조해 어긋나면 그 자리에서 실패.
- **관측 소스 이중화**: ① 같은 장비의 스냅샷 JSONL(20분 해상도, 증분 읽기) 1순위 ② 이번 사이클 rows 2순위. 스냅샷 없어도 30분 해상도로 degrade될 뿐 죽지 않는다. **스냅샷은 이 노트북에만 있다** — 학습·재보정·probe는 이 장비에서만 가능, 팀원 장비는 degrade가 정상.
- **잔차 재보정** (`calibrate.py`): hvec raw가 생존시간을 1.5배 과대예측 → 재보정 상수(μR=−0.431, σR=1.797) 적용, τ30분 ECE 0.272→0.114. 확장 필드는 raw가 이미 정직(ECE 0.03~0.06)해 미적용 (관문이 저장 거부).
- **다필드 확장** (`train_field.py`, 자급 학습): 채택 — 수술실 hvoc(C 0.867)·입원실 hvgc(0.856)·소아 hv28(0.784). 기각 — 중환자실 hvicc(이벤트 1,578 < 2,000, **~2026-10-12 재시도**: `python -m reliability.train_field --field hvicc --theta 2`).
- **hub로 나가는 것**: `bedReliability`·`bedReliabilityByType` = `{predictedSurvivalSec, bornAt, sigma, authorityAtSend, ttlSec, modelTag}` (source: "ai"). authority는 나이에 따라 계속 감소하므로 전송 시점 값은 스냅샷일 뿐 — **hub가 매칭 시점마다 재계산**한다.
- **월 1회 재학습 프로토콜**: 새 모델 JSON 복사 → `python -m reliability.build_route_med_gap`(리듬 테이블 재생성) → selftest. 다음 재학습 때 확장 필드 재보정 창 분리(현재 early stopping 창과 겹침).

## 6. 중증신고 신선도 (`severe.py`) — 모델이 아니라 규칙

47일 실측(`probe_severe.py`)에서 중증질환 신고(MKioskTy)는 값 변화의 90%가 Y↔정보미제공 왕복, 만료 수명의 60.1%가 정확히 9.0시간 = **시스템 자동 만료 규칙**이 지배 → AFT 학습 보류 (진짜 내용 변화 Y↔불가능은 2,658건뿐, ~1개월 축적 후 재평가). 대신 E-Gen 응답에 신고 시각 필드가 없다는 점을 파고들어, **스냅샷 추적만이 아는 "이 신고가 언제부터 이 값이었는지"**를 `severeDeclarations`(source: "rule", 정보미제공 그룹은 키 없음)로 내보낸다 — hub가 신고 나이·9h 잔여로 환산.

## 7. 거절 로그 (운영 데이터의 유일한 정답원)

점수의 진짜 정답은 "병원이 실제로 받았는가" — 운영 로그가 쌓여야 나오고 **소급 생성이 불가**하므로 지금부터 담는 것이 핵심.

- **수신구**: `python -m hospital_score.ingest` (포트 5003, 상시 프로세스와 **별개로 띄우는 선택적 서버** — 안 떠 있으면 hub가 조용히 흡수하고 그 기간 로그는 소실).
- **관대한 수신 원칙**: 필수 필드는 `hospitalId` 하나뿐, 사유 없으면 `UNSPECIFIED`, 모르는 필드는 `extra`에 보존 (어휘 확장이 로그 소실로 이어지지 않게).
- **4축 사유 분류** (`python -m hospital_score.rejection --vocab`): 구조적(NO_WARD/NO_DEPARTMENT/NO_EQUIPMENT → 역량 벡터 수정) / 주기적(ON_CALL_MISMATCH/NIGHT_UNAVAILABLE → 시간대 패턴) / 순간적(BEDS_FULL/OR_OCCUPIED/STAFF_BUSY → 그때의 여건) / 환자 요인(SEVERITY_EXCEEDED/AGE_LIMIT → 병원 속성 아님). 축이 다르면 갱신 대상이 다르다 — 일시적 사정으로 병원을 영구히 밀어내지 않기 위한 설계.
- **결정 시점 스냅샷**(hub가 동봉): `declaredAtRequest`와 대조하면 "가능 신고였는데 거절"을 셀 수 있고, BEDS_FULL 거절 + `*AtRequest` 병상값은 정보 무효의 독립 관측(infosurv G2 라벨 재료).
- **무응답(NO_RESPONSE) 소비 지침**: 수용성 판정에 쓰지 않는다 — 거절은 "수용 능력" 정보지만 무응답은 "채널" 정보. `reachedAtBroadcast` false = 미도달(보급 지표, 병원 탓 아님) / true = 무시(응답성 지표 — 소비처는 순위 강등이 아니라 "전화 확인 우선 대상" 플래그). `caseFinalized` false는 분석에서 별도 격리.
- **데모 도구**: `python -m hospital_score.demo_rejections`(전부 demo:true 마커) → `python -m hospital_score.rejection_report --html` → `data/rejections/report.html`. 실 로그가 쌓이면 `--exclude-demo`로 완전 분리.

## 8. 실행·검증

```bash
# 환경: dev conda env (xgboost 포함)
cd info && python send_to_hub.py                          # 상시 프로세스 (30분 주기)
cd info/Hospital_inform/info
python -m reliability.selftest                            # 신뢰도 트랙 전체 검증 (API 0회) — "전부 통과" 확인
python -m hospital_score.report                           # 관측치 리포트 (API 0회)
python -m hospital_score.ingest                           # 거절 로그 수신 서버 (포트 5003)
python -m hospital_score.rejection_report --html          # 거절 집계 HTML
```
⚠ Git Bash 파이프에서 selftest 등이 `UnicodeEncodeError`(cp949)로 죽으면 `PYTHONIOENCODING=utf-8` 프리픽스 (코드 결함 아님).

## 9. 설계 원칙 (되살리지 말 것 / 지킬 것)

- **fail-soft 계층화**: hospital_score·reliability 어느 트랙을 통째로 지워도 send_to_hub는 원본만으로 계속 동작.
- **신뢰도는 전부 순위 불개입 설명용** (유일 예외: declared_no 정렬 강등, hub 담당). score×confidence 곱 금지.
- **후보 제거 금지** — 미상·낡음·무응답 어느 것도 병원을 후보에서 빼는 근거가 아니다.
- **측정 후 결정 — 기각 이력 3가지 되살리지 말 것**: ① 신고 나이 기반 confidence 강등 (나이는 낡음이 아니라 성실성의 증거 — 99.5% 실측) ② "무신호=방치" 게이트 (무신호 병원 59곳의 병상 채널이 활발 — 전제 오류) ③ hvidate 피처·Disagreement 피처 (연구 쪽 기각).
- **가공 전 원본 스냅샷 보존**: 매핑 해석이 바뀌어도 과거 데이터를 재해석할 수 있어야 한다 (가공본만 남기면 매핑 수정마다 과거가 죽는다).
