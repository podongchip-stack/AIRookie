# 골든링크 (GoldenLink) — 2026 AI ROOKIE 대회 출품작

응급이송 과정에서 발생하는 음성·병원 응답 로그를 자동 수집·구조화하여 병원 수용
판단을 지원하고, 모든 의사결정 과정을 자동 기록하는 **Zero Data Entry 기반
응급이송 지원 플랫폼**이다. 구급대원이 여러 병원에 순차적으로 전화를 돌리는
"뺑뺑이" 문제를, 첫 병원과의 통화 내용을 텍스트로 요약해 존(Zone) 내 모든 후보
병원에 동시에 전달하는 방식으로 없앤다.

AI는 의료진의 판단을 대체하지 않는다 — 환자 정보 구조화와 의사결정 기록
자동화만 맡고, 병원 매칭(거리·병상·존)은 규칙 기반 엔진이 담당한다. 자세한
철학·원칙·데이터 포맷은 [CLAUDE.md](CLAUDE.md)를 참고한다 (모든 브랜치에
공통 적용되는 문서). 보고서용 재료 정리는 [REPORT.md](REPORT.md)(통합 시스템
기준)와 각 브랜치의 `REPORT.md`/`REPORT_NOTES.md`를 참고한다.

---

## 폴더 구조

이 저장소는 여러 브랜치가 하나의 작업 폴더를 공유하는 모노레포 구조다. 각
브랜치가 담당 영역을 자기 폴더로 분리해서 관리하며, `develop`은 4개 브랜치를
전부 통합해 실제로 통신이 되는 상태까지 합친 브랜치다.

```
AIRookie/
├── CLAUDE.md         공통 컨텍스트 (전 브랜치 동일 적용)
├── REPORT.md          통합 시스템 보고서 재료 (수식·통신·실측 근거)
├── voice/            음성 수집·STT·오인식 교정·SBAR 구조화 (feature/voice)
├── hub/              병원 매칭 엔진 + HTTP/WebSocket 서버 (feature/hub)
├── info/             병원 정보 관리: E-Gen·심평원 API·OCR (feature/info)
└── dashboard/        구급차·병원 대시보드 (feature/dashboard)
```

각 폴더의 상세 내용(모델, 스키마, 실행 방법)은 폴더별 문서를 참고한다.

| 폴더 | 문서 | 담당 영역 |
|---|---|---|
| `voice/` | [voice/README.md](voice/README.md) | STT, 오인식 교정, SBAR 구조화 |
| `hub/` | [hub/README.md](hub/README.md), [hub/REPORT.md](hub/REPORT.md) | 존 기반 병원 매칭, 진료과 임베딩 매칭, HTTP/WebSocket 서버 |
| `info/` | [info/README.md](info/README.md), [info/REPORT_NOTES.md](info/REPORT_NOTES.md) | E-Gen·심평원 API 병원 정보 정규화, 신뢰도 진단(`hospital_score`), 서류 OCR |
| `dashboard/` | [dashboard/README.md](dashboard/README.md) | 구급차/병원 실시간 화면, 승인 워크플로우 |

`info/ocr/`, `info/LLMdata/`, `info/simulation/`은 병원 서류 OCR 기반 정보
추출 경로다(경로 B). 현재 상시 파이프라인은 `info/Hospital_inform/`(경로 A,
E-Gen·심평원 실 API)을 기준으로 하며, 경로 B는 아직 경로 A와 병합되지 않았다
(당직 정보·tPA만 서류로 메울 수 있음).

---

## 지금까지 통합된 것 / 남은 것

**완료**
- `voice`·`hub`·`info`·`dashboard` 4개 브랜치가 전부 `develop`에 병합돼 실제
  통신까지 검증됨(HTTP/WebSocket 전부 실서버로 확인)
- voice → hub, info → hub, hub ↔ dashboard(WebSocket) 전 구간 연동 완료
- **병원 정보는 Supabase가 아니라 E-Gen·심평원 실 API로만 받는다.** 병원용
  Supabase는 2026-08-13 완전히 제거됐다 — `hospitalId`도 자체 발급 코드가
  아니라 실제 E-Gen 기관코드(`A1100017` 등)를 그대로 쓴다
- 수집 범위가 서울특별시에서 **전국(533곳)**으로 확장됨
- info-v2(`hospital_score/`)가 병원 신고 데이터의 신뢰도를 심평원 대조로
  진단해 hub·dashboard까지 전달됨(설명용) + `declared_no`(명시적 수용 불가
  신고)는 hub 순위 정렬에도 실제로 반영됨(2026-08-14)
- 병상 차감은 hub 메모리의 TTL 오버레이(15분)로 처리 — info로 되돌려 쓰지 않음
- 여러 사건(구급차)이 동시에 처리돼도 `caseId`·`apid`로 격리됨
- 존(Zone) 확장(거절 비율 기반), 신원 확인(`GET /identity`), dashboard의 거절
  사유 선택 UI까지 전부 구현·병합 완료

