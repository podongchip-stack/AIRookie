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
| 0 | 두 기기 비교 테스트 (`scripts/compare_devices.py`) | 완료 — 12 Pro를 주 녹화기로 확정(15 Pro iOS 26.6.1은 뎁스 신뢰도 0%, 표면 잡음 약 4.5배) |
| 1 | 고정 녹화 모드 (iPhone 앱) | 구현 — 앱 안 "3D 스캔 / 4D 고정 녹화" 모드 선택, 실기기 확인 대기 |
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

## 1단계 — iPhone 앱의 4D 고정 녹화 모드

앱(`lidar3d/iphone/LiDAR_Space3D/`, 빌드는 `AIROOKIE/LiDAR_Space3D/LiDAR_Space3D.xcodeproj`)에서
**촬영 모드**를 고른다. 파일 형식은 3D 스캔과 같아서 Mac 쪽은 그대로 읽는다.

| 항목 | 3D 스캔 | 4D 고정 녹화 |
|---|---|---|
| ARKit 메시 | 켬 | 끔 (Mac이 원본 뎁스로 재구성, 발열 감소) |
| 뎁스 저장 | 10Hz | 15Hz (영상 15Hz와 맞춤) |
| 뎁스 저장·업로드 | 선택 | 항상 켬 |
| 최대 시간 | 없음 | 8분 자동 종료 (depth.zip 2GB 상한) |
| 고정 감시 | — | 기준 자세에서 3cm·2° 넘으면 진동 경고, `coaching.csv`에 기록 |
| 세션 이름 | `session_…v3_iPhone12Pro` | `session_…v3_iPhone12Pro_4D` |
| metadata | `capture_mode: lidar_arkit` | `capture_mode: lidar_arkit_fixed4d` + `fixed4d_*` 요약 |

서버는 `scene_mesh.ply`가 없는 4D 세션을 3DGS 자동 큐에 넣지 않는다(`server/app.py`).
