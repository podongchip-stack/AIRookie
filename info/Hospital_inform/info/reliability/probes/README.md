# E-Gen 피드 성질 탐침 (2026-10-10)

`AIROOKIE-EGEN.md` §9-1의 수치를 낸 스크립트와 그날의 결과 원자료다. 스냅샷 기반 스크립트는
`info/Hospital_inform/info`에서 실행한다(`data/snapshots_nationwide/*.jsonl`을 상대 경로로 읽음).
스냅샷은 클라우드 사본이므로 먼저 `python snapshot_cloud.py --sync`. 환경은 `rookie_info`(pandas 불필요).

| 스크립트 | 무엇을 재나 | API 호출 | 결과 파일 |
|---|---|---|---|
| `hvidate_cadence_probe.py [out.json]` | 병원별 hvidate 송출 주기 — 서로 다른 hvidate 값들의 분·초 격자, 간격 gcd, 폴링 시점 경과 p95. "자동 격자 / 불규칙" 분류 | 0 | `result_hvidate_cadence_2026-10-10.json` (420곳) |
| `value_change_rhythm.py [out.json]` | 병원×필드별 **값 변화** 리듬 — 20분당 변화 확률, 변화 간격 중위, 변화 시각 상위 3시간 점유, 주말 비율 → 상시/간헐/정시 몰림/불변 분류 | 0 | `result_value_rhythm_2026-10-10.json` (hvec·hv28·hvicc·hvoc·hvgc) |
| `live_1min_probe.py N [out.json]` | E-Gen 전국 병상을 1분마다 N회 읽어, 묶음마다 hvidate 전진 병원 수와 필드별 값 변화 병원 수 | N | `result_live_1min_2026-10-10.json` (32회, 12:04~12:34) |
| `live_1min_delta_probe.py N out.json` | 같은 1분 폴링으로 묶음별 **변화 폭(Δ)** 분포와 병원별 from→to 기록 | N | `result_live_1min_delta_2026-10-10.json` (22회, 4묶음, hvec 528건) |

1분 탐침은 `egen/client.py`의 `HttpEgenClient`(`.env`의 `EGEN_SERVICE_KEY`)를 쓰고 하루 트래픽 한도에
포함되므로 N을 50 안쪽으로 둘 것.

핵심 결과(상세는 AIROOKIE-EGEN.md §9-1): E-Gen은 5분 묶음 송출, 응급실 값은 환자 1명 단위 실시간
(5분 묶음당 전국 29% 변화·±1 83%), hvidate는 자동 재송출 시각, 중환자실·수술실은 평일 10~14시 수기.

관련: 유령·레짐 4분할은 `../probe_regime.py`, 심장박동 필터 검증은 Modeling 저장소 `explore/E21_LIVENESS.md`,
끊김 에피소드 집계와 죽은 피드 조사는 세션 중 일회성 스크립트였고 수치만 §9-1에 남겼다
(죽은 피드 목록은 `data/output/dead_feed_hospitals_2026-10-10.csv`).
