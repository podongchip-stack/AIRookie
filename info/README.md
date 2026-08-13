# [feature/info] — 병원 정보 수집·정규화 (E-Gen API + 서류 OCR)

> **폴더 구조 안내(모노레포)**: 이 저장소는 `feature/voice`·`feature/hub`·
> `feature/info`·`feature/dashboard`가 하나의 저장소를 공유하며, 각 브랜치는
> 자기 작업 폴더(`voice/`·`hub/`·`info/`·`dashboard/`)만 갖는다. **지금 이
> 브랜치에는 `info/` 폴더만 있고 `voice/`·`hub/`·`dashboard/`는 없다.** 만약
> 작업 중 낯선 폴더가 보인다면 `develop`을 머지했거나 다른 브랜치를 체크아웃한
> 상태라는 뜻이니, 실수로 만들어진 게 아닌지 걱정하지 않아도 된다.

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은** `feature/hub`**로 이관하는 것으로
> 확정**되어 구 스키마(존 기반 병원 매칭 결과)는 이 문서에서 제거했습니다.
> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)의
> 수신 주체도 `feature/hub`**로 확정**되었습니다 (dashboard는 feature/hub와만
> 직접 통신하기 때문). 이 브랜치는 승인 액션을 직접 받지 않는 대신, hub가
> 확정 처리 후 내려주는 "병상 갱신 알림"을 받는다 (아래 참고).

## 담당자

- 이름: 김동현
- 역할: 리드 개발자



- 이름: 최준혁
- 역할: 리드 개발자

## 이 브랜치가 하는 일

응급의료기관의 상태를 모아 **표준 형식(`HospitalInfo`)으로 정규화해
`feature/hub`에 공급**한다. 환자에게 어느 병원이 적합한지는 판정하지 않는다 —
그건 `feature/hub`의 몫이다.

데이터 소스가 둘이고 성격이 정반대인 것이 이 브랜치의 특징이다. 2026-08-12부터
**경로 C**가 붙었는데, 이건 새 소스가 아니라 **가져온 정보를 믿을 수 있는지 검증하는**
층이다.

| | 경로 A — E-Gen 공개 API | 경로 B — 병원 서류 OCR | 경로 C — 신뢰도 진단 |
|---|---|---|---|
| 폴더 | [`Hospital_inform/`](Hospital_inform/README.md) | [`ocr/`](ocr/README.md) | [`hospital_score/`](Hospital_inform/info/hospital_score/README.md) |
| 질문 | 정보를 어디서 가져오나 | 공개 API가 못 주는 것 | **가져온 정보를 믿을 수 있나** |
| 범위 | 전국 533곳 | 소수 기관 | 전국 533곳 |
| 실시간성 | 실시간 | 정적 (서류 발급 시점) | 실시간 + 정적 대조 |
| 깊이 | 얕음 — 병상 6종, 시술·장비 역량 | 깊음 — 당직 전문의, 진료과별 인력 | 15그룹 역량 + 근거·신뢰도 |
| 처리 | 규칙 기반 (AI 미사용) | AI(레이아웃·인식·추출) + 규칙(검증) | 규칙 기반 (AI 미사용) |
| 현재 상태 | **실 API 연동 완료** (2026-08-10 승인) | 로직 완성 — 실측 대기 | **구현 완료 — hub 연동 대기** |

**당직 전문의 정보는 공개 API로 나오지 않는다.** 그 공백을 서류 OCR로 메우는 것이
이 브랜치의 고유 가치다. E-Gen의 "중증질환 수용가능 정보"가 그 상당 부분을 대체할
수 있는지는 서비스키 승인 후 실측으로 확인했다 — **일부만 대체된다.**

- 대체됨: 재관류(심근경색·뇌경색), 뇌출혈 수술, 응급 제왕절개, CT·혈관촬영기 가용 여부
- **E-Gen으로는 대체 안 됨**: 진료과별 의사 수, 정맥 혈전용해술(tPA)
- **다른 공개 API로 대체됨(2026-08-12)**: 진료과별 전문의 수는 **심평원
  의료기관별상세정보서비스**가 준다. "공개 API에 항목 자체가 없다"고 적었던 것은
  E-Gen만 봤을 때의 이야기였고, 지금은 실제로 받아 쓰고 있다
  ([`Hospital_inform/info/hospital_score/`](Hospital_inform/info/hospital_score/README.md))
- **여전히 어디에도 없음**: tPA — `MKioskTy` 28개 항목 어디에도 없다

즉 서류 OCR이 메워야 할 공백이 **무엇인지가 구체적으로 확정**됐다. 자세한 것은
[`Hospital_inform/README.md`](Hospital_inform/README.md) "실측으로 확인한 것" 참고.

### 경로 C — 신뢰도 진단·외부 대조 (`hospital_score/`, 2026-08-12 신설, 구현 완료)

> **구현은 끝났고 hub 연동만 남았다.** 점수 산출(`scoring.py`)까지 전부 돌아가며
> 불변식 검사와 전문병원 홀드아웃 검증을 통과했다. 다만 상시 파이프라인
> (`send_to_hub.py`)은 오늘도 E-Gen 신고만 보낸다 — `assessment` 필드는 hub와
> **동시 배포**여야 하기 때문이다(hub가 unknown 필드를 거부하면 그 순간 기존 연동이
> 깨진다). 이 폴더는 통째로 지워도 기존 경로가 멀쩡하도록 격리돼 있다.

경로 A·B가 "정보를 어디서 가져오나"의 문제라면, 경로 C는 **"가져온 정보를 믿을 수
있나"**의 문제다. 만들게 된 계기는 실측 하나였다.

```
전국 가용병상 1위  한림대학교한강성심병원  30병상
                  → 2019년 11월 19일에 입력된 값 (2,457일 전)
                  → 게다가 국내 대표 화상 전문병원인데 [중증화상] 항목은 "정보미제공"
```

E-Gen이 주는 값은 전부 **병원이 스스로 신고한 것**이고, 같은 소스 안에서는 그게
맞는지 검증할 방법이 없다. 그래서 **소스를 늘려 어긋나는 지점을 드러낸다.**

실측으로 확인한 것 (전부 `python -m hospital_score.report`로 재현된다):

| 발견 | 규모 |
|---|---|
| 하루 넘게 방치된 병상 값을 실시간으로 송출 중 | 전국 **25곳**, 최고 **8.6년** — 전부 응급실운영신고기관 |
| 중증질환 수용가능 신고의 "정보미제공" | 전체 **70.8%**, 등급별로 21.4% → 53.0% → 88.2% → 96.4% |
| 명부엔 있는데 병상 응답에 없는 병원 | **90곳** ("병상 0"과 다르다) |
| 화상 전문병원 중 E-Gen에 화상 역량이 보이는 곳 | 5곳 중 **0곳** |

붙인 외부 소스 (전부 심평원, 같은 계정 인증키):

| 데이터 | 얻는 것 |
|---|---|
| 병원정보서비스 (15001698) | `ykiho` · 좌표 · 의사 수 — **조인의 출발점** |
| 의료기관별상세정보 (15001699, v2.8) | 전문과목별 전문의 수 · 진료과목 · 장비 등 11종 |
| 전문병원 지정 현황 (15051054, odcloud) | 분야별 전문병원 114곳 |

E-Gen과 심평원은 공통 식별자가 없어(`hpid` ↔ `ykiho`) **좌표 최근접으로 붙였고,
533곳 중 518곳(97.2%)이 1.2km 이내, 오차 중앙값 11m**로 연결됐다.

산출물은 병원별 **`[여건 스칼라 + 15그룹 역량 벡터] + 신뢰도 + 근거`**다. 병원당 단일
점수는 만들지 않는다 — 심근경색 환자와 화상 환자에게 같은 병원의 수용가능성이 다르다.

점수는 "정답이 없으므로" 최적화하지 않고, **근거 강도의 계층 5단계와 불변식**으로 정한다.

