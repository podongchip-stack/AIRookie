# reliability/ — E-Gen 병상 정보 신뢰도 모델(infosurv) 서빙

GoldenLink가 그동안 갖지 못했던 "이 병원의 병상 숫자를 지금 믿어도 되는가"를
병원별·시점별 **캘리브레이트된 확률**로 계산한다. 모델은 모델링 프로젝트
(`C:\Dev\Modeling\Source-Action-Based Dynamic Reliability and Egress Estimation
Model`)에서 학습된 XGBoost AFT 생존모델이고, 배경·성능·운영 수칙은 저장소
루트 `AIROOKIE-EGEN.md`가 정본이다 (θ3 기준 C-index 0.764, 문헌 최선 대비
IBS 2.1~2.4배 우위).

## 무엇을 내보내나

`send_to_hub.py`가 사이클마다 병원별로 `HospitalInfo.bedReliability`를 붙인다:

| 필드 | 의미 |
|---|---|
| `predictedSurvivalSec` | 모델의 예측 생존시간(초) — hub가 임의 시점 확률을 재계산하는 재료 |
| `bornAt` | 현재 claim-version 탄생 시각(값이 이 값으로 바뀐 게 관측된 시각, UTC) |
| `authorityAtSend` | 전송 시점의 authority(지금 믿어도 될 확률) — 로그·대조용 스냅샷 |
| `ttlSec` | authority가 0.8 아래로 떨어질 때까지 남은 초 |
| `modelTag` | `aft_egen_theta3_ext0923` — 어느 모델의 출력인지 |
| `source` | `"ai"` (생성형은 아니지만 학습 모델 — 규칙 기반과 구분) |

authority는 정보 나이에 따라 계속 떨어지는 값이라, **hub가 매칭 시점마다
`hub/bed_reliability.py`로 재계산**해 `HospitalMatch.bedReliability`
(authority / rArrive / ttlSec)로 dashboard에 내보낸다. 순위(finalScore)에는
관여하지 않는 설명용이다 — hospital_score의 `reliability`와 같은 원칙.

## 구조와 설계 결정

```
reliability/
├── serve.py                  infosurv.serve 벤더링 사본 (수정 금지 — 원본 갱신 시 통째로 재복사)
├── features.py               claim-version 추적 + 피처 9종 실시간 구성 (신규 구현)
├── engine.py                 모델 로드·스냅샷 워밍업·예측 (신규 구현)
├── build_route_med_gap.py    병원별 리듬 테이블 재생성 CLI
├── selftest.py               자체검증 (API 호출 0회)
└── model/
    ├── aft_egen_theta3_ext0923.json   학습 모델 (모델링 프로젝트에서 복사)
    └── route_med_gap.json             병원별 평소 버전수명 중위값 (스냅샷에서 생성)
```

- **벤더링인 이유**: 모델링 저장소는 git remote가 없는 로컬 전용이라 pip 로컬
  경로 의존(`pip install -e`)이면 팀원 장비에서 재현이 안 된다. 필요한 파일만
  복사해 커밋했다.
- **실시간 피처 빌더는 새로 짰다**: infosurv에는 배치(parquet) 파이프라인만
  있다. `features.py`가 학습 파이프라인(egen_pipeline.py)의 규칙 — 값 변화 =
  새 버전, 관측 공백 1시간 초과 = 세그먼트 리셋, 첫 버전의 리듬 피처는 NaN
  (0으로 채우면 안 됨 — XGBoost가 결측을 네이티브로 다룸) — 을 관측 스트림
  방식으로 동일하게 재현한다.
- **route_med_gap만 정적 테이블**: "이 병원의 평소 버전 수명 중위값"은 긴
  이력이 필요해 실시간으로 못 만든다. 스냅샷 축적본에서 미리 뽑아 모델과 함께
  배포하고, 테이블에 없는 신규 병원은 전국 중위값으로 대체한다(전국 1개 모델을
  신규 병원에 zero-shot 적용해도 native의 99%라는 실측 — AIROOKIE-EGEN.md §6-1).
- **관측 소스가 둘**: 같은 장비의 스냅샷 JSONL(20분 주기)을 증분으로 읽는 게
  1순위, 이번 사이클 rows(30분)가 2순위. 사이클 안에서 반드시
  `ingest_snapshots()` → `observe_rows()` 순서여야 한다(tracker의 단조 규칙이
  역순이면 스냅샷 줄을 버린다). **스냅샷이 없어도 죽지 않는다** — 피처 해상도가
  거칠어질 뿐이다.
- **fail-soft**: 이 폴더는 바깥을 import하지 않고, `send_to_hub.py` 쪽 호출부는
  try/except로 감싸져 있다. 폴더를 통째로 지워도 `bedReliability` 없이 원본
  그대로 전송된다(hospital_score와 같은 원칙).

## 학습·서빙 정의가 어긋나기 쉬운 함정 3가지 (모델링 프로젝트가 실제로 밟은 것)

1. **시각 피처는 UTC다.** `hour_utc`/`dow`를 KST로 넣으면 C-index가 실측으로
   떨어진다. `features.py`가 born을 UTC로 변환해 계산한다.
2. **infosurv `features.build()`를 그대로 쓰면 안 된다.** 그쪽 중립 스키마와
   실제 모델의 feature_names가 4개 다르다(`hour`↔`hour_utc` 등). `engine.py`가
   로드 시점에 모델의 feature_names를 `features.FEATURES`와 대조해 어긋나면
   즉시 실패시킨다 — 재학습 모델 교체 시 이 검사가 안전망이다.
3. **첫 버전의 결측은 NaN 유지.** `mean_interval_so_far`/`prev_lifetime`/
   `delta_pred_s`를 0으로 채우면 "갱신 간격 0초인 병원"으로 오독된다.

## 운영 — 월 1회 모델 갱신 프로토콜

모델링 프로젝트에서 재학습(명령 두 줄, AIROOKIE-EGEN.md §5)한 뒤:

```powershell
# 1. 새 모델 복사 (파일명이 바뀌면 engine.py의 _DEFAULT_MODEL도 갱신)
Copy-Item "<모델링 프로젝트>\explore\data\aft_egen_theta3_<새태그>.json" model\
# 2. 리듬 테이블 재생성 (스냅샷 축적 전체 기준, API 호출 0회, 수십 초)
python -m reliability.build_route_med_gap
# 3. 자체검증
python -m reliability.selftest
```

## 검증

```powershell
python -m reliability.selftest
```

세 가지를 확인한다: ① 피처 규칙이 학습 파이프라인과 일치(합성 관측 대조),
② 실데이터 워밍업→예측 전 구간(authority ∈ [0,1], 나이에 따른 단조 감소),
③ hub 쪽 표준 라이브러리 수식과 여기 scipy 수식의 수치 등가성(< 1e-9) —
hub는 브랜치 폴더 원칙상 이 폴더를 import할 수 없어 생존함수를 따로 들고
있는데, 그 두 구현이 갈라지지 않았음을 여기서 못박는다. hub 쪽 통합 검증은
`hub/run_match.py`의 `test_bed_reliability()`.
