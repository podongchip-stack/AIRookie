# 보고서 작성용 정리 — develop (통합 시스템 기준)

이 문서의 용도: 보고서를 쓸 때 꺼내 쓰는 재료 모음이다. `voice/`·`info/`·
`hub/`가 각자 REPORT.md/README.md를 갖고 있고(`hub/REPORT.md`가 가장 상세),
이 문서는 **네 브랜치가 develop에서 실제로 어떻게 하나의 시스템으로
합쳐지는지**를 상위 시점에서 정리한다.

숫자는 전부 코드·실 API와 대조해 확인한 값이며, 재현 명령을 함께 적었다.

작성: 2026-08-14, 갱신: 2026-09-24(병상 정보 신뢰도 모델 연동 — §2-3) ·
기준 브랜치 `develop` (4개 feature 브랜치 병합 완료 상태)

---

## 0. 프레이밍 — 전체 시스템이 지키는 원칙

**Zero Data Entry**: 구급대원이 타이핑하지 않는다. 통화가 끝나면 정보가
자동으로 구조화되고, 구급대원은 확인·수정(Override)만 한다.

**AI는 판단을 대체하지 않는다**:

| 기능 | 방식 | 담당 |
|---|---|---|
| 음성 → 텍스트 | AI (Whisper) | voice |
| 통화 내용 → SBAR 구조화 | AI (LLM) | voice |
| 병원 정보 → 표준 형식 정규화 | 규칙 | info |
| 병원 신고 데이터의 신뢰도 진단 | 규칙 (외부 근거 대조) | info(hospital_score) |
| 병원 리스트 정렬 (거리·존) | 규칙 | hub |
| 진료과 매칭 (예상 병명 ↔ 진료과) | AI 보조 (임베딩 유사도, 생성형 아님) | hub |
| 최종 순위 산출 | 규칙 (가중합 + declared_no 정렬 규칙) | hub |
| 병원 서류 → 필드 추출 | AI(검출·인식·추출) + 규칙(검증) | info(경로 B, OCR) |
| 병상 숫자의 유효 확률 예측 | AI (XGBoost AFT 생존모델, 생성형 아님) | info(reliability) → hub 환산 |

**생성형 LLM은 판정 자리에 없다.** SBAR 구조화(voice)에만 생성형 LLM을 쓰고,
병원 순위를 정하는 hub는 결정적 규칙+비생성형 임베딩 모델만 쓴다.

### 브랜치 4개가 하나로 합쳐지는 순서

```
voice   ──[통화 1건 → SBAR JSON]──────────────┐
                                              ▼
info    ──[E-Gen·HIRA → HospitalInfo]──▶   hub   ──[WebSocket]──▶ dashboard
                                              ▲                        │
                                              └────[승인 액션]──────────┘
```

**dashboard와 직접 통신하는 유일한 브랜치가 hub다.**

---

## 1. 기능 목록 — 브랜치별 핵심 기능과 문서 위치

| 브랜치 | 핵심 기능 | 상세 문서 |
|---|---|---|
| `voice/` | 통화 음성 → STT(faster-whisper) → 오인식 교정(규칙) → SBAR 구조화(Ollama qwen3:14b) | `voice/README.md` |
| `info/` | E-Gen 3API+HIRA 3API로 병원 정보 정규화(`HospitalInfo`) + 신뢰도 진단(`hospital_score`) + 서류 OCR(경로B) | `info/README.md`, `info/REPORT_NOTES.md` |
| `hub/` | voice+info 결합 2단계 매칭(존 기반 후보→진료과 임베딩+거리 가중합+declared_no 정렬), dashboard와 유일하게 직접 통신 | `hub/README.md`, `hub/REPORT.md` |
| `dashboard/` | 구급차/병원 실시간 화면, 승인 워크플로우(거절 사유 선택 포함), 다중 사건 지원, 신원 확인 | `dashboard/README.md` |

---

## 2. 매칭·점수 산출 방식 — 요약과 상호관계

