# live4d — 시간에 따른 3D(4D) 현장 재구성

사고 현장을 **LiDAR 폰 두 대**(iPhone 15 Pro · 12 Pro)로 동시에 고정 녹화해, 시간대별 3D를
슬라이더로 넘겨 보고 자유 시점으로 돌려 볼 수 있게 만드는 모듈이다. `lidar3d`(정적 공간 3D)와
별개로 두되, 촬영 원본 형식과 재구성 스크립트는 lidar3d의 것을 재사용한다.

## 원칙

- **lidar3d 세션은 읽기만 한다.** 만드는 파일은 전부 `live4d/data/` 아래(`.gitignore`로 제외).
- 정적 배경(한 번, 가장 정확)과 움직이는 대상(시간마다)을 나눠 쌓는다.
- 측정한 부분과 추정한 부분을 섞지 않는다 — 안 본 곳은 지어내지 않는다.

## 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 두 기기 비교 테스트 (`scripts/compare_devices.py`) | 스크립트 완료, 촬영 대기 |
| 1 | 고정 녹화 모드 (iPhone 앱) | |
| 2 | 공통 시각 + 동기화 신호 (폰끼리 시계 맞추기 + 플래시, XIAO는 선택) | |
| 3 | 좌표 정합 + 사건 묶기(caseId) | |
| 4 | 시간별 융합 | |
| 5 | 4D 뷰어 (시간 슬라이더 + 자유 시점) | |
| 6 | (선택) 사람 추적·자세 | |
| 7 | (선택) 동적 3DGS — A100 (대회 GPU 서버 2026-11-05 회수) | |

## 0단계 사용법 (저장소 루트에서)

```bash
/opt/anaconda3/envs/labs/bin/python live4d/scripts/compare_devices.py \
  lidar3d/server/sessions/<15 Pro 세션> lidar3d/server/sessions/<12 Pro 세션>
```

결과: `live4d/data/compare/` 아래에 세션별 비교용 메시와 `compare_<A>_vs_<B>.json`.
