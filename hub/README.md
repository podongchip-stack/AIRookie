# [feature/hub] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **폴더 구조 안내(모노레포)**: 이 저장소는 `feature/voice`·`feature/hub`·
> `feature/info`·`feature/dashboard`가 하나의 저장소를 공유하며, 각 브랜치는
> 자기 작업 폴더(`voice/`·`hub/`·`info/`·`dashboard/`)만 갖는다. **지금 이
> 브랜치에는 `hub/` 폴더만 있고 `voice/`·`info/`·`dashboard/`는 없다.** 만약
> 작업 중 낯선 폴더가 보인다면 `develop`을 머지했거나 다른 브랜치를 체크아웃한
> 상태라는 뜻이니, 실수로 만들어진 게 아닌지 걱정하지 않아도 된다.

> **신설 브랜치 안내**: `feature/hub`는 develop 기준으로 새로 만들어진 브랜치입니다.
> 아래 "입출력 데이터 포맷"에 정리된 스키마(feature/voice 입력, feature/info 입력,
> feature/dashboard 입력·출력, feature/info 출력)는 모두 **가안이며 팀 리뷰 후 확정
> 예정**입니다.

## 휴대폰 사건 기록 영구 보관·동기화

`record_archive.py`가 사건 스냅샷·승인/거절 이력·인계확인서를 SQLite에 보관한다. 진행 중 사건뿐 아니라 종료 사건도
구급차별 키로 인증한 휴대폰에 변경 순번으로 내려준다. 새 기기 최초 다운로드, 기존 로컬 기록 이관, 오프라인 수정 재전송과 충돌 처리를 지원한다.
최초 키 발급·서버 DB 경로·WebSocket 계약은 [RECORD_SYNC.md](RECORD_SYNC.md)를 참고한다.

## 담당자

- 이름: 이승주
- 역할: 리드 개발자

## 이 브랜치가 하는 일

feature/voice가 보내는 환자 정보(부상 상태, 예상 병명, 중증도)와 feature/info가
보내는 병원 정보(위치, 병상, 전문성)를 결합해 규칙 기반 스코어링으로 병원 후보를
매칭하고, 존(Zone) 로직을 수행하는 브랜치입니다. **feature/dashboard와 직접
통신하는 유일한 브랜치**로, feature/voice·feature/info는 dashboard로 직접 보내지
않고 이 브랜치를 거칩니다.

처리는 2단계다: (1) GPS와 feature/info의 병원 정보로 먼저 존 기반 병원 후보
리스트를 만들어 보관하고, (2) feature/voice의 의료 정보가 도착하면 이를 반영해
리스트를 재처리한다. 최종적으로 의료 정보·예상 병명·병원 정보·병원 리스트를 모두
합쳐 feature/dashboard로 전달한다.

> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)의
> 수신 주체는 **이 브랜치(feature/hub)로 확정**되었습니다 (dashboard가 feature/hub와만
> 직접 통신하기 때문). 매칭 상태(`hospitals[].status`) 반영과, `final_approval` 시
> 병상을 TTL 오버레이로 차감하는 처리("입출력 데이터 포맷"의 입력 스키마 3 참고)는
> `HubEngine.apply_approval_action()`으로 **구현·테스트 완료**했습니다 (`run_match.py`
> 참고). dashboard와의 실제 WebSocket 통신도 연동 완료됐습니다. feature/info로의
> 병상 갱신 HTTP 전송(`send_to_info()`)은 2026-08-13 병원 Supabase 제거와 함께
> 완전히 폐지됐습니다 — 아래 "출력 스키마 5" 참고.

