# lidar3d — iPhone LiDAR 기반 3D 현장 캡처

응급 현장을 iPhone Pro의 LiDAR로 스캔해 **미터 단위 3D 공간**과 **사람별 3D 형상**을 만들고,
웹 뷰어로 확인하는 모듈이다.

## 무엇을 하는가

```
iPhone(ARKit LiDAR) ──업로드──> Mac 서버 ──후처리──> 웹 3D 뷰어
  영상·뎁스·포즈·메시            FastAPI          three.js
```

- **미터 단위**로 공간이 나온다 (LiDAR 실측). "문까지 2m" 같은 말을 실제로 할 수 있다.
- 현장에 있는 **사람을 개별 3D 조각으로 분리**한다.
- 시민은 QR로 웹 뷰어에 접속해 결과만 본다 (촬영은 앱이 필요).

## 폴더

| 경로 | 역할 |
|---|---|
| `server/app.py` | 업로드·조회·후처리 실행 API (FastAPI) |
| `server/viewer/` | 웹 3D 뷰어 (`index.html`), YOLO 검출 재생, 안드로이드 촬영 실험 |
| `scripts/` | 후처리 파이프라인 (YOLO 마스크 → TSDF 융합 → 사람 분리 → 색 입히기 → 3DGS) |
| `iphone/LiDAR_Space3D/` | iOS 촬영 앱 (Swift, ARKit) |
| `docs/` | 좌표계 규약, 서버 분석 문서 |

## 실행

```bash
cd lidar3d/server
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
# 브라우저: http://localhost:8000/viewer/
```

공개 주소로 열 때는 `LIDAR_TOKEN` 환경변수를 **반드시** 설정한다.
안 그러면 주소를 아는 누구나 업로드·후처리를 실행할 수 있다.

## 문서

- `docs/coordinate_system.md` — ARKit 좌표·시간 규약 (**변환 방향을 틀리기 쉬운 지점** 정리)
- `docs/SERVER_ANALYSIS.md` — 서버·파이프라인 전체 분석, 바디캠 연동 검토
- `docs/SERVER_ANALYSIS_2.md` — 렌더링 경로·투영 방식·필수 메타데이터

## 알려진 한계

- **뎁스와 영상이 모두 있어야** 사람 인식이 된다. 둘 중 하나만으로는 안 된다.
- 3D 형상이 생성되는 범위는 **4.0m 이내** (파이프라인 설정값).
- 움직이는 사람은 TSDF 잔상으로 여러 조각에 흩어진다.
- `ultralytics` 가 **AGPL-3.0** 이라 배포 형태 검토가 필요하다.

## 주의

- `server/sessions/` 에는 **개인 영상이 포함된 촬영 원본**이 쌓인다. 저장소에 올리지 않는다.
- 세션 데이터·모델 가중치는 `.gitignore` 로 제외돼 있다.
