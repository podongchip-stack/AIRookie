# 코드 전수검사 — 동작·구조·검증 기록

**2026-10-22 실행.** 저장소 전체를 훑어 ① 무엇이 어디에 있고 ② 실제로 어떻게 동작하며
③ 돌려서 통과하는지 ④ 어디가 깨졌는지를 기록한다. 추측으로 적은 줄은 없다 — 모든 "통과"는
이 날 실제로 실행한 결과이고, 확인하지 못한 것은 **미검증**으로 표시했다.

- 브랜치 `feature/spider` · 기준 커밋 `13ec671`
- 설계·규칙의 정본은 `CLAUDE.md`, 숫자의 정본은 `poc/IR_NUMBERS.md`, 서사는 `STORY.md`.
  **이 문서는 "지금 코드가 실제로 하는 일"만 적는다** — 셋이 어긋나면 그 사실을 §7에 남겼다.

---

## 1. 이번에 고친 것 (2026-10-22)

임상 자문(응급의학과 전문의 12문항) 대조 결과에 따른 설계 변경 둘. 근거·수치는
`poc/CLINICAL_CONVERGENCE.md`.

### 1-1. τ 창 충돌·양보를 순위에서 걷어냈다 → 표시만

| 전 | 후 |
|---|---|
| 같은 병원·같은 τ(10분) 창에 우선하는 사건의 줄이 한도(2)만큼 차면 **그 병원을 건너뜀**(점수 띠 한 단계 내림) | **건너뛰지 않는다.** `spiderWindow`에 사실만 싣고 수용 판단은 병원이 한다 |
| 우선하는 사건이 들어오면 밀린 사건이 다음 병원으로 줄을 옮김(양보) | **양보 없음.** 재계산 순서는 창 *표시*를 맞추는 데만 쓴다 |
| `plan_mci`(대량사고 분배)도 창 한도를 1차 정렬 키로 사용 | 줄 길이 + 부하 페널티만. 부하가 분산을 담당한다 |
| 점수 띠 3단 (줄 있음 > 창 찬 줄 > 줄 없음) | **2단** (줄 있음 > 줄 없음) |

근거가 둘 다 같은 방향이다 — ① `spider/replay_probe.py` 실측: 창 항을 켜면 서울 밀집에서
도착 거절이 46→51(lag 0)·56→65(lag 15)로 **늘고** 시간 이득이 없다 ② 임상 자문: *"중등도를
받기로 한 상태에서 심정지가 추가로 오면 혼란이 있더라도 두 환자를 모두 수용하고 대응하려
노력하는 경우가 많다."* hub가 미리 건너뛰면 병원이 판단할 기회 자체가 없어진다.

고친 파일: `hub/spider_rule.py`(`score()` 시그니처에서 `window_full` 제거) ·
`hub/hub_engine.py`(점수 호출·설명 문구·`_spider_record_pick` 조건·`plan_mci` 정렬 키) ·
`hub/schema.py`(필드 설명) · `hub/app.py`(주석) · `hub/test_spider_rule.py`(검사 교체).

⚠ **spider 연구 엔진(`spider/engine/`·`spider/map.html`)은 창 항을 그대로 둔다** — 그쪽은
연구 대상이고, `spider/README.md`의 "①~⑤를 합친 판단"도 "창 혼잡·양보는 (hub에) 넣지
않는다"다. 즉 **hub와 spider는 이제 τ 창에서 의도적으로 다르다.** `parity_check.py`는
spider 내부(py ↔ js)만 대조하므로 영향받지 않는다.

### 1-2. 미선택 병원 통보를 새로 넣었다

임상 자문 요구: *"다수 병원이 수용 가능성을 회신하더라도 실제 수용 확약은 최종 선택한 한
병원에만 부여하고, 나머지 병원에는 선택되지 않았음을 즉시 자동으로 알리는 기능이 필요합니다."*

**고치기 전 실제 동작**: 병원 대시보드는 "다른 병원으로 확정된 사건"의 카드를 목록에서
빼므로(2026-08-11 결정, `HospitalDashboard.tsx`의 `myCases` 필터), 승인해 둔 카드가
**아무 설명 없이 사라졌다.** 수용 승낙은 빈 병상 확인이 아니라 처치 공간 확보·기존 진료
조정·신규 수용 제한 같은 자원 선배정이라, 그 준비가 묶인 채로 남는다.