점수 산출 로직이 **두 군데**에 있고, 서로 독립이다.

| | hub의 `finalScore` | info의 `hospital_score` (assessment) |
|---|---|---|
| 무엇을 정하나 | **순위** — 어느 병원을 먼저 보여줄지 | **신뢰도** — 그 병원 신고를 얼마나 믿을 수 있는지 |
| 계산식 | $0.6 \times \text{진료과 매칭} + 0.4 \times \text{거리}$ | 5단계 계층 ($0.2 \sim 1.0$), tier 기반 |
| dashboard 반영 | `hospitals[]` 정렬 순서 대부분 | `hospitals[].reliability` — 설명용 칩 |
| 순위에 영향 | **직접 결정** | **declared_no일 때만 정렬 순서에 영향(2026-08-14)**, `finalScore` 값 자체는 안 바뀜 |

### 2-1. hub의 순위 공식

$$
\text{finalScore} = 0.6 \cdot \max_{d} \cos\_\text{sim}(E(\text{예상병명}), E(d)) + 0.4 \cdot \left(1 - \frac{\text{distanceKm}}{20}\right)
$$

$$
\text{sortKey} = \big(\text{demote},\ -\text{finalScore},\ \text{distanceKm},\ \text{hospitalId}\big)
$$

`demote`는 관련 질환군이 `declared_no`(병원이 명시적으로 "수용 불가"라고
신고)일 때만 True — `finalScore`가 아무리 높아도 정렬에서 맨 뒤로 밀린다.
**계산식 자체는 안 바뀌고 정렬 순서만 조정된다.** 이 방식(가중합이 아닌 정렬
규칙)을 택한 이유는 실험(민감도 분석)으로 확인됐다 — 가중합으로 완전한 안전을
보장하려면 신뢰도 가중치가 70%대까지 필요해 거리·진료과 반영이 무의미해진다
(자세한 유도 과정은 `hub/REPORT.md` §2-9 참고).

### 2-2. info의 신뢰도 계층

$$
\text{score}(g) = \frac{\text{tier}(g)}{5}, \quad \text{tier} \in \{1_{\text{declared\_no}}, 2_{\text{unknown\_bare}}, 3_{\text{unknown\_specialist}}, 4_{\text{unknown\_designated}}, 5_{\text{declared\_yes}}\}
$$

심평원 전문의 수·전문병원 지정 여부로 "미상"을 보정하되, 병원의 "불가능"
신고보다 낮게 두지는 않는다(불변식 검사로 강제).

### 2-3. 병상 정보 신뢰도(bedReliability) — 셋째 축 (2026-09-24 연동)

위 둘과 또 다른 축이다: 2-2가 "중증질환 **수용 신고**를 믿을 수 있나"라면,
이쪽은 "**가용 병상 숫자 값 자체**가 아직 유효한가"를 본다. 모델링 프로젝트에서
학습한 XGBoost AFT 생존모델(infosurv)을 `info/Hospital_inform/info/reliability/`에
벤더링해 연동했다 (배경·모델 상세는 `AIROOKIE-EGEN.md`, 서빙 구조는 그 폴더
README.md).

**기존에는** — E-Gen 병상 숫자를 전 병원 똑같이 그대로 믿었다. "얼마나 믿을 수
있나"라는 값 자체가 없었고(설계 문서상 상수 0.50 취급 = 무정보), 낡음 처리는
일률 상수 두 개뿐이었다: info의 24시간 stale 절벽(23시간 묵은 값과 5분 전 값이
동일 취급), hub의 병상 오버레이 TTL 15분(전 병원 동일). 실측상 병상 값의 수명
중위는 20분(관측의 48%에서 값이 바뀜)이고 하루 넘게 방치된 값을 실시간처럼
송출하는 병원이 전국 25곳(최장 8.6년)인데, 시계처럼 갱신하는 병원과 몇 년
방치한 병원이 화면에서 구분되지 않았다.

