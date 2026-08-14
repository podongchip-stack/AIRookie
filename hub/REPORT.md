# 보고서 작성용 정리 — feature/hub (현재 구축 방식 기준)

이 문서의 용도: 보고서를 쓸 때 꺼내 쓰는 재료 모음이다. `hub/README.md`(브랜치
정문)와 겹치는 내용도 있지만, 여기서는 **수식·페이로드 실물·실측 근거를 한
자리에 모으는 것**이 목적이다.

**중요한 전제 하나**: `Hospital_inform/hospital-info-interface-proposal.md`가
제안한 "표준 코드 정확 대조" 방식은 **아직 hub에 반영되지 않았다.** 이 문서는
**현재 실제로 돌아가는 방식**(진료과 임베딩 유사도 매칭 + hospital_score
declared_no 하드 데모션)을 기준으로 정리했다.

숫자는 전부 코드와 대조해 확인한 값이며, 재현 명령을 함께 적었다.

작성: 2026-08-14 · 대상 브랜치 `feature/hub` (develop 병합 기준)

---

## 0. 프레이밍 — hub가 실제로 하는 일

voice·info 두 브랜치는 hub로 직접 통신하지만 dashboard로는 보내지 않는다.
**dashboard와 직접 통신하는 유일한 브랜치가 hub**이고, 그래서 voice의 자유
텍스트 진단명과 info의 병원 목록을 "어떻게 짝지을 것인가"라는 판정을 hub가
전담한다.

```
voice : LLM 자유 텍스트(expectedDiagnosis)
                │
                ▼
hub   : [임베딩 유사도] 진료과 후보와 코사인 유사도 계산 (결정적, 임계값 없음)
        [규칙]         거리 점수, zone 분류/확장, 최종 가중합
        [규칙]         hospital_score declared_no → 순위 맨 뒤 (2026-08-14 추가)
                │
                ▼
dashboard : hospitals[] (specialtyMatch.score, reliability 그대로 노출)
```

순위 결정은 **두 층**이다 — 하드필터(제외)는 없고, 소프트 스코어링(가중합)과
정렬 규칙(데모션)만 있다.

| 층 | 방식 | 대상 |
|---|---|---|
| 소프트 스코어링 | 가중합 (`0.6×진료과 + 0.4×거리`) | 모든 후보의 1차 순위 |
| 정렬 규칙 (2026-08-14 추가) | hospital_score 계층이 `declared_no`면 맨 뒤로 | finalScore와 무관하게 적용 |

진료과 매칭이 실패해도(유사도가 낮거나 병원에 진료과 정보가 없어도) 병원을
후보에서 제외하지 않고, 거리 점수만으로 순위에 남긴다("뺑뺑이 방지"가 목적이라
잘못 걸러내는 게 더 위험하다는 판단, `specialty_matcher.py` docstring 참고).

**왜 hospital_score를 가중합이 아니라 정렬 규칙으로만 쓰는가.** 가상 worktree에서
민감도 분석을 실제로 돌려본 결과, declared_no(0.2)가 unknown_bare(0.4) 같은 다른
계층을 절대 못 앞지르게 완전히 보장하려면 신뢰도 가중치가 최소 73~83%까지
필요했다 — 그 지점에서는 거리·진료과 가중치가 10~17%로 쪼그라들어 사실상
무의미해진다. hospital_score 자신의 tier 값도 "순서만 의미 있고 값 자체엔 의미
없다"고 설계돼 있어(`hospital_score/scoring.py:57`), 산술 가중합보다 순서 조정이
그 설계 의도와 더 맞는다.

---

## 1. 기능 목록 — 무엇을 구현했나