| 층 | 추가한 것 |
|---|---|
| hub 엔진 | `HospitalMatch.notSelected`(bool, 기본 False). `_mark_not_selected()`가 `_sort_matches()` 안에서 세운다 — 확정 병원이 있고 내 상태가 `approved`면 True. 확정이 풀리면 자동으로 False |
| hub 푸시 | WS `selection_released` → 해당 병원 소켓에만. `{caseId, hospitalId, confirmedHospitalId, confirmedHospitalName, timestamp}` |
| 의사결정 로그 | `selection_released` — **보낼 대상**(`releasedHospitalIds`)과 **실제 전달**(`deliveredHospitalIds`)을 따로 남긴다. 통보 누락·지연을 나중에 셀 수 있게 |
| 대시보드 | `SelectionReleased` 타입 · `state.selectionReleased` · 병원 화면 토스트 "○○(으)로 이송이 확정됐습니다 — 귀원은 선택되지 않았습니다." |

**status는 건드리지 않는다**(approved 그대로) — 승인 자체는 유효하고 이동 중 재선택 대상으로
남아야 한다(뺑뺑이 방지 원칙). 재선택하면 깃발이 뒤바뀐다(검사로 고정).

탭이 꺼져 있었거나 뒤늦게 열린 경우 푸시를 못 받으므로, 대시보드는 **따라잡기로 온 매칭
결과의 `notSelected` 깃발로도 같은 안내를 만든다**(`useSelectionNotice`, caseId로 중복 제거).

### 1-3. 같이 고친 결함

| 파일 | 결함 | 처리 |
|---|---|---|
| `hub/test_er_occupancy.py` | **시한폭탄** — `updatedAt="2026-10-07T00:00:00Z"`가 박혀 있어, 그날이 1일을 넘긴 뒤로는 `_is_bed_data_stale`이 True가 되고 `_er_capacity`가 포화도를 내지 않아 **영구히 실패**했다(HEAD에서도 실패 확인) | 신고 시각을 `now`로 생성 |
| `poc/IR_NUMBERS.md` §5 | MCI 쏠림·센터 이송 비율에 **장면 표기가 없어 일산 값과 이태원 값이 한 표에 섞여** 있었다(경증 줄만 이태원). 두 장면을 다시 돌려 확인 | 장면별 표로 분리 + §6 금지 줄 추가 |

> 변경 중 `plan_mci`에서 `arrivals` 변수를 지우며 사용처 한 줄을 남겨 `NameError`가 났는데
> `test_mci_allocate.py`가 즉시 잡았다. 전수 실행이 없으면 넘어갔을 자리다.

---

## 2. 폴더별 구조 — 무엇이 어디에 있나

커밋된 소스만 센다(node_modules·`__pycache__`·`.next`·build 제외).

| 폴더 | 파일 | 줄 | 역할 | 진입점 | 실행 환경 |
|---|---|---|---|---|---|
| `hub/` | 35 | 11,901 | 매칭·존·승인·상태·시뮬레이션. **dashboard와 직접 통신하는 유일한 층** | `app.py`(Flask+flask_sock, 5001) | conda `rookie_info` |
| `info/` | 76 | 15,456 | E-Gen·심평원 수집, 신뢰도 판정·서빙, 거절 로그 수신구 | `send_to_hub.py`(상시) · `hospital_score.ingest`(5003) | conda `rookie_info` |
| `voice/` | 17 | 2,617 | STT(Qwen3-ASR+LoRA) · 구조화(MF_BERT 17필드) | `start-voice.sh`(6000 중앙 / 6001~ 구급차별) | 전용 env `AIRookieProject` |
| `dashboard/` | 181 | 60,960 | 구급차·병원·관제·전화 앱 웹 + iOS/Android/iPad 네이티브 | `npm run dev`(3000) | Node |
| `spider/` | 24 | 3,592 | 거미줄 분배 모델 실험실 + 3D 화면 서버 | `serve.py`(2700) · `map.html`(쌍둥이) | conda `rookie_info` |
| `sim/` | 8 | 1,701 | 대량사고(MCI) 분산 이송 시뮬레이션 | `run.py --scene ilsan\|itaewon` | conda `rookie_info` |
| `poc/` | 11 | 4,364 | 현장 실증(PoC) 리포트 — 승인 0명·환자 0건 | `build_jinju_replay.py` 등 | conda `dev`/`rookie_info` |
| `lidar3d/` | 95(tracked) | 10,649 | iPhone LiDAR 3D 현장 캡처 → 웹 뷰어. **선택 모듈**(`start-all --lidar`) | `server.app:app`(uvicorn, 8000) | 전용 env |
| `supabase/` | 2 | 368 | Edge Function `egen-snapshot`(5분 pg_cron) | 클라우드 배포 | Deno |