**지금은** — 병원의 행동 메타데이터(평소 갱신 리듬·버전 나이·간격·변화폭·
시각/요일, 9종 피처)로 병원별·시점별 확률 셋을 낸다:

| 값 | 의미 | 계산 주체 |
|---|---|---|
| `authority` | 지금 이 병상 숫자를 믿어도 될 확률 | hub가 **매칭 시점마다** 재계산 (info의 전송 시점 값은 30분씩 낡으므로) |
| `rArrive` | **도착했을 때**도 유효할 확률 (거리/40km/h horizon) | hub |
| `ttlSec` | authority가 0.8 아래로 떨어질 때까지 남은 초 — 병원별로 다름 | info(전송 시점)·hub(매칭 시점) |

순위(finalScore)에는 관여하지 않는 **설명용**이다 — 2-2와 같은 원칙. 단 2-2의
서수 티어와 달리 이쪽은 캘리브레이트된 확률이라, 거절 로그로 효과가 실측되면
`rArrive`의 랭킹 가중치 승격을 재검토한다(§5 후속 작업).

**성능 차이** (판별력 C-index, θ3=3병상 이상 어긋남 / θ5 기준):

| 방식 | θ3 | θ5 |
|---|---|---|
| 기존 (전 병원 동일 취급 = 무정보) | 0.5 | 0.5 |
| 단순 휴리스틱 (병원 갱신리듬 단독) | 0.701 | 0.740 |
| **본 모델** | **0.764** | **0.829** |

문헌 최선 곡선 대비 예측오차(IBS) 2.1~2.4배 우위. 숫자보다 중요한 차이는
**캘리브레이션** — 휴리스틱도 순위는 흉내내지만 "유효 확률 87%가 실제로
87%"인 값은 모델만 제공하며, 확률을 화면에 그대로 노출하는 구조에선 이게
결정적이다. 체감 예(실사이클): 방금 갱신된 병원 authority 1.0 → 30분 묵으면
0.61, ttl은 병원마다 188초~1,140초로 갈린다 — 일률 15분/24시간 상수로는 전부
뭉개지던 차이다.

---

## 3. 브랜치 간 통신 과정

```
voice ──[HTTP POST, 이벤트성]──▶ hub
   POST /voice/summary       통화 종료 시 SBAR 결과 전송
   POST /voice/register      기동 시 자기 IP 자가등록

hub ──[HTTP POST, 중계]──▶ voice
   POST /call/start, /call/end   dashboard의 통화 시작/종료 신호 중계

info ──[HTTP POST, 상시 프로세스·30분 주기]──▶ hub
   POST /info/hospitals      HospitalInfo (assessment·bedReliability 포함)
   POST /info/ambulances     AmbulanceInfo

hub ──[WebSocket, 실시간]──▶ dashboard
   HubMatchResult             매칭 결과
   DashboardIdentityInfo      신원 확인 응답

dashboard ──[WebSocket]──▶ hub
   DashboardIdentify · ApprovalAction · CallSignal

dashboard ──[HTTP GET]──▶ hub
   GET /identity?role=&id=    랜딩 페이지 사전 검증

hub ──× info (2026-08-13 폐지)
   병상 갱신 왕복(POST /hub/bed-update) 제거 — TTL 오버레이로 대체

hub ──× info (미구현, hub/REPORT.md §5-1 참고)
   거절 로그(POST /hub/rejection) — info 수신구는 준비됐으나 hub가 안 부름

info ──× dashboard, voice ──× dashboard (직접 연결 없음 — 원칙)
```

### 연결한 외부 API·모델 전체