```
불가능 신고 0.2  <  근거 없는 미상 0.4  <  전문의 있는 미상 0.6
                 <  전문병원 지정 미상 0.8  <  가능 신고 1.0
```

`score`와 `confidence`는 **끝까지 곱하지 않는다.** 섞으면 "확실히 낮음"과 "모르겠음"이
구분되지 않는다 — 미상과 확인된 만실을 구분해온 원칙과 같다. 전문병원 지정을 홀드아웃
정답으로 쓴 검증에서 **화상 후보가 0곳 → 4곳**이 됐다.

hub로는 기존 `HospitalInfo`에 **`assessment` 키 하나만 얹은 superset**으로 나간다
(병원당 약 5.1KB). 기존 필드는 하나도 바뀌지 않는다.

거절 로그 수신구(`POST /hub/rejection`)도 함께 세워뒀다. 점수의 진짜 정답은 "병원이
실제로 받았는가"인데 그건 운영 로그가 쌓여야 나오고, **로그는 소급해서 만들 수 없기**
때문이다. hub는 지금 보내는 형태 그대로도 연동된다.

자세한 것과 팀에 요청하는 사항은
[`Hospital_inform/info/hospital_score/README.md`](Hospital_inform/info/hospital_score/README.md).

```
[경로 A] E-Gen 공개 API (전국 실시간, 얕음)
    ├─ getEgytListInfoInqire               좌표 · 응급의료기관 등급
    ├─ getEmrrmRltmUsefulSckbdInfoInqire   실시간 가용병상 6종 · 총병상 · 장비 가용
    └─ getSrsillDissAceptncPosblInfoInqire 중증질환 수용가능 28항목
         │
         ├─ [규칙] 3개 응답을 hpid로 합치고 결측·과밀·입력오류 처리 (egen/mapper.py)
         │     HospitalInfo ────────────────────────────┐
         │                                              │
         └─ [축적] 원본 응답 그대로 시계열 저장 (snapshot.py, 전국 20분)
               data/snapshots_nationwide/YYYY-MM-DD.jsonl
                    │                                   │
                    ↓                                   │
[경로 C] 신뢰도 진단·외부 대조 (hospital_score/)          │
    ├─ 심평원 병원정보 (15001698)        ykiho · 좌표     │
    ├─ 심평원 의료기관별상세 (15001699)  전문과목별 전문의 수
    └─ 심평원 전문병원 지정 (15051054)   분야별 114곳      │
         │                                              │
         └─ [규칙] 좌표 최근접 조인(518곳) → 계층 기반 점수 │
               assessment (여건 + 15그룹 역량 + 신뢰도 + 근거)
                                    (배선 대기) ─────────┤
                                                        │
[경로 B] 병원 서류 이미지 (정적, 깊음)                     │
         ↓ [AI]  레이아웃 검출 → 영역별 텍스트 인식        │
      텍스트                                             │
         ↓ [AI]  필드 그룹별 추출 (JSON Schema 제약 디코딩)│
         ↓ [규칙] 근거 대조(환각 필터) · 어휘 검증          │
      DocumentFields ──→ (병합 미구현) ──────────────────┤
                                                        ↓
                                                  feature/hub
```

두 경로의 **합류 지점(`DocumentFields` → `HospitalInfo` 병합)은 아직 미구현**이다.
현재는 각 경로가 독립적으로 자기 산출물을 낸다.

## 사용한 AI / 모델

| 구분 | 모델명 | 용도 | 비고 |
| --- | --- | --- | --- |
| 레이아웃 검출 | [DocLayout-YOLO-DocStructBench-ONNX](https://huggingface.co/podongchip/DocLayout-YOLO-DocStructBench-ONNX) | 서류 이미지에서 영역 위치·종류(10종) 검출 | Apache-2.0. 원본 가중치를 ONNX로 변환해 재배포한 것 — 원본 실행 패키지가 AGPL-3.0이라 `onnxruntime`(MIT)으로 실행 |
| 텍스트 인식 | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) (0.9B) | 잘라낸 영역별 텍스트 추출 (표는 표 인식 모드) | Apache-2.0. 로컬 실행, 외부 API 미사용 |
| 정보 구조화 | qwen3:14b (Ollama) | 추출된 텍스트 → 병원 정보 필드 | Apache-2.0. 로컬 실행. JSON Schema 제약 디코딩으로 형식 보장. 모델명은 환경변수로 교체 가능 |

상세 내용은 [`ocr/README.md`](ocr/README.md) 참고.

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
>
> - [x] AI 처리 — 서류 이미지의 레이아웃 검출·텍스트 인식, 텍스트에서 필드 추출
> - [x] 규칙 기반 — 영역 정리·태스크 라우팅, 근거 대조·어휘 검증, E-Gen 정규화, hub 연동

한 브랜치 안에서 두 영역이 나뉜다. 경로 A는 전부 규칙 기반이고, 경로 B는 단계별로
갈린다. **값을 찾아내는 일만 AI가 하고, 그 값을 받아들일지는 전부 규칙이 정한다.**
결과 JSON에 `source: "ai"` / `"rule"` 로 표시된다.

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 실행 환경: 로컬 (On-Premise 원칙 — 환자·병원 데이터가 외부 상용 API로 나가지 않는다)

의존성이 셋으로 나뉜다. 목적이 다르고, 하나만 필요한 경우가 많기 때문이다.

| 파일 | 내용 | 언제 필요한가 |
|---|---|---|
| `requirements.txt` | Flask, Flask-SocketIO, requests, python-dotenv | 서버·E-Gen API 호출. `send_to_hub.py`(주기적 재조회)와 `app.py`(hub의 병상 갱신 수신)가 이 의존성을 쓴다 |
| `ocr/requirements.txt` | torch, transformers, onnxruntime, opencv 등 | 서류 이미지 → 텍스트. **NVIDIA GPU 필요** |
| `ocr/requirements-extract.txt` | pydantic | 텍스트 → 필드. GPU 불필요, Ollama 서버만 있으면 됨 |
| `simulation/requirements.txt` | tkinterdnd2, pypdfium2 | 처리 과정을 보는 GUI. 위 두 개 위에 창만 얹는다 |

`LLMdata/`는 코드가 아니라 데이터라 의존성이 없다 — 서류 원본과, 처리하면서 쌓이는
학습용 입력·타깃이 들어간다.

`Hospital_inform/`(경로 A)은 가볍다 — torch도 onnxruntime도 필요 없다.
fixture로 로직만 돌릴 때는 **pydantic 하나**, 실제 API를 칠 때는 여기에
`requests`·`python-dotenv`가 더 필요하다(XML 파싱은 표준 라이브러리를 쓴다).
GPU 없는 장비에서 E-Gen 정규화와 필드 추출 로직을 개발할 수 있게 의존성을 이렇게
갈라 두었다.

> `requirements.txt`의 주석은 외부 API를 "hv1(전문의 보유) / hvec(병상 현황) /
> hv2(중증질환별 수용 가능)"로 적고 있는데 **이는 CLAUDE.md에서 온 명세 오류다.**
> 활용가이드 V4와 실응답으로 확인했다 — `hvec`·`hv2`는 별도 API가 아니라 가용병상
> 응답 **안의 필드**이고, 뜻도 각각 응급실 일반병상 수·**내과 중환자실 병상 수**다.
> 중증질환 수용가능은 `getSrsillDissAceptncPosblInfoInqire`라는 별개 오퍼레이션이며
> 필드는 `MKioskTy1`~`MKioskTy28`이다. 정정 요청 내용은
> [`Hospital_inform/README.md`](Hospital_inform/README.md) "팀 확인 요청" 참고.

## 입출력 데이터 포맷 (약식)

> 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어, 기존에 있던 "바이탈
> 스트림 → dashboard" 스키마는 이 문서에서 제거했습니다.

> 존 기반 병원 매칭 결과 스키마는 `feature/hub` 신설로 대체되어 이 문서에서
> 제거했습니다. 최신 스키마는 `feature/hub` README.md의 "입출력 데이터 포맷 >
> 출력 스키마 4"를 참고하세요.