> **여러 사건(구급차) 동시 처리 지원 완료.** 처음엔 사건 1건 단독 처리만
> 다뤘지만, 이제 `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분해
> 여러 구급차가 동시에 진행돼도 서로 안 섞인다. 바뀐 것 세 가지:
> 1. **dashboard 연결을 소켓 집합으로 관리하고 전체에 브로드캐스트한다** —
>    예전엔 전역 변수 하나라 마지막에 연결한 탭만 갱신을 받는 버그가 있었다
>    (구급차 대시보드 + 병원 대시보드를 동시에 열면 한쪽만 죽는 문제)
> 2. **승인 액션 처리 후 캐시된 사건 결과를 재브로드캐스트한다** — 예전엔
>    이 단계가 아예 없어서 승인 버튼을 눌러도 화면에 반영되지 않았다
> 3. **voice가 여러 대(구급차마다 한 대씩)로 늘어나 apid로 구분**한다.
>    voice가 뜰 때 자기 IP를 자동 탐지해 hub에 자가등록하면(`POST
>    /voice/register`), hub는 그 IP + `AmbulanceInfo.voicePort`를 합쳐
>    주소를 기억해뒀다가 통화 시작/종료 신호를 그 구급차의 voice로 중계한다.
>    구급차 GPS도 하드코딩된 고정값 대신 이 `AmbulanceInfo`(feature/info가
>    Supabase `ambulances` 테이블에서 읽어 보내줌) 조회로 대체했다.

> **존(zone) 확장이 실제 서버(`app.py`)에 배선됐다(2026-08-11).** 그 전까지는
> `MAX_ZONE = 1`(0~5km)이 상수로 고정돼 있어서, 실제 E-Gen/Supabase 병원
> 7곳이 서울 전역에 흩어진 데이터로 테스트했을 때 zone 1 안에 후보가
> 하나도 없어 매칭 결과가 0건으로 나오는 문제가 실제로 재현됐다(`reject_ratio`/
> `expand_if_needed`는 이미 구현·`run_match.py`에서 검증돼 있었지만, 그건
> 스크립트가 수동으로 호출하는 테스트 경로였을 뿐 `/voice/summary`가 실제로
> 쓰는 경로엔 연결돼 있지 않았다). 두 가지를 추가했다:
> 1. `HubEngine.resolve_start_zone()` — 첫 매칭 시 zone 1부터 후보가 하나라도
>    잡힐 때까지 넓힌다. 거절 비율 기반 확장은 "후보가 있는데 다 거절당함"만
>    감지해서, 애초에 후보가 0개인 사각지대(거절할 대상이 없어 비율이 항상
>    0)는 못 잡는다 — 그 사각지대를 메운다.
> 2. `HubEngine.maybe_expand_zone()` — `hospital_reject` 액션 처리 후에만
>    호출한다(`app.py`가 gating). `reject_ratio`가 누적 계산이라, 승인/최종승인
>    뒤에도 이걸 부르면 새 거절이 하나도 없는데 계속 확장되는 문제가 있어서
>    (실제로 재현·수정됨) 거절 액션에만 배선했다.

> **승인 후 캐시된 병상 수가 안 바뀌던 문제 수정(2026-08-11).** `final_approval`로
> `apply_approval_action()`이 `self._hospitals`의 병상 수를 실제로 깎아도,
> dashboard로 나가는 캐시(`_case_results`)의 `HospitalMatch.availableBedCount`는
> 별도 스냅샷이라 반영이 안 됐다 — "이송 확정" 상태는 바뀌는데 병상 배지는 옛날
> 값 그대로 보이는 문제가 실제로 재현됐다(Supabase 자체는 정상 차감돼서 더
> 헷갈렸음). `_patch_case_result_status()`가 status와 함께 `self._hospitals`의
> 최신 병상 수·`bedCountUnknown`도 같이 다시 읽어오도록 고쳤고, 호출 시점도
> 병상 차감 **이후**로 옮겼다.

## 사용한 AI / 모델

거리·병상·존(Zone) 분류는 규칙 기반이지만, "예상 병명 ↔ 병원 진료과" 매칭만은
가벼운 임베딩 모델로 보조한다. `expectedDiagnosis`가 voice의 LLM이 만든 자유
텍스트라서, 하드코딩된 문자열 매칭으로는 실제 데이터를 안정적으로 못 잡기
때문이다 (예: "흉부 손상" ↔ "흉부외과").

| 구분 | 모델명 | 용도 | 비고 |
|---|---|---|---|
| 진료과 매칭 | paraphrase-multilingual-MiniLM-L12-v2 (sentence-transformers) — [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | 예상 병명과 병원 진료과명 임베딩 간 코사인 유사도로 최적 진료과 선택 | feature/voice의 "실시간 음성 필터링"과 동일 모델 재사용. 결정적(deterministic)이고 로컬에서만 동작해 On-Premise 원칙 유지 |
| 거리 / 병상 / 존(Zone) 분류·확장 | — (규칙 기반) | GPS 거리 계산, 존 분류, 거절 비율 기반 존 확장 | 숫자 비교이므로 순수 규칙으로 충분 |

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [x] AI 처리 (진료과 매칭만, 임베딩 유사도 보조)
> - [x] 규칙 기반 (거리·병상·존 로직, 최종 스코어링)

**설명 가능성 유지**: 진료과 매칭도 결과에 `specialtyMatch.score`(0~1 유사도 점수)를
그대로 노출하므로, 왜 이 병원이 이 순위인지 구급대원이 화면에서 확인할 수 있다.
생성형 LLM은 이 브랜치 어디에도 쓰지 않는다 (매번 같은 입력엔 같은 점수가 나와야
하는 매칭 단계라 재현성이 중요함).

## 병원 신뢰도(hospital_score) 반영

info-v2(`hospital_score/`)가 병원마다 15개 중증질환군에 대해 5단계 신뢰도
(`declared_yes` 1.0 ~ `declared_no` 0.2)를 판정해 `HospitalInfo.assessment`로
보낸다. hub는 이걸 두 가지 방식으로 쓴다 — **설명(순위 무관)**과 **정렬(순위에
직접 영향, 2026-08-14 추가)**로 층이 다르다.

**① 설명 — `HospitalMatch.reliability`.** `process_voice_summary()`가 예상
병명에서 이 15개 질환군 중 하나를 **키워드 규칙으로** 고르고(`disease_group.py`, 2026-10-02 —
예전 임베딩은 다리 골절·심근경색·"미상"까지 전부 담낭담관질환으로 골랐다), 매칭된 병원의 그 그룹 판정을
dashboard에 그대로 전달한다. 해당 질환군이 없으면(골절·타박상·발열 등) 칩도 `declared_no` 내림도 없다. `finalScore`
계산식(`0.6×진료과매칭 + 0.4×이동시간 점수`) 자체는 이 값과 무관하다 — "왜 이 순위인지"의
설명 근거로만 쓰인다.

**② 정렬 — `declared_no`만 하드 데모션.** 관련 질환군이 `declared_no`(병원이
"이 시술은 수용 불가"라고 명시적으로 신고)면, `finalScore`가 아무리 높아도 순위
맨 뒤로 밀린다(`scoring.rank()`의 `demote` 정렬 키, `hub_engine.py`의
`_should_demote()`). 후보에서 **제거**하지는 않는다 — 병상 미상 원칙과 같은
논리로, 잘못 걸러내는 게 더 위험하기 때문이다.

가중합(`finalScore`에 신뢰도 점수를 비중 곱해서 섞는 방식)이 아니라 순서 조정만
쓰는 이유는 실험(가상 worktree, 민감도 분석)으로 확인했다 — declared_no가
unknown 계층보다 절대 안 앞서게 완전히 보장하려면 신뢰도 가중치가 70%대까지
필요해서, 그 지점에서는 거리·진료과 반영이 사실상 무의미해진다. hospital_score
자신의 계층 값이 "순서만 의미 있고 값 자체엔 의미 없다"는 설계(`scoring.py`의
`TIER_*` 주석)와도 가중합보다 순서 조정 쪽이 더 맞는다.

**거절 로그가 쌓이면 재검토한다.** 지금은 실제 운영 데이터(병원이 실제로
받았는지)가 없어서 안전 위주로 결정했다 — hub는 이제 `hospital_reject`마다
`POST /hub/rejection`으로 사유를 info에 중계하므로(2026-09-10 배선 완료,
"결과 저장 및 전송 방식" 참고), 로그가 쌓이기 시작하면 tier·거리·진료과매칭이
실제 승인율과 어떤 관계인지 역산해 가중합으로 승격할지 재검토할 수 있다.

## 순위 규칙 (2026-09-28 정비, 2026-10-01 보강)

> ⚠ **2026-10-15부터 finalScore는 spider 거미줄 분배 모델의 줄 길이에서 만든다**(`spider_rule.py` — 줄 길이 = 도로 분 −
> μ×역량 이득 또는 + ν×모자람 + 부하·포화 페널티, 질환군 벽, 정렬 띠 줄 있음 > 줄 없음). 아래 `0.6×진료과 + 0.4×이동시간` 식과
> 전문성·등급 가산은 이제 설명 문구(`bonusReasons`)로만 남는다. 정렬 순서(확정 → 승인 → 나머지 → 내림 → 거절)는 그대로.
> **τ 창(같은 병원에 10분 안 도착 겹침)은 2026-10-22부터 순위에 쓰지 않는다** — `spiderWindow`로 사실만 싣는다(예전엔 한도 2가 차면
> 그 병원을 건너뛰었다). 근거는 `spider_rule.py` 모듈 설명 ⚠ · `poc/CLINICAL_CONVERGENCE.md` §3. 검증 `python test_spider_rule.py`

`finalScore = 0.6 × 진료과 점수 + 0.4 × 이동시간 점수(이동분 − 가산분 + 부하 페널티분 + 포화도 페널티분)`으로 매기고, 아래 순서로
정렬한다(`scoring.rank_key()`). 계산·감사용 후보는 삭제하지 않고 뒤로 내린다. 실제 대시보드 전달 목록에는 아래 KTAS 필터를 적용한다. **순위는 hub 한 곳에서만
정한다** — dashboard는 받은 `hospitals[]` 순서를 그대로 쓴다(2026-10-01, 그 전엔 dashboard가 자체
정렬로 이 규칙을 덮어써서 화면에 반영되지 않았다).

### 음성 KTAS에 따른 병원 전달 필터 (2026-11-01)

음성 요약의 `ktas_level`과 질환군을 `spider_rule.py`의 기존 규칙으로 비교한다. 아이폰에서 통화 전에 누르는
Pre-KTAS 버튼은 이 입력을 덮어쓰지 않는다. KTAS는 환자 중증도이며 병원 자체의 인증 등급이 아니다.
아래 수치는 **spider 시연 모형의 전문의 검토 전 초안**이다. 실제 수용 가능을 보장하지 않는다.

| 음성 KTAS | 모형의 필요 역량 |
|---|---:|
| 1 | 4 |
| 2 | 3 |
| 3 | 2 |
| 4·5 | 1 |

병원 기본 역량은 권역응급의료센터 4, 지역응급의료센터 3, 지역응급의료기관 2, 응급실운영신고기관 1이다.
응급의학과 전문의 수와 야간 보정을 더한 유효 역량이 필요 역량보다 0.75를 초과해 부족하거나, 기존 질환군 벽
(심근경색: 혈관조영 운영, 뇌졸중: CT 운영·기관 등급, 중증외상: 센터급)을 통과하지 못하면 새 전달 대상에서 제외한다.
진료과 임베딩 점수와 병상 정보 유효 확률로 새 제외 기준을 만들지는 않는다.

`hospital_dispatch.dashboard_payload()`가 실제 전송 직전에 `hospitals[]`를 고른다. 따라서 폰·패드·웹·관제 및
재접속 시 동일한 목록·개수를 받는다. 내부 전체 후보와 제외 사유는 계산·감사 로그에 남고, 병원별
`ktasSuitability`(적합 KTAS 목록·역량·현재 질환군·source: rule), 전달별 `dispatchPolicy`로 근거를 전달한다.
병원이 이미 명시적으로 승인하거나 이송 확정된 경우에는 모형 추정만으로 승인을 취소하지 않는다.

맞는 병원이 없으면 최대 Zone 10(50km)까지 맞는 병원이 있는 존을 찾아 확장한다. 끝까지 없으면 0곳이며
부적합 병원으로 우회 전송하지 않는다. 시간 기반 확장과 거절 비율도 적합한 전달 후보를 기준으로 계산한다.
KTAS 변경으로 기존 대상에서 빠진 병원에는 새 환자 정보 대신 해당 병원에만 `case_closed`를 보내 요청 카드를 회수한다.
대상에서 빠진 병원의 오래된 승인 액션도 거부한다. 기록 동기화에 쓰는 현재 스냅샷 역시 전달 목록을 사용한다.

검증: `python hub/test_ktas_dispatch.py`(모델·외부 API 없이 역량/장비/존 확장/양방향 기기 목록/재접속/철회/승인 유지).

1. 이 사건의 이송 확정(`confirmed`) 병원 → 병원이 승인(`approved`)한 병원
2. 나머지 병원: `finalScore` 내림차순 (같으면 가까운 순 → ID 순)
3. 그 뒤: `declared_no`(관련 질환군 수용 불가 신고) · `severe_blocked`(관련 질환군 E-Gen 차단 메시지, 2026-10-07) · `beds_full`(병상 0이 **확인된** 만실)
4. 맨 뒤: 이 사건에서 거절(`rejected`)한 병원

**진료과 점수** (2026-10-01): voice의 `summary.required_department`(심평원 과목 표기)가 병원 진료과에
있으면 **정확 일치 1.0**(`specialtyMatch.basis = "exact"`), 없으면 예상 병명과 진료과명의 임베딩
유사도(`"embedding"`). 진료과는 info가 E-Gen 역량 4개 과 + 심평원 전문과목별 전문의 수로 채운다.

**전문성·등급 가산** (2026-10-01, `scoring.expertise_bonus_min()`): 점수에 더하지 않고 **이동시간에서
분을 뺀다.** 점수에 더하면 같은 가산이 가까운 병원 사이에선 4분, 먼 병원 사이에선 20분의 가치가 되어
버린다. 분 단위라 불변식이 정확히 선다 — **가산을 다 받아도 `MAX_BONUS_MIN`(8)분 넘게 먼 병원은
가까운 병원을 이길 수 없다**(`run_match.py`가 3/10/30/60분에서 검사).
- 매칭된 진료과 전문의 수: 최대 3분 (log 스케일 — 1명 0.7분, 5명 1.8분, 20명 이상 3분)
- 중증(`severity_tag = "high"`)일 때만 응급의료기관 등급: 권역응급의료센터 5분, 지역응급의료센터 2분
- 모르는 값은 0분(불리하게 두지 않음). 쓴 값과 이유는 `travelBonusMin`·`bonusReasons`로 나간다
- 값은 수용 결과 데이터 없이 정한 보수적 초기값이다 — 거절 로그가 쌓이면 재보정한다
- **경증 역가산** (2026-10-03, `MILD_CENTER_PENALTY_MIN`): 경증(`low`) 환자에게는 권역·지역
  응급의료센터에 거꾸로 **+3분**을 더한다 — "경증은 센터를 아껴라". 경증이 최근접이라는 이유로
  센터의 마지막 병상을 차지하면 뒤에 오는 중증이 최종치료 가능한 곳에 못 들어간다(재난의료의
  "경증은 멀리" 원칙). 음수 가산으로 섞여 나가므로 스키마·dashboard 수정이 없고
  (`travelBonusMin`이 음수, `bonusReasons`에 "경증 · 권역응급의료센터 +3분(센터 보존)"),
  제외가 아니라 순위 조정이라 주변에 센터뿐이면 여전히 센터로 간다. 중증 가산·부하 페널티와
  합쳐지면 별도 재난 계획자 없이 "중증은 센터로, 경증은 분산, 차면 다음으로"가 가격 신호만으로
  성립한다. 검증 `run_match.py test_mild_center_penalty()`

**이송 중 부하 페널티** (2026-10-03, `scoring.load_penalty_min()`): 가산의 대칭형으로, 같은 병원으로
확정돼 이송 중인 건수(TTL 오버레이, 사건 무관 병원 단위)가 많을수록 **이동시간에 분을 더한다** —
`페널티 = 10분 × 이송 중 / (이송 중 + 실질 가용)`. 예전엔 차감된 병상이 화면 표시·만실 판정에만 쓰이고
순위에는 닿지 않아서, 병상 20개 병원에 19명을 확정해도 20번째 환자에게 1순위로 떴다(만실이 되는 순간에야
beds_full 절벽 강등). 이 페널티는 만실 **전에** 연속적으로 분산시킨다 — 대량사고(MCI) 분산의 실제 작동
지점이고, 대량사고 시뮬레이션(`sim/`)의 goldenlink 팔과 로직이 일치하게 됐다.
- **평시 불변**: 이송 중 0건이면 페널티 0 — 단일 사건 평시 순위는 이 변경 전과 완전히 같다
- 상한 10분(`LOAD_PENALTY_MAX_MIN`) — 가산 불변식과 같은 틀. 병상 미상이면 압력을 정의할 수 없어 0분
- 쓴 값과 이유는 `inFlightCount`·`loadPenaltyMin`·`loadReason`으로 나간다. 검증 `run_match.py`의
  `test_load_penalty()` (평시 불변 + 확정 16건 → +8분 → 만실 전 분산)
- 관제 지도(`map_overview`)의 병원마다 `inFlightCount`가 실려, 확정·도착 결과 때마다 다시 간다

**응급실 포화도 페널티** (2026-10-07, `scoring.occupancy_penalty_min()`): info가 보내는 응급실 정원
(`bedCapacityByType.ER_ADULT`, E-Gen `hvs01`)으로 포화도 `(정원 − 가용) ÷ 정원`을 내고, 그에 비례해
**이동시간에 최대 5분**을 더한다(`OCCUPANCY_PENALTY_MAX_MIN`). 같은 "가용 2석"이라도 정원 10석과 40석은 다르다.
- 불변식: 페널티를 다 받아도 5분 넘게 가까운 병원은 역전당하지 않는다
- 부하 페널티의 절반 — 부하는 우리가 확정한 사실이고 포화도는 병원 신고값이라 낡을 수 있다
- 이송 확정 차감 **전** E-Gen 값으로 계산한다 — 이송 중 환자는 부하 페널티가 세므로 두 번 세지 않는다.
  화면의 `erOccupancyPct`는 차감까지 반영한 표시값이다
- 병상 미상·1일 넘은 값·정원 없음이면 0분. 쓴 값과 이유는 `occupancyPenaltyMin`·`occupancyReason`
- 대량사고 분배(`plan_mci`)도 같은 값을 더한다. **`sim/`의 goldenlink 팔에는 아직 없다** — 시뮬과 실코드의
  로직 일치를 유지하려면 sim 쪽에도 같은 페널티를 넣어야 한다
- 값은 팀 합의 전 초기값이다. 검증 `test_er_occupancy.py`

내린 이유는 `hospitals[].demoteReasons`로 나간다. 세부 규칙:

- **이동시간 점수**는 `0.5^(이동분/15)` — 15분마다 절반이 되고 0이 되지 않는다. 예전 거리
  점수(`1 - km/20`)는 20km 밖 병원을 전부 0으로 봐서, 반경 20km 안에 병원이 없는 지역에선
  거리 차이가 순위에 전혀 반영되지 않았다. 카카오 키가 없을 때(직선 1.5분/km) 10km에서
  0.5가 되어 가까운 거리에서는 예전 곡선과 거의 같다.
- **이동분은 카카오 ETA가 있으면 ETA**, 없으면(키 없음·반경 10km 밖) 직선거리 × 이 사건에서
  ETA를 받은 병원들의 "분/km" 중앙값(표본이 없으면 1.5분/km)으로 추정한다. 고정 속도로
  추정하면 ETA를 받은 병원(실제 교통 반영)보다 추정한 먼 병원이 부당하게 유리해진다.
  쓴 값과 출처는 `travelMin`·`travelBasis`(`"eta"`|`"estimate"`)로 나간다. 존(zone) 판정은
  계속 직선거리다(후보를 거르는 1차 필터라 외부 호출 없이 빨라야 한다).
- **beds_full은 확인된 만실만**이다. 병상 미상(`bedCountUnknown`)이나 오래된 값
  (`bedDataStale` — 마지막 갱신 1일 초과, 또는 info assessment의 `stale`·`missingFromFeed`)의
  0은 만실로 믿지 않는다. 미상을 이유로 밀어내면 뺑뺑이가 오히려 늘어난다는 기존 원칙과 같다.
- **병원이 이 사건에 승인·확정 응답을 했으면 declared_no·beds_full로 내리지 않는다.** 그
  병원의 명시적 응답이 미리 해둔 신고나 병상 숫자보다 우선이다. 특히 확정 직후 병상 차감
  오버레이로 0이 된 병원이 자기 사건에서 만실로 밀려나지 않게 한다.
- 승인 액션이 오면 캐시된 결과를 **재정렬**해서 다시 보낸다. 예전엔 status만 바꿔서 거절한
  병원이 1위 자리에 그대로 남았다.
- **이송이 확정된 사건은 60초 재계산에서 재정렬하지 않는다**(2026-10-01). 목적지가 정해졌는데
  목록이 뒤섞이고 후보 전체 ETA를 다시 부를 이유가 없다. 승인 액션 뒤 패치는 그대로 된다.
- `nightDutyAvailable`은 순위에 쓰지 않는다. info가 `bool(capabilities)`(E-Gen에 역량을 하나라도
  신고했는가)로 채우는 프록시라 실제 야간 당직 정보가 아니고, 진료과 점수와 같은 신호를
  두 번 반영하게 된다.

## 승인 흐름 규칙 (2026-09-28)

- **주체 짝**: `hospital_approve`·`hospital_reject`는 `actor: "hospital"`, `final_approval`은 `actor: "paramedic"`만 받는다
- **순서**: `final_approval`은 병원이 그 사건에 `approved`한 병원에만 허용한다(병원 승인 = 후보 등록, 이송 승인 = 최종 확정)
- 어긋난 액션은 상태를 바꾸지 않고 `approval_action_refused` 이벤트로 사유만 의사결정 로그에 남긴다
- **재선택**: 같은 사건에서 다른 병원을 이송 승인하면, 이전 확정 병원은 `approved`로 되돌리고(새 상태값 없음 — dashboard 타입 유지) 그 확정이 얹은 병상 차감을 회수한다(`approval_released` 이벤트)
- dashboard는 이미 이 규칙대로만 버튼을 연다(`HospitalCandidateListPanel.tsx`의 `approvable`, `ApprovalActions.tsx`의 role 분기)
- **미선택 통보(2026-10-22)**: 이송이 확정되면 승인했지만 선택되지 않은 병원에 `HospitalMatch.notSelected = true`(status는 `approved`
  그대로 — 재선택 대상, 확정이 풀리면 false)를 세우고, 그 병원 탭에 `{"type": "selection_released", caseId, hospitalId,
  confirmedHospitalId, confirmedHospitalName, timestamp}`를 보낸다. 탭이 없던 병원은 따라잡기의 깃발로 받는다. 의사결정 로그
  `selection_released`(releasedHospitalIds·deliveredHospitalIds). 관제 요약(`case_overview`)에도 `notSelected`가 실린다(2026-10-24)

### 도착 결과와 신뢰도 정답 데이터 (2026-10-01)

신뢰도 모델(AIROOKIE-EGEN.md)의 지금 정답은 "병원이 나중에 숫자를 스스로 고쳤는가"(G1)뿐이다. 병원 신고와
무관한 **독립 관측(G2)**은 "실제로 받았는가"이고, 그건 운영에서만 생긴다(§7 ④ 도착 결과). 그래서:

- **도착 결과 액션**: `arrival_accepted` / `arrival_refused`(`actor: "hospital"`, 거절 사유 4축 어휘). 이 사건의
  **확정 병원에만**, 결과는 한 번만. 출동 시뮬레이션 중엔 구급차가 그 병원에 **실제로 도착했을 때만** 받는다
  (이송 중 도착 결과가 들어와 엔진만 바뀌는 어긋남이 E2E에서 실제로 났다)
- **도착 후 수용 불가**: 확정을 풀고 `rejected`, 병상 차감 회수, 사건은 다시 미확정. 거절 로그에 `stage: "arrival"`과
  **결정 시점 스냅샷**(그때 보였던 병상 수·authority·rArrive)이 남는다 — "확실하다고 봤는데 틀렸다"를 셀 수 있는 유일한 기록.
  승인한 다른 병원이 없으면 **같은 환자 정보로 존을 한 단계 넓혀** 새 후보 병원들에게 다시 보낸다(재통화 없음, `force_expand_zone`)
- **도착 수용**: `HubMatchResult.arrival`에 기록. 사건 종료
- **재선택 해제 사유**: `approval_released.cause = "paramedic_reselect"` + 두 병원의 당시 이동시간·점수(`atDecision`).
  재선택은 "더 나은 병원"이지 "정보가 틀림"이 아니라서, 라벨을 만들 때 실패로 세면 안 된다(그 병원은 받겠다고 했다)
- **무응답(`NO_RESPONSE`)은 사건이 끝날 때 기록한다** — 도착 수용·현장 종료·방치 정리. 예전엔 첫 이송 승인 순간에
  기록해서, 그 뒤 승인하고 재선택된 병원까지 "무응답"으로 남았다(거부된 이송 승인에도 기록되던 문제 포함)
- 실서버 E2E(재선택 → 도착 후 수용 불가 → 다른 승인 병원 → 수용) 결과: 거절 로그에 도착 후 BEDS_FULL 1건(당시 병상 3·authority 1.0),
  끝까지 응답 안 한 2곳만 NO_RESPONSE, 승인했던 병원은 무응답으로 안 찍힘

## 병상 정보 신뢰도(bedReliability) 반영 (2026-09-24 신설)

위 hospital_score(중증질환 **수용 신고**의 신뢰도)와는 다른 축으로, feature/info의
`reliability/` 모듈(infosurv 벤더링 — XGBoost AFT 생존모델, AIROOKIE-EGEN.md 참고)이
**가용 병상 수 값 자체가 아직 유효한가**를 병원별·시점별 확률로 계산해
`HospitalInfo.bedReliability`로 보낸다(source: "ai" — 생성형은 아니지만 학습 모델).

hub가 실제로 쓰는 건 `predictedSurvivalSec`(예측 생존시간)과 `bornAt`(현재
claim-version 탄생 시각) 둘이다. authority(지금 믿어도 될 확률)는 정보 나이에
따라 계속 떨어지는 값이라 info의 전송 시점 스냅샷을 그대로 쓰면 재조회
주기(30분)만큼 낡는다 — 그래서 `bed_reliability.evaluate()`가 **매칭 시점마다**
재계산해 `HospitalMatch.bedReliability`로 내보낸다:

| 필드 | 의미 |
|---|---|
| `authority` | 지금 이 병상 숫자를 믿어도 될 확률 (0~1) |
| `rArrive` | **도착 시점**(`horizonSec` 뒤 — 순위에 쓴 이동 시간 `travelMin`과 같은 값, 2026-09-28)에도 유효할 확률 |
| `ttlSec` | authority가 0.8 아래로 떨어질 때까지 남은 초 (재확인 알림 후보) |
| `modelTag` | 사용 모델 식별자 (`aft_egen_theta3_ext0923` 등) |

**순위(finalScore)에는 관여하지 않는다** — `reliability`(hospital_score)와 같은
설명용 원칙. 단 이쪽은 서수 티어가 아니라 **캘리브레이트된 확률**이라, 거절
로그로 효과가 실측되면 `rArrive`를 랭킹 가중치로 승격하는 것이 다음 단계 후보다
(AIROOKIE-EGEN.md §5-1이 권하는 방향). 수식은 info 쪽 벤더링 사본과 동일한
log-normal AFT 생존함수를 표준 라이브러리로 재구현한 것이고(scipy 의존 회피),
수치 등가성은 info의 `python -m reliability.selftest`가 검증한다. 이 필드 없이
오는 구 feature/info 데이터는 `bedReliability=null`로 그대로 통과한다.

### 중증질환 신고 신선도 (severeFreshness, 2026-09-28 신설 — 규칙 기반)

같은 취지의 셋째 축인데 **모델이 아니라 규칙**이다. info의 실측(스냅샷 47일)
에서 중증질환 수용가능 신고(MKioskTy)는 값 변화의 90%가 Y↔정보미제공 왕복
이고 만료 수명의 60.1%가 정확히 9.0시간 — 시스템 자동 만료 규칙이 지배해서
모델을 만들지 않기로 했다(info의 `reliability/README.md` 참고). E-Gen 응답에
신고 시각 필드가 없어서 "이 신고가 언제 적 것인지"는 info의 스냅샷 추적
(`HospitalInfo.severeDeclarations`)만이 알고, hub는 매칭된 질환군에 대해
신고 나이(`ageSec`)와 9시간 규칙 잔여(`ruleRemainingSec`)를 계산해
`HospitalMatch.severeFreshness`(source: "rule")로 내보낸다. `ageIsMin`이
true면 추적 시작부터 그 값이었다는 뜻이라 "최소 X시간 전"으로 읽어야 하고,
`ruleRemainingSec`이 0인데 신고가 여전히 떠 있으면 병원이 갱신을 지속 중
이라는 뜻이지 신고가 죽었다는 뜻이 아니다. `reliability`(같은 신고를 심평원
대조로 "믿을 만한가")와 상보적이며, 역시 순위에는 관여하지 않는다.

### 병원 정보 확인 루프 (info_confirm / hospital_self_info, 2026-09-29 신설)

신뢰도 스택의 나머지가 전부 "낡음을 감지해 소비자에게 경고"하는 대증이라면,
이건 **원인(공급자) 쪽 피드백 루프**다. E-Gen 포털엔 병원에게 "당신 정보가
얼마나 낡았는지"를 보여주는 화면이 없어 수년 묵은 값이 방치된다(실측 2,457일).

- **`hospital_self_info` (hub → 병원 대시보드)**: "귀원 정보 현황" — 병상 수·
  자기 병상 신뢰도(horizon 0이라 rArrive==authority, 곡선 파라미터 포함)·
  확장 필드·중증 신고 현황. identify 직후, info의 30분 upsert 직후, 정보 확인
  직후에 그 병원 소켓으로만 보낸다(`_build_self_info()`/`_send_self_info_to_hospital()`).
- **`info_confirm` (병원 대시보드 → hub)**: "현재 정보가 맞습니다" 버튼.
  `HubEngine.confirm_hospital_info()`가 기록하고(상태 파일에 저장·복구),
  `bed_reliability.evaluate()`가 **조건부 생존 S(a)/S(u)** 로 그 병원 확률을
  되올린다 — infosurv serve의 `confirmed_at` 메커니즘이 처음으로 실신호를
  받는 지점이다. 값이 바뀌어 claim이 새로 태어나면 확인은 자동 무효
  (confirmedAt < bornAt). 확인은 의사결정 로그(`hospital_info_confirmed`)에도
  남아 나중에 infosurv 유효 확인(G1+) 라벨 재료가 된다. 구급차 화면 칩에는
  ✓로 표시(`BedReliabilityMatch.confirmedAgeSec`), 관련 사건은 즉시 재계산·
  재브로드캐스트된다. 수식 등가성은 info의 selftest 3번(조건부 항목)이 검증.

### 이송 중 활력징후 모니터링 (2.5단계, 2026-10-04 신설 — 규칙 기반)

이송 확정 뒤 환자 상태 변화를 받아 판정하고 역할별로 알린다. 규칙표·기준값 출처·
초안 한계는 **`hub/TRANSPORT_TRIAGE.md`**, 엔진은 `transport_triage.py`(순수 함수,
NEWS2 공개 표준 + 쇼크지수), 검증은 `python test_transport_triage.py`(시연 시나리오
5종이 픽스처).

- **입력 구멍**: `POST /vitals`(HTTP — 향후 119구급스마트시스템·구급차 모니터 어댑터)와
  dashboard WS `transport_vitals`(지금은 가상 시나리오·수기)가 같은 처리로 모인다.
  형식 `VitalObservationIn` — 종류·값·측정시각·출처(voice/manual/monitor/demo).
  장비는 사지 않고 자리만 만든다는 원칙.
- **판정 티어**: record(기록) / hold(초과 1회째 — 오경보 필터) / notify(연속 2회 또는
  NEWS2 ≥ 7 → 확정 병원에 전달) / review(+ 치료 변화 신호 → 대체 병원 최대 3곳 제안,
  결정은 사람) / heli_advisory(대체 후보 0곳 → 헬기 대기 권고, 결정은 관제).
- **전송 범위**(`transport_assessment`): 구급차 탭 전부 · 확정 병원 탭 notify 이상만 ·
  관제 지도 heli_advisory만(활력징후 상세 없이 — 환자 상세는 병원 대시보드만 받는 원칙).
  notify 이상은 의사결정 로그에 남는다. 사건이 닫히면 판정 상태도 같이 지운다.
- 대체 후보는 캐시된 매칭 결과에서 승인/대기 병원 중 `HUB_TRANSPORT_ALT_MAX_MIN`
  (기본 30분) 안쪽만 — 수용 불가 신고·확인된 만실·거절 병원은 내밀지 않는다.

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 주요 라이브러리·프레임워크: pydantic(스키마 검증), sentence-transformers(진료과 매칭), numpy
- 실행 환경: 로컬 (CPU로 충분 — MiniLM은 경량 모델이라 GPU 불필요)
- **가상환경 이름 컨벤션**: `rookie_hub`. 이 저장소는 5개 브랜치가 작업 폴더를 공유하기
  때문에, feature/voice는 `rookie_voice`, feature/hub는 `rookie_hub`처럼 브랜치별로
  가상환경 이름을 분리해서 쓴다 (같은 이름의 환경을 여러 브랜치가 같이 쓰면 서로 다른
  의존성 버전이 섞여 꼬일 수 있음). `rookie_hub`는 hub의 `requirements.txt`만으로 처음부터
  새로 설치해서 검증했다 — voice 쪽 라이브러리(faster-whisper 등)는 안 들어있는 깔끔한
  환경이다.

## 입출력 데이터 포맷

> 아래 스키마 모두 가안이며 팀 리뷰 후 확정 예정.

### 입력 스키마 1: feature/voice로부터 (환자 정보)

**2026-11-01 처치판 호환**: `summary={patient_count:1, patients:[...]}`도 받는다. `voice_treatments.py`가
환자의 주증상·의식·활력징후·규칙 Pre-KTAS와 `treat_categories` 28범주를 기존 `VoiceSummary`로 변환한다.
`PatientInfo.treatment`를 통해 iPhone 인계확인서의 처치 칸이 자동으로 채워진다. 범주 한글화는 규칙 기반이며 생성형 AI를 쓰지 않는다.
기존 v1/v2 형식도 유지한다. 현재 사건/대시보드는 단일 환자이므로 다중 환자는 입력 검증에서 거절한다.
주증상이 미상인 경우 임의 진료과를 지정하지 않는다. Pre-KTAS 추정이 없으면 `ktas_level=null`이고
기존 3단계 매칭 계약의 기본 `severity_tag=medium`을 사용한다(의료진의 확정 등급이 아님).


> **2026-10-01**: voice가 summary를 v2 스키마(MF_BERT 17필드)로 바꿨다. hub는 v2와 아래 예전 형식을 **둘 다** 받는다 — v2면 `voice_v2.normalize()`가 예전 필드(`patient`·`mechanism`·`symptoms`·`treatment`·`severity_tag`·`required_department`)로 옮기고 KTAS·활력징후·의식·발생 시점·주 호소를 더한다. v2 원본 형식은 CLAUDE.md "데이터 포맷 1번"이 최신이다. 필요 진료과 대응표는 팀 확인 전 초안(`voice_v2.py` 상단).

기존 feature/voice README.md에 정의된 출력 스키마를 그대로 참조한다
(`transcript`, `summary.mechanism`, `summary.symptoms`, `summary.treatment`,
`summary.severity_tag` 등, 자세한 필드 설명은 feature/voice README.md 참고).
feature/hub는 `summary` 필드(부상 상태, 예상 병명, 중증도)는 매칭 스코어링에
쓰고, `transcript.raw_text`/`transcript.filtered_text`(원본·필터링 전문)는
스코어링에는 안 쓰지만 dashboard가 확인할 수 있도록 "출력 스키마 4"의
`patientInfo`에 그대로 실어 전달한다.

### 입력 스키마 2: feature/info로부터 (병원 정보)

```json
{
  "hospitalId": "H001",
  "name": "○○병원",
  "gps": { "lat": 35.1795, "lng": 128.1076 },
  "availableBedCount": 12,
  "bedsByType": { "ER_ADULT": 12, "ICU": 3 },
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

| 필드 | 타입 | 설명 |
|---|---|---|
| `hospitalId` | string | 병원 고유 식별자 |
| `name` | string | 병원명 |
| `gps.lat` / `gps.lng` | number | 병원 위치 좌표 (Hub의 거리 계산에 사용) |
| `availableBedCount` | number | 현재 실시간 가용 응급실 병상 수. **미상일 때도 0이 들어온다** — 아래 `bedsByType`으로 구분한다 |
| `bedsByType` | object (optional) | 병상 종류별 가용 수(`ER_ADULT`·`ICU` 등). feature/info는 **미상인 종류의 키를 아예 넣지 않는 것**으로 "확인된 만실(`{"ER_ADULT": 0}`)"과 "미상(키 없음)"을 구분한다. hub는 `availableBedCount == 0`이면서 `ER_ADULT` 키가 없을 때만 미상으로 판정한다 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[].department` | string | 진료과명 |
| `specialties[].doctorCount` | number | 해당 진료과 수술 가능 의사 수 |
| `specialties[].recentProcedureTags` | string[] | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반이며 향후 실제 데이터로 교체 예정) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 이 정보가 마지막으로 갱신된 시각 |
| `assessment` | object (optional) | info-v2(hospital_score)의 신뢰도 진단 — 위 "병원 신뢰도(hospital_score) 반영" 참고 |
| `bedReliability` | object (optional) | 병상 정보 신뢰도 예측(`predictedSurvivalSec`·`bornAt`·`sigma`·`authorityAtSend`·`ttlSec`·`modelTag`, source: "ai"). `sigma`는 잔차 재보정(σR)이 적용된 생존곡선 척도(raw면 1.0, 2026-09-28) — 위 "병상 정보 신뢰도(bedReliability) 반영" 참고 |
| `bedReliabilityByType` | object (optional, 2026-09-28 다필드 확장) | 응급실 일반 외 확장 필드의 신뢰도 예측. 키는 E-Gen 필드명(`hvoc` 수술실·`hvgc` 입원실·`hv28` 소아 — info의 `train_field.py` 관문 통과분), 값 구조는 `bedReliability`와 동일 |
| `severeDeclarations` | object (optional) | 중증질환 수용가능 신고의 질환군별 현재 값·관측 기준 탄생시각(`groups.{질환군}.{value, bornAt, ageIsMin}`, source: "rule"). 정보미제공 그룹은 키가 없다 — 위 "중증질환 신고 신선도" 참고 |

### 입력 스키마 3: feature/dashboard로부터 (승인 액션)

dashboard는 feature/hub와만 직접 통신하므로, 승인 액션(hospital_approve/
hospital_reject/final_approval)의 수신 주체는 이 브랜치로 확정한다. **전송
방식은 WebSocket이다** — dashboard가 `new WebSocket()`(socket.io 아님)으로
`ws://<hub 주소>/ws/dashboard`에 연결해 JSON 문자열 프레임으로 보낸다
(`app.py`의 `/ws/dashboard` 참고).

```json
{
  "caseId": "case-abc123",
  "action": "final_approval",
  "hospital_id": "H001",
  "actor": "paramedic",
  "timestamp": "2026-07-30T14:20:00Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `caseId` | string | 어느 사건(구급차)에 대한 승인인지. 여러 사건이 동시에 진행되면 `hospital_id`만으로는 특정할 수 없어 추가됐다. dashboard는 자기가 보고 있는 사건의 caseId를 "출력 스키마 4"로 이미 받아 알고 있다 |
| `action` | `"hospital_approve"` \| `"hospital_reject"` \| `"final_approval"` | 어떤 승인 행위인지 |
| `hospital_id` | string | 대상 병원 식별자 |
| `actor` | `"hospital"` \| `"paramedic"` | 누가 누른 행위인지 |
| `timestamp` | string (ISO 8601) | 행위 발생 시각 |

이 액션을 받으면 해당 병원의 `hospitals[].status`를 갱신하고, `final_approval`인
경우 아래 "출력 스키마 5"로 feature/info에도 병상 갱신을 알린다.

### 입력 스키마 6: feature/dashboard로부터 (통화 시작/종료 신호)

같은 `/ws/dashboard` 연결로 dashboard의 "통화 시작"/"통화 종료" 버튼 신호도
받는다. hub는 이 신호를 **그 구급차(apid)의 voice 인스턴스로** HTTP POST
중계한다 — 오디오 자체는 hub를 거치지 않는다 (dashboard가 `sendAudioChunk()`로
브라우저 마이크 오디오도 같이 보내지만, 실제 STT 입력은 voice의 로컬 마이크로
확정되어 hub는 그 바이너리 프레임을 받기만 하고 버린다).

> **2026-10-03: 중앙 voice가 등록돼 있으면 위 설명 대신 아래 "중앙 voice와 휴대폰 통화"가 적용된다** — 브라우저
> 음성이 실제 STT 입력이 되고, voice 한 대가 모든 구급차를 처리한다. 중앙 voice가 없거나 등록이 90초 넘게
> 끊기면 위의 구급차별 방식으로 돌아간다.

구급차마다 voice가 별도 장비에서 뜨기 때문에(apid별로 다름), hub는 이 apid로
`POST /voice/register`(아래 "입력 스키마 8" 참고)로 등록된 주소를 찾아 그
주소로 중계한다 — 아직 등록 전이면 조용히 건너뛴다. `call_started` 시점에
`(caseId -> apid)`를 기억해뒀다가, 나중에 그 caseId로 도착하는 voice 요약이
어느 구급차의 GPS를 써야 하는지 찾는 데도 쓴다.

```json
{
  "type": "call_signal",
  "signal": "call_started",
  "timestamp": "2026-07-30T14:15:00Z",
  "apid": "A0000001",
  "caseId": "case-abc123"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"call_signal"` | 고정값 |
| `signal` | `"call_started"` \| `"call_ended"` | 통화 시작인지 종료인지 |
| `timestamp` | string (ISO 8601) | 신호 발생 시각 |
| `apid` | string | 어느 구급차(voice 인스턴스)인지. hub가 중계 대상 주소를 찾는 키 |
| `caseId` | string | 이번 통화가 어느 사건인지. dashboard가 `call_started` 시점에 새로 생성해 보낸다 |
| `hospitalId` | string? | 휴대폰 통화 화면에서 고른 첫 통화 병원(2026-10-03). 있으면 그 병원 탭에 `call_status`가 가고 `first_call_selected`가 기록된다 |
| `device` | `"phone"` \| `"tablet"`? | 어느 화면에서 건 통화인지(2026-10-03). 표시용 |

### 중앙 voice와 휴대폰 통화 (2026-10-03 신설)

voice를 구급차마다 띄우지 않고 **한 대만** 띄운다(`./voice/start-voice.sh` 인자 없이 — voice README 참고).
대시보드(대원 휴대폰 전화 앱 `/phone`, 구급차 대시보드 `/ambulance`의 통화 시연)가 마이크 음성을 **16kHz 모노 16비트 리틀엔디언 PCM** 바이너리
프레임(약 0.1초씩)으로 같은 `/ws/dashboard` 소켓에 보내면, hub가 사건별로 모아 중앙 voice에 넘긴다.

- **등록**: voice가 `POST /voice/register {"central": true, "ip", "port"}`로 30초마다 알린다. 90초
  (`CENTRAL_VOICE_STALE_SEC`) 넘게 소식이 없으면 꺼진 것으로 보고 구급차별 방식으로 돌아간다. `central`이
  없으면 예전처럼 `apid`가 필요하다(없으면 400)
- **중계**: `call_started`를 보낸 소켓을 그 사건에 묶고(`_socket_call`), 그 소켓의 음성만 사건별 전송기
  (`_AudioRelay`)가 0.25초마다 voice `POST /call/<caseId>/audio`로 넘긴다. 시작 신호를 안 보낸 소켓의 음성은
  버린다. `call_ended`면 남은 음성을 다 보낸 **뒤에** `POST /call/end`를 보낸다(끝말이 잘리지 않게). 음성은
  저장·로그하지 않는다. 소켓이 끊기면 묶음만 풀고, voice가 60초 무음이면 통화를 저절로 끝낸다
- **통화 상태 `call_status`** (hub → 그 구급차 탭 전부·전화 건 병원 탭·관제 지도, 연결 직후 따라잡기 포함):
  `{type, caseId, apid, ambulanceName, hospitalId, hospitalName, device, state: "calling"|"ended", startedAt, endedAt}`.
  통화는 **연출**이라 병원과 실제 음성이 연결되지는 않는다 — 병원 대시보드엔 "📞 ○○ 통화 중"만 뜨고, 통화
  내용은 STT·구조화 뒤 평소처럼 존 안 후보 병원 전체에 매칭 결과로 간다
- **현장 후보 따라잡기**: 마지막 `scene_candidates`를 사건별로 들고 있다가(`_case_scene`) 구급차 탭이 새로 붙으면
  다시 준다 — 현장 도착 뒤에 연 휴대폰도 전화할 병원 목록을 받는다
- **의사결정 로그** `first_call_selected`: `{caseId, apid, hospitalId, recommendedHospitalId, followedRecommendation, device}`
  — 첫 연락 추천(`first_call_recommended`)이 실제로 따라졌는지 셀 재료
- **대시보드 통화 허용 `HUB_DASHBOARD_CALL`**(start-all `--dashboard-call`): 기본 꺼짐 — 통화는 휴대폰 전화 앱(`device: "phone"`)으로만 받고, `device: "tablet"`인 통화 시작은 거부한다(`call_start_refused`, reason `dashboard_call_off`, device 없는 예전 신호는 통과). `identity_info.dashboardCall`로 알려 구급차 대시보드가 [통화 시작] 패널 대신 보기 전용 통화 현황을 띄운다
- 검증: `python test_central_voice.py`(가짜 voice 서버로 실제 HTTP 요청을 받아 본다, 임시 로그 경로)

### 입력 스키마 7: feature/info로부터 (구급차 정보)

병원 정보(입력 스키마 2)와 짝을 이루는 구급차 레지스트리. feature/info가
Supabase `ambulances` 테이블에서 읽어 보내준다.

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
| `gps.lat` / `gps.lng` | number | 구급차 위치. 대회 데모 단계라 서울 랜드마크로 고정한 값(실시간 GPS 아님) |
| `voicePort` | number | 이 구급차 voice 인스턴스가 뜰 포트. 장비마다 미리 정해둔 값이라 안정적이다 — IP는 여기 없다(아래 "입력 스키마 8" 참고) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 마지막 갱신 시각 |

### 입력 스키마 8: feature/voice로부터 (voice 자가등록)

voice는 구급차 노트북마다 별도로 뜨고, 노트북이 붙는 네트워크(와이파이/
핫스풋)가 자주 바뀔 수 있어 IP를 Supabase 등에 고정 저장하지 않는다. 대신
voice가 뜰 때 자기 IP를 자동 탐지해 이 엔드포인트로 hub에 알려준다.

```json
{
  "apid": "A0000001",
  "ip": "192.168.0.101"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `apid` | string | 이 voice 인스턴스가 담당하는 구급차 |
| `ip` | string | 이 voice 인스턴스가 자동 탐지한 자기 IP. hub는 `AmbulanceInfo.voicePort`와 합쳐 `http://{ip}:{voicePort}` 주소로 저장한다 |

중앙 voice(2026-10-03)는 `{"central": true, "ip": "...", "port": 6000}`으로 등록한다 — 위 "중앙 voice와 휴대폰 통화" 참고.

이 apid의 `AmbulanceInfo`가 아직 hub에 등록되기 전이면(포트를 모르므로)
`409`를 반환하고 등록을 보류한다 — feature/info가 구급차 정보를 먼저 보낸
뒤에 voice가 자가등록하는 순서를 전제로 한다.

### 입력 스키마 9: feature/dashboard로부터 (소켓 연결 시 자기소개, 2026-08-11 신설)

hub는 `/ws/dashboard` 연결을 그동안 완전히 익명으로 취급해서, 매칭 결과를
"그 순간 연결된 소켓"에만 브로드캐스트했다. 그래서 진행 중인 사건이 있는
상태로 새 대시보드 탭이 뒤늦게 열리면, 그 탭은 이전 브로드캐스트를 놓쳐
화면에 아무것도 안 뜨는 문제가 실제로 있었다(구급1호차·서울대병원 탭이
연결된 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로 열면 그 사건이 안
보임). 이 메시지로 자기가 병원인지 구급차인지, 어느 hpid/apid인지
알려주면 hub가 연결 시점에 관련된 사건들을 즉시 그 소켓에만 돌려준다.

```json
{
  "type": "identify",
  "role": "hospital",
  "id": "S0000001"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"identify"` | 고정값 |
| `role` | `"hospital"` \| `"ambulance"` | 이 소켓이 병원 대시보드인지 구급차 대시보드인지 |
| `id` | string | `role="hospital"`이면 hpid, `role="ambulance"`면 apid |

**응답은 두 가지다(2026-08-11, 순서대로 전송):**
1. **"출력 스키마 6"(`DashboardIdentityInfo`)** — 사건 유무와 무관하게
   즉시 보내는 신원 확인. hub가 이미 인메모리로 갖고 있는 병원/구급차
   레지스트리에서 이름을 바로 조회해 돌려준다(사건이 하나도 없어도, 즉
   통화 전이라도 상단바에 실명이 뜬다). `known=false`면 hub가 그
   hpid/apid를 모른다는 뜻이라 dashboard가 "존재하지 않는 접근 코드"로
   판단할 수 있다.
2. 관련된 사건 각각에 대해, 평소 브로드캐스트와 동일한 형식의
   "출력 스키마 4"(`HubMatchResult`)를 그 소켓에만 개별 전송(따라잡기) —
   새 메시지 포맷을 따로 안 만들어서 dashboard 쪽은 이 부분에 별도 분기가
   필요 없다. `role="hospital"`이면 `HubEngine.get_cases_for_hospital()`로
   그 hpid가 `hospitals[]`에 들어있는 사건 전부를, `role="ambulance"`면
   `HubEngine.get_cases_for_apid()`로 그 apid가 등록한 사건을 찾아 돌려준다.

### 출력 스키마 4: feature/hub → feature/dashboard (통합 매칭 결과)

```json
{
  "type": "match_result",
  "caseId": "case-abc123",
  "patientInfo": {
    "injuryStatus": ["의식 저하", "호흡 곤란"],
    "expectedDiagnosis": "흉부 손상",
    "severityTag": "high",
    "rawTranscript": "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다...",
    "filteredTranscript": "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란."
  },
  "zoneActive": [1, 2],
  "hospitals": [
    {
      "hospitalId": "H001",
      "name": "○○병원",
      "gps": { "lat": 35.1795, "lng": 128.1076 },
      "distanceKm": 2.1,
      "specialtyMatch": {
        "department": "흉부외과",
        "score": 0.82
      },
      "availableBedCount": 12,
      "bedCountUnknown": false,
      "status": "confirmed",
      "etaMin": 6,
      "finalScore": 0.7843,
      "travelMin": 5.4,
      "travelBasis": "eta",
      "demoteReasons": [],
      "bedDataStale": false
    }
  ],
  "source": "rule",
  "ambulanceName": "구급 1호차",
  "ambulanceGpsFallback": false
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"match_result"` (2026-09-28 신설) | 메시지 종류 구분자. `identity_info`와 구분하려고 넣었다 |
| `caseId` | string | 이 매칭 결과가 어느 사건 것인지. dashboard는 여러 사건을 동시에 받을 수 있어 자기가 보는 사건의 caseId로 걸러 써야 한다 |
| `patientInfo.injuryStatus` | string[] | voice가 추출한 부상 상태 목록 (원본 `summary.symptoms` 기반) |
| `patientInfo.expectedDiagnosis` | string | voice가 추출한 예상 병명 (원본 `summary.mechanism` 기반) |
| `patientInfo.severityTag` | `"high"` \| `"medium"` \| `"low"` | 중증도 |
| `patientInfo.rawTranscript` | string | voice의 통화 원문 전체 (`transcript.raw_text` 그대로) |
| `patientInfo.filteredTranscript` | string | voice가 오인식 교정(`corrections.json`)을 거쳐 LLM 입력으로 쓴 텍스트 (`transcript.filtered_text` 그대로). "실시간 음성 필터링" 단계는 voice에서 제거됨 — 필드명만 하위호환으로 유지 |
| `zoneActive` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospitalId` / `name` | string | 병원 식별자 및 병원명 |
| `hospitals[].gps` | object | 병원 위치 좌표 (대시보드 지도 표시용) |
| `hospitals[].distanceKm` | number | GPS 기준 거리 |
| `hospitals[].specialtyMatch.department` | string | 예상 병명에 매칭된 진료과 |
| `hospitals[].specialtyMatch.score` | number (0~1) | 해당 진료과의 수술 전문성 적합도 점수. 이동시간 점수와 가중합되어 최종 순위 산출 |
| `hospitals[].availableBedCount` | number | 실시간 가용 병상 수 |
| `hospitals[].bedCountUnknown` | boolean | `availableBedCount`가 0일 때 그게 **"확인된 만실"(false)**인지 **"미상"(true)**인지. **dashboard는 true면 "0"이 아니라 "미상"으로 표시해야 한다** — 미상을 0으로 보여주면 구급대원이 멀쩡한 병원을 직접 후보에서 빼게 되어, 뺑뺑이를 줄이려는 목적과 정반대가 된다 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].etaMin` | number \| null | 카카오 도로 기준 도착 예상 시간(분, 올림). 키 없음·조회 실패·반경 10km 밖이면 null |
| `hospitals[].finalScore` | number (2026-09-28) | 정렬에 쓴 가중합 점수 |
| `hospitals[].travelMin` / `travelBasis` | number / `"eta"`\|`"estimate"` (2026-09-28) | 순위에 쓴 이동 시간(분)과 출처 — 위 "순위 규칙" 참고 |
| `hospitals[].demoteReasons` | (`"declared_no"`\|`"beds_full"`\|`"rejected"`)[] (2026-09-28) | 순위를 뒤로 내린 이유. 비면 `finalScore` 순서 그대로 |
| `hospitals[].bedDataStale` | boolean (2026-09-28) | 병상 값이 1일 넘게 갱신 안 됐거나 실시간 피드에 없음. 이 경우 0이어도 만실로 보지 않는다 |
| `hospitals[].reliability` | object \| null | info-v2 신뢰도 판정("왜 이 순위인지" 설명용, `group`·`score`·`confidence`·`basis`) — 위 "병원 신뢰도(hospital_score) 반영" 참고 |
| `hospitals[].bedReliability` | object \| null (2026-09-24 신설) | 병상 숫자 자체의 유효 확률(`authority`·`rArrive`·`horizonSec`·`ttlSec`·`modelTag`, source: "ai"). 매칭 시점에 hub가 재계산한 값이고, dashboard가 브로드캐스트 사이에도 초 단위로 감쇠를 직접 그릴 수 있게 곡선 파라미터(`predictedSurvivalSec`·`bornAt`·`sigma`, 2026-09-28)도 같이 실린다. 순위에는 관여하지 않는 설명용 — 위 "병상 정보 신뢰도(bedReliability) 반영" 참고 |
| `hospitals[].bedReliabilityByType` | object \| null (2026-09-28 다필드 확장) | 수술실(`hvoc`)·입원실(`hvgc`)·소아(`hv28`) 등 확장 필드의 유효 확률 환산. 키는 E-Gen 필드명, 값 구조는 `bedReliability`와 동일(같은 horizon) |
| `hospitals[].severeFreshness` | object \| null (2026-09-28 신설) | 매칭된 질환군의 수용가능 신고가 언제 적 것인지(`group`·`value`·`ageSec`·`ageIsMin`·`ruleRemainingSec`, source: "rule"). `ageIsMin=true`면 "최소 X시간 전"으로 표시해야 한다. 순위 불변 — 위 "중증질환 신고 신선도" 참고 |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `ambulanceGpsFallback` | boolean (2026-09-28 신설) | `ambulanceGps`가 실제 구급차 위치가 아니라 기본 좌표(서울시청)로 대체된 값인지. true면 거리·존·순위가 엉뚱한 기준일 수 있다 |
| `ambulanceName` | string \| null (2026-08-11 신설) | 구급차 대시보드 상단바 표시용. `hospitals[].name`(병원명)과 같은 패턴 — 이 사건의 apid를 `register_case()`로 기억해둔 값에서 찾아 구급차 레지스트리(`AmbulanceInfo.name`)를 그대로 채운다. apid를 못 찾으면(통화 시작 신호 없이 직접 `/voice/summary`를 부른 테스트 등) `null`이고, dashboard는 URL의 apid로 대체 표시한다. **병원명과 마찬가지로 그 구급차가 실제로 사건에 등장해야만 채워진다** — 사건이 아예 없는 상태(대시보드를 열었지만 아직 통화가 없음)에서는 아직 이 필드 자체를 못 받으므로 ID 폴백이 계속 보인다 |

### ~~출력 스키마 5: feature/hub → feature/info (병상 갱신 알림)~~ → 2026-08-13 폐지

> 예전엔 `final_approval` 확정 즉시 hub가 `POST /hub/bed-update`
> (`info/app.py`, 포트 5002)로 병상 갱신을 info에 알려 Supabase에 반영시켰다
> (+ 재시도 큐, `hub/data/pending_bed_updates.jsonl`). info가 병원 Supabase
> 자체를 없애면서(E-Gen 실 API로 병상까지 직접 조회 — 조회 전용이라 원래
> 쓰기가 불가능한 곳이었다) 이 왕복이 의미를 잃어 **완전히 제거했다.**
> `info/app.py`, `hub/delivery.py`의 `send_to_info()`/재시도 큐/
> `has_pending_bed_update()`, `hub/schema.py`의 `HospitalBedUpdate` 전부
> 삭제됐다.
>
> 대신 병상 차감은 **hub 혼자 자기 메모리에서 한시적으로만 처리**한다.
> `HubEngine._bed_overlay`(hpid -> `BedHold` 목록)에 `final_approval`마다
> 기록 하나가 쌓이고, `effective_bed_count()`가 조회 시점에 아직 유효한
> 개수만큼만 원본(`HospitalInfo.availableBedCount`)에서 빼서 보여준다.
> 언제 푸는가(2026-10-08, 예전 고정 15분 대체): 확정 + 예상 이동시간 + 20분은 무조건 유지 → 그 뒤 E-Gen 응급실 원값이 확정 당시보다 줄면 해제(줄어든 만큼만) → 끝까지 안 줄면 도착 예상 + 60분에 해제, 수용 완료 시 기준을 실제 도착으로 재설정.
> 15분의 근거였던 "hvidate 갱신 간격 중앙값 5분"은 병원 입력 주기가 아니라 E-Gen의
> 5분 묶음 주기였고, 15분이면 구급차가 도착하기도 전에 차감이 풀렸다. 해제 이유는
> 의사결정 로그 `bed_hold_released`로 남는다. 검증 `test_bed_hold.py`. 예전 대기열 방어
> 로직(`HubEngine.update_hospital_info()`가 재시도 중인 병원은 upsert
> 건너뛰기)도 필요 없어졌다 — 오버레이가 read-time에 적용되므로 info가
> 보내는 최신 원본값을 매번 그대로 덮어써도 안전하다.

### 출력 스키마 6: feature/hub → feature/dashboard (신원 확인 응답, 2026-08-11 신설)

"입력 스키마 9"(자기소개)에 대한 첫 번째 응답. `_send_catchup()`(사건
기반 따라잡기)과 달리, 사건이 하나도 없어도(대시보드를 막 열어서 아직
통화 전인 상태라도) hub가 이미 인메모리로 갖고 있는 병원/구급차
레지스트리(`HubEngine._hospitals`/`_ambulances` — feature/info가 Supabase에서
읽어 보내준 것)에서 이름을 즉시 찾아 돌려준다. "병원 ID: S0000001",
"구급 A0000001호차"처럼 사건 발생 전까지 ID로만 표시되던 문제를 없애기
위해 추가됐다(`app.py`의 `_send_identity_info()`).

```json
{
  "type": "identity_info",
  "role": "hospital",
  "id": "S0000001",
  "name": "서울대학교병원",
  "known": true
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"identity_info"` | 고정값 |
| `role` | `"hospital"` \| `"ambulance"` | 요청받은 `DashboardIdentify.role` 그대로 |
| `id` | string | 요청받은 `DashboardIdentify.id` 그대로 |
| `name` | string \| null | hub가 아는 실제 이름. 모르면(레지스트리에 없으면) `null` |
| `known` | boolean | hub의 레지스트리에 이 hpid/apid가 등록돼 있는지. `false`면 dashboard가 "존재하지 않는 접근 코드"로 판단해 접근을 막는 근거로 쓸 수 있다 |

### `GET /identity` (HTTP, 랜딩 페이지 사전 확인용, 2026-08-11 신설)

처음엔 `/hospital`, `/ambulance` 페이지가 열린 뒤(WebSocket `identify` 이후)에만
존재 여부를 알 수 있어서, 존재하지 않는 코드로 들어가면 그 페이지 전체가
"존재하지 않는 접근 코드입니다" 화면으로 막히는 방식이었다. 코드를 입력하는
**첫 페이지에서, 넘어가기 전에** 바로 확인하고 싶다는 요청에 따라 REST
엔드포인트로 별도 노출했다 — 랜딩 페이지는 아직 어느 사건에도 속하지 않은
1회성 확인만 하면 되니, 지속 연결(WebSocket)을 열었다 바로 닫는 것보다 단순
요청-응답이 더 잘 맞는다. `_resolve_identity()`로 위 `identity_info`와 완전히
같은 조회 로직을 재사용한다.

```
GET /identity?role=hospital&id=S0000001
```

응답(200):
```json
{
  "role": "hospital",
  "id": "S0000001",
  "name": "서울대학교병원",
  "known": true
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `role` | `"hospital"` \| `"ambulance"` | 요청 그대로 |
| `id` | string | 요청 그대로 |
| `name` | string \| null | hub가 아는 실제 이름. 모르면 `null` |
| `known` | boolean | hub의 레지스트리에 등록돼 있는지 |

`role`이 `hospital`/`ambulance`가 아니거나 `id`가 없으면 `400`. dashboard(포트
3000)와 hub(포트 5001)는 다른 origin이라 브라우저 `fetch`가 CORS로 막히므로,
이 엔드포인트만 `Access-Control-Allow-Origin: *`을 붙인다 — 인증이 없는 단순
조회라 전체 허용해도 안전하다고 판단했다.

### 입력 스키마 10: feature/voice로부터 (통화 중 발화 인식, 2026-10-03 신설)

`POST /voice/utterance` — voice가 통화 중 발화 하나를 인식할 때마다 보낸다. hub는 그 구급차(apid) 대시보드 탭에만
`{"type": "call_transcript", apid, caseId, start, end, text, source: "ai"}`로 넘긴다(통화 시연 패널의 실시간 자막).
병원·관제 지도로는 보내지 않고, 상태 파일·의사결정 로그에도 남기지 않는다. 응답 202 `{"delivered": 탭 수}`.

```json
{ "apid": "A0000001", "caseId": "case-abc123", "start": 1.2, "end": 3.4, "text": "62세 남자 환자고요" }
```

### 출력 스키마 7: feature/hub → 관제 지도 (role=monitor, 2026-10-03 신설)

dashboard의 관제 지도(`/map`, 보기 전용 — 병원 대시보드와는 분리돼 있어 병원 대시보드는 첫 페이지에서 접근 코드로 연다).
관제 지도는 `identify`에 `role: "monitor"`(id 아무 값, 보통 `"map"`)로 붙고 아래를 받는다. **통화 전문·활력징후 등
환자 상세는 보내지 않는다** — 그건 요청을 받은 병원 대시보드(role=hospital)만 받는다.

| 메시지 | 언제 | 내용 |
|---|---|---|
| `identity_info` | 연결 직후 | `name: "관제 지도"`, `known: true` |
| `map_overview` | 연결 직후 · 병원 목록 한 주기 끝(`POST /info/hospitals/roster`) · 구급차 정보 갱신 | `hospitals[] {hospitalId, name, gps, emergencyLevel}`, `ambulances[] {apid, name, gps(시뮬레이션 위치 우선), base}`, `simDispatch` |
| `case_overview` | 연결 직후(진행 중 사건 전부) · 매칭 결과가 나갈 때마다 | `caseId, apid, ambulanceName, ambulanceGps, severityTag, zoneActive, zoneBandKm(5), hospitals[] {hospitalId, name, status, distanceKm, zone, notSelected(2026-10-24)}` — 거절 비율로 존이 넓혀지면 바깥 존 병원이 `hospitals`에 새로 들어온다. **2026-10-14** spider 실시간 화면(`/spider/?mode=live`, 같은 monitor 소켓)용 환자 요약 `ktasLevel, expectedDiagnosis, chiefComplaint, requiredDepartment, patient, confirmedBy`(모두 Optional) 추가 — 통화 전문·활력징후·의식은 여전히 안 보낸다 |
| `ambulance_phase`·`ambulance_position` | 연결 직후(구급차 전부) · 이동 중 1초마다 | 출동 시뮬레이션 상태(구급차 탭과 같은 형식, 전 구급차) |
| `case_closed` | 사건이 끝날 때 | 지도에서 그 사건의 요청 표시·존 범위를 지운다 |
| `case_sync` | 연결(재연결) 직후 따라잡기 끝(모든 역할 공통, 2026-10-03) | `caseIds` — 지금 진행 중인 사건. 탭은 이 목록에 없는 사건을 지운다(hub 재시작 등으로 그 사이 끝난 사건). 구급차 탭은 매칭 결과 전(출동·통화 중) 사건도 포함 |

- `GET /identity`는 여전히 `hospital`/`ambulance`만 받는다(관제 지도는 사전 확인이 필요 없다)
- 검증: `python test_monitor_map.py`(실제 로그를 건드리지 않게 임시 경로로 돌린다)

### 입력 스키마 11: feature/dashboard로부터 (통화 요약 확인·수정 — Override, 2026-10-13 신설)

WebSocket `{"type": "patient_override", "caseId", ...고친 칸}` — 칸 정의와 규칙은 CLAUDE.md "데이터 포맷 및 흐름 > 4".

- **받는 소켓**: 그 사건을 연 구급차(`role: "ambulance"`, `engine.get_case_apid(caseId)`와 같은 apid)만. 병원·관제·다른 구급차는
  `action_refused`(reason `not_owner`). 일시정지 중이면 `paused`. 사건이 없으면 `no_case`
- **처리**(`HubEngine.apply_patient_override`, 작업 스레드): 고친 값을 사건의 통화 요약(`_case_voice`)에 덮어써서 60초 재계산·존 확장도
  고친 값으로 돈다. 순위 칸(예상 병명·KTAS·필요 진료과)이 바뀌고 이송 확정 전이면 `process_voice_summary`로 재매칭(넓힌 존·병원 승인 유지),
  아니면 `patientInfo`만 교체. 확인 상태(`_case_override`: 확인 시각 + 칸별 `OverrideRecord`)는 `_patient_info()`가 매번 찍고, 상태 파일에
  저장·복구된다. 같은 칸을 여러 번 고쳐도 `ai`는 처음 AI 값, AI 값으로 되돌리면 그 칸은 빠진다. 새 통화 회차(`add_call_summary`)는 초기화
- **출력**: 평소 매칭 결과 전송(`_send_to_dashboard`) — 구급차 탭·후보 병원 탭·관제 요약. `PatientInfo.confirmedBy`·`confirmedAt`·`overrides`
- **로그**: `patient_override` `{caseId, confirmedOnly, rematched, caseConfirmed, changes: [{field, before, after}]}`
- 검증: `python test_patient_override.py`(엔진 9개 검사, 임베딩 없이). 실서버 E2E(소켓 4개 — 구급차·다른 구급차·병원 2곳)로 소유자 검사·
  병원 2곳 갱신본 수신·KTAS 3→2 재정렬·로그 기록을 확인했다(2026-10-13)

## 결과 저장 및 전송 방식 (`delivery.py`)

로컬 파일 저장은 항상 하고, 실시간 dashboard 전송은 `app.py`가 처리한다.

- **파일명 규칙**: feature/voice가 실제로 만드는 파일이 `<stem>_call_summary.json`
  형태이므로(예: `DrRomantic3v3_call_summary.json`), hub의 결과물도 같은 stem을
  이어받아 `<stem>_hub_match_result.json`으로 저장한다. 입력과 출력이 파일명만으로
  짝지어지기 때문에, 여러 사건이 동시에 처리돼도 결과 파일이 서로 덮어써지거나
  섞이지 않는다 (ERD에는 없는, 사건 단위로 voice↔hub를 연결할 임시 상관관계 키다).
- **저장 위치**: 테스트(`run_match.py`)는 `data/test/output/<stem>_hub_match_result.json`,
  실서버(`app.py`)는 `data/live/output/live_<시각>_hub_match_result.json`(2026-09-28 분리 —
  예전엔 둘이 같은 폴더에 섞였다)
- **`deliver()`는 로컬 저장 전용으로 남겨뒀다**: `save_local()`이 로컬 저장을
  담당하고, `send_to_dashboard()`는 원래 계획대로라면 `requests.post(...)`를
  채울 자리였는데, 실제 전송 채널이 살아있는 WebSocket 연결(dashboard가
  `new WebSocket()`으로 접속)이라 그 연결 객체를 쥐고 있는 `app.py`의
  `/voice/summary` 핸들러에서 직접 `ws.send(...)`로 처리한다 (`app.py`의
  `_send_to_dashboard()` 참고). `send_to_dashboard()` 자체는 로그만 남기는
  자리로 남아 있다.
- ~~**`feature/info`로 보내는 병상 갱신도 같은 패턴**: `deliver_bed_update()`가...~~
  → **2026-08-13 삭제.** `deliver_bed_update()`/`save_local_bed_update()`/
  `send_to_info()` 전부 없앴다 — 위 "출력 스키마 5" 참고. 병상 차감은 이제
  파일로도 안 남기고 `HubEngine._bed_overlay`(메모리)에만 있다가 TTL이
  지나면 조용히 사라진다.
- **`send_rejection_to_info()` (2026-09-10 추가, 09-28~29 확충)**: `app.py`의
  `_handle_dashboard_action()`이 `hospital_reject`일 때 `_rejection_payload()`로
  `{hospitalId, caseId, timestamp, reasonCode}` + 사건 캐시가 있으면
  `severity`·`diseaseGroup`·`declaredAtRequest`에 더해 **결정 시점 스냅샷**
  (`availableBedCountAtRequest`·`bedCountUnknownAtRequest`·`bedDataStaleAtRequest`·
  `travelMinAtRequest`·`finalScoreAtRequest`·`bedAuthorityAtRequest`·
  `bedRArriveAtRequest` — G2 라벨·확률 운영 검증 재료)를 만들어 `HUB_REJECTION_URL`
  (기본 `http://127.0.0.1:5003/hub/rejection`)로 POST한다. **무응답도 기록한다**:
  사건이 결말에 이르는 두 시점(`final_approval` 확정 / 확정 없이
  `HUB_UNRESOLVED_TIMEOUT_MIN` 기본 120분 유휴 시 sweep)에 pending 후보들을
  `reasonCode=NO_RESPONSE`로 일괄 전송하며, `reachedAtBroadcast`(도달 이력 —
  미도달=보급 지표 / 도달했는데 무응답=응답성 지표)·`hospitalDashboardConnected`·
  `caseFinalized`(미결 종료 구분)를 실어 소비 축을 분리한다(CLAUDE.md 소비 지침
  참고 — 무응답은 수용성 판정에 쓰지 않는다). fire-and-forget —
  수신구(`hospital_score/ingest.py`, 별도 기동하는 선택적 서버)가 안 떠 있어도
  예외를 삼키고 계속한다. 병상 갱신과 달리 이건 E-Gen이 아니라 info가 쓰기
  가능한 자체 운영 로그라 왕복이 성립한다. 회귀 테스트: `test_rejection_forward.py`.
- 데모 단계에서는 통신을 붙인 뒤에도 로컬 저장을 계속 같이 한다 (감사·재현 목적).
  실제 사업화 단계에서는 이 부분을 재검토해야 한다.

## 의사결정 로그 (`decision_log.py`)

CLAUDE.md "보안 및 개인정보 원칙"의 "모든 의사결정 로그는 타임스탬프 + SHA-256
해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다"를 구현한다.

- `hub_engine.py`가 매칭 결과(`process_voice_summary`)를 만들거나 승인 액션
  (`apply_approval_action`)을 처리할 때마다 `decision_log.log_decision()`을 호출해
  `data/logs/decision_log.jsonl`에 한 줄씩 append한다 (기존 줄은 절대 수정하지 않음)
- 기록 하나는 `{timestamp, eventType, payload, prevHash, hash}` 형태이고, `hash`는
  `timestamp+eventType+payload+prevHash`를 정렬된 JSON으로 직렬화한 값의 SHA-256이다.
  **`prevHash`는 바로 앞 기록의 `hash`다(해시 체인, 2026-09-28).** 예전엔 줄마다 자기
  내용만 해시해서, 내용을 고친 뒤 해시를 다시 계산하거나 줄을 지우거나 순서를 바꾸면
  검증을 통과했다. 지금은 중간 한 줄만 건드려도 그 뒤 줄의 `prevHash`가 어긋난다.
  한계: 파일 **끝부분**을 잘라내는 것은 체인만으로는 못 잡는다(마지막 hash를 따로 보관해
  대조해야 함). 쓰기는 락으로 직렬화한다(여러 스레드가 동시에 쓰면 체인이 갈라짐)
- 체인 이전(`prevHash` 없는) 기존 기록은 예전 방식으로 검증하고, 체인이 시작된 뒤에
  `prevHash` 없는 줄이 끼어 있으면 위변조로 본다
- 매칭 결과(`hub_match_result`), 주기적 재계산에서 순위·상태·병상이 바뀐 경우
  (`hub_match_refreshed`), 승인 액션을 기록한다
- `decision_log.verify_log()`로 로그 파일 전체를 검증할 수 있다 — 위변조 여부와
  검사한 줄 수를 반환한다 (`run_match.py` 맨 마지막에서 실행함)
- **통화 전문은 지문으로만 남긴다 (2026-09-10)**: `hub_match_result` 항목의
  `patientInfo.rawTranscript`/`filteredTranscript`는 `_redact_transcript()`가
  `{"sha256", "chars"}`로 치환한 뒤 기록한다. 원본은 feature/voice의 로컬 파일에
  이미 보존되고, 위변조 방지 append-only 파일(절대 지우지 않음)에 개인정보 섞인
  자유 텍스트를 영구 중복 적재하지 않으려는 것이다. 구조화 필드(severity·
  expectedDiagnosis·injuryStatus·병원 순위)는 그대로라 "왜 이 순위인지" 감사는
  그대로 가능하고, 지문이 있어 voice 원본과 대조도 된다. dashboard로 나가는
  `HubMatchResult` 자체는 이 치환을 거치지 않는다(전문 표시 기능 유지).

## 실행 방법

```bash
cd hub
conda create -n rookie_hub python=3.11
conda activate rookie_hub
pip install -r requirements.txt
```

**테스트 데이터로 매칭 엔진 실행** (`data/test/`의 병원 정보·voice 요약 샘플을 사용)
```bash
python run_match.py
```
1단계(GPS+병원 정보로 존 기반 후보 리스트 생성)와 2단계(voice 정보 반영 재처리) 결과를
각각 터미널에 출력하고, 최종 결과는 `data/test/output/DrRomantic3v3_hub_match_result.json`에도
저장한다 (파일명 규칙은 아래 "결과 저장 및 전송 방식" 참고).

**HTTP 레이어 검사** (앱을 import해 실제 경로를 탄다, 상태 파일은 임시 폴더를 쓴다)
```bash
python test_app_background.py     # 202 응답·비동기 매칭·주기적 재계산·상태 저장/복구
python test_rejection_forward.py  # 거절 사유 → info 거절 로그 중계
```

**서버 실행**
```bash
python app.py        # 포트 5001, debug 꺼짐
HUB_DEBUG=1 python app.py   # 개발 중에만 — 코드 리로더·예외 화면 켜짐
```

### 서버 운영 동작 (2026-09-28)

| 동작 | 내용 | 환경변수 |
|---|---|---|
| 비동기 매칭 | `/voice/summary`는 검증만 하고 **202** `{"status":"accepted","caseId"}`로 바로 답한다. 매칭(임베딩 + 카카오 호출)은 작업 스레드 1개에서 순서대로 돌고, 결과는 WebSocket으로 나간다. voice는 응답 본문을 쓰지 않고 성공 여부만 본다(전송 타임아웃 10초를 넘길 여지 제거) | — |
| 주기적 재계산 | 진행 중인 사건을 같은 환자 정보·같은 zone으로 다시 계산해, 병상·ETA·병상 신뢰도·순위가 **달라진 사건만** 대시보드에 다시 보낸다. 카카오 ETA는 5분 캐시라 호출이 주기만큼 늘지 않는다. 이송 중 순위가 저절로 바뀔 수 있다 | `HUB_REFRESH_INTERVAL_SEC` (기본 60, 0이면 끔) |
| 상태 저장·복구 | 병원·구급차 레지스트리, 승인 상태, 병상 오버레이, 사건(구조화 요약·결과), voice 주소를 5초마다(변경 있을 때만) 저장하고 뜰 때 복구한다. 재시작 뒤 info의 다음 전송(최대 30분)까지 병원이 0곳이던 문제를 없앤다. **통화 원문은 저장하지 않는다** — 복구된 사건은 원문 자리에 안내 문구가 뜬다. 종료(Ctrl+C·SIGTERM) 때도 저장한다 | `HUB_STATE_PATH` (기본 `data/state/hub_state.json`), `HUB_PERSIST_STATE=0`이면 끔 |
| 스레드 안전 | 엔진 상태는 락 안에서만 읽고 쓰되, 임베딩·카카오 호출은 락 밖에서 한다(그동안 승인 액션이 막히지 않게). 소켓 집합·전송, voice 주소, 의사결정 로그 쓰기도 락으로 보호한다 | — |
| debug | 기본 꺼짐. 켜면 코드 리로더가 파일 변경마다 재시작해 인메모리 상태가 날아가고 예외 화면이 외부에 노출된다 | `HUB_DEBUG=1` |
| 백그라운드 시작 | 위 재계산·저장·방치 사건 정리 루프는 `start_background()`가 띄운다. `start-all.sh`가 예전엔 `app.app.run()`만 불러 **실서버에서 이 루프들이 한 번도 돌지 않았다**(2026-10-01 수정) | — |
| 역할별 전송 | 매칭 결과는 그 구급차(apid) 탭과 후보에 오른 적 있는 병원(hpid) 탭에만 보낸다(2026-10-01). identify 전 소켓은 따라잡기로 받는다 | — |
| 방치 사건 닫기 | 확정 없이 120분 활동이 없으면 무응답(`NO_RESPONSE`)을 기록한 뒤 사건을 닫고 `{"type":"case_closed"}`를 보낸다 — 대시보드가 카드를 지운다(2026-10-01) | `HUB_UNRESOLVED_TIMEOUT_MIN` |
| 현장 후보 | 통화 시작(출동 시뮬레이션이면 현장 도착) 때 거리순 후보를 `{"type":"scene_candidates"}`로 그 구급차 탭에만 보낸다(규칙 기반, 환자 정보 전이라 병원 탭엔 안 보냄). 2026-10-03부터 후보마다 `bedReliability`(병상 신뢰도, AI — 매칭 결과와 같은 `BedReliabilityMatch` 형태, 없으면 null)가 붙고, **첫 연락 추천** 한 곳에 `firstCallRecommended: true`가 표시된다 — 빈 병상이 실제로 확인됐고(미상·확인된 만실·1일 넘은 값 제외) 도착 시점 유효 확률(rArrive)이 가장 높은 병원, 동률이면 가까운 쪽. 순위(거리순)·finalScore에는 여전히 신뢰도를 안 쓴다 — 첫 통화 상대 제안은 틀려도 존 전체 동시 전달이 뒤를 받치는 비용 낮은 결정이라 여기만 확률을 직접 쓴다. 추천은 `first_call_recommended`로 의사결정 로그에 남아, 나중에 승인·거절 로그와 대조해 적중률(추천 병원이 실제로 수용했는가)을 셀 수 있다 | — |
| 병원 목록 동기화 | info가 한 주기 끝에 `POST /info/hospitals/roster {"hospitalIds": [...]}`를 보내면 목록에 없는 병원을 뺀다. 진행 중 사건 후보는 보류, 목록이 절반 아래로 급감하면 부분 조회 실패로 보고 안 뺀다 | — |
| 구급차 목록 동기화 | info가 구급차를 `POST /info/ambulances/batch {"ambulances": [...]}`로 한 번에 보내고(관제 지도 전송 한 번, 형식 틀린 한 대는 `rejected`) 이어서 `POST /info/ambulances/roster {"apids": [...]}`를 보내면 목록에 없는 구급차를 레지스트리·시뮬레이션·voice 주소에서 뺀다(2026-10-04). 진행 중 사건·출동 중 구급차는 보류, 목록이 비었거나 절반 아래로 급감하면 안 뺀다. 한 대씩 받는 `POST /info/ambulances`도 그대로 | — |
| 출동 시뮬레이션 | 아래 "출동 시뮬레이션" 절 | `HUB_SIM_DISPATCH=1` |

### 출동 시뮬레이션 (2026-10-01, 시연용 가짜 위치)

`start-all.sh`가 기본으로 켠다(= `HUB_SIM_DISPATCH=1`, 2026-10-03부터 기본값 — 실제 구급차 GPS 수신 경로가 없어서다. 끄려면 `--no-sim-dispatch`). 구급차 대시보드의 [이동]을 누를 때만
구급차가 움직인다(`ambulance_sim.py`, 설계는 `documents/1001v1_0134_...`).

```
idle ─[이동]→ dispatching ─도착→ on_scene ─이송 승인→ transporting ─도착→ at_hospital ─수용→바로→ returning ─도착→ idle
                                    └─[현장 종료]→ returning          │ 수용 불가
                                                                       └→ rerouting(그 자리 대기) ─이송 승인→ transporting
   (returning 중 [이동] = 재출동, rerouting에서 [현장 종료]도 가능)    at_hospital은 병원이 결과를 고를 때까지 기다린다
```

- 환자 발생 위치: 기지(Supabase 등록 좌표)에서 자동차로 5~12분 걸리는 지점 30~50곳을 처음 한 번 카카오
  다중 목적지 ETA로 골라 `data/sim/incident_points_<apid>.json`에 저장(이후 호출 0회)
- 구간마다 도로 경로 1회. 화면 시간은 출동 5초(`HUB_SIM_TRIP_SEC`), 병원 이송 30초(`HUB_SIM_TRANSPORT_SEC`), 기지 복귀 30초(`HUB_SIM_RETURN_SEC`)다:
  가까워도 멀어도 그 시간에 도착하도록 구간마다 배속을 정한다(먼 곳일수록 빠름). 남은 ETA는 실제 도로 기준,
  배속은 위치 메시지 `speedup`으로 화면에 표시. 예전(2026-10-01)엔 기본 5배속에 출동·이송 90초·복귀 30초 상한이었다
- **정지·상황 재개**(2026-10-03): `dispatching`·`on_scene`·`transporting`에서 `sim_pause`하면 위치·남은 시간·진행이
  그 자리에 멈추고(`paused: true`), `sim_resume`하면 멈춘 자리에서 이어 간다. 정지 중에도 통화·병원 승인·이송 승인은
  받으며, 정지 중 이송 확정되면 경로만 잡아 두고 재개 때 출발한다. 정지 중 [현장 종료]는 정지를 풀고 복귀
- **출동 위치 지정**(2026-10-01): `dispatch`에 `target {lat,lng}`·`targetMode("address"|"map")`를 주면 그곳으로, 없으면 무작위.
  대시보드는 주소 검색(`GET /geocode?query=&apid=` — hub가 카카오 장소·주소 검색을 대신 부르고 기지에서의 예상 분을 붙임,
  서버 전체 1분 `HUB_GEOCODE_PER_MIN`(30)회 제한·5분 캐시)과 지도 클릭으로 고른다. **주소 글자는 hub로 안 보내고**, 검색어는
  저장·로그하지 않으며, 의사결정 로그엔 약 1km로 뭉갠 좌표만 남긴다(집 주소일 수 있음)
- **좌표 → 주소**(2026-10-27): `GET /geocode/reverse?lat=&lng=` → `{"address": "서울특별시 중구 세종대로 110 (서울특별시청)"}`.
  아이패드 인계확인서(출동 및 처치 기록지)의 "출발지 주소"가 좌표 대신 실제 주소를 적으려고 부른다 — 카카오 키를 화면에
  두지 않으려고 hub가 대신 부르고(`routing.reverse_geocode`, 도로명 우선·건물명 괄호), `/geocode`와 **같은 분당 한도**와
  5분 캐시를 쓴다. 좌표는 캐시 키로만 쓰고 저장·로그하지 않는다(사고 현장 위치). 키가 없으면 `address: null`
- 위치는 레지스트리 GPS를 덮어쓰지 않고 조회 시점에 얹는다 — info의 30분 재전송과 안 부딪히고, 재시작하면 기지 대기
- 통화 시작은 `on_scene`이고 caseId가 같을 때만 voice로 중계한다(아니면 `call_start_refused`)
- dashboard ↔ hub 메시지
  - 받음: `{"type":"dispatch"|"scene_end"|"sim_pause"|"sim_resume","apid","caseId","timestamp"}`
    (`sim_pause`·`sim_resume`은 apid로 구급차를 가리고 caseId는 로그용)
  - 보냄: `ambulance_phase`(상태 바뀔 때·정지/재개 때, 경로 포함) · `ambulance_position`(움직이는 동안 1초마다) — 모두
    `simulated: true`. 그 구급차 탭 전부 + 이송 중·병원 도착일 때만 확정 병원 탭. `identity_info.simDispatch`
- 의사결정 로그: `sim_dispatch_enabled`, `ambulance_dispatched`/`dispatch_refused`, `ambulance_phase`, `case_closed`,
  `sim_paused`/`sim_resumed`/`sim_control_refused`
- 구급차 대시보드는 hub가 보낸 시뮬레이션 상태의 `caseId`를 그 구급차의 현재 사건으로 쓴다(2026-10-03) — 탭에 기억한
  caseId만 쓰던 때는 브라우저를 껐다 켜면 [현장 종료]·통화 시작이 엉뚱한 caseId로 나가 hub가 거부했다
- 검증: `python ambulance_sim.py`(상태 머신·보간), `python test_dispatch_sim.py`(앱 레이어 전체 흐름)

## 폴더 구조

```
hub/                        (저장소 루트의 .gitignore, CLAUDE.md는 브랜치 공통이라 여기 포함 안 됨)
├── DEVELOPMENT.md
├── README.md
├── requirements.txt
├── schema.py            입출력 pydantic 모델 (voice/info/dashboard 스키마와 1:1 대응)
├── geo.py                GPS 거리 계산, 존(Zone) 분류·확장 판단
├── specialty_matcher.py  임베딩 기반 예상 병명 ↔ 진료과 매칭
├── scoring.py             이동시간·진료과 점수 가중합, 전문성·등급 가산(분), 순위 결정
├── ambulance_sim.py       구급차 출동 시뮬레이션(시연용 가짜 위치) 상태 머신·경로 보간
├── hub_engine.py         2단계 매칭 오케스트레이션 + 승인 액션 반영(상태 보관 + 재처리)
├── decision_log.py       의사결정 로그 (타임스탬프 + SHA-256 해시, 위변조 검증 가능)
├── delivery.py           결과 저장 + dashboard로의 실제 통신 — 파일명을 voice 입력에서 이어받음
│                         (info로의 병상 갱신 전송은 2026-08-13 삭제됨)
├── run_match.py          테스트 데이터로 엔진을 실행하는 CLI
├── test_app_background.py   app 레이어 검사 (비동기 매칭·재계산·상태 저장)
├── test_rejection_forward.py 거절 사유 중계 검사
├── test_dispatch_sim.py   출동 시뮬레이션 앱 레이어 검사
└── data/                 (.gitignore 대상)
    ├── test/
    │   ├── hospitals/                        병원 정보 샘플 (feature/info 역할, H001~H004.json)
    │   ├── DrRomantic3v3_call_summary.json    voice 요약 샘플 (feature/voice 역할)
    │   └── output/
    │       └── DrRomantic3v3_hub_match_result.json  매칭 결과 (delivery.py가 생성)
    ├── live/output/      실서버 매칭 결과 사본 (app.py)
    ├── state/hub_state.json  재시작 복구용 상태 (app.py, 통화 원문 제외)
    ├── sim/              출동 시뮬레이션 환자 발생 위치 후보 (ambulance_sim.py)
    └── logs/
        └── decision_log.jsonl   의사결정 로그 (decision_log.py가 생성, append-only, 해시 체인)
```

## 코드 구조 — 모듈 간 관계

```
run_match.py  (테스트 실행 진입점)
   │  HospitalInfo · VoiceCallSummaryMessage를 JSON에서 읽어들임
   ▼
hub_engine.py  (HubEngine — 병원 정보 상태 보관 + 2단계 매칭 오케스트레이션)
   │
   ├─→ schema.py             모든 모듈이 공유하는 데이터 형태 (다른 모듈에 의존하지 않음)
   ├─→ geo.py                거리 계산 · 존 분류/확장 판단 (다른 모듈에 의존하지 않음)
   ├─→ specialty_matcher.py  진료과 임베딩 매칭 (다른 모듈에 의존하지 않음)
   ├─→ scoring.py            점수 가중합 · 순위 결정 (다른 모듈에 의존하지 않음)
   └─→ decision_log.py       매칭 결과·승인 처리마다 로그 기록 (다른 모듈에 의존하지 않음)

run_match.py
   │  hub_engine.py가 만든 HubMatchResult를 그대로 넘김
   ▼
delivery.py  (로컬 저장 + 자리만 준비된 통신, schema.py에만 의존)
```

- **`schema.py`가 가장 아래 계층**이다. 나머지 5개 파일이 전부 이 파일의 타입을 가져다
  쓰지만, `schema.py` 자신은 아무것도 import하지 않는다 — 데이터 "형태"만 정의하고
  로직은 하나도 없기 때문.
- **`geo.py` / `specialty_matcher.py` / `scoring.py`는 서로를 전혀 모른다.** 셋 다
  `hub_engine.py`에서만 쓰이고, 서로 독립적이라 하나를 통째로 바꿔도(예: 진료과 매칭
  모델을 다른 임베딩 모델로 교체) 나머지 둘과 `hub_engine.py`의 흐름 자체는 안 바뀐다.
  CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리해서 구현한다" 원칙을 그대로
  코드 구조에 반영한 것이다.
- **`hub_engine.py`가 유일하게 저 세 계산 모듈을 전부 알고 조립하는 곳**이다. "1단계:
  GPS로 존 후보 생성 → 2단계: voice 도착 시 진료과 매칭+스코어링으로 재처리"라는
  실제 업무 흐름이 여기에만 있다.
- **`run_match.py`는 `hub_engine.py`와 `schema.py`만 알면 된다.** geo/specialty_matcher/
  scoring 내부 구현을 몰라도 `HubEngine`을 통해 실행할 수 있다.
- **`delivery.py`는 매칭 로직(`hub_engine.py`)과 완전히 분리돼 있다.** `schema.py`만
  알고, "결과를 어떻게 내보낼지"(로컬 저장/통신)만 책임진다. 나중에 Flask 통신을
  붙일 때 이 파일만 고치면 되고, `hub_engine.py`는 건드릴 필요가 없다.
- **`decision_log.py`도 매칭 로직과 분리돼 있다.** `hub_engine.py`가 매칭 결과를
  만들거나 승인 액션을 처리할 때마다 호출만 하고, "어떻게 기록·검증할지"는
  전적으로 이 모듈이 책임진다.

> 위 다이어그램은 "코드가 무엇을 import하는지"(의존 관계)이고, 실제 운영 중 데이터가
> 오가는 순서("데이터 포맷 및 흐름" 섹션에서 설명한 voice/info → hub → dashboard)는
> 별개의 축이다. 예를 들어 `geo.py`는 다른 모듈에 의존하지 않지만, 실제로는
> feature/info의 GPS 데이터가 들어와야 의미가 생긴다.

## 알려진 제약사항 / TODO

- 존 확장 임계값(`REJECT_RATIO_THRESHOLD` = 0.4, 2026-10-01부터 **존 안 후보 전체 대비** 거절 비율), 스코어링 가중치(`W_SPECIALTY`/`W_DISTANCE`),
  이동시간 반감기(`TRAVEL_HALF_LIFE_MIN`)는 `scoring.py`/`geo.py`에 상수로 박아뒀다 — 실제 운영 데이터 없이 정한 값이라 테스트하며
  조정 필요
- 구급차 GPS는 실시간이 아니라 `AmbulanceInfo`에 고정 저장된 값이다. 시연에서는 출동
  시뮬레이션(`start-all.sh` 기본값)이 가짜 위치를 얹는다. 진짜 실시간 GPS(브라우저 geolocation 등)
  수신 경로는 아직 없다
- **WebSocket에 인증이 없다.** 주소를 아는 누구나 접속해 승인 액션(`final_approval` 포함)과 출동
  명령을 보낼 수 있다. 시연 범위에선 허용하되, 공개 운영 전에는 Cloudflare Access 같은 로그인을
  도메인 앞에 두거나 소켓별 토큰을 붙여야 한다
- voice 자가등록(`/voice/register`)이 온 apid의 `AmbulanceInfo`가 아직 없으면(즉
  feature/info가 그 구급차 정보를 아직 안 보냈으면) 409로 거부하고 재시도 큐 없이
  그냥 실패한다 — voice 쪽에서 재시도 로직을 두거나, info가 먼저 뜨는 걸 운영 순서로
  못박아야 한다
- ~~브라우저 마이크 오디오는 받기만 하고 버린다~~ → 2026-10-03 중앙 voice가 등록돼 있으면 STT 입력으로 넘긴다
  ("중앙 voice와 휴대폰 통화"). 중앙 voice는 모델 하나를 통화들이 차례로 나눠 써서, 동시 통화가 많으면 인식이
  밀린다(시연 규모 3대는 문제없음)
- 휴대폰 통화는 연출이다 — 병원과 양방향 음성 연결은 없다
- **거절 로그 수신구는 별도로 띄워야 한다.** hub는 `hospital_reject`마다
  `POST /hub/rejection`으로 사유를 중계하지만(2026-09-10 배선 완료), 받는 쪽
  (`hospital_score/ingest.py`, 포트 5003)은 info의 상시 프로세스와 별개라
  `python -m hospital_score.ingest`로 직접 실행해야 로그가 쌓인다. 안 띄우면
  hub는 조용히 넘어가고 그 기간의 거절 로그는 사라진다(소급 생성 불가)

## 추가사항


### 통화 전 추천·미응답 재시도 (2026-11-01)

구급대 소켓은 `first_call_request`에 `caseId`, `ktas`(1~5), 선택적으로
`noAnswerHospitalId`를 보낸다. 본인 사건만 허용하고 `scene_candidates`로 응답한다.
`preKtas`, `callAttempts`(미응답 병원 ID), `firstCallExhausted`와 병원별
`firstCallReason`/`firstCallRecommended`를 제공한다.

일반 질환 기준 기존 spider KTAS 적합도를 먼저 적용한다. 이동시간에 경증(K4·5)의
상급 센터 보존 비용(등급 2 초과 단계당 5분), 다른 사건의 통화 중·응답 대기·이송 중
건당 5분을 더해 정렬한다. 임상 검증 전 규칙이며 예약/수용 보장이 아니다.
미시도 후보가 없으면 최대 zone 10(50km)까지 넓힌다. 미응답은 수용 거절로 바꾸지
않으며 KTAS 변경·소켓 재접속에도 사건 캐시에 유지한다(서버 재시작에는 유지하지 않음).
iPhone은 현장 통화 대기 중 15초마다 새 추천을 요청하며, 이력에서 수동 재시도가 가능하다.


### 전화 연결 대기와 수용 판단 분리

iPhone 전화 요청은 `call_connection`(operation=request, caseId, hospitalId, requestId,
timestamp)으로 전송한다. hub는 ringing을 방송하고 이때는 voice·마이크를 시작하지 않는다.
관제 상단 「전화 응답」(answer) 이후 calling으로 바뀌어 녹음을 시작한다. 「전화 미응답」
(no_answer)은 녹음 없이 요청을 종료하고 다음 후보를 추천한다. iPhone에서도 연결 대기 중
「미응답 · 다음 병원」이나 「취소」를 선택할 수 있다. 연결 이후에는 미응답 버튼이 없다.
요청 ID로 취소 후 늦은 응답·중복 응답을 무시하고, 요청 기기 소켓이 끊기면 대기를 취소한다.
관제의 병원 승인 pending 표시는 「수용 판단 대기」로 구분한다.
새 흐름은 hub·관제·iPhone을 함께 업데이트해야 한다. 실제 전화망 수신 감지가 아닌 시연 제어다.


### 사건 간 첫 통화 추천 조정 (시뮬레이션 가능)

`first_call.Coordinator`가 hub에서 추천 계산과 의향 반영을 직렬화한다.
추천 의향은 45초(1분 상당), 전화 요청/통화 중은 2분, 수용 판단 대기는
한 사건의 후보 전체에 합계 1분을 나누고, 이송 확정은 6분 상당을 반영한다.
동일 사건·병원에 여러 상태가 겹치면 가장 강한 상태만 계산한다.
시뮬레이터의 남은 도로 ETA가 있으면 도착 예상 차이 15분 초과인 확정 이송의
가산을 1.5분으로 낮춘다. ETA 미상은 6분을 유지한다.
중증(K1·2)은 총 가산 최대 2분, K3은 5분, K4·5는 10분이다.
모든 값은 임상 검증 전 시연용 규칙이며 실제 예약·수용 차단이 아니다.
통화 요청/통화 중 선택은 유지하고 대기 중 새 추천은 15초 주기로 갱신한다.
추천 의향은 취소·사건 종료·만료 시 제거한다. 재시작 시 초기화된다.

재현: `python hub/demo_coordination.py` — 동일 조건 6건, 거리만 고려 A=6건과
규칙 조정 A/B/C=각2건 비교. 합성 사례이며 실서비스 성능 증명은 아니다.
`python hub/test_coordination.py`, `python hub/test_first_call.py`로 부하 중복 방지,
도착시간, 중증 상한, 두 구급차의 실제 hub 추천 분산을 검사한다.
실제 관제 시연은 여러 구급대를 출동시켜 같은 KTAS를 선택한다. 추천 이유의
진행 부하와 병원 선택을 비교하고, 이송 확정 뒤 후속 사건의 추천 변화를 확인한다.
현재 위치/ETA는 시뮬레이터 입력을 사용하며 실제 GPS 어댑터는 별도다.