⚠ **`lidar3d/`는 `CLAUDE.md`에 한 줄도 없다** — 95파일·10,649줄인데 브랜치 표·시스템
흐름·담당 영역 어디에도 없다. 루트 `README.md`에는 한 줄 있다("3D 뷰어(선택, start-all
--lidar)")(§7-E).

### 의존 방향 (실제 import 기준)

```
voice ──HTTP(요약)──→ hub ←──HTTP(병원·구급차)── info
                       │                          ↑
                       │                          └── HTTP(거절 로그) ──┐
       dashboard ──WebSocket(양방향)── hub ────────────────────────────┘
       spider  ──HTTP(GET /hospital-features) + WS(role=monitor)──→ hub
```

- **`hub/`는 다른 폴더를 import 하지 않는다.** `info/`의 신뢰도 생존함수도 표준 라이브러리로
  재구현해 뒀다(`hub/bed_reliability.py`) — 폴더 경계 원칙.
- `spider/`·`sim/`·`poc/`는 "다른 폴더의 기존 파일을 수정하지 않는다"가 운영 규칙이고,
  `info/` 데이터·어휘 모듈 **읽기 전용**만 한다. 통째로 지워도 나머지가 돈다(확인: `poc/`는
  `hospital_score.vocabulary`만, `sim/`은 스냅샷 파일과 `fetch_coords.py`만 참조).

---

## 3. 런타임 — `start-all.sh`가 띄우는 것

| 포트 | 프로세스 | 끄는 법 | 로그 |
|---|---|---|---|
| 5001 | hub (`hub/app.py`) | — | `hub.log` |
| 3000 | dashboard (Next.js) | — | `dashboard.log`·`dashboard-build.log` |
| 5003 | 거절 로그 수신구 (`hospital_score.ingest`) | `--no-info` | `info.log` |
| 2700 | spider 화면 서버 (`spider/serve.py`) | `--no-spider` | `spider.log` |
| 8000 | lidar3d (uvicorn) | **기본 꺼짐** — `--lidar`로만 켜진다 | — |
| — | E-Gen 스냅샷 **동기화**(`snapshot_cloud.py --watch`) | — | `snapshot.log` |
| 6000 / 6001~ | voice (별도 기동, `start-voice.sh`) | — | — |

- 포트 선택 근거가 코드에 적혀 있다: 5000·7000은 macOS AirPlay 수신기가 점유해 피했다.
- **스냅샷은 수집이 아니라 동기화다**(2026-10-04 클라우드 이관). 수집은 Supabase Edge
  Function이 5분 pg_cron으로 하고, 로컬은 내려받아 JSONL로 복원만 한다. 이 노트북의 작업
  스케줄러 로컬 수집은 2026-10-10 Disabled.
- `--no-sim-dispatch`를 주지 않으면 **출동 시뮬레이션이 기본으로 켜진다**(실제 구급차 GPS
  수신 경로가 없어서). 이동 구간은 전부 고정 초(출동·복귀 5초, 병원 이송 30초).

---

## 4. hub 동작 — 실제 인터페이스

### 4-1. HTTP (17개, `hub/app.py`)

| 메서드 | 경로 | 쓰는 쪽 |
|---|---|---|
| POST | `/info/hospitals` · `/info/hospitals/roster` | info 상시 프로세스(5분 주기) |
| POST | `/info/ambulances` · `/ambulances/batch` · `/ambulances/roster` | info(구급차 레지스트리) |
| POST | `/voice/register` · `/voice/utterance` · `/voice/summary` | voice |
| POST | `/vitals` | 이송 중 활력징후 "입력 구멍"(voice/manual/monitor/demo 공용) |
| GET | `/route` · `/geocode` | dashboard (카카오 대리 호출) |
| GET | `/identity` | 첫 페이지 접근 코드 검증 (CORS 허용) |
| GET | `/verification` · `/verification/live` | 신뢰도 검증 화면 (info 5003 중계) |
| GET | `/hospital-backup` | [배후역량] 모달 |
| GET | `/hospital-features` | **spider 서버**가 30초마다 (읽기 전용) |
| WS | `/ws/dashboard` | dashboard 전부 |

### 4-2. WebSocket — 받는 것

