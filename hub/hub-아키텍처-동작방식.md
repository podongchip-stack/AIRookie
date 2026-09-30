# feature/hub — 아키텍처 · 동작 방식 · 연산 방식 · 스키마

> 작성일: 2026-09-29 (develop `97182de` 기준)
> 정본 문서: `hub/README.md` ("입출력 데이터 포맷"이 스키마 정본) · 공통 컨텍스트: 저장소 루트 `CLAUDE.md`

---

## 1. 역할과 위치

hub는 **voice(환자 정보)와 info(병원 정보)를 결합해 병원 후보를 매칭하고, dashboard와 직접 통신하는 유일한 브랜치**다. voice·info는 dashboard로 직접 보내지 않고 전부 hub를 거친다.

```
feature/voice ──(의료 정보·예상 병명·통화 전문, HTTP)──→ ┌─────────┐
feature/info  ──(병원 정보 + assessment/신뢰도, HTTP)──→ │   hub    │──(통합 매칭 결과, WebSocket)──→ dashboard
dashboard     ──(승인 액션 / 통화 신호, WebSocket)──────→ │ 포트 5001 │──(통화 신호 HTTP 중계)────────→ voice
                                                          └─────────┘──(거절 로그 POST, fire-and-forget)→ info(:5003)
```

- 처리 원칙: **거리·존·최종 스코어링은 규칙 기반**(source: "rule"), **진료과 매칭만 경량 임베딩 모델**(paraphrase-multilingual-MiniLM-L12-v2, 코사인 유사도, 결정적·점수 노출)로 보조. 생성형 LLM은 어디에도 안 쓴다.
- 후보 **제거 금지 원칙**: 어떤 이유로도 병원을 후보에서 빼지 않는다 — 뒤로 내릴 뿐(뺑뺑이 방지가 목적이라 잘못 걸러내는 게 더 위험).

## 2. 아키텍처 (모듈 구조)

```
app.py                서버 (Flask + 순수 WebSocket, socket.io 아님) — 소켓 집합 관리·브로드캐스트·중계
hub_engine.py         HubEngine — 상태 보관 + 2단계 매칭 오케스트레이션 + 승인 처리 (계산 모듈을 유일하게 조립)
├── schema.py         pydantic 입출력 모델 — 최하위 계층, 아무것도 import 안 함 (dashboard/src/types/dashboard.ts와 1:1 계약)
├── geo.py            GPS 직선거리·존 분류·존 확장 판단 (독립)
├── specialty_matcher.py  예상 병명 ↔ 진료과 임베딩 매칭 (독립)
├── scoring.py        가중합 점수·순위 결정 rank()/rank_key() (독립)
├── routing.py        카카오 ETA (키 없으면 직선거리 폴백, 5분 캐시)
├── bed_reliability.py    병상 신뢰도 확률 환산 — log-normal AFT 생존함수를 표준 라이브러리로 재구현 (scipy 회피)
└── decision_log.py   의사결정 로그 (append-only JSONL + SHA-256 해시 체인)
delivery.py           결과 로컬 저장 + info 거절 로그 전송 (매칭 로직과 완전 분리)
```

geo/specialty_matcher/scoring은 서로를 전혀 모르고 hub_engine에서만 조립된다 — 모델 교체가 로직에 영향을 주지 않게 하는 CLAUDE.md 원칙의 구현.

## 3. 동작 흐름

### 3-1. 2단계 매칭
1. **1단계 (사전 준비)**: info가 30분 주기로 보내는 병원 정보 + 구급차 GPS로 **존(Zone) 기반 후보 리스트**를 만들어 보관한다. 존 판정은 직선거리(외부 호출 없이 빨라야 하는 1차 필터).
2. **2단계 (voice 도착 시)**: `/voice/summary`로 환자 정보가 오면, 예상 병명(`summary.mechanism`)을 병원 진료과와 임베딩 유사도로 매칭한 점수 + 이동시간 점수를 가중합해 리스트를 재처리하고, WebSocket으로 dashboard에 브로드캐스트한다.