**아직 범위 밖**
- hub → info 거절 로그 전달 배선(`POST /hub/rejection`) — info 수신구는
  준비돼 있으나 hub가 아직 안 부름(`hub/REPORT.md` §5-1)
- 서류 OCR(경로 B) → E-Gen 정규화(경로 A) 병합
- 구급차 실시간 GPS(지금은 `AmbulanceInfo`에 저장된 고정값)
- 카카오내비 자동 연동(CLAUDE.md 시스템 흐름도에만 명시, 코드 없음)

---

## 로컬에서 전체 흐름 실행해보기

네 서비스는 HTTP/WebSocket으로 통신하므로 각자 독립된 가상환경에서 따로
실행한다 (하나로 통합하지 않는다 — torch/transformers 등 버전이 서로 달라
한 환경에 넣으면 충돌한다). 아래는 conda 기준이며, `venv` 등 다른 도구를 써도
무방하다.

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

`voice`는 [voice/README.md](voice/README.md)의 "빠른 시작"을, `dashboard`는
[dashboard/README.md](dashboard/README.md)를 참고한다(Node.js 기반, `npm
install` 후 `npm run dev`).

### 0-1. info: API 키 준비 (최초 1회)

병원 Supabase는 더 이상 안 쓴다 — `info/Hospital_inform/.env`에 아래 두 값만
있으면 된다(같은 계정 인증키 하나를 두 서비스에 활용신청한 것이라 값은 같다):

```
EGEN_SERVICE_KEY=<E-Gen 서비스키>
HIRA_SERVICE_KEY=<심평원 서비스키, EGEN_SERVICE_KEY와 동일한 값>
```

구급차 레지스트리(병원용과 별도 Supabase 프로젝트)를 쓰려면
`AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY`도 추가한다 — 없으면 이
부분만 조용히 건너뛰고 병원 정보 동기화는 계속된다.

심평원 조인·전문의 수 캐시가 로컬에 없으면(새 장비 등) 아래를 한 번 실행해야
`hospital_score`의 신뢰도 진단이 제대로 나온다(안 해도 죽지 않고 `unknown_bare`로
안전하게 낮아질 뿐이다):
```bash
cd info/Hospital_inform/info
python -m hospital_score.hira_files --fetch
python -m hospital_score.hira --build-join
```

**1. hub 서버 실행**
```bash
conda activate rookie_hub
cd hub
python app.py            # http://127.0.0.1:5001
```

**2. info → hub: 병원 정보 상시 전송**
```bash
conda activate rookie_info
cd info
python send_to_hub.py
```
E-Gen·심평원 실 API에서 전국 병원 정보를 조회해 기본 30분 주기로 hub에 계속
재전송하는 상시 프로세스다(1회성 아님). hub를 재시작하면 메모리 안의 병원
정보가 초기화되므로, 다음 주기까지 기다리거나 이 스크립트를 다시 실행한다.

**3. voice → hub: 통화 요약 전송**

`voice/transcribe.py --summarize`를 실행하면 STT + 구조화가 끝난 뒤 자동으로
hub에 전송된다(자세한 실행법은 [voice/README.md](voice/README.md) 참고).

음성 파이프라인 없이 매칭만 빠르게 확인하려면 curl로 대신할 수 있다 (2번을
먼저 실행해 병원이 등록된 상태여야 함):
```bash
curl -s -X POST http://127.0.0.1:5001/voice/summary \
  -H "Content-Type: application/json" \
  -d '{"caseId": "case-test", "transcript": {"raw_text": "x", "filtered_text": "x"}, "summary": {"patient": "60대 남성", "mechanism": "급성 심근경색 의심", "symptoms": ["흉통", "호흡곤란"], "treatment": ["산소 공급"], "severity_tag": "high"}, "source": "ai"}' \
  | python -m json.tool
```

**4. dashboard 실행**
```bash
cd dashboard
npm install
npm run dev               # http://localhost:3000
```
`NEXT_PUBLIC_HUB_HTTP_URL`(예: `http://127.0.0.1:5001`)을 `.env.local`에
설정한다. `/ambulance?id=<apid>`·`/hospital?id=<hpid>`로 접속하며, 접근 코드는
`send_to_hub.py`가 실제로 보낸 hpid/apid를 써야 한다(더 이상 `S0000001~7`
같은 고정 코드가 아니다).

**결과 확인**: hub가 반환한 매칭 결과는 `hub/data/test/output/`에 저장되고,
모든 의사결정은 `hub/data/logs/decision_log.jsonl`에 타임스탬프+해시로
기록된다(`hub/decision_log.py`).
