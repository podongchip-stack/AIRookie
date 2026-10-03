# demo — 시연 영상 자동 생성 (demo 브랜치 전용)

> ⚠️ **이 폴더와 `demo` 브랜치의 작업은 `develop`·`main`에 병합하지 않는다.** develop → demo 방향으로만 가져온다.

시연장 모니터에 틀어 둘 영상을 만든다. 가상 응급 상황(시나리오)을 사람 손 없이 재생하고 녹화한다.
**화면에는 항상 "가상 시나리오 · 실제 병원의 응답이 아닙니다"가 보인다** — 병원 이름·위치·병상은 E-Gen 실제 데이터(고정 스냅샷)지만, 병원의 수용·거절은 시나리오가 정한 연출이다.

## 녹화

```bash
./voice/start-voice.sh          # 터미널 1 — 대본 구조화(MF_BERT)에 쓴다. demo 브랜치 코드로 띄울 것
./demo/record.sh 01             # 터미널 2 — 시나리오 01 → demo/out/scenario_01.mp4
./demo/record.sh 01 05 12       # 여러 개
./demo/record.sh all            # 전부
./demo/record.sh --play 01      # 녹화 없이 화면으로만 확인
```

`record.sh`가 알아서 띄우고 끈다: 시연용 hub(포트 5101) · 시연용 대시보드(포트 3100, `next dev`). 실서버(`start-all.sh`)와 동시에 떠 있어도 섞이지 않는다.

⚠ **카카오 지도**는 카카오 콘솔에 등록된 주소에서만 뜬다 — `http://localhost:3100`을 JavaScript SDK 도메인에 등록하거나, 실서버를 끄고 `DEMO_DASH_PORT=3000 ./demo/record.sh …`로 녹화한다.

## 구성

| 파일 | 하는 일 |
|---|---|
| `scenarios/NN.json` | 시나리오 하나 — 소개 문구, 구급차별 출동 위치·통화 대본·병원 응답(수용/불가·사유)·도착 결과 |
| `player/play.mjs` | 시나리오 진행기 + 녹화(Playwright). 실제 사용자와 같은 메시지를 hub에 보내고, 무대에서 장면을 연출한다 |
| `player/hub.mjs` | 시연용 hub 접속(구급차 한 대의 보이지 않는 탭) |
| `../dashboard/public/demo-stage.html` | 무대 — 1920×1080에 대시보드 창(관제 지도·구급차·대원 휴대폰·병원)을 배치. 지금 일이 벌어지는 창을 크게, 나머지는 오른쪽 썸네일 |
| `run_hub.py` | 시연용 hub — 실서버 코드 그대로, 포트 5101, 모든 기록(의사결정·거절 로그·상태)은 임시 폴더 |
| `snapshot.py` | 병원 정보 고정 스냅샷 `save`(실서버 hub 상태에서) / `load`(시연용 hub에, 시각은 지금으로 옮김) |
| `data/hospital_snapshot.json` | 고정 스냅샷(병원 415곳·구급차 3대, 2026-10-03 23시 기준) |
| `../voice/demo_text.py` | voice의 대본 입구 `POST /demo/structure` — STT 없이 실제 MF_BERT 구조화만 하고 결과를 돌려준다(hub로 직접 안 보냄) |

## 무엇이 실제고 무엇이 연출인가

- **실제**: hub 매칭·순위·존 확장·병상 판정(규칙 기반 엔진 그대로), MF_BERT 구조화(대본을 실제로 넣고 걸린 시간 그대로), 병상 신뢰도 확률(AI), 대시보드 화면 전부
- **연출**: 통화 음성(대본을 사람 말 속도로 자막에 재생 — 음성 인식 단계는 건너뜀), 병원의 수용·거절과 사유, 출동 위치, 구급차 이동(시뮬레이션, 구간 5초)
- 녹화마다 같은 스냅샷을 넣어 병원 후보·병상이 같다. 이동 시간은 카카오 실시간 ETA라 순위가 조금 달라질 수 있어, 시나리오는 "가장 위 병원이 거절"처럼 순위로 응답할 병원을 고른다

## 시나리오 형식

```json
{
  "id": "01", "title": "…", "intro": ["소개 카드 줄", "…"], "tags": ["구급차 1대", "…"],
  "ambulances": [{
    "apid": "A0000001", "name": "역삼 구급대", "startDelaySec": 0,
    "incident": { "lat": 37.498, "lng": 127.028, "label": "강남역 인근 사무실" },
    "call": "recommended",                       // 휴대폰으로 처음 전화할 병원: recommended | {"rank": 2}
    "script": ["대원 발화 한 줄", "…"],
    "responses": [                               // 매칭 순위대로 응답할 병원을 고른다
      { "who": "top", "action": "reject", "reason": "BEDS_FULL" },
      { "who": "top", "action": "approve" }      // who: top | {"rank": n} | called(전화한 병원)
    ],
    "arrival": "accept"                          // 또는 {"refuse": "NO_EQUIPMENT", "then": [ …응답… ]}
  }]
}
```

거절 사유: `BEDS_FULL` `OR_OCCUPIED` `STAFF_BUSY` `NO_WARD` `NO_DEPARTMENT` `NO_EQUIPMENT` `ON_CALL_MISMATCH` `NIGHT_UNAVAILABLE` `SEVERITY_EXCEEDED` `AGE_LIMIT`
