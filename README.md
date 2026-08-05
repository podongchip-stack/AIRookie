# 골든링크 (GoldenLink) — 2026 AI ROOKIE 대회 출품작

응급이송 과정에서 발생하는 음성·병원 응답 로그를 자동 수집·구조화하여 병원 수용
판단을 지원하고, 모든 의사결정 과정을 자동 기록하는 **Zero Data Entry 기반
응급이송 지원 플랫폼**이다. 구급대원이 여러 병원에 순차적으로 전화를 돌리는
"뺑뺑이" 문제를, 첫 병원과의 통화 내용을 텍스트로 요약해 존(Zone) 내 모든 후보
병원에 동시에 전달하는 방식으로 없앤다.

AI는 의료진의 판단을 대체하지 않는다 — 환자 정보 구조화와 의사결정 기록
자동화만 맡고, 병원 매칭(거리·병상·존)은 규칙 기반 엔진이 담당한다. 자세한
철학·원칙·데이터 포맷은 [CLAUDE.md](CLAUDE.md)를 참고한다 (모든 브랜치에
공통 적용되는 문서).

---

## 폴더 구조

이 저장소는 여러 브랜치가 하나의 작업 폴더를 공유하는 모노레포 구조다. 각
브랜치가 담당 영역을 자기 폴더로 분리해서 관리하며, develop은 그 셋을 통합해
실제로 통신이 되는 상태까지 합친 브랜치다.

```
AIRookie/
├── CLAUDE.md         공통 컨텍스트 (전 브랜치 동일 적용)
├── voice/            음성 수집·STT·실시간 음성 필터링·정보 구조화 (feature/voice)
├── hub/              병원 매칭 엔진 + HTTP 서버 (feature/hub)
├── info/             병원 정보 관리: E-Gen API·OCR (feature/info)
└── (dashboard/는 아직 develop에 통합되지 않음 — feature/dashboard 작업 완료 후 병합 예정)
```

각 폴더의 상세 내용(모델, 스키마, 실행 방법)은 폴더별 문서를 참고한다.

| 폴더 | 문서 | 담당 영역 |
|---|---|---|
| `voice/` | [voice/README.md](voice/README.md) | STT, 실시간 음성 필터링, SBAR 구조화 |
| `hub/` | [hub/README.md](hub/README.md) | 존 기반 병원 매칭, 진료과 임베딩 매칭, HTTP 서버 |
| `info/` | [info/README.md](info/README.md) | E-Gen API 병원 정보 정규화, 서류 OCR (현재 미사용) |

`info/ocr/`, `info/LLMdata/`, `info/simulation/`은 병원 서류 OCR 기반 정보
추출 경로다. 코드는 그대로 두었지만, 현재 병원 정보는 `info/Hospital_inform/`
(E-Gen API 경로)을 기준으로 하며 OCR 경로는 이번 통합 범위에서는 쓰지 않는다.

---

## 지금까지 통합된 것 / 남은 것

**완료 (이 브랜치)**
- voice·hub·info 세 브랜치를 각자 폴더 구조로 정리한 뒤 develop에 병합
- hub에 Flask 서버(`hub/app.py`) 구축 — `hub_engine.py`/`delivery.py`/
  `decision_log.py`의 기존 매칭·기록 로직은 그대로 재사용
- voice → hub: 통화 요약을 실제 HTTP POST로 전송 (`voice/transcribe.py`의
  `send_to_hub()`)
- info → hub: 병원 정보를 실제 HTTP POST로 전송 (`info/send_to_hub.py`).
  E-Gen 서비스키 승인 전까지, Supabase에 넣어둔 **실제 서울 권역응급의료센터
  7곳** 정보를 대신 가져와 보낸다 (병원명·주소·좌표는 실제, 병상·장비 등
  운영 데이터는 플레이스홀더 — [info/Hospital_inform/README.md](info/Hospital_inform/README.md) 참고)
- 위 두 통신 경로를 단독 처리(구급차 한 대) 시나리오로 실제 HTTP 통신까지 검증 완료
  (구급차 테스트 좌표도 병원 위치에 맞춰 서울시청 부근으로 맞춰둠)

