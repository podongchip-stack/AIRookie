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
| 1 | 고정 녹화 모드 (iPhone 앱) | 완료 — 12 Pro 실기기 검증(15Hz 481장, 뎁스·포즈·영상 1:1, 거치 흔들림 0.4cm) |
| 2 | 시간 맞추기 | 구현 — 앱이 시계 대응(clock_sync) 기록 + Mac이 움직임 곡선 교차상관으로 정밀 보정, 두 폰 촬영 대기 |
| 3 | 공간 맞추기 | 구현 — 인쇄한 ChArUco 판(`markers/`)을 모든 세션이 비추면 Mac이 판 좌표계로 통일 (`align_sessions.py`), 두 폰 촬영 대기 |
| 4 | 시간별 3D (`scripts/build_4d.py`) | 1대 버전 완료 — 배경 중앙값 + 배경보다 10cm 앞 화소, 측정값만 |
| 5 | 4D 뷰어 (`viewer/index.html`) | 1대 버전 완료 — 슬라이더·재생·배속·잔상·강조·촬영 시점 |
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

## 4·5단계 — 시간별 3D와 슬라이더 뷰어 (1대 버전)

```bash
# 4) 4D 세션 → 시간별 3D (live4d/data/4d/<세션>/)
/opt/anaconda3/envs/labs/bin/python live4d/scripts/build_4d.py lidar3d/server/sessions/<세션>_4D

# 5) 뷰어 — live4d/ 폴더를 웹 루트로 서빙
python3 -m http.server 8010 --bind 127.0.0.1 --directory live4d
# 브라우저: http://127.0.0.1:8010/viewer/?session=<세션>_4D   (선택: &t=12.5 시각, &hi=1 강조)
```

**원리(측정값만, AI 추정 없음)**: 고정 카메라라 화소별 뎁스 중앙값이 배경이 되고, 매 프레임에서 배경보다
10cm 이상 앞에 있는 화소를 움직이는 대상으로 뽑아 그 순간의 포즈로 3D에 놓는다. 색은 같은 프레임 영상.
뎁스 정리는 lidar3d `fuse_depth.clean_depth`와 같은 기준(4.0m, 경계 튐, 스치는 각도).

**뷰어**: 배경 1개 + 현재 프레임 점, 시간 슬라이더·재생/정지·이전/다음(←/→, Space)·배속(0.25~2×),
잔상(최근 1초), 움직이는 대상 강조, 촬영 카메라 위치 표시, "촬영 시점으로". 위쪽은 중력 방향.

**알려진 한계**
- 고정 시점 1대라 카메라가 본 면만 있다(사람 뒷면 없음) → 2·3단계(두 대)로 보완.
- 사람이 녹화의 절반 넘게 머문 자리는 배경 중앙값이 사람 쪽으로 끌려 흐릿한 형체가 남는다
  → 3D 스캔 모드로 찍은 빈 공간을 배경으로 쓰면 해결(예정).
- 첫 1초 안팎은 ARKit 트래킹이 자리 잡는 중이라 제외된다(트래킹 정상 프레임만 사용).

## 2·3단계 — 두 폰 + 3D 스캔 배경 합치기

**앱 수정은 최소**(metadata에 시계 대응 `clock_sync`만 추가)이고, 맞추기는 모두 Mac에서 한다
— 기기 종류와 무관하게(안드로이드 포함) 같은 방식으로 쓸 수 있다.

| 맞출 것 | 방법 |
|---|---|
| 공간 | 모든 세션이 **ChArUco 판**(`markers/charuco_5x7_35mm.pdf`, A4 100% 인쇄)을 한 번 이상 비춘다 → 판 좌표계로 통일 |
| 시간(1차) | 앱의 `clock_sync`(부팅 후 경과 시간 ↔ 유닉스 시각)로 ARKit 시각을 공통 시각으로 |
| 시간(2차) | 두 4D 세션의 움직임 곡선 교차상관으로 남은 어긋남 보정(상관 0.5 미만이면 1차만) |
| 배경 | 3D 스캔 세션이 있으면 그것을 배경으로(중앙값 배경의 흐릿한 사람 형체 제거) |

```bash
python3 live4d/scripts/board.py                      # 판 인쇄 파일 생성(이미 markers/에 있음)
python3 live4d/scripts/align_sessions.py --name <이름> \
    --scan lidar3d/server/sessions/<3D 스캔> lidar3d/server/sessions/<4D A> lidar3d/server/sessions/<4D B>
python3 live4d/scripts/build_4d.py --align <이름>    # → live4d/data/4d/<이름>/
# 뷰어: http://127.0.0.1:8010/viewer/?session=<이름>
```