| # | 기능 | 파일 | 상태 |
|---|---|---|---|
| 1 | GPS 거리 계산(Haversine), 존 분류/확장 판단 | `geo.py` | 완료 |
| 2 | 예상 병명 ↔ 진료과 임베딩 유사도 매칭 (배치 인코딩 + 캐시) | `specialty_matcher.py` | 완료 |
| 3 | 거리·진료과 점수 가중합 + declared_no 데모션 정렬 | `scoring.py` | 완료 (데모션 2026-08-14) |
| 4 | 입출력 pydantic 스키마 (voice/info/dashboard 계약) | `schema.py` | 완료 |
| 5 | 2단계 매칭 오케스트레이션 (존 후보 생성 → voice 도착 시 재처리) | `hub_engine.py` | 완료 |
| 6 | 존 부트스트랩 — 후보 0개 사각지대 보정 (`resolve_start_zone`) | `hub_engine.py` | 완료, 실배선(2026-08-11) |
| 7 | 존 확장 — 거절 비율 기반 (`maybe_expand_zone`, `hospital_reject`에만 게이팅) | `hub_engine.py` | 완료, 실배선(2026-08-11) |
| 8 | 승인 액션 반영 (상태 갱신 + 멱등성 가드 + TTL 병상 오버레이) | `hub_engine.py` | 완료 |
| 9 | TTL 병상 오버레이 (`_bed_overlay`, `effective_bed_count`, 15분) | `hub_engine.py` | 완료 (2026-08-13) |
| 10 | info-v2 신뢰도(assessment) 재매칭 — 설명용 | `hub_engine.py` | 완료 (2026-08-13) |
| 11 | **declared_no 하드 데모션** — 순위 맨 뒤로 정렬 | `scoring.py`/`hub_engine.py` | 완료 (2026-08-14) |
| 12 | 다중 사건(caseId)·다중 구급차(apid) 격리 관리 | `hub_engine.py` | 완료 |
| 13 | 의사결정 로그 (타임스탬프+SHA-256, append-only, 위변조 검증) | `decision_log.py` | 완료 |
| 14 | 결과 로컬 저장 (voice 파일명 stem 이어받기) | `delivery.py` | 완료 |
| 15 | 병원/구급차 정보 수신, voice 자가등록, 매칭 실행, WebSocket 브로드캐스트, 신원 확인 | `app.py` | 완료 |
| 16 | 테스트 데이터로 엔진 실행하는 CLI (declared_no 데모션 회귀 테스트 포함) | `run_match.py` | 완료 |

**미구현**:
- info의 표준 코드 정확 대조 제안(하드필터 프리필터) — 미채택, voice의 코드
  출력이 선행 조건
- **dashboard의 `hospital_reject` 액션을 info의 `POST /hub/rejection`으로
  전달하는 로직** — hub에 이 전달 코드가 없다. info 쪽 수신구는 준비돼 있어 hub가
  몇 줄만 추가하면 연동된다. hospital_score 가중치를 실측 기반(3번 방법)으로
  검증하려면 이게 최우선 선행 과제다

---

## 2. 매칭 산출 방식

### 2-1. 거리 — Haversine

$$
d = 2R \cdot \arcsin\!\left(\sqrt{\sin^2\!\left(\frac{\Delta\varphi}{2}\right) + \cos\varphi_1 \cos\varphi_2 \sin^2\!\left(\frac{\Delta\lambda}{2}\right)}\right), \quad R = 6371\text{km}
$$

### 2-2. 존(Zone) 분류

$$
\text{zone}(d) = \left\lfloor \frac{d}{5} \right\rfloor + 1 \qquad (\text{ZONE\_BAND\_KM} = 5.0)
$$

### 2-3. 진료과 매칭 — 임베딩 코사인 유사도

$$
\text{score}_{\text{specialty}} = \max_{d \in \text{Hospital.departments}} \cos\_\text{sim}\big(E(\text{expectedDiagnosis}),\ E(d)\big)
$$

모델: `paraphrase-multilingual-MiniLM-L12-v2`. `SpecialtyMatcher.match_many()`가
병원 전체 진료과명을 중복 제거 후 배치 인코딩하고 캐시한다. 코사인 유사도는
`[0,1]`로 클리핑. 진료과 목록이 빈 병원은 `(None, 0.0)`.

### 2-4. 거리 점수 및 최종 점수

$$
\text{score}_{\text{distance}}(d) = \begin{cases} 1 - \dfrac{d}{20} & d < 20\text{km} \\ 0 & d \geq 20\text{km} \end{cases}
$$

$$
\text{finalScore} = 0.6 \cdot \text{score}_{\text{specialty}} + 0.4 \cdot \text{score}_{\text{distance}} \qquad (W_{\text{SPECIALTY}}=0.6,\ W_{\text{DISTANCE}}=0.4)
$$

### 2-5. 정렬 — declared_no 데모션 (2026-08-14)

$$
\text{sortKey} = \big(\text{demote},\ -\text{finalScore},\ d,\ \text{hospitalId}\big)
$$

$$
\text{demote} = \begin{cases} \text{True} & \text{assessment.groups[관련그룹].tier} = \text{"declared\_no"} \\ \text{False} & \text{그 외(assessment 없음 포함)} \end{cases}
$$

`demote=True`인 병원은 `finalScore`가 아무리 높아도 정렬에서 맨 뒤로 밀린다.
`finalScore` 값 자체는 전혀 바뀌지 않는다 — 순수하게 정렬 순서만 조정한다.
`hub_engine.py::_should_demote()`가 계산하고, `scoring.py::rank()`가 정렬을
수행한다.

### 2-6. 존 확장