**아직 범위 밖**
- feature/dashboard와의 통신 (hub → dashboard, dashboard → hub 승인 액션)
- hub → info 병상 갱신 알림 (`hub/delivery.py`의 `send_to_info()`는 자리만 있음)
- 여러 사건(구급차)이 동시에 처리되는 경우의 상태 분리 — 지금은 `HubEngine`
  인스턴스 하나를 전역으로 쓴다
- 구급차 실제 GPS를 받는 입력 채널 — 지금은 `hub/app.py`에 서울시청 부근
  테스트 좌표가 고정값으로 들어가 있다 (실제 GPS 연동 전까지 임시)
- E-Gen 실제 API 연동 — 서비스키 승인 전까지 Supabase 대체 DB로 대신함

---

## 로컬에서 전체 흐름 실행해보기

세 서비스는 HTTP로 통신하므로 각자 독립된 가상환경에서 따로 실행한다 (하나로
통합하지 않는다 — torch/transformers 등 버전이 서로 달라 한 환경에 넣으면
충돌한다). 아래는 conda 기준이며, `venv` 등 다른 도구를 써도 무방하다.

### 0. 가상환경 준비 (최초 1회)

```bash
# hub용
conda create -n rookie_hub python=3.11 -y
conda activate rookie_hub
cd hub && pip install -r requirements.txt && cd ..

# info용 (hub와 별도 환경)
conda create -n rookie_info python=3.11 -y
conda activate rookie_info
cd info && pip install -r requirements.txt && cd ..
```

`voice`는 이미 존재하는 `rookie_voice` 환경(또는 [voice/README.md](voice/README.md)의
"빠른 시작")을 그대로 쓰면 된다.

### 0-1. info: Supabase 접속 정보 받기 (최초 1회)

info는 E-Gen 서비스키 승인 전까지 Supabase를 대체 DB로 쓴다. 이미 만들어둔
Supabase 프로젝트(서울 권역응급의료센터 7곳 데이터 포함)의 **Project URL과
secret key를 팀 채널(예: 슬랙 DM)로 전달받아야 한다** — 이 값은 git 저장소에
올라가 있지 않다 (`Hospital_inform/.env`가 `.gitignore` 대상).

받은 값으로 `info/Hospital_inform/.env` 파일을 새로 만든다:
```
SUPABASE_URL=<전달받은 Project URL>
SUPABASE_KEY=<전달받은 secret key>   # publishable key 아님, sb_secret_로 시작하는 값
```

**1. hub 서버 실행**
```bash
conda activate rookie_hub
cd hub
python app.py            # http://127.0.0.1:5001
```

**2. info → hub: 병원 정보 전송**
```bash
conda activate rookie_info
cd info
python send_to_hub.py
```
Supabase에서 서울 병원 7곳을 조회해 hub로 전송한다. hub를 재시작(코드 수정
등으로 자동 리로드된 경우 포함)하면 메모리 안의 병원 정보가 초기화되므로,
그때마다 이 스크립트를 다시 실행해야 한다.

**3. voice → hub: 통화 요약 전송**

`voice/transcribe.py --summarize`를 실행하면 STT + 구조화가 끝난 뒤 자동으로
hub에 전송된다 (자세한 실행법은 [voice/README.md](voice/README.md) 참고).
hub 주소를 바꾸려면 `HUB_VOICE_SUMMARY_URL` 환경변수를 쓴다.

음성 파이프라인 없이 매칭만 빠르게 확인하려면 curl로 대신할 수 있다 (2번을
먼저 실행해 병원이 등록된 상태여야 함):
```bash
curl -s -X POST http://127.0.0.1:5001/voice/summary \
  -H "Content-Type: application/json" \
  -d '{"summary": {"patient": "60대 남성", "mechanism": "급성 심근경색 의심", "symptoms": ["흉통", "호흡곤란"], "treatment": ["산소 공급"], "severity_tag": "high"}, "source": "ai"}' \
  | python -m json.tool
```
구급차 테스트 좌표가 서울시청 부근으로 고정돼 있어, zone 1(0~5km) 안의
서울대학교병원·고려대학교안암병원 정도가 매칭되어 나오는 게 정상이다.

**결과 확인**: hub가 반환한 매칭 결과는 `hub/data/test/output/`에 저장되고,
모든 의사결정은 `hub/data/logs/decision_log.jsonl`에 타임스탬프+해시로
기록된다 (`hub/decision_log.py`).