### 3-2. 서버 운영 (app.py)
| 동작 | 내용 | 환경변수 |
|---|---|---|
| 비동기 매칭 | `/voice/summary`는 검증만 하고 **202로 즉시 응답**, 매칭(임베딩+카카오)은 작업 스레드 1개에서 순서대로 | — |
| 주기적 재계산 | 진행 중 사건을 재계산해 **바뀐 것만** 재전송 (이송 중 순위가 저절로 갱신됨) | `HUB_REFRESH_INTERVAL_SEC` (기본 60) |
| 상태 저장·복구 | 병원·구급차·승인·병상 오버레이·사건·voice 주소를 5초마다(변경 시) 저장, 재시작 시 복구. **통화 원문은 저장 안 함** | `HUB_STATE_PATH`, `HUB_PERSIST_STATE=0`로 끔 |
| 스레드 안전 | 엔진 상태는 락 안에서만, 임베딩·카카오 호출은 락 밖에서 (승인 액션이 안 막히게) | — |
| 사건 정리 | 확정 후 60분 지난 사건을 read-time lazy 정리 (`_prune_old_cases`) | `CASE_RETENTION_MIN=60` |
| 미결 sweep | 확정 없이 120분 유휴면 NO_RESPONSE 로그만 남김 (사건은 안 지움) | `HUB_UNRESOLVED_TIMEOUT_MIN=120` |

### 3-3. 다중 사건·다중 소켓
- `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분. 승인 상태는 `(caseId, hospitalId)` 키로 격리.
- dashboard 소켓은 **집합**으로 관리해 전체 브로드캐스트 (과거: 전역 변수 하나 → 마지막 탭만 갱신받는 버그).
- 소켓 연결 직후 `identify` 자기소개 → ① `identity_info`(이름/존재 여부 즉시 응답) ② 관련 진행 중 사건들을 `HubMatchResult` 형식 그대로 따라잡기 전송 (`_send_catchup`).
- 승인 액션 처리 후 캐시된 결과의 해당 병원 status만 패치 + **재정렬**해 재브로드캐스트 (재계산 없음).

### 3-4. 통화 신호 중계
dashboard "통화 시작/종료" 버튼 → 같은 WebSocket으로 수신 → hub가 **그 apid의 voice 주소로 HTTP 중계**. voice 주소 = voice 자가등록 IP(`POST /voice/register`) + info가 보낸 `AmbulanceInfo.voicePort`. 오디오는 hub를 거치지 않는다(브라우저 마이크 프레임은 받고 버림 — 실제 STT는 voice 로컬 마이크).

### 3-5. 병상 차감 — TTL 오버레이
`final_approval`마다 `_bed_overlay`(hpid → 만료 시각 목록)에 기록 하나를 쌓고, `effective_bed_count()`가 **조회 시점에** 만료 안 된 개수만큼 원본에서 빼서 보여준다. `BED_OVERLAY_TTL_MIN=15`분 — hvidate 갱신 간격 실측(중앙값 5분, 88.7%가 10분 이내)에 여유를 둔 값. 원본 `HospitalInfo`는 mutate하지 않으므로 info의 최신값을 매번 덮어써도 안전하다. **info로 되돌려 쓰는 병상 갱신은 2026-08-13 완전 폐지** (E-Gen이 조회 전용이라 왕복 불가).

### 3-6. 거절 로그 중계 (hub → info)
`hospital_reject`마다 `_rejection_payload()`로 아래를 만들어 `HUB_REJECTION_URL`(기본 `http://127.0.0.1:5003/hub/rejection`)에 POST. **fire-and-forget** — 수신구가 안 떠 있어도 승인 처리는 계속.
- 기본: `hospitalId`·`caseId`·`timestamp`·`reasonCode`(4축 어휘, 없으면 UNSPECIFIED)
- 사건 캐시 best-effort: `severity`·`diseaseGroup`·`declaredAtRequest`
- **결정 시점 스냅샷**: `availableBedCountAtRequest`·`bedCountUnknownAtRequest`·`bedDataStaleAtRequest`·`travelMinAtRequest`·`finalScoreAtRequest`·`bedAuthorityAtRequest`·`bedRArriveAtRequest` (infosurv G2 라벨·확률 운영 검증 재료 — 소급 생성 불가)
- **무응답(NO_RESPONSE)**: 사건 결말 두 시점(final_approval 확정 / 미결 120분 sweep)에 pending 후보 일괄 기록. `reachedAtBroadcast`(도달 이력 — false=미도달=보급 지표, true인데 무응답=응답성 지표)·`caseFinalized`로 소비 축 분리. **무응답은 수용성 판정에 쓰지 않는다.**

