"""E-Gen 병상 정보 신뢰도 모델(infosurv) 서빙 모듈.

모델링 프로젝트(C:\\Dev\\Modeling\\Source-Action-Based Dynamic Reliability and
Egress Estimation Model — git remote가 없는 로컬 전용 저장소)에서 학습한
XGBoost AFT 생존모델로, "이 병원의 병상 숫자가 t초 뒤에도 유효할 확률"을
병원별·시점별로 계산한다. 자세한 배경은 저장소 루트의 AIROOKIE-EGEN.md 참고.

이 폴더는 hospital_score/와 같은 원칙을 따른다:
- 바깥 모듈을 import하지 않는다 — 이 폴더만 통째로 지워도
  send_to_hub.py가 bedReliability 없이 원본 그대로 보내는 것으로 안전하게
  낮아진다(try/except로 감싸져 있음).
- 판정 결과는 기존 HospitalInfo에 `bedReliability` 키 하나를 얹은 superset.

구성:
- serve.py    : infosurv.serve 벤더링 사본 (생존곡선 → authority/ttl/at)
- features.py : claim-version 상태 추적 + 모델 입력 피처 9종 실시간 구성
- engine.py   : 모델 로드·스냅샷 워밍업·예측을 묶은 서빙 엔진
- build_route_med_gap.py : 병원별 평소 리듬(route_med_gap) 정적 테이블 생성 CLI
- model/      : 학습된 모델 JSON + route_med_gap 테이블 (재학습 시 교체)
"""

from .engine import BedReliabilityEngine, BedPrediction  # noqa: F401