### 통합 데이터 모델: HospitalInfo

`feature/info`와 `feature/hub` 사이를 오가는 두 메시지(아래 1·2번)는 서로 다른
스키마가 아니라, **같은 병원 레코드(HospitalInfo)를 서로 다른 크기로 주고받는
것**이다. info가 hub로는 전체 레코드를 보내고, hub가 info로는 병상 수만 담은
부분 갱신(patch)을 돌려준다 — 필드 집합은 아래 표 하나를 기준으로 통일한다.

| 필드                                  | 타입                           | 설명                                            | 1번(info→hub 전체 전송) | 2번(hub→info 부분 갱신)                    |
| ----------------------------------- | ---------------------------- | --------------------------------------------- | ------------------ | ------------------------------------- |
| `hospitalId`                        | string                       | 병원 고유 식별자                                     | 포함                 | 포함 (대상 식별용)                           |
| `name`                              | string                       | 병원명                                           | 포함                 | 미포함 (안 바뀌는 값)                         |
| `gps.lat` / `gps.lng`               | number                       | 병원 위치 좌표 (Hub의 거리 계산에 사용)                     | 포함                 | 미포함                                   |
| `availableBedCount`                 | number                       | 실시간 가용 응급실 병상 수                               | 포함 (현재값)           | 포함 (hub가 확정 처리 후 계산한 최신값 — 이 값으로 덮어씀) |
| `nightDutyAvailable`                | boolean                      | 야간 당직 전문의 존재 여부                               | 포함                 | 미포함                                   |
| `specialties[].department`          | string                       | 진료과명                                          | 포함                 | 미포함                                   |
| `specialties[].doctorCount`         | number                       | 해당 진료과 수술 가능 의사 수                             | 포함                 | 미포함                                   |
| `specialties[].recentProcedureTags` | string[]                     | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반) | 포함                 | 미포함                                   |
| `status`                            | `"confirmed"` \| `"rejected"` | 이 갱신이 발생한 사유                                 | 미포함 (해당 없음)        | 포함                                    |
| `source`                            | `"rule"`                     | 규칙 기반 데이터임을 나타내는 고정값                          | 포함                 | 포함                                    |
| `updatedAt`                         | string (ISO 8601)            | 이 레코드/갱신이 마지막으로 발생한 시각                        | 포함                 | 포함                                    |

위 표가 **팀 합의 기준**이다. 여기에 더해 아래 두 필드를 optional 확장으로 덧붙여
내보낸다. 기존 필드는 하나도 바꾸지 않았고, hub의 `HospitalInfo`는 모르는 필드를
무시하므로(pydantic 기본 동작) 읽지 않아도 아무것도 깨지지 않는다.

| 필드 | 타입 | 설명 | 상태 |
|---|---|---|---|
| `bedsByType` | `{[코드]: number}` | 병상 종류별 가용 수 (`ER_ADULT`, `ER_PEDIATRIC`, `ICU` …). 성인/소아 분기의 핵심. **미상인 종류는 키 자체를 넣지 않는다** | 확장 (합의됨) |
| `capabilities` | string[] | 수행 가능한 시술·장비 표준 코드 (`PROC_PCI_EMERGENCY`, `EQP_CT_24H` …). hub의 하드필터 대조 대상 | 확장 (합의됨) |
| `assessment` | object | 경로 C의 판정 — 여건 + 15그룹 역량 벡터 + 신뢰도 + 근거 | **제안 · hub와 동시 배포 필요** |

두 어휘는 `Hospital_inform/info/schema.py`에 고정돼 있고 값이 어휘 밖이면
**만드는 순간 실패**한다(병상 6종 `BED_CODES`, 역량 7종 `CAPABILITY_CODES`).
voice가 보내는 "필요역량"과 여기서 올리는 "보유역량"이 같은 어휘여야 hub가 대조할 수
있는데, 한쪽이 임의 코드를 쓰면 에러 없이 조용히 매칭에서 빠지기 때문이다.

⚠️ **이름이 겹쳐 헷갈리기 쉽다.** 기존 `capabilities`는 역량 코드 7종의 `list[str]`이고,
경로 C 판정의 15그룹은 `assessment.groups`다. 서로 다른 것이라 네임스페이스를 분리했다.

배경은 [`Hospital_inform/hospital-info-interface-proposal.md`](Hospital_inform/hospital-info-interface-proposal.md) 참고 —
매칭 판정을 임베딩 유사도에서 **표준 코드 정확 대조**로 옮기고 임베딩은 info의 정규화
단계로 내리자는 제안이며, 위 확장 필드가 전부 여기서 나왔다.

### 1. feature/info → feature/hub (HospitalInfo 전체 전송)

> `feature/hub` 신설에 따라 추가된 스키마. `feature/hub`가 실제로 받는
> 입력 형태와 동일하다. 가안이며 팀 리뷰 후 확정 예정.

> **상시 파이프라인의 데이터 출처 (2026-08-11 갱신)**: `send_to_hub.py`의
> `fetch_hospitals()`가 목록·좌표·중증질환 수용가능정보는 실 E-Gen API
> (`HttpEgenClient`)에서, 실시간 병상 수(hvec)는 여전히 Supabase 대체 DB
> (`SupabaseEgenClient`)에서 읽어 합친다. 병상만 Supabase에 남긴 이유: E-Gen은
> 조회 전용 공개 API라 hub가 이송 확정(`final_approval`) 시 차감한 병상 수를
> 되돌려 쓸 방법이 없다(`egen/client.py`의 `HttpEgenClient.update_bed_count()`는
> `NotImplementedError`). 병상까지 실 API로 읽으면 재조회 때마다(기본 30분) hub가
> 이미 차감해둔 값이 되돌아가 뺑뺑이 방지 취지와 반대로 간다 — 자세한 근거는
> `send_to_hub.py` 모듈 docstring 참고. 실 API 호출이 실패하면(서비스키 미설정,
> 일일 트래픽 한도 초과 등) 이번 주기는 목록·중증질환도 Supabase 값으로 대체해
> 계속 돈다.
>
> **hpid 불일치 주의**: Supabase 대체 DB는 서비스키 승인 전에 만들어져 실제
> hpid를 몰랐고 자체 식별자(`S0000001`~`S0000007`)를 붙였다 — 실 API의
> hpid(`A11...`)와 전혀 다른 값이다. 그대로는 두 소스를 hpid로 join할 수 없어서,
> `send_to_hub.py`의 `SUPABASE_TO_EGEN_HPID`에 GPS 최근접 대조로 검증한(전부
> 1.2km 이내) 7곳 수기 대응표를 두고 실 API 응답의 hpid를 Supabase hpid로
> 되돌려 맞춘다. **`hospitalId`는 (아직은) `S0000001`~`S0000007` 체계를 유지한다**
> (hub·dashboard가 이미 이 값을 식별자로 쓰고 있어 바꾸면 파급이 크다). 이 7개
> 병원 구성이 바뀌면 대응표도 같이 갱신해야 한다.
>
> 🔴 **여기서 병원 526곳이 버려진다 — 최우선 과제 (2026-08-13 hub와 해소 합의).**
> `_remap_to_supabase_hpid()`가 대응표 밖 기관을 전부 버려서 **E-Gen에서 533곳을
> 받아도 hub에는 7곳만 간다.** 존(Zone)을 넓혀도 전국 후보가 7곳뿐이고 그 7곳은
> 전부 서울이라 지방 이송은 후보가 0곳이다. 합의된 해법은 **병상 차감을 Supabase가
> 아니라 짧은 TTL(10~15분) 오버레이로 관리**하고 병상 자체는 E-Gen 실값을 쓰는 것이다
> (`hvidate` 갱신 경과 중앙값이 5분, 443곳 중 88.7%가 10분 이내라는 실측이 근거).
> Supabase 의존이 사라지면 대응표도 불필요해지고 533곳이 전부 hub로 간다.
> **딸려오는 변경**: `hospitalId`가 실 hpid(`A1100017` 등)로 바뀌므로 병원
> 대시보드의 `?id=` 라우팅과 hub의 `GET /identity` 대상 값 확인이 필요하다.