### 3-7. 의사결정 로그 — 해시 체인
`data/logs/decision_log.jsonl`에 append-only. 기록 = `{timestamp, eventType, payload, prevHash, hash}`, `hash` = 전체의 SHA-256, **`prevHash` = 앞 기록의 hash** (체인 — 중간 한 줄만 건드려도 뒤가 전부 어긋남. 한계: 파일 끝 잘라내기는 체인만으론 못 잡음). 통화 전문은 `_redact_transcript()`가 `{"sha256", "chars"}` 지문으로 치환해 기록 (dashboard로 나가는 결과 자체는 전문 유지). `verify_log()`로 전체 검증.

## 4. 연산 방식 (순위·확률)

### 4-1. finalScore와 정렬
```
finalScore = 0.6 × 진료과 유사도 + 0.4 × 이동시간 점수
이동시간 점수 = 0.5^(이동분 / 15)     ← 15분마다 절반, 절대 0이 안 됨
```
- 이동분: 카카오 ETA 우선 → 없으면(키 없음·반경 10km 밖) 직선거리 × **같은 사건에서 ETA 받은 병원들의 분/km 중앙값**(표본 없으면 1.5분/km)으로 보정 추정. 출처는 `travelBasis`(`"eta"`|`"estimate"`)로 노출.
- 정렬 (`scoring.rank_key()`): ① finalScore 내림차순 → ② `declared_no`(수용 불가 신고)·`beds_full`(**확인된** 만실만 — 미상·1일 초과 stale 값 제외) → ③ 맨 뒤 `rejected`. 내린 이유는 `demoteReasons`로 나감.
- **승인·확정 응답을 한 병원은 declared_no·beds_full로 안 내린다** (명시적 응답 > 사전 신고. 확정 직후 오버레이로 0이 된 병원이 자기 사건에서 만실로 밀리는 것 방지).
- 진료과 매칭 실패(유사도 낮음·진료과 정보 없음)해도 제외하지 않는다 — 거리 기준만으로 순위에 남김.
- `nightDutyAvailable`은 순위에 안 쓴다 (`bool(capabilities)` 프록시라 진료과 신호의 중복 반영).

### 4-2. 존(Zone) 로직
- 존 = 직선거리 구간 그룹 (zone 1 = 0~5km, ...).
- `resolve_start_zone()`: 첫 매칭 시 후보가 하나라도 잡힐 때까지 확장 (후보 0개 사각지대 — 거절 비율 방식으론 못 잡음).
- `maybe_expand_zone()`: **명시적 거절 비율** 기준, `hospital_reject` 액션 뒤에만 호출 (reject_ratio가 누적 계산이라 승인 뒤에 부르면 새 거절 없이 계속 확장되는 버그 → gating으로 해결).