| 분류 | 이름 | 담당 | 상태 |
|---|---|---|---|
| 공공데이터 | E-Gen 3종 (목록·가용병상·중증질환) | info | 실 연동, 전국 확장 완료 |
| 공공데이터 | 심평원(HIRA) 3종 | info(hospital_score) | 실 연동, 상시 연결 완료, 재현 스크립트(`discarded.py`) 추가됨 |
| 로컬 AI | Whisper(faster-whisper) | voice | STT |
| 로컬 AI | Ollama(qwen3:14b) | voice, info(경로B) | SBAR 구조화 / 서류 필드 추출 |
| 로컬 AI | sentence-transformers(MiniLM) | hub | 진료과 임베딩 매칭, CPU로 충분 |
| 로컬 AI | DocLayout-YOLO / PaddleOCR-VL | info(경로B) | 서류 레이아웃·텍스트 인식, 실측 대기 |
| 로컬 AI | XGBoost AFT 생존모델 (infosurv 벤더링) | info(reliability) → hub | 병상 정보 신뢰도(§2-3), 연동 완료(2026-09-24), CPU로 충분 |
| DB | Supabase (구급차 전용 프로젝트) | info → hub | 사용 중 |
| DB | Supabase (병원용, 구 프로젝트) | — | 완전 제거 |
| 지도 | Kakao Maps JS SDK | dashboard | 지도 렌더링만, 사용 중 |
| 지도 | 카카오내비 자동 연동 | (미배정) | 시스템 흐름도에만 명시, 실제 코드 없음 |

---

## 4. 전체 데이터 흐름도

```
                    [사고 발생 → 구급대 도착]
                              │
             ┌────────────────┴────────────────┐
             ▼                                  ▼
   ┌─────────────────────┐          ┌─────────────────────┐
   │  voice                │          │  info                 │
   │  마이크 → STT →       │          │  E-Gen(3) + HIRA(3)   │
   │  오인식교정 → SBAR    │          │  → HospitalInfo        │
   │  = 환자정보 JSON      │          │  + hospital_score      │
   └──────────┬────────────┘          └──────────┬────────────┘
              │ POST /voice/summary               │ POST (30분 주기)
              ▼                                   ▼
        ┌───────────────────────────────────────────┐
        │                    hub                        │
        │ ① GPS+병원정보 → 존 기반 후보              │
        │ ② voice 도착 시 진료과 임베딩+거리 재처리   │
        │ ③ 신뢰도 재매칭 → 설명 + declared_no 정렬  │
        │ ④ 승인 액션 반영, TTL 병상 오버레이         │
        │ ⑤ 의사결정 로그(SHA-256)                    │
        └────────────────────┬──────────────────────┘
                             │ WebSocket
                             ▼
                  ┌───────────────────────┐
                  │      dashboard           │
                  │  구급차 화면 / 병원 화면  │
                  │  승인·불가(+사유)/이송승인│
                  └────────────┬───────────┘
                             │ WebSocket (승인 액션)
                             ▼
                  hub가 상태 갱신 후 재브로드캐스트
```

---

## 5. 후속 작업 — 전체 취합

| 우선 | 브랜치 | 항목 | 상세 |
|---|---|---|---|
| 🔴 | hub | 거절 로그를 info로 전달하는 배선 없음 | `hub/REPORT.md` §5-1. info 수신구는 준비됨, hub가 안 부름. hospital_score 가중치를 실측 기반으로 검증하려면 이게 최우선 |
| 🔴 | info | 두 경로 합류 미구현 | 경로 B(서류 OCR) → 경로 A(`HospitalInfo`) 병합 로직 없음 — 당직·tPA 정보가 아직 hub로 안 감 |
| 🟡 | hub | declared_no 정렬 → 가중합 승격 재검토 | 거절 로그(위 항목) 쌓인 뒤. 지금은 정답 데이터가 없어 안전 위주(정렬)로 결정 |
| 🟡 | hub | bedReliability의 `rArrive` 랭킹 가중치 승격 재검토 | §2-3. 캘리브레이트된 확률이라 승격 근거는 있으나(AIROOKIE-EGEN.md §5-1) 1단계는 설명용만. 거절 로그로 효과 실측 후 |
| 🟡 | dashboard | bedReliability(authority/rArrive) 표시 UI 미구현 | hub가 이미 보내고 있음 — reliability 칩과 같은 패턴으로 추가하면 됨 |
| 🟡 | voice | 화자분리(diarization) 미구현 | 모든 턴이 `"미분리"`로 고정 |
| 🟡 | dashboard | AI/규칙 구분 배지 구현 여부 미확인 | README 체크박스가 미완료 상태로 남아있음 |
| 🟢 | 전체 | 카카오내비 자동 연동 미구현 | 시스템 흐름도에만 명시, 실제 코드 없음 |
| 🟢 | hub | 존 확장 임계값·가중치 미검증 | 실 운영 데이터 없이 정한 상수 |