`approval_action`(승인 5종 + 도착 결과 2종 + 철회) · `identify` · `call_signal` ·
`voice_summary`(아이폰 온디바이스) · `patient_override` · `info_confirm` ·
`transport_vitals` · `dispatch` · `scene_end` · `sim_pause`/`resume`/`reset`/`fast_forward` ·
`zone_expand_now` · `mci_preview` · `mci_allocate` · `demo_mode`.

### 4-3. WebSocket — 보내는 것

`match_result`(핵심) · `identity_info` · `hospital_self_info` · `scene_candidates` ·
`case_closed` · `case_sync` · `case_meta` · `case_history` · `map_overview` ·
`case_overview` · `call_transcript` · `call_status` · `transport_assessment` ·
`pre_alert` · `action_refused` · **`selection_released`(신규)** · `mci_plan` ·
`mci_allocated` · `scene_input_mode` · `ambulance_phase`/`position` · `demo_mode`.

**역할별 전송**: `match_result`는 그 구급차(apid) 탭과 **후보에 오른 적 있는** 병원 탭에만
간다. 관제 지도(monitor)는 환자 상세 없는 `case_overview`만 받는다.

### 4-4. 순위 규칙 (2026-10-22 현재)

```
줄 길이 = 도로 분 − μ×(올라가는 역량 이득)        (유효 역량 ≥ 필요)
        = 도로 분 + ν×(모자란 양)                 (미달. 0.75 넘게 모자라면 줄 없음)
        + 이송 중 부하(최대 10분) + 포화도(최대 5분)

유효 역량 z = 등급(1~4) + 응급의학과 전문의 두께 + 야간 감점
필요 역량   = KTAS 1→4 · 2→3 · 3→2 · 4·5→1
μ = K1·2 30분/레벨 · K3 5분 · K4·5 −5분(센터 보존)  — 이송 중 중증 10명이면 0까지 감쇠
ν = 30 / 15 / 5분
벽 = 심근경색→혈관조영 운영 · 뇌졸중→CT 운영+등급2↑ · 중증외상→등급3↑
```

정렬 띠: **확정 → 병원 승인 → 나머지(줄 길이) → 내림(`declared_no`·확인된 만실·중증 차단)
→ 거절**. 줄 없는 병원도 **후보에서 빼지 않고** 맨 뒤로. τ 창은 표시만(§1-1).

순위에 **쓰지 않는** 것: 병상 신뢰도 확률(설명용·첫 연락 추천에만) · 진료과 임베딩 점수 ·
`nightDutyAvailable`(info가 `bool(capabilities)`로 채우는 프록시).

### 4-5. 상태와 기록

- 상태 파일 `data/state/hub_state.json` — 병원·구급차·승인·병상 오버레이·사건·voice 주소.
  **통화 원문은 저장하지 않는다.**
- 의사결정 로그 `decision_log.jsonl` — **해시 체인**(`prevHash`). 28종 기록:
  `hub_match_result` `approval_action_applied` `approval_action_refused` `bed_hold_released`
  `zone_expanded` `patient_override` `selection_released`(신규) `first_call_recommended`
  `transport_assessment` 등. 통화 전문은 `{sha256, chars}`로 치환.
- 병상 차감은 **사건 기준 유지·해제**(`BedHold`): 확정 + 예상 이동 + 20분 무조건 유지 →
  E-Gen 원값이 줄면 해제 → 안 줄면 도착 + 60분.

---

## 5. 검증 결과 — 이 날 실제로 돌린 것

환경: `conda rookie_info`(Python) · Node 22 / `PYTHONUTF8=1` 필수(Windows cp949).

### 5-1. hub — 19/19 통과

```
PASS  run_match.py                 PASS  test_input_mode.py
PASS  test_acceptance_messages.py  PASS  test_mci_allocate.py
PASS  test_ambulance_roster.py     PASS  test_monitor_map.py
PASS  test_app_background.py       PASS  test_patient_override.py
PASS  test_backup_view.py          PASS  test_rejection_forward.py
PASS  test_bed_hold.py             PASS  test_sim_reset.py
PASS  test_central_voice.py        PASS  test_spider_rule.py
PASS  test_dispatch_sim.py         PASS  test_transport_triage.py
PASS  test_er_occupancy.py  ← §1-3 고친 뒤   PASS  test_transport_withdraw.py
PASS  hub/disease_group.py         PASS  test_zone_timer.py
```

### 5-2. info — 4/4 통과