### 4-3. 신뢰도 3축 — 전부 순위 불개입 설명용 (유일 예외: declared_no 정렬 강등)
| 축 | 소스 | 질문 | hub의 처리 |
|---|---|---|---|
| `reliability` | info `assessment` (hospital_score, HIRA 대조) | 이 수용 신고를 **믿을 만한가** (5단계 서수 티어) | 예상 병명을 15개 질환군 어휘와 매칭해 그 그룹 판정을 그대로 전달. `declared_no`만 정렬 강등 |
| `bedReliability` | info infosurv AFT 모델 (source: "ai") | 이 병상 **숫자가 아직 유효한가** (캘리브레이트된 확률) | **매칭 시점마다 재계산** — 아래 4-4 |
| `severeFreshness` | info `severeDeclarations` (source: "rule") | 이 신고가 **언제 적 것인가** | 신고 나이 + 9시간 자동 만료 규칙 잔여 환산 |

가중합으로 안 섞는 이유(실측): declared_no의 역전을 완전히 막으려면 신뢰도 가중치가 70%대까지 필요 → 거리·진료과가 무의미해짐. 거절 로그가 쌓여 실측 기반 가중치가 나오면 승격 재검토 (특히 `rArrive`의 `finalScore × rArrive` 곱 구조 — AIROOKIE-EGEN.md §5-1).

### 4-4. 병상 신뢰도 확률 환산 (`bed_reliability.evaluate()`)
info가 보내는 `predictedSurvivalSec`(예측 생존시간)·`bornAt`(claim 탄생 시각)·`sigma`(재보정된 곡선 척도)로, log-normal AFT 생존함수를 매칭 시점마다 계산:
- **authority** = S(age) — 지금 이 숫자를 믿어도 될 확률
- **rArrive** = 도착 시점(horizon = 순위에 쓴 `travelMin`과 동일)에도 유효할 확률
- **ttlSec** = authority가 0.8 아래로 떨어질 때까지 남은 초
- **조건부 생존 S(a)/S(u)**: 병원이 `info_confirm`("현재 정보가 맞습니다")을 누르면 확인 시각 u 기준으로 확률을 되올림 (실측 0.61→1.0). 값이 바뀌어 claim이 새로 태어나면 자동 무효(confirmedAt < bornAt).
- info 전송 시점 스냅샷을 그대로 쓰지 않는 이유: authority는 나이에 따라 계속 감소 → 30분 재조회 주기만큼 낡음. dashboard가 초 단위 감쇠를 직접 그릴 수 있게 곡선 파라미터도 같이 내보냄.
- 수치 등가성(scipy 원본 대비 오차 <1e-9)은 info의 `python -m reliability.selftest`가 검증.

### 4-5. 병원 정보 확인 루프 (공급자 피드백, 2026-09-29)
- **`hospital_self_info`** (hub → 병원 대시보드): "귀원 정보 현황" — 자기 병상 신뢰도(horizon 0이라 rArrive==authority)·확장 필드·중증 신고 현황. identify 직후 / info 30분 upsert 직후 / 확인 직후에 그 병원 소켓으로만.
- **`info_confirm`** (병원 → hub): `confirm_hospital_info()`가 기록(상태 파일 저장·복구), 조건부 생존으로 확률 복원, 의사결정 로그 `hospital_info_confirmed` 기록(향후 infosurv G1+ 라벨 재료), 구급차 칩 ✓(`confirmedAgeSec`), 관련 사건 즉시 재계산·재브로드캐스트.

## 5. 스키마 요약 (정본: hub/README.md "입출력 데이터 포맷" ↔ `hub/schema.py` ↔ `dashboard/src/types/dashboard.ts`)