$$
\text{reject\_ratio} = \frac{\#\{\text{rejected}\}}{\#\{\text{approved} \cup \text{rejected} \cup \text{confirmed}\}} \qquad \text{expand if} \geq 0.5
$$

`resolve_start_zone()`(부트스트랩, 후보 0개 사각지대) / `maybe_expand_zone()`
(`hospital_reject`에만 게이팅, 누적 비율 오작동 방지).

### 2-7. 병상 — TTL 오버레이

$$
\text{effectiveBedCount} = \max\!\Big(0,\ \text{availableBedCount} - \big|\{t \in \text{overlay}[\text{hpid}] : t > \text{now}\}\big|\Big)
$$

`BED_OVERLAY_TTL_MIN = 15`(분), 근거: `hvidate` 갱신 간격 실측(중앙값 5분,
443곳 중 88.7~90.5%가 10분 이내, 2026-08-14 라이브 재확인).

### 2-8. 신뢰도(assessment) 재매칭 — 설명용, finalScore와 별도 계산

$$
\text{group}^* = \arg\max_{g \,\in\, \text{15개 질환군}} \cos\_\text{sim}\big(E(\text{expectedDiagnosis}),\ E(g)\big)
$$

진료과 매칭과는 독립된 두 번째 `match_many()` 호출. 결과(`group*`의 tier·score·
confidence·basis)는 `HospitalMatch.reliability`로 dashboard에 실리고, **동시에**
`_should_demote()`가 이 결과의 `tier`를 읽어 정렬 여부를 결정한다 — 즉 같은
매칭 결과가 "설명"과 "정렬"에 각각 다른 방식으로 쓰인다(설명은 값 그대로 노출,
정렬은 declared_no 여부만 이진 판단).

**주의(실측으로 반복 확인된 현상)**: 이 그룹 매칭이 항상 의미상 가장 적절한
그룹을 고르진 않는다. "재관류 중재술"을 명시한 통화에서 "대동맥응급"이 뽑힌
사례가 실제 데모(2026-08-13)와 검증 스크립트 양쪽에서 재현됐다 — 진료과 매칭의
"신경외과 vs 순환기내과" 오매칭과 같은 계열의 현상이다.

### 2-9. 민감도 분석 실측 결과 (declared_no 데모션 채택 근거)

| 가정 | declared_no가 unknown_bare를 못 앞지르게 하는 최소 신뢰도 가중치 |
|---|---|
| 이론적 최악(진료과·거리 점수 [0,1] 전 구간) | 0.833 |
| 실측 기반(진료과 유사도 관측 최댓값 0.2786 반영) | 0.733 |

재현: 가상 worktree(`/tmp/hub-experiment`, 실험 종료 후 삭제됨)에서 이분 탐색으로
계산. 두 경우 다 신뢰도 가중치가 70%대 이상이어야 완전한 안전이 보장돼, 가중합
방식 자체가 실용적이지 않다는 결론의 근거가 됐다.

### 2-10. 검증

- `run_match.py`가 다중 사건 격리, 승인 후 캐시 병상 반영, TTL 만료 시뮬레이션,
  **declared_no 데모션(거리 1위·진료과 동점이어도 맨 뒤로 밀리는지, assessment
  없는 병원은 영향 없는지)**을 전부 회귀 테스트로 검증한다.
- 실서버 E2E: hub+info 동시 기동, 소켓 2개 동시 연결, apid 기반 신호 중계, 승인
  후 재브로드캐스트까지 실제 HTTP/WebSocket으로 검증됨.

### 2-11. 알려진 한계

| 항목 | 이유 |
|---|---|
| 존 확장 임계값·가중치(`W_SPECIALTY`/`W_DISTANCE`) | 실제 운영 데이터 없이 정한 상수 |
| declared_no 데모션의 "다음 단계"(가중합 승격) | 거절 로그 0건이라 실측 검증 불가 — hub→info 전달 배선부터 필요 |
| 구급차 GPS | 실시간 아님, `AmbulanceInfo` 고정값 |
| voice 자가등록 재시도 | `AmbulanceInfo` 미등록 시 409, 재시도 큐 없음 |

---

## 3. 근거 송수신 데이터 목록

### 3-1. 엔드포인트 전체

| # | 방향 | 엔드포인트 | 페이로드 | 프로토콜 | 상태 |
|---|---|---|---|---|---|
| 1 | info → hub | `POST /info/hospitals` | HospitalInfo (assessment 포함) | HTTP | 가동 |
| 2 | info → hub | `POST /info/ambulances` | AmbulanceInfo | HTTP | 가동 |
| 3 | voice → hub | `POST /voice/register` | VoiceRegistration | HTTP | 가동 |
| 4 | voice → hub | `POST /voice/summary` | VoiceCallSummaryMessage | HTTP | 가동 |
| 5 | dashboard ↔ hub | `WS /ws/dashboard` | HubMatchResult / ApprovalAction / CallSignal / identify | WebSocket | 가동 |
| 6 | dashboard → hub | `GET /identity?role=&id=` | — | HTTP REST, CORS `*` | 가동 |
| 7 | hub → voice | `POST /call/start`, `/call/end` (중계) | `{timestamp, caseId}` | HTTP | 가동 |
| 8 | hub → info | `POST /hub/rejection` | 거절 로그 | HTTP | **미구현** |

포트: hub `5001`(고정). voice는 apid마다 다른 포트.

### 3-2. 유일한 외부 의존 — 로컬 AI 모델

hub는 외부 공공 API를 직접 호출하지 않는다. 입력은 전부 다른 브랜치(voice·info·
dashboard)와의 통신이고, 유일한 외부 의존은 `sentence-transformers`
(`paraphrase-multilingual-MiniLM-L12-v2`, 로컬 실행, CPU로 충분)뿐이다.

---

## 4. 페이로드 실물

### 4-1. 출력 — `HubMatchResult` (실제 데모 캡처, 2026-08-13)

```json
{
  "caseId": "85f174bb-f40a-47a6-9c4a-026bd409d4d4",
  "patientInfo": {
    "expectedDiagnosis": "심장질환 · 가슴 통증",
    "severityTag": "high"
  },
  "hospitals": [
    {
      "hospitalId": "A1100015", "name": "연세대학교의과대학강남세브란스병원",
      "distanceKm": 1.75,
      "specialtyMatch": { "department": "신경외과", "score": 0.2786 },
      "availableBedCount": 0, "bedCountUnknown": false, "status": "pending",
      "reliability": { "group": "대동맥응급", "score": 1.0, "confidence": "high",
        "basis": ["병원 신고: 수용 가능", "등급: 지역응급의료센터"] }
    }
  ],
  "source": "rule"
}
```

### 4-2. declared_no 데모션 실측 (회귀 테스트, `run_match.py`)

거리 0.14km·진료과 동점인 가상 병원(D001)이 `declared_no` 신고 하나만으로
맨 뒤로 밀리는 것을 실제 코드로 확인함:

```
D002 [테스트] 그다음, 미상 — 거리 1.99km, reliability=[대동맥응급/0.4]
D003 [테스트] assessment 없음 (구 데이터) — 거리 2.99km, reliability=[없음]
D001 [테스트] 초근접·진료과 동점, 수용불가 신고 — 거리 0.14km, reliability=[대동맥응급/0.2]
```

---

## 5. 후속 작업

### 5-1. 🔴 거절 로그를 info로 전달하는 배선 추가

`_handle_dashboard_action()`에 `hospital_reject` 액션일 때 info의
`POST /hub/rejection`으로 최소 페이로드(`hospitalId`, `timestamp`)를 POST하는
코드 몇 줄만 추가하면 된다. 이게 되어야 hospital_score 가중치를 실측(거절 로그)
기반으로 검증하는 단계로 넘어갈 수 있다.

### 5-2. 🟡 declared_no 데모션 → 가중합 승격 재검토

거절 로그가 쌓이면(5-1 선행), tier·거리·진료과매칭과 실제 승인율의 관계를
역산해 지금의 하드 데모션을 실측 기반 가중합으로 바꿀지 재검토한다. 이때도
"declared_no는 항상 최하위권"이라는 불변식을 잃지 않는지 검증할 것.

### 5-3. 🟢 존 확장 임계값·가중치 튜닝

실제 운영 데이터 없이 정한 상수(`REJECT_RATIO_THRESHOLD=0.5` 등)를 5-1 이후
재검토.

---

## 6. 보고서에 실을 실측 근거

| 발견 | 숫자 |
|---|---|
| 존 사각지대 실제 재현 | `MAX_ZONE=1` 고정 시절, 서울 전역 병원 7곳 데이터로 zone 1 후보 0건 |
| 승인 후 캐시 병상 미반영 버그 실제 재현·수정 | 2026-08-11 |
| 전국 확장 파이프라인 통과율 | E-Gen 533곳 중 매핑 성공 443곳, assessment 첨부 443/443 |
| declared_no 데모션 안전 가중치(민감도 분석) | 이론적 0.833, 실측 기반 0.733 |
| declared_no 데모션 실제 동작 확인 | 거리 1위·진료과 동점 가상 병원이 declared_no 하나로 맨 뒤로 밀림 (회귀 테스트) |

재현: `python hub/run_match.py`(전체 회귀 테스트, declared_no 데모션 포함),
`python -c "import decision_log; print(decision_log.verify_log())"`.