| 검사 | 결과 | 확인 내용 |
|---|---|---|
| `egen.test_hvec_minus_one` | PASS | 응급실 `hvec` −1을 과밀 1명으로 읽는 규칙 |
| `reliability.selftest` | PASS | 실시간 피처 빌더가 학습 파이프라인 claim-version 규칙과 동등 |
| `egen.messages` | PASS | 수용 제한 메시지 파싱·질환군 변환 |
| `hospital_score.discarded` | PASS | 폐기 판정 2건(병상 수 예측·미상 추정) 재현 |

### 5-3. spider — 13/14 사례 일치

`parity_check.py`(py 엔진 ↔ js 쌍둥이). 어긋난 1건은 **같은 사례 안의 도로 거리 표시**
(`8.4km` vs `8.7km`)뿐이고 줄 길이(22.7)·도착 예정(32분)·선택 병원은 같다 → 경로 탐색
타이브레이크 차이로 보인다(§7-D).

### 5-4. sim — IR 수치 재현 확인

| | nearest | sequential | **goldenlink** |
|---|---|---|---|
| 일산 138명 이송 중앙값 | 19.6분 | 22.0분 | **14.7분** |
| 이태원 120명 | 23.0분 | 28.5분 | **14.8분** |

`IR_NUMBERS.md`와 일치. 쏠림·센터 이송 비율은 **장면마다 다르다**(§1-3에서 교정).

### 5-5. poc — 2/2 통과 (API 호출 0회)

`build_jinju_replay.py` · `build_gyeongnam.py` 모두 리포트 재생성 성공.

### 5-6. dashboard

| 검사 | 결과 |
|---|---|
| `npx tsc --noEmit` | **PASS** (오류 0) |
| `npx eslint src` | **오류 3 · 경고 6** — 전부 이번 변경과 무관한 기존 결함(§7-C) |

### 5-7. 돌리지 못한 것 (미검증)

| 대상 | 이유 |
|---|---|
| `voice/` | 전용 env(`AIRookieProject`, transformers 5.17) + HF 가중치 ~수 GB 필요. 자체 검사 스크립트 없음 |
| iPhone `GoldenLinkCore` 테스트 | Xcode 필요(macOS) |
| Android `:core:test` | Android SDK/Gradle 필요 |
| iPad 앱 | Xcode 필요 |
| `lidar3d/` | 전용 env + iPhone 기기 |
| `supabase/functions` | 클라우드 배포분 |

---

## 6. 전수검사에서 확인한 "실제로 이렇게 동작한다"

문서와 코드가 **일치함을 확인한** 항목(추측 아님):

1. **hub가 다른 폴더를 import 하지 않는다** — 생존함수까지 표준 라이브러리로 재구현.
2. **`match_result`는 관련 소켓에만 간다** — `_match_recipients()`로 apid·후보 병원만.
3. **관제 지도는 환자 상세를 못 받는다** — `case_overview`에 통화 전문·활력징후·의식 없음.
4. **통화 원문은 상태 파일·해시 체인 로그에 저장되지 않는다** — 로그는 `{sha256, chars}`.
5. **확인된 만실 병원은 병원 승인이 거부된다** — 단 미상·1일 넘은 값은 만실로 보지 않는다.
6. **미상과 확인된 만실이 끝까지 분리된다** — `bedCountUnknown`·`bedDataStale` 두 축 별도.
7. **신뢰도 확률은 순위에 안 들어간다** — `finalScore`는 줄 길이에서만 만들어진다.
8. **이송 승인은 병원이 승인한 병원에만** 허용되고, 어긋나면 로그만 남고 거부된다.
9. **중복 `final_approval`은 멱등** — 병상이 두 번 깎이지 않는다(`run_match.py`가 고정).
10. **일시정지 중 모든 조작을 hub가 거부한다** — 화면만 막는 게 아니라 서버도 지킨다.

---

## 7. 발견한 결함 — 우선순위 순

> 아직 안 고친 것은 루트 [README.md](README.md)의 **"⚠ 고쳐야 할 것"** 절에도 올려 뒀다
> (README를 먼저 보는 팀원이 놓치지 않게). 고치면 **양쪽 다** "고침 + 날짜"로 바꾼다.