### 입력
| # | 발신 | 채널 | 핵심 필드 |
|---|---|---|---|
| 1 | voice (환자 정보) | HTTP `/voice/summary` | `caseId`, `transcript.{raw_text, filtered_text}`, `summary.{patient, mechanism, symptoms, treatment, severity_tag(high/medium/low), required_department?}`, `source:"ai"` |
| 2 | info (병원 정보) | HTTP | `hospitalId`(실 E-Gen hpid), `name`, `gps`, `availableBedCount`, `bedsByType`(**미상 종류는 키 자체가 없음** — 확인된 만실 `{"ER_ADULT":0}`과 구분), `specialties[]`, `updatedAt`, + Optional: `assessment`, `bedReliability`, `bedReliabilityByType`(hvoc/hvgc/hv28), `severeDeclarations` |
| 3 | dashboard (승인 액션) | WS `/ws/dashboard` | `caseId`, `action`(hospital_approve/hospital_reject/final_approval), `hospital_id`, `actor`(hospital/paramedic), `timestamp`, `reason?`(Optional[str] — 어휘 확장이 액션 거부로 안 이어지게 Literal 아님) |
| 6 | dashboard (통화 신호) | WS | `type:"call_signal"`, `signal`(call_started/call_ended), `apid`, `caseId`(dashboard가 시작 시 생성) |
| 7 | info (구급차 정보) | HTTP `/info/ambulances` | `apid`, `name`, `gps`(데모용 고정), `voicePort` |
| 8 | voice (자가등록) | HTTP `/voice/register` | `apid`, `ip`(자동 탐지). AmbulanceInfo 미등록이면 409 |
| 9 | dashboard (자기소개) | WS | `type:"identify"`, `role`(hospital/ambulance), `id` |
| — | 병원 dashboard (정보 확인) | WS | `type:"info_confirm"` |

### 출력
| # | 수신 | 핵심 필드 |
|---|---|---|
| 4 `HubMatchResult` | dashboard (WS 브로드캐스트) | `type:"match_result"`, `caseId`, `patientInfo`(전문 포함), `zoneActive[]`, `hospitals[]`, `source:"rule"`, `ambulanceName`, `ambulanceGpsFallback` |
| ↳ `hospitals[]` | | `hospitalId`·`name`·`gps`·`distanceKm`·`specialtyMatch{department,score}`·`availableBedCount`·**`bedCountUnknown`**(true면 dashboard는 "0"이 아니라 **"미상"** 표시 필수)·`status`(pending/approved/rejected/confirmed)·`etaMin`·`finalScore`·`travelMin`/`travelBasis`·`demoteReasons[]`·`bedDataStale`·`reliability?`·`bedReliability?`(authority·rArrive·ttlSec + 곡선 파라미터 predictedSurvivalSec·bornAt·sigma·confirmedAgeSec)·`bedReliabilityByType?`·`severeFreshness?`(group·value·ageSec·ageIsMin·ruleRemainingSec) |
| 6 `identity_info` | dashboard | `type:"identity_info"`, `role`, `id`, `name`, `known` |
| `GET /identity` | 랜딩 페이지 (HTTP, 유일하게 CORS `*`) | 위와 동일 필드 — 라우팅 전 접근 코드 존재 확인 |
| `hospital_self_info` | 병원 dashboard (해당 소켓만) | 자기 병상 신뢰도·확장 필드·중증 신고 요약 |
| 거절 로그 | info `:5003/hub/rejection` (HTTP POST) | §3-6 참고 |

## 6. 검증·실행

```bash
# 환경: rookie_hub (팀 컨벤션) — 이 노트북에서는 rookie_info env로 검증해 왔음
python run_match.py                 # 매칭·신뢰도 3종·확인 루프·순위·상태 복구·해시 체인 (전부 실데이터 형식)
python test_app_background.py       # 202 비동기·주기 재계산·상태 저장/복구
python test_rejection_forward.py    # 거절 스냅샷·NO_RESPONSE·sweep·멱등·fire-and-forget
python app.py                       # 실서버 (포트 5001, HUB_DEBUG=1은 개발 중에만)
```

## 7. 알려진 제약
- 스코어링 가중치·존 임계값·이동시간 반감기는 상수 (운영 데이터 없이 정함 — 조정 필요)
- 구급차 GPS는 데모용 고정값 (실시간 연동은 범위 외)
- voice 자가등록은 info가 먼저 떠 있어야 함 (409, 재시도 큐 없음)
- **거절 로그 수신구(`hospital_score/ingest.py`, 포트 5003)는 별도 기동** — 안 띄우면 그 기간 로그는 소급 불가로 소실