**출력** (위 HospitalInfo 표의 "1번" 열에 해당하는 필드 전부)

```json
{
  "hospitalId": "H001",
  "name": "○○병원",
  "gps": { "lat": 35.1795, "lng": 128.1076 },
  "availableBedCount": 12,
  "nightDutyAvailable": true,
  "specialties": [
    {
      "department": "흉부외과",
      "doctorCount": 3,
      "recentProcedureTags": ["기흉", "흉부외상"]
    }
  ],
  "source": "rule",
  "updatedAt": "2026-07-29T10:00:00Z"
}
```

### 1-B. feature/info → feature/hub (AmbulanceInfo — 구급차 레지스트리, 신규)

여러 구급차가 동시에 사건을 진행하는 걸 지원하면서 추가됐다. 병원 정보와
같은 주기(`send_to_hub.py`의 `sync_once()`)로, 병원용과는 **별도의 Supabase
프로젝트**(`ambulances` 테이블)에서 읽어 `POST /info/ambulances`로 보낸다.
`AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면 이 부분만
조용히 건너뛰고 병원 정보 동기화는 그대로 진행한다.

```json
{
  "apid": "A0000001",
  "name": "구급 1호차",
  "gps": { "lat": 37.4979, "lng": 127.0276 },
  "voicePort": 6000,
  "source": "rule",
  "updatedAt": "2026-08-11T00:00:00Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `apid` | string | 구급차 고유 식별자 |
| `name` | string | 표시용 이름 |
| `gps.lat` / `gps.lng` | number | 구급차 위치. 대회 데모 단계라 서울 랜드마크로 고정한 값(실시간 아님) |
| `voicePort` | number | 이 구급차 voice 인스턴스가 뜰 포트. IP는 여기 없다 — voice가 뜰 때 자기 IP를 자동 탐지해 hub에 직접 자가등록한다(feature/hub README.md 참고) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 마지막 갱신 시각 |

### 2. feature/hub → feature/info (HospitalInfo 부분 갱신 — 병상 수만)

> dashboard의 승인 액션은 feature/hub가 직접 받는다 (feature/info는 받지 않음).
> 대신 `final_approval`로 이송이 확정되면, 같은 병상에 다른 구급차가 중복
> 매칭되는 걸 막기 위해 hub가 이 브랜치에 갱신된 병상 수를 알려준다. 동시에
> 여러 구급차가 매칭 중일 수 있어서 필요한 흐름이다 — `send_to_hub.py`의
> 주기적 재조회(기본 30분)만으로는 확정 시점에 바로 반영이 안 될 수 있기
> 때문. 위 HospitalInfo의 다른 필드(name/gps/nightDutyAvailable/specialties)는
> hub가 바꿀 이유가 없어서 이 메시지엔 담지 않는다 — 받은 쪽(info)은
> `hospitalId`로 기존 레코드를 찾아 `availableBedCount`만 덮어쓰면 된다.
>
> **구현 완료.** `info/app.py`가 `POST /hub/bed-update`(기본 포트 5002 — 팀
> 합의로 info 고정 포트, 2026-08-11)로 이 메시지를 받아
> `SupabaseEgenClient.update_bed_count()`로 Supabase의 `hvec` 컬럼에 즉시
> 반영한다. hub 쪽 전송 URL은 `INFO_BED_UPDATE_URL` 환경변수(기본값
> `http://127.0.0.1:5002/hub/bed-update`)로 바꿀 수 있고,
> info 서버가 잠깐 안 떠 있어도 hub는 예외를 흡수하고 계속 진행한다 — 그
> 경우엔 최대 재조회 주기(기본 30분) 뒤에 `send_to_hub.py`가 다시 맞춰준다.
> 실제 Supabase 병상이 줄어드는 것까지 확인된 상태다.

**입력** (위 HospitalInfo 표의 "2번" 열에 해당하는 필드만) — 엔드포인트: `POST /hub/bed-update`

```json
{
  "hospitalId": "H001",
  "availableBedCount": 11,
  "status": "confirmed",
  "updatedAt": "2026-07-30T14:20:00Z",
  "source": "rule"
}
```

### 3. 서류 1장 → DocumentFields (브랜치 내부 중간 산출물, 신규)

경로 B가 서류 1장에서 뽑아내는 형식이다. **hub로 보내는 계약이 아니라 브랜치
내부 산출물**이며, `HospitalInfo`와 합치는 단계가 아직 없다.

서류에는 좌표도 실시간 병상 수도 없으므로 `HospitalInfo`가 될 수 없다. 그래서
**서류에서 실제로 읽어낸 것만** 담고, 못 읽은 필드는 키 자체를 넣지 않는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `hospitalName` / `hospitalId` | string | 기관명 · 기관코드(서류에 인쇄된 경우만) |
| `documentType` | string | 당직표 / 진료과안내 / 장비현황 / 병상현황 / 진단서 / 기타 |
| `effectiveDate` | string | **이 서류가 언제 기준인가.** 서류는 정적이라 이게 없으면 3년 전 당직표를 오늘 것으로 쓰게 된다 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[]` | object[] | 진료과 · 의사 수 · 시술 태그 · 당직 편성 여부 |
| `capabilities[]` | string[] | 표준 역량 코드 (위 확장 필드와 같은 어휘) |
| `equipment[]` | string[] | 서류에 적힌 장비명 원문. 표준 코드로 못 바꾼 것도 버리지 않는다 |
| `evidence[]` | object[] | 값별 원문 근거. **근거 대조에서 버려진 값도 남는다** |
| `needsReview` / `reviewReasons` | boolean / string[] | 사람 확인이 필요한가, 그 이유 |
| `source` | `"ai"` | AI 산출물임을 나타내는 고정값 |

```json
{
  "hospitalName": "○○대학교병원 응급의료센터",
  "documentType": "DUTY_ROSTER",
  "effectiveDate": "2026-08",
  "nightDutyAvailable": true,
  "specialties": [
    { "department": "흉부외과", "doctorCount": 2, "procedureTags": [] }
  ],
  "capabilities": ["EQP_ANGIO_SUITE", "EQP_CT_24H", "PROC_PCI_EMERGENCY"],
  "evidence": [
    {
      "field": "specialties[0].department",
      "value": "흉부외과",
      "sourceText": "흉부외과 2명",
      "grounded": true,
      "regionIndex": 2
    }
  ],
  "needsReview": false,
  "reviewReasons": [],
  "documentId": "당직표",
  "extractedAt": "2026-08-03T21:19:13+09:00",
  "schemaVersion": "0.1",
  "source": "ai",
  "modelUsed": { "llm": "qwen3:14b" }
}
```

`0` / `[]` / 키 없음을 절대 섞지 않는다. `[]`는 "읽었는데 없다", 키 없음은
"확인하지 못했다"이고, 이 둘이 뭉개지면 병합할 때 **모르는 값이 없는 값을 덮는다.**

## 실행 방법

> 아래 명령은 모두 저장소 루트가 아니라 `info/` 안에서 실행한다 (`cd info`).
> `Hospital_inform/`·`ocr/`·`simulation/` 등 하위 경로는 전부 `info/` 기준
> 상대 경로다.

### 공통

```bash
cd info
conda create -n <가상환경명> python=3.11
conda activate <가상환경명>
pip install -r requirements.txt
```

`requirements.txt`는 직접 설치 대상(용도별 설명 포함)과 하위 의존성까지 모두 버전이
고정되어 있어, 위 명령 한 번으로 다른 팀원도 동일한 버전 조합을 그대로 재현할 수 있다.

### 경로 A — E-Gen 정규화 (`Hospital_inform/`)

```bash
cd Hospital_inform
pip install pydantic requests python-dotenv

python info/build_hospitals.py --http     # 실제 API (서울 전체)
python info/build_hospitals.py            # fixture (키 없이 개발할 때)
```

`--http`는 `Hospital_inform/.env`의 `EGEN_SERVICE_KEY`를 쓴다. 결과는
`info/data/output/`에 병원 1곳당 JSON 1개로 떨어진다. fixture는 커밋되지 않으므로
`--http` 없이 돌리려면 먼저 만들어야 한다
([`Hospital_inform/README.md`](Hospital_inform/README.md) "데이터 정책" 참고).

### 경로 A — 시계열 축적 (`snapshot.py`)

```bash
cd Hospital_inform
python info/snapshot.py                   # 1회 — 서울 (기본값)
python info/snapshot.py --interval 600    # 600초마다 반복 (콘솔 상주)

# 전국 — 현재 상시 수집이 도는 형태
python info/snapshot.py --stage1 "" --dir "info\data\snapshots_nationwide"
```

E-Gen은 **"지금 값"만 주고 과거 이력을 주지 않는다.** 나중에 몰아서 받을 방법이
없으므로 지금부터 직접 찍어 쌓는다. `data/snapshots_nationwide/YYYY-MM-DD.jsonl`에
**가공하지 않은 원본 행**을 append하며, 호출 실패도 한 줄로 남긴다 ("데이터가 없다"와
"호출이 실패했다"는 다르다). 좌표·등급은 거의 안 바뀌므로 하루 한 번만 부른다 —
20분 주기 기준 하루 145회다.

**`--stage1`을 비우면 전국이 1회 호출로 온다** — 호출 횟수가 서울만 받을 때와 같다.
상시 수집은 `snapshot_nationwide.bat`을 Windows 작업 스케줄러에 등록해 **20분 주기로
가동 중**이다(전국 443곳, 2026-08-12~). 서울 전용(`snapshot.bat`, 10분)은 전국이 서울을
포함하므로 같은 날 멈췄다.

> ⚠️ 이 데이터는 커밋되지 않아 **이 장비의 `data/` 폴더가 유일본**이고, E-Gen은 과거
> 이력을 주지 않으므로 지우면 복구할 방법이 없다.

### 경로 C — 신뢰도 진단·점수 (`hospital_score/`)

```bash
cd Hospital_inform/info
python -m hospital_score.report                        # 신뢰도 진단 리포트 (6개 절)
python -m hospital_score.discarded                     # 폐기 판정 근거 재계산 (병상 예측·미상 추정)
python -m hospital_score.scoring --check --validate    # 불변식 + 전문병원 홀드아웃 검증
python -m hospital_score.scoring --sample 한강성심       # 병원 하나 들여다보기
python -m hospital_score.scoring --payload 한강성심      # hub로 보낼 합친 객체 실물
python -m hospital_score.rejection --vocab             # 거절 사유 어휘 (dashboard 선택지용)
python -m hospital_score.ingest                        # 거절 로그 수신 서버 (포트 5003)
```

전부 로컬 파일만 읽으므로 **네트워크 없이 돈다.** 단, 심평원 캐시는 `data/` 아래라
커밋되지 않으므로 **새 장비에서는 아래를 한 번 돌려야 한다.**

```bash
python -m hospital_score.hira_files --fetch    # 전문병원 지정 현황 (API 2회)
python -m hospital_score.hira --build-join     # 조인 + 전문의 수 (API 약 520회)
```

캐시가 없어도 점수는 나오지만 **심평원 근거가 통째로 빠져 미상이 전부
`unknown_bare`(0.4)로 떨어지고**, 화상 0→4를 보여주는 홀드아웃 검증도 재현되지 않는다.
`--build-join`은 재시도 3회·25곳마다 중간저장·이어받기를 한다.

### 경로 B — 서류 OCR·필드 추출 (`ocr/`)

```bat
:: 셋업 (GPU 장비)
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r ocr\requirements.txt -r ocr\requirements-extract.txt
python ocr\scripts\download_models.py
ollama pull qwen3:14b

:: 이미지 → 텍스트만
python ocr\scripts\run_ocr.py <이미지경로> [--json]

:: 이미지 → 필드까지 (OCR + LLM 동시 상주)
python ocr\scripts\run_extract.py --image <이미지경로> [...]

:: 저장된 OCR 결과에서 필드만 (GPU 불필요)
python ocr\scripts\run_extract.py --ocr-json <결과.json>

:: LLM 없이 로직만 / 환각 필터가 실제로 거르는지 확인
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub-hallucinate
```

결과는 `ocr/output/`에 `YYYYMMDD_HHMMSS_<문서명>.json`으로 쌓인다. 덮어쓰지 않는다.

### 경로 B를 눈으로 확인 (`simulation/`) — 팀원용

```bat
pip install -r simulation\requirements.txt
python simulation\gui.py
```

`LLMdata/data_original/`의 서류를 **전부 창에 끌어놓으면** 순서대로 처리된다.
영역 검출 → 인식 → 필드 추출 → 근거 대조가 진행 중에 그려지고, 최종 JSON도 탭에서
바로 볼 수 있다. 결과는 CLI와 같고 다른 것은 과정이 보인다는 점뿐이다.
**PDF를 받는 유일한 경로**이기도 하다 — CLI는 이미지만 받는다.

성능만 확인할 거라면 **설정은 기본값 그대로** 두면 된다 — 학습 데이터는 쌓이지
않고 추출 결과만 `ocr/output/`에 남는다. `[설정…]`에서 추출 방식(Ollama/Stub),
해상도, 저장 위치, 학습 데이터 수집 여부를 정할 수 있고 값은 유지된다.
`Stub`을 고르면 Ollama·GPU 없이도 전 과정이 돈다.

Ollama가 꺼져 있으면 시작할 때 확인창이 떠서 **켤지 Stub으로 갈지** 고르게 되고,
켜기를 고르면 서버를 자동으로 띄운다 ([`simulation/README.md`](simulation/README.md)).

### 필드 추출 모델 학습 데이터 (`LLMdata/`)

`simulation`이나 `run_extract.py --image`로 서류를 처리할 때 **학습 데이터 수집을
켜면** OCR 텍스트(`raw/`)와 LLM 가공 전 응답(`llm_raw/`)이 같은 이름으로 쌓인다.
필드 추출 LLM을 파인튜닝할 때의 입력과 타깃이다. 기본값은 꺼짐이다
([`LLMdata/README.md`](LLMdata/README.md)).

## 폴더 구조

```
info/                              (저장소 루트의 .gitignore, CLAUDE.md, pull-all.sh는 브랜치 공통이라 여기 포함 안 됨)
├── README.md                      이 문서
├── DEVELOPMENT.md                 브랜치 전략
├── requirements.txt               서버 의존성 (Flask 등)
├── app.py                         hub의 병상 갱신 수신 서버 (POST /hub/bed-update)
├── send_to_hub.py                 Supabase → hub 주기적 재조회 상시 프로세스 (기본 30분)
│
├── Hospital_inform/               [경로 A] E-Gen 공개 API → HospitalInfo   (규칙 기반)
│   ├── README.md                  이 경로의 상세 문서
│   ├── hospital-info-interface-proposal.md   hub 인터페이스 변경 제안
│   ├── snapshot.bat               시계열 수집 1회 — 서울 (작업 스케줄러 등록용)
│   ├── snapshot_nationwide.bat    시계열 수집 1회 — 전국 (현재 가동 중, 20분 주기)
│   └── info/
│       ├── schema.py              HospitalInfo 정의 + 검사기 (hub 계약, 아무것도 import 안 함)
│       ├── egen/
│       │   ├── client.py          데이터 취득 — Fixture / Supabase / Http 세 구현
│       │   └── mapper.py          E-Gen 원본 → HospitalInfo 변환          ★본체
│       ├── build_hospitals.py     변환 실행 진입점
│       ├── snapshot.py            원본 응답을 주기적으로 떠서 시계열로 축적
│       ├── verify_with_hub.py     hub 엔진 연동 검증 (검증 전용, 프로덕션 아님)
│       ├── hospital_score/        [경로 C] 신뢰도 진단·외부 대조   (구현 완료, hub 연동 대기)
│       │   ├── README.md          이 경로의 상세 문서 + 팀 요청 사항
│       │   ├── vocabulary.py      MKioskTy 28항목 · 15그룹 · 연령축
│       │   ├── dataset.py         스냅샷 JSONL → 시각별 관측
│       │   ├── report.py          신뢰도 진단 리포트 (API 호출 0회)
│       │   ├── scoring.py         계층 기반 점수 + 불변식 + 전송 객체 조립  ★본체
│       │   ├── hira.py            심평원 상세정보 2.8 / 병원정보 v2
│       │   ├── hira_files.py      심평원 파일데이터 (전문병원 지정 현황)
│       │   ├── rejection.py       거절 이유 어휘 · 로그 · 축별 집계
│       │   └── ingest.py          거절 로그 수신구 (POST /hub/rejection)
│       └── data/                  (전부 커밋하지 않음 — .gitignore의 `data/`가 경로 무관)
│           ├── fixtures/          E-Gen 응답을 흉내낸 가상 데이터
│           ├── output/            변환 결과 JSON
│           ├── snapshots/         원본 시계열 — 서울 55곳 (2026-08-12 중단)
│           ├── snapshots_nationwide/  원본 시계열 — 전국 443곳 (20분, 가동 중)
│           ├── hira/              심평원 캐시 (조인 518 · 전문의 518 · 전문병원 114)
│           └── rejections/        거절 로그 JSONL (append-only)
│
├── ocr/                           [경로 B] 병원 서류 이미지 → 필드   (AI + 규칙)
│   ├── README.md                  이 경로의 상세 문서
│   ├── requirements.txt           torch·onnxruntime 등 — 이미지 → 텍스트
│   ├── requirements-extract.txt   pydantic — 텍스트 → 필드
│   ├── configs/models.yaml        OCR 모델 저장소 ID·커밋 SHA·임계값
│   ├── models/                    OCR 가중치 (커밋하지 않음, 스크립트로 내려받음)
│   ├── output/                    추출 결과 JSON (커밋하지 않음, 실행마다 누적)
│   ├── scripts/
│   │   ├── download_models.py     OCR 가중치 내려받기
│   │   ├── run_ocr.py             이미지 → 텍스트 CLI
│   │   └── run_extract.py         이미지/텍스트 → 필드 CLI
│   └── src/
│       ├── goldenlink_ocr/        이미지 → 텍스트     (torch·GPU 필요)
│       │   ├── layout.py          ONNX 레이아웃 검출                    [AI]
│       │   ├── router.py          중복 제거·읽기 순서·태스크 배분        [규칙]
│       │   ├── recognizer.py      PaddleOCR-VL 래퍼                     [AI]
│       │   ├── validator.py       반복 생성·잘림 감지 → needs_review    [규칙]
│       │   ├── pipeline.py        위 넷을 엮는 진입점 (진행 콜백 제공)
│       │   └── config.py          models.yaml 로더
│       └── goldenlink_extract/    텍스트 → 필드       (pydantic만 필요)
│           ├── prompts.py         필드 그룹 4종 + JSON Schema
│           ├── llm/
│           │   ├── base.py        LlmClient Protocol (모델 교체 지점)
│           │   ├── ollama.py      Ollama 구조화 출력 호출               [AI]
│           │   └── stub.py        LLM 없이 도는 구현 (개발·테스트)
│           ├── grounding.py       근거 대조 — 환각 필터                 [규칙]
│           ├── schema.py          DocumentFields 정의 + 어휘 검증       [규칙]
│           ├── vocabulary.py      표준 코드(복사본) + 서류 종류
│           ├── extractor.py       위를 엮는 본체 (진행 콜백 제공)
│           └── config.py          모델·동작 설정 (환경변수)
│
├── simulation/                    [경로 B 확인용] 처리 과정을 보는 GUI
│   ├── README.md                  화면 · 설정 · 성능 실측 · 의존성
│   ├── requirements.txt           tkinterdnd2 · pypdfium2
│   ├── gui.py                     화면 (tkinter) · 설정 모달
│   ├── runner.py                  워커 스레드 — 대기열 처리, 이벤트를 큐로 (Tk 의존 없음)
│   ├── settings.py                실행 설정 (무엇을 어디에 남길 것인가)
│   ├── ollama_service.py          Ollama 상태 확인 · 자동 실행
│   └── pdf.py                     PDF 페이지 → 이미지 (pypdfium2)
│
└── LLMdata/                       [경로 B] 서류 원본 · 필드 추출 모델 학습 데이터
    ├── README.md                  학습 단위 · 라벨 4종 · 작업 순서
    ├── data_original/             서류 원본 (합성본 — 여기만 커밋. 용량 때문에 5건만)
    ├── raw/                       OCR 텍스트  = 학습 입력   (커밋하지 않음)
    ├── llm_raw/                   LLM 가공 전 응답 = 학습 타깃 (커밋하지 않음)
    └── 0*_*.jsonl                 데이터 종류별 예시 (SFT · DPO 3종 · 평가셋)
```

`ocr/src/` 아래 패키지를 둘로 나눈 이유는 **의존성이 다르기 때문**이다. 추출만
돌릴 때는 torch도 onnxruntime도 필요 없어서, GPU 없는 장비에서 저장된 OCR
결과(`run_ocr.py --json`)로 추출 로직만 따로 개발할 수 있다.

`simulation/`은 `ocr/`을 가져다 쓰기만 하는 확인용 창이다. 반대 방향 의존은
없다 — `ocr/`은 이 폴더의 존재를 모르고, 폴더를 통째로 지워도 CLI는 그대로 돈다.

`Hospital_inform/`은 개인 작업 공간에서 개발하던 것을 옮겨온 것이라 아직 브랜치
폴더 구조에 편입하지 않았다. hub 연동 검증이 끝난 뒤에 합친다.

## 알려진 제약사항 / TODO

### 외부 대기

- ~~E-Gen 서비스키 미승인~~ → **2026-08-10 승인 완료.** 실 API 연동·매핑 확정까지
  끝났다. 개발계정이라 일일 트래픽 한도가 있어 폴링 주기를 여기에 맞춘다
- ~~실 API가 `build_hospitals.py --http` CLI 도구에만 연결되고 상시 파이프라인
  (`send_to_hub.py`)은 그대로 Supabase만 씀~~ → **2026-08-11 상시 파이프라인에도
  연결 완료.** 병상 수만 Supabase 유지, 나머지는 실 API (위 "1. feature/info →
  feature/hub" 절 참고)
- ~~실측 전 가정 (`hv11`=소아 병상, `MKioskTy` 번호별 질환, 결측 표현)~~ →
  **활용가이드 V4 + 실응답으로 전부 확정.** `egen/mapper.py` 상단에 `[추정]`이 하나도
  남아 있지 않다

### 미구현

- 🔴 **hub로 흐르는 병원이 7곳뿐** — `send_to_hub.py`의 `_remap_to_supabase_hpid()`가
  대응표 밖 기관을 전부 버린다. 2026-08-13에 해소 방향(병상 차감을 짧은 TTL 오버레이로)
  까지 합의됐고, info 쪽 작업은 `_remap_to_supabase_hpid()` 제거와 `fetch_hospitals()`가
  병상도 실 API로 읽게 바꾸는 것이다 (위 "1. feature/info → feature/hub" 참고)
- **경로 C의 `assessment`를 상시 파이프라인에 배선** — `scoring.build_payload()`는
  완성됐지만 지금은 CLI 데모(`--payload`)에서만 불린다. `fetch_hospitals()` 결과에
  `score_hospital()` 결과를 얹으면 되는데, **hub의 `assessment` 수용과 동시**여야 한다
- **거절 로그는 수신구만 세워둔 상태** — `POST /hub/rejection`은 완성됐고 hub가 지금
  형태 그대로 보내도 기록된다(필수 필드 `hospitalId` 하나). 아직 0건이며, **로그는
  소급해서 만들 수 없으므로** 붙이는 게 늦어질수록 그만큼 영구 손실이다
- **두 경로의 합류 지점** — `DocumentFields` → `HospitalInfo` 병합. 서류는 정적이라
  좌표·실시간 병상 수는 건드리지 않고, E-Gen이 못 채우는 당직·인력만 덮어야 한다.
  어느 값이 어디서 왔는지(AI / 규칙) 표기하는 방식도 미정
- **서버** — hub의 병상 갱신을 받는 `POST /hub/bed-update`(`app.py`, 기본 포트
  5002 — 팀 합의로 고정)는 구현·검증 완료(실제 Supabase 병상이 줄어드는 것까지
  확인). 다만 `requirements.txt`의 `Flask-SocketIO`는 이 엔드포인트가 순수
  REST(Flask)라 실제로는 안 쓰인다 — 제거 검토 필요
- 구급차 정보(`AmbulanceInfo`) 동기화는 구현·검증 완료(실제 Supabase
  `ambulances` 테이블 3건 조회 확인). 다만 병원용과 별도 프로젝트라
  `AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY`를 각자 `.env`에 따로
  받아 넣어야 한다
- OCR 필드 값 누락 검사 — 워터마크 문서에서 라벨은 읽고 값을 비우는 사례에 대한
  스키마 기반 검사

### 검증 대기

- **재현율을 아직 못 쟀다.** 근거 통과율은 쟀지만(아래 실측 참고), "원문에 있는데
  안 뽑은 값"은 사람이 만든 정답지가 있어야 센다.
  `LLMdata/07_eval_gold.jsonl`이 그 형식이고 손으로 채워야 한다
- ~~OCR 존폐를 가르는 커버리지 실측~~ → **측정 완료** (아래 "E-Gen 실측" 참고).
  E-Gen이 시술 역량 상당 부분을 덮지만 **tPA는 못 덮는다**는 결론.
  의사 수는 심평원이 덮는 것으로 2026-08-12에 확인됐다
- hub 엔진 연동 검증(매칭 순위 확인)은 계약 검증(4/4 통과)까지만 됐고 실행 대기
- **경로 C의 점수는 "정답"으로 검증할 수 없다** — "이 병원이 이 환자를 실제로
  받았는가"의 정답이 없기 때문이다. 그래서 ①불변식 검사(계층 순서·미상이 불가능
  이하로 평가되지 않음·근거가 비어 있지 않음 등)와 ②전문병원 지정을 홀드아웃
  정답으로 쓴 부분 검증(화상 0→4)으로 대신했고 둘 다 통과했다. **진짜 정답은
  거절 로그가 쌓여야 나온다**
- ~~**미상 칸을 채우는 추정 모델**~~ → **보류 판정 (2026-08-12, 2026-08-14 재계산).**
  관측 3,574칸 중 **95.6%가 "가능"**이라 상수 기준선이 이미 95점이고(서울 표본은 97.3%),
  라벨이 상위 등급에 편중된 MNAR이라 미신고 병원에 적용하면 "미신고 병원도 대부분 수용
  가능"이라는 **위험한 방향**의 오류가 난다. 편중의 크기는 실측된다 — **명부의 21.8%를
  차지하는 최하위 등급이 라벨의 0.7%만 내놓는다.** 추정 대신 **외부 근거 유무로 계층을
  나누는 방식**을 택했다
- ~~**병상 추정 모델**~~ → **폐기 판정 (2026-08-12, 2026-08-14 재계산).** 서울 6,519쌍으로
  잰 `P(만실 전환) = 0.568%`(95% CI 0.41~0.78%, 10분 지평)가 사전 등록 기준(2%)에 크게
  못 미쳤다. 전국 50,133쌍(20분 지평)은 0.301%로 더 낮다. 병상은 움직이지만 0까지 가는
  일이 거의 없어 예측의 최대 이득이 모델 오차보다 작다
  - **최초 분석(2026-08-11)의 `0.618%`와 신뢰구간이 겹친다** — 다른 시점·다른 코드로
    두 번 계산해 같은 결론이 나왔다
- **위 두 판정은 이제 명령 하나로 재현된다**: `python -m hospital_score.discarded`
  (API 호출 0회). 2026-08-14 이전에는 관측치만 `report.py`로 재현됐고 이 두 판정은
  근거 코드가 없었다. 자세한 것은
  [`hospital_score/README.md`](Hospital_inform/info/hospital_score/README.md)
  "판정한 것 / 보류한 것"

### 유지보수 주의

- **심평원 캐시는 커밋되지 않는다.** 새 장비에서 경로 C를 돌리려면 아래를 한 번
  실행해야 한다. 안 하면 점수는 나오지만 **미상이 전부 `unknown_bare`로 떨어져**
  화상 0→4 같은 결과가 재현되지 않는다.
  ```bash
  cd info/Hospital_inform/info
  python -m hospital_score.hira_files --fetch    # 전문병원 지정 (API 2회)
  python -m hospital_score.hira --build-join     # 조인 + 전문의 수 (API 약 520회)
  ```
- **`hospital_score/`는 의도적으로 격리돼 있다.** 바깥 모듈을 import 하지 않고 바깥에서도
  이 폴더를 import 하지 않아, 폴더째 지워도 기존 경로가 멀쩡하다. 배선할 때 이 성질을
  깨지 않도록 주의한다 (유일한 예외는 `scoring.py --payload`의 CLI 전용 지연 import)
- **`send_to_hub.py`의 `SUPABASE_TO_EGEN_HPID` 대응표는 수기 관리다.** Supabase
  `hospitals` 테이블에 병원이 추가·교체되면 이 표도 같이 갱신해야 한다 (GPS
  최근접 대조로 새 대응 쌍을 찾는 방법은 위 "1. feature/info → feature/hub" 절
  참고). 안 맞으면 해당 병원은 목록·중증질환 정보 없이 병상 수만 있는 상태로
  빠진다(`map_all()`이 `skipped_no_location`으로 건너뜀 — 조용히 사라지지 않고
  `fetch_hospitals()` 로그의 리포트에 이름이 남는다)
- **표준 역량·병상 코드 어휘가 두 벌 있다.** `Hospital_inform/info/schema.py`가
  원본이고 `ocr/src/goldenlink_extract/vocabulary.py`가 복사본이다. 두 경로의
  의존성을 갈라 두려고 일부러 복사했으며, 어긋났는지는 아래로 확인한다.
  ```bash
  python ocr/scripts/run_extract.py --check-vocabulary
  ```
- ~~**CLAUDE.md 명세 오류 정정 필요**~~ → **정정 완료.** `hv1`·`hv2`를 별도 API로
  적고 있던 것을 "가용병상 응답 안의 필드"로 고쳤고, 팀 공통 문서에도 반영됐다.
  **아직 남은 곳은 `requirements.txt` 상단 주석 하나뿐**이다
- OCR이 읽지 못하는 유형이 있다 — 직인이 덮은 글자, 손글씨, 세로 병합 셀 안쪽,
  팩스 저품질 문서 (실측 268개 항목 중 13개)

## 추가사항

### E-Gen 실측 (2026-08-10 · 서울특별시 전체)

서비스키 승인 후 실제 응답을 처음 받아 본 결과다. **fixture로 개발하는 동안 세워둔
가정 중 세 개가 틀렸고, 셋 다 조용히 잘못된 값을 내보내고 있었다.**

| 발견 | 무슨 일이 있었나 |
|---|---|
| **음수 병상 = 과밀** | `hvec`에 `-24 ~ -2`가 온다. "정원보다 환자가 그만큼 많다"는 뜻인데, 매퍼가 `-1` 이하를 전부 미상 처리해 **가장 갈 수 없는 병원이 "모르는 병원"이 되고 있었다.** 서울 55곳 중 6곳이 여기 해당했고 전부 상급종합병원이다 |
| **소아 병상 필드가 틀렸다** | `hv11`을 소아 병상으로 매핑해 뒀는데 실제로는 인큐베이터 보유 여부(Y/N)다. `int('Y')`가 실패해 **소아 병상이 늘 미상**이었다. 진짜 필드는 `hv28` |
| **`불가능`과 `정보미제공`이 뭉개졌다** | 중증질환 값은 `Y`/`불가능`/`정보미제공` 3종인데 매퍼가 `N`으로 시작하는 값만 불가로 봤다. 3상태를 지키려던 설계가 실제 값 앞에서 무너져 있었다 |

고친 뒤 결과 — 어휘의 병상 코드 6개가 **전부** 채워졌다 (3개는 정의만 있고 한 번도
쓰이지 않던 것이다).

| 병상 코드 | E-Gen 필드 | 신고 병원 (55곳 중) |
|---|---|---|
| `ER_ADULT` | `hvec` 일반 | 55 |
| `ER_PEDIATRIC` | `hv28` 소아 | 23 |
| `ER_NEGATIVE` | `hv29` 응급실 음압격리 | 37 |
| `ICU` | `hvicc` [중환자실] 일반 | 35 |
| `CCU` | `hv34` [중환자실] 심장내과 | 12 |
| `OR` | `hvoc` [기타] 수술실 | 54 |

역량 코드도 **장비 가용 여부(`hvctayn`·`hvangioayn`)가 가용병상 응답에 같이 온다**는
걸 확인해 연결했다. "역량 정보가 전혀 없는 병원"이 21곳 → 1곳으로 줄었다.

| 역량 코드 | 보유 병원 |
|---|---|
| `EQP_CT_24H` | 54 |
| `EQP_ANGIO_SUITE` | 38 |
| `PROC_PCI_EMERGENCY` | 33 |
| `PROC_CRANIOTOMY` | 31 |
| `PROC_EVT_THROMBECTOMY` | 29 |
| `PROC_CESAREAN_EMERGENCY` | 22 |
| `PROC_IV_THROMBOLYSIS` | **0 — E-Gen에 대응 항목이 없다** |

마지막 줄이 OCR의 존재 이유다. tPA(정맥 혈전용해술)는 `MKioskTy` 28개 항목 어디에도
없어서 **공개 API로는 채울 수 없다.**

> **정정 (2026-08-12)** — 원래 이 문단은 "진료과별 의사 수도 마찬가지"라고 적었는데
> 그건 틀렸다. E-Gen에 없을 뿐 **심평원 의료기관별상세정보서비스가 전문과목별 전문의
> 수를 준다.** 실제로 연동해 병원 514곳에서 받아 쓰고 있다. 즉 OCR이 메워야 할 공백은
> 이제 **tPA와 당직 편성** 쪽으로 좁혀졌다.

그 밖에 확인한 것:

- **병상 "미상"은 서울에 거의 없다** (55곳 중 0~1곳). 병원들이 병상 수는 성실히
  입력한다. 미상 보간보다 **도착 시점 예측**이 실제 문제라는 뜻이다
- **입력 오류가 있다** — 국립중앙의료원이 거의 전 필드에 `12312` 같은 시험값을 넣어
  뒀다. 임의의 상한 대신 그 병원이 신고한 총 병상(`hvs38`)을 넘으면 버린다
- **시도 전체를 1회 호출로 받을 수 있다** (`STAGE2` 생략 가능). 자치구 25번 나눠
  부를 필요가 없어 트래픽이 크게 절약된다
- 값은 실제로 계속 변한다 — 14분 사이에 과밀 병원 목록과 수치가 모두 바뀌었다.
  시계열을 쌓을 가치가 데이터로 확인된 셈이다

### 필드 추출 실측 (합성 서류 53건 · 81페이지 · qwen3:14b)

`LLMdata/data_original/`을 실제로 돌려 나온 숫자다. 로직이 의도대로 도는지가
아니라 **실제 LLM이 얼마나 뽑는지**를 처음 잰 결과다.

| 지표 | 값 |
|---|---|
| 근거 통과율 | **72.4%** (267/369) |
| 그룹 호출 실패 | 2.5% (8/324) — `시술·장비` 7%, 나머지 대부분 0% |
| 사람 확인 필요 | 57% (46/81) |

기각 102건의 최대 원인은 환각이 아니라 **근거 인용 규율**이었다.

| 기각 사유 | 건수 |
|---|---|
| 원문에 없는 근거 | 63 — 그중 **37건이 프롬프트의 코드·한글 라벨을 근거란에 복사** |
| 근거가 너무 짧음 | 19 |
| 근거가 값과 무관 | 10 |
| 값이 근거에 없음 | 7 |

```
capabilities[0]  근거 <- "CT 24시간 가동"          ← 원문이 아니라 프롬프트의 라벨
hospitalName     근거 <- "문서 상에 명시된 병원명"    ← 원문이 아니라 모델의 설명
```

**값 자체는 맞는데 근거 때문에 버려진 경우**라, 환각을 막은 게 아니라 재현율을
잃은 것이다. 그래서 대응은 모델이 아니라 프롬프트 쪽이었다 — 지시문에 "이
지시문의 코드·설명을 근거로 쓰지 마라 / 떨어진 줄을 이어붙이지 마라"를 명시했고,
같은 서류로 다시 재 비교할 예정이다.

그룹 실패 8건은 전부 `num_predict` 한도(1024)에 걸려 생성이 잘린 것이었다.
구조화 출력은 문법 제약이 걸려 있어 형식이 깨질 수 없는데, 한도에 걸리면 문자열이
열린 채 끝나 파싱이 실패한다. 게다가 `temperature=0`이라 재시도해도 같은 지점에서
같은 실패가 반복됐다. 한도를 2048로 올렸다.

필드별로는 `specialties` 100%, `documentType` 98%, `hospitalName` 88%,
`effectiveDate` 81%로 나왔고, **`nightDutyAvailable`은 1%였다** — 표본에 당직표가
거의 없다는 뜻이다. 이 브랜치가 메우려는 공백(당직 정보)이 바로 그 필드라,
당직표 중심으로 표본을 늘려 다시 봐야 한다.

### 영역별로 나눠 읽는 이유 (실측)

이미지 → 텍스트 변환은 페이지를 통째로 넣지 않고 레이아웃 모델로 영역을 나눈 뒤
종류에 맞는 인식 태스크로 읽는다. 한글 실물 문서 15장(핵심 문자열 268개) 기준:

| 방식 | 재현율 | VRAM 피크 |
|---|---|---|
| 페이지 전체를 한 번에 | 68% | 8,312MB |
| **영역별 분리 + 태스크 라우팅** | **88%** | **2,078MB** |

영역을 나누면 조각이 작아 VRAM이 오히려 4분의 1로 줄고, 무한 반복(루프)도 사라진다.

### 모델이 스스로 보고하는 지표를 믿지 않는다

측정 중 **모델이 같은 토큰을 무한 반복하는 동안에도 confidence가 0.99로 나오는**
사례를 확인했다. 출력은 망가졌는데 신뢰도 지표는 정상으로 보인 것이다. 그래서
OCR 단계는 confidence 대신 토큰 한도 도달·고유 토큰 비율을 본다.

추출 단계도 같은 원칙이다. JSON Schema로 디코딩을 제약하면 형식은 반드시 맞지만
**형식이 맞는 거짓말**은 얼마든지 만들어진다. 그래서 값과 함께 근거 원문을 받아
규칙으로 세 겹 검사한다.

| 검사 | 잡는 것 |
|---|---|
| 근거가 원문에 있는가 | 근거 문장 자체를 지어낸 경우 |
| 값이 근거 안에 있는가 | 근거는 진짜인데 값만 다른 경우 (`"흉부외과 2명"` → `doctorCount: 7`) |
| 근거가 값을 뒷받침하는가 | 둘 다 진짜지만 서로 무관한 경우 (`"흉부외과 2명"` → 개두술 가능) |

걸린 값은 결과에서 빠지되 `evidence`에 `grounded: false`와 이유가 남는다.
무엇을 왜 버렸는지 사람이 볼 수 있어야 하기 때문이다.