| # | 심각도 | 위치 | 내용 |
|---|---|---|---|
| A | 🔴 고침 | `hub/test_er_occupancy.py` | 시한폭탄 테스트 — 하드코딩된 신고 시각이 1일을 넘겨 영구 실패(§1-3) |
| B | 🔴 고침 | `poc/IR_NUMBERS.md` §5 | IR 정본에 **일산·이태원 수치가 장면 표기 없이 섞여** 있었다(§1-3) |
| C | 🟠 남음 | `dashboard/src/app/case/page.tsx:33,48` · `components/ambulance/TransportMonitorPanel.tsx:158` | eslint 오류 3건 — effect 안 동기 setState(연쇄 렌더), 의존성 배열이 단순 식이 아님, 선언 전 변수 접근. **타입체크는 통과하므로 런타임에 조용히 틀릴 수 있는 쪽** |
| D | 🟡 남음 | `spider/parity_check.py` | 14사례 중 1건에서 도로 거리 표시가 8.4km vs 8.7km로 다름(줄 길이·선택은 동일). 경로 타이브레이크 차이 추정 |
| E | 🟡 남음 | `CLAUDE.md` | **`lidar3d/`가 공통 컨텍스트에 전혀 없다** — 95파일·10,649줄 모듈이 브랜치 표·흐름도·담당 영역 어디에도 없다(루트 README에만 한 줄). `--lidar`로만 켜지는 선택 모듈이라 급하지는 않다 |
| F | 🟡 남음 | 개발 환경 | conda `dev` 환경에는 `flask_sock`·`sentence_transformers`가 없어 **hub 테스트 19개 중 13개가 import 단계에서 실패**한다. 올바른 환경은 `rookie_info`인데 `hub/`에 그 안내가 없다 |
| G | 🟢 의도 | `hub/` ↔ `spider/` | τ 창에서 **의도적으로 다르다**(§1-1). "한쪽을 고치면 다른 쪽도"라는 기존 주석과 어긋나 보이므로 양쪽에 이유를 적어 뒀다 |
| H | 🟢 의도 | `notSelected` | 구급차 화면·관제 지도는 아직 쓰지 않는다(병원에게만 의미 있는 값) |
| I | ⚪ 정리 | `memo/` | 빈 untracked 폴더(`memo/memo` 0바이트) |

### C의 권고

`case/page.tsx`는 관제 상황판이고 `TransportMonitorPanel`은 이송 중 활력징후 시연 패널이라
둘 다 시연 경로에 있다. "선언 전 변수 접근"은 번들러가 호이스팅으로 넘어가다가 특정 렌더
순서에서 `undefined`가 될 수 있는 모양이라 **발표 전에 보는 게 좋다.** 이번 작업 범위를
넘어서 손대지 않았다.

---

## 8. 재현 명령

```bash
# hub — 19개 전부 (PYTHONUTF8=1 필수, 환경은 rookie_info)
cd hub && for f in run_match.py test_*.py; do PYTHONUTF8=1 HUB_SPIDER_HOUR=14 python "$f"; done

# info — API 호출 0회
cd info/Hospital_inform/info
python -m egen.test_hvec_minus_one
python -m reliability.selftest
python -m egen.messages
python -m hospital_score.discarded

# spider — py ↔ js 쌍둥이 대조 (node 필요)
cd spider && python parity_check.py

# sim — 대량사고 세 팔 비교
cd sim && PYTHONUTF8=1 python run.py --scene ilsan --seeds 2

# poc — 리포트 재생성 (API 0회)
cd poc && python build_jinju_replay.py && python build_gyeongnam.py

# dashboard
cd dashboard && npx tsc --noEmit && npx eslint src
```

⚠ `HUB_SPIDER_HOUR=14`를 주지 않으면 **밤에 돌릴 때 야간 감점 때문에 순위 검사가 흔들린다**
(얇은 지역기관이 경증도 못 받는 순위가 나온다). `test_spider_rule.py`는 스스로 고정한다.

⚠ `run_match.py`·`test_*.py`는 **임시 경로**를 쓴다(`HUB_DECISION_LOG_PATH`·`HUB_STATE_PATH`).
실로그에 돌리면 해시 체인이 끊긴다 — 2026-10-04에 실제로 한 번 끊겼고 체인이라 지울 수 없다.

---

## 9. 이 문서를 다시 돌릴 때

1. §8 명령을 전부 돌려 §5 표를 갱신한다(통과 수를 기억으로 적지 않는다).
2. §7에서 고쳐진 줄은 "고침"으로 바꾸고 날짜를 남긴다. **지우지 않는다** — 무엇이 한 번
   깨졌는지가 다음 검사의 재료다.
3. 새 폴더·새 포트·새 WS 메시지가 생겼으면 §2·§3·§4에 더한다. `CLAUDE.md`에도 같이
   적혔는지 확인한다(§7-E가 그걸 빠뜨린 사례다).