---

## 6. 보고서에 실을 실측 근거 (전체 취합)

| 발견 | 숫자 | 담당 |
|---|---|---|
| voice 처리 시간 실측 | STT 14.6초+구조화 9.7초 ≈ 28초 (RTX 5080, GPU) | voice |
| E-Gen 전국 확장 실측 | 목록 533곳, 파이프라인 통과 443곳, assessment 첨부 443/443(100%) | info |
| E-Gen↔HIRA 좌표 조인 | 533곳 중 518곳(97.2%), 오차 중앙값 11m | info |
| 병원 신고 데이터 품질 문제 | 전국 25곳이 최고 8.6년 묵은 병상값을 실시간처럼 송출 | info(hospital_score) |
| 폐기 판정 근거 재현성 확보 | `P(만실전환)` 0.618%(근거 코드 없던 값) → 0.568%/0.301%(재계산, `discarded.py`로 재현됨, 신뢰구간 겹쳐 교차검증) | info(hospital_score), 2026-08-14 |
| 존 사각지대 버그 실제 재현 | `MAX_ZONE=1` 고정 시절, 서울 전역 병원 7곳 데이터로 zone 1 후보 0건 재현 | hub |
| **declared_no 정렬 채택 근거(민감도 분석)** | 가중합으로 완전한 안전을 보장하려면 신뢰도 가중치 최소 73~83% 필요 → 정렬 규칙으로 대체 | hub, 2026-08-14 |
| declared_no 정렬 실제 동작 확인 | 거리 1위·진료과 동점 가상 병원이 declared_no 하나로 순위 맨 뒤로 밀림(회귀 테스트) | hub, 2026-08-14 |
| **병상 정보 신뢰도 모델 판별력** | C-index θ3 0.764 / θ5 0.829 (갱신리듬 휴리스틱 0.701/0.740, 무정보 0.5), 문헌 최선 대비 IBS 2.1~2.4배 (근거: AIROOKIE-EGEN.md §4) | info(reliability), 2026-09-24 |
| 병상 신뢰도 서빙 실사이클 검증 | 전국 416/416곳 예측 첨부 → hub 스키마 파싱·환산까지 통과. 30분 묵은 값 authority 0.61, 병원별 ttl 188~1,140초 | info+hub, 2026-09-24 |
| 병상 값 수명 실측(모델 학습 근거) | 수명 중위 20분(=폴링 간격), 관측의 48%에서 값 변화 — `route_med_gap.json` 재생성 시 전국 중위 1,200초로 재확인 | info(reliability), 2026-09-24 |

---

## 7. 문서·코드 정합성 — develop 병합 상태

`feature/voice`·`feature/info`·`feature/hub`·`feature/dashboard` 전부 develop에
병합됐다. `feature/info-v2`는 `feature/info`에 흡수된 뒤 삭제됨(2026-08-14).

**저장소 루트 `README.md`는 갱신이 필요하다** — "dashboard는 아직 통합 전"이라고
적혀 있는데 이미 4개 브랜치 통신(거절 사유 선택 포함)까지 전부 연결된 상태다.

**이번 세션에 새로 반영된 것**:
- E-Gen 수집 범위 전국 확장, dashboard 거절 사유 선택 UI
- hospital_score 폐기 판정 근거 재현 스크립트(`discarded.py`) 추가, 관련 문서
  정정(`report.py` UTF-8 버그 수정 포함)
- **hub의 declared_no 하드 데모션** — hospital_score가 처음으로 순위(정렬)에
  실제 영향을 주기 시작함
