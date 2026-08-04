"""OCR 텍스트에서 병원 정보 필드를 뽑는다.

    OCR 결과(텍스트) → [AI] 필드 그룹별 추출 → [규칙] 근거 대조 → DocumentFields

`ocr/README.md`가 "다음 작업"으로 남겨둔 1번(필드 추출)이 여기다.

AI와 규칙의 경계
----------------
CLAUDE.md의 핵심 AI 활용 원칙에 따라 두 층을 섞지 않는다.

| 단계 | 구분 | 어디 |
|---|---|---|
| 자유 텍스트에서 값 찾기 | **AI** | `llm/` |
| 형식 보장 | 규칙(문법 제약 디코딩) | `prompts.py`의 JSON Schema |
| 어휘 검증 | **규칙** | `schema.py`의 validator |
| 근거 대조(환각 필터) | **규칙** | `grounding.py` |
| 검토 필요 판정 | **규칙** | 이 파일 |

AI가 하는 일은 "이 문장이 무슨 뜻인가"뿐이고, 그 답을 받아들일지는 전부 규칙이
정한다. 왜 그런 결과가 나왔는지 설명할 수 있어야 하기 때문이다.

실패했을 때의 태도
------------------
그룹 하나가 실패해도 나머지는 살린다. 진료과를 못 읽었다고 당직 정보까지 버릴
이유가 없다. 실패한 그룹은 값이 `None`으로 남고 `reviewReasons`에 이유가 쌓인다.
`None`은 "확인된 부재"가 아니라 "모름"이며, 이 구분이 나중에 합칠 때 덮어쓸지
말지를 가른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import grounding, prompts
from .config import KST, MISSING_SENTINEL, UNKNOWN_TEXT, ExtractConfig
from .llm.base import LlmClient, LlmError
from .schema import DocumentFields, Evidence, Specialty


@dataclass
class GroupOutcome:
    """필드 그룹 1개를 처리한 결과."""

    values: dict = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class FieldExtractor:
    """OCR 결과 1건을 `DocumentFields` 1건으로 바꾼다."""

    def __init__(self, client: LlmClient, config: ExtractConfig | None = None) -> None:
        self._llm = client
        self._cfg = config or ExtractConfig.from_env()

    def extract(
        self,
        ocr_result: dict,
        document_id: str,
        on_progress: Callable[[dict], None] | None = None,
    ) -> DocumentFields:
        """OCR 결과에서 필드를 뽑는다.

        `ocr_result`는 `goldenlink_ocr.DocumentOCR.read()`의 반환값 형태다
        (`text`, `regions`, `needs_review`). `run_ocr.py --json`으로 저장해둔
        출력을 그대로 넣어도 된다.

        `on_progress`를 주면 그룹(LLM 호출 1회) 단위로 진행을 알린다. 4번의 호출이
        각각 수십 초씩 걸리므로, 먼저 끝난 그룹부터 보여줄 수 있어야 한다.

            {"stage": "group_start",  "source": "ai",   "key": ..., "label": ..., "index": 0, "total": 4}
            {"stage": "group_done",   "source": "rule", ..., "values": {...}, "evidence": [...], "raw": {...}}
            {"stage": "group_failed", "source": "rule", ..., "error": "..."}

        `group_done`의 `raw`는 가공 전 LLM 응답 그대로다. 이 파일은 그걸 값·근거로
        바꾸고 나면 버리는데, 받는 쪽에서 필요할 수 있어 이벤트에 함께 싣는다
        (필드 추출 모델을 학습시키려면 이 원본이 타깃이 된다 — `LLMdata/README.md`).

        값을 **찾는** 것은 AI(`group_start`)이고 그것을 **받아들일지** 정하는 것은
        규칙(`group_done`의 근거 대조)이라 `source`가 다르다.
        콜백은 추출과 같은 스레드에서 불리며 예외를 던지지 않아야 한다.
        """
        notify = on_progress or (lambda event: None)

        text = (ocr_result.get("text") or "").strip()
        regions = ocr_result.get("regions") or []

        values: dict = {}
        evidence: list[Evidence] = []
        reasons: list[str] = []

        # OCR 단계에서 이미 검토 대상으로 찍힌 문서는 그 사실을 물려받는다.
        # 글자가 깨진 상태로 뽑은 필드는 형식이 맞아도 내용을 믿을 수 없다
        if ocr_result.get("needs_review"):
            flagged = sum(1 for region in regions if region.get("needs_review"))
            reasons.append(f"OCR 단계에서 검토 대상으로 표시됨 (영역 {flagged}개)")

        if not text:
            reasons.append("OCR 텍스트가 비어 있어 추출을 시도하지 않았다")
            return self._build(document_id, values, evidence, reasons)

        handlers: dict[str, Callable[[dict, str, list[dict]], GroupOutcome]] = {
            prompts.DOCUMENT.key: self._handle_document,
            prompts.NIGHT_DUTY.key: self._handle_night_duty,
            prompts.SPECIALTIES.key: self._handle_specialties,
            prompts.CAPABILITIES.key: self._handle_capabilities,
        }

        total = len(prompts.FIELD_GROUPS)
        for index, group in enumerate(prompts.FIELD_GROUPS):
            progress = {
                "key": group.key, "label": group.label, "index": index, "total": total,
            }
            notify({"stage": "group_start", "source": "ai", **progress})

            try:
                raw = self._llm.complete_json(
                    system=prompts.SYSTEM_PROMPT,
                    prompt=prompts.build_user_prompt(group, text),
                    json_schema=group.schema,
                )
            except LlmError as error:
                # 그룹 하나의 실패가 문서 전체를 버리게 두지 않는다
                reasons.append(f"'{group.label}' 추출 실패: {error}")
                notify({
                    "stage": "group_failed", "source": "rule",
                    "error": str(error), **progress,
                })
                continue

            outcome = handlers[group.key](raw, text, regions)
            values.update(outcome.values)
            evidence.extend(outcome.evidence)
            reasons.extend(outcome.reasons)
            notify({
                "stage": "group_done", "source": "rule",
                "values": outcome.values,
                "evidence": outcome.evidence,
                "reasons": outcome.reasons,
                # 가공 전 원본. 이 파일은 안 쓰지만 학습 데이터의 타깃이 된다
                "raw": raw,
                **progress,
            })

        return self._build(document_id, values, evidence, reasons)

    # --- 그룹별 처리 --------------------------------------------------------
    #
    # 각 핸들러는 LLM 원시 응답을 받아 (값, 근거, 검토사유)로 바꾼다.
    # 근거 대조에 실패한 값은 `values`에 넣지 않되 `evidence`에는 남긴다.

    def _handle_document(self, raw: dict, text: str, regions: list[dict]) -> GroupOutcome:
        outcome = GroupOutcome()

        name = str(raw.get("hospitalName") or "").strip()
        if name:
            # 기관명은 로고·직인에 걸쳐 있어 줄이 잘리기 쉽다. 값이 근거 안에 그대로
            # 있기를 요구하면 정상적인 경우까지 걸린다
            if self._check(
                "hospitalName", name,
                str(raw.get("hospitalNameEvidence") or ""), text, regions, outcome,
            ):
                outcome.values["hospitalName"] = name
        else:
            outcome.reasons.append("기관명을 찾지 못했다 — 어느 병원의 서류인지 특정할 수 없다")

        hpid = str(raw.get("hospitalId") or "").strip()
        if hpid:
            # 기관코드는 오독 한 글자가 다른 병원을 가리킨다. 근거 안에 코드가
            # 그대로 있어야만 인정한다
            if self._check(
                "hospitalId", hpid,
                str(raw.get("hospitalIdEvidence") or ""), text, regions, outcome,
                require_value_in_evidence=True,
            ):
                outcome.values["hospitalId"] = hpid

        # 서류 종류는 enum으로 제약돼 있어 어휘 밖 값이 못 온다. 근거는 서류 전체를
        # 보고 판단하는 것이라 특정 문장에 묶이지 않으므로 대조하지 않는다
        document_type = str(raw.get("documentType") or "").strip()
        if document_type:
            outcome.values["documentType"] = document_type

        date = _clean_date(raw.get("effectiveDate"))
        date_evidence = str(raw.get("effectiveDateEvidence") or "")
        if date:
            # 날짜는 서류 기반 정보에서 가장 위험한 필드다. 3년 전 당직표를 오늘
            # 것으로 쓰는 사고가 여기서 난다. 근거에 그 숫자들이 있어야 인정한다
            if self._check(
                "effectiveDate", date, date_evidence, text, regions, outcome,
                supports=lambda: _date_supported_by(date, date_evidence),
                unsupported_reason=f"근거에 {date}의 연·월이 없다 — 오늘 날짜를 넣었을 수 있다",
            ):
                outcome.values["effectiveDate"] = date
        else:
            outcome.reasons.append(
                "기준일자를 찾지 못했다 — 이 서류가 언제 것인지 알 수 없어 신선도를 판단할 수 없다"
            )

        return outcome

    def _handle_night_duty(self, raw: dict, text: str, regions: list[dict]) -> GroupOutcome:
        outcome = GroupOutcome()
        state = str(raw.get("nightDuty") or UNKNOWN_TEXT).strip().upper()

        # 미상은 정상적인 답이다. 검토 사유가 아니다 — 모든 서류에 당직 정보가
        # 있는 게 아니다
        if state in ("", UNKNOWN_TEXT):
            return outcome

        evidence_text = str(raw.get("evidence") or "")
        if self._check("nightDutyAvailable", state, evidence_text, text, regions, outcome):
            outcome.values["nightDutyAvailable"] = state == "Y"

        return outcome

    def _handle_specialties(self, raw: dict, text: str, regions: list[dict]) -> GroupOutcome:
        outcome = GroupOutcome()
        items = raw.get("specialties")
        if not isinstance(items, list):
            outcome.reasons.append("진료과 응답 형식이 목록이 아니다")
            return outcome

        found: list[Specialty] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            department = str(item.get("department") or "").strip()
            if not department:
                continue

            evidence_text = str(item.get("evidence") or "")
            prefix = f"specialties[{index}]"

            # 진료과명 자체가 근거 안에 있어야 한다. 근거는 원문에서 가져왔는데
            # 과 이름은 딴 데서 온 경우를 잡는다
            if not self._check(
                f"{prefix}.department", department, evidence_text, text, regions, outcome,
                require_value_in_evidence=True,
            ):
                continue

            doctor_count = _clean_count(item.get("doctorCount"))
            if doctor_count is not None and not grounding.value_appears_in(
                str(doctor_count), evidence_text
            ):
                # 숫자는 정규화가 흡수해줄 여지가 없다. 근거에 그 숫자가 없으면
                # 인원만 미상으로 되돌리고 과 정보 자체는 살린다
                outcome.evidence.append(Evidence(
                    field=f"{prefix}.doctorCount",
                    value=str(doctor_count),
                    sourceText=evidence_text,
                    grounded=False,
                    groundReason="근거에 그 숫자가 없다 — 인원을 미상으로 되돌렸다",
                    regionIndex=grounding.locate_region(evidence_text, regions),
                ))
                outcome.reasons.append(f"'{department}' 인원 수의 근거가 없어 미상 처리했다")
                doctor_count = None

            on_duty = str(item.get("onDuty") or UNKNOWN_TEXT).strip().upper()
            found.append(Specialty(
                department=department,
                doctorCount=doctor_count,
                procedureTags=_clean_str_list(item.get("procedureTags")),
                onDuty=None if on_duty in ("", UNKNOWN_TEXT) else on_duty == "Y",
            ))

        # 빈 목록도 정보다 — "서류를 봤는데 진료과가 없더라"(`[]`)와 "아예 못
        # 봤다"(`None`)는 다르다. 호출이 실패했다면 이 줄에 도달하지 못하고 키가
        # 없는 채로 남는다
        outcome.values["specialties"] = _merge_specialties(found)
        return outcome

    def _handle_capabilities(self, raw: dict, text: str, regions: list[dict]) -> GroupOutcome:
        outcome = GroupOutcome()

        codes: list[str] = []
        items = raw.get("capabilities")
        if not isinstance(items, list):
            outcome.reasons.append("역량 응답 형식이 목록이 아니다")
        else:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "").strip()
                if not code:
                    continue
                evidence_text = str(item.get("evidence") or "")
                if self._check(
                    f"capabilities[{index}]", code, evidence_text, text, regions, outcome,
                    # 코드는 영문이라 원문에 그대로 있을 리 없다. 대신 코드별 원문
                    # 표현이 근거에 있는지를 본다 — 원문의 아무 문장이나 근거로
                    # 붙이는 것을 막는다
                    supports=lambda code=code, ev=evidence_text: (
                        grounding.capability_supported_by(code, ev)
                    ),
                    unsupported_reason=(
                        f"근거가 {code}와 무관하다 — "
                        f"{'/'.join(grounding.CAPABILITY_EVIDENCE_TERMS.get(code, ('?',))[:3])} "
                        f"같은 표현이 근거에 없다"
                    ),
                ):
                    codes.append(code)
            outcome.values["capabilities"] = sorted(set(codes))

        equipment: list[str] = []
        raw_equipment = raw.get("equipment")
        if isinstance(raw_equipment, list):
            for index, item in enumerate(raw_equipment):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                evidence_text = str(item.get("evidence") or "")
                # 장비명은 원문 표기를 그대로 옮기는 것이라 근거 안에 있어야 한다
                if self._check(
                    f"equipment[{index}]", name, evidence_text, text, regions, outcome,
                    require_value_in_evidence=True,
                ):
                    equipment.append(name)
            outcome.values["equipment"] = sorted(set(equipment))

        return outcome

    # --- 공통 검사 ----------------------------------------------------------

    def _check(
        self,
        field_name: str,
        value: str,
        evidence_text: str,
        document_text: str,
        regions: list[dict],
        outcome: GroupOutcome,
        *,
        require_value_in_evidence: bool = False,
        supports: Callable[[], bool] | None = None,
        unsupported_reason: str = "근거가 이 값을 뒷받침하지 않는다",
    ) -> bool:
        """값 하나를 받아들일지 판정하고 근거를 기록한다.

        검사는 세 겹이고, 뒤로 갈수록 엄격해진다.

        1. **근거가 원문에 있는가** — 문장 자체를 지어낸 경우를 잡는다
        2. **값이 근거 안에 있는가**(`require_value_in_evidence`) — 근거는 진짜인데
           값만 다른 경우를 잡는다. 인원 수·기관코드·장비명처럼 원문 표기와 값이
           같아야 하는 항목에 쓴다
        3. **근거가 값을 뒷받침하는가**(`supports`) — 근거도 진짜고 값도 어휘에
           있지만 둘이 무관한 경우를 잡는다. 역량 코드처럼 값이 원문에 그대로
           나올 수 없어 2번을 못 쓰는 항목에 쓴다

        통과하면 True. 실패해도 `evidence`에는 `grounded=False`로 남긴다 —
        무엇을 왜 버렸는지 사람이 볼 수 있어야 한다.
        """
        grounded, reason = grounding.is_grounded(
            evidence_text, document_text, self._cfg.min_evidence_chars
        )

        if grounded and require_value_in_evidence:
            if not grounding.value_appears_in(value, evidence_text):
                grounded = False
                reason = f"근거에 값 {value!r}이 없다 — 근거와 값이 따로 논다"

        if grounded and supports is not None and not supports():
            grounded = False
            reason = unsupported_reason

        outcome.evidence.append(Evidence(
            field=field_name,
            value=value,
            sourceText=evidence_text,
            grounded=grounded,
            groundReason=reason,
            regionIndex=grounding.locate_region(evidence_text, regions) if grounded else None,
        ))

        if not grounded:
            outcome.reasons.append(f"{field_name}: {reason}")
            return not self._cfg.drop_ungrounded
        return True

    # --- 조립 ---------------------------------------------------------------

    def _build(
        self,
        document_id: str,
        values: dict,
        evidence: list[Evidence],
        reasons: list[str],
    ) -> DocumentFields:
        return DocumentFields(
            **values,
            evidence=evidence,
            needsReview=bool(reasons),
            reviewReasons=reasons,
            documentId=document_id,
            extractedAt=datetime.now(KST).isoformat(),
            modelUsed={"llm": self._llm.describe()},
        )


# --- 값 정리 ----------------------------------------------------------------


def _clean_count(raw: object) -> int | None:
    """인원 수를 정리한다. 미상이면 `None`.

    `0`("0명이라고 적혀 있다")과 `None`("서류에 안 적혀 있다")을 절대 섞지 않는다.
    """
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return None if value <= MISSING_SENTINEL else value


def _clean_date(raw: object) -> str | None:
    """기준일자를 'YYYY-MM' 또는 'YYYY-MM-DD'로 정리한다. 못 읽으면 `None`.

    형식 검증은 `schema.py`가 다시 하지만, 여기서 먼저 걸러야 검증 예외 대신
    "못 찾았다"로 처리된다. 서류에 날짜가 없는 것은 정상이고 예외 상황이 아니다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            datetime.strptime(text, pattern)
            return text
        except ValueError:
            continue
    return None


def _date_supported_by(date: str, evidence: str) -> bool:
    """근거에 그 날짜의 연도와 월이 실제로 있는지 확인한다.

    "오늘 날짜를 넣지 마라"고 프롬프트에 적어도 모델은 종종 넣는다. 서류 기반
    정보에서 기준일자가 틀리면 낡은 정보를 최신으로 오인하게 되므로, 지시에
    기대지 않고 확인한다.

    표기가 다양해서(2026년 8월 / 2026-08 / 2026.08) 정규화 후 연도와 월을 따로
    찾는다. 월은 앞의 0을 뗀 형태도 함께 본다.
    """
    normalized = grounding.normalize(evidence)
    year, month = date.split("-")[0], date.split("-")[1]
    if year not in normalized:
        return False
    return month in normalized or month.lstrip("0") in normalized


def _clean_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _merge_specialties(items: list[Specialty]) -> list[Specialty]:
    """같은 진료과가 여러 번 나오면 합친다.

    서류의 표와 본문에 같은 과가 중복 등장하는 일이 흔하다. 인원 수는 **큰 쪽**을
    남긴다 — 한 곳에 일부만, 다른 곳에 전체가 적히는 경우가 많고 적은 쪽을 택하면
    실제보다 축소된다. 당직 여부는 한 번이라도 Y면 Y다.
    """
    merged: dict[str, Specialty] = {}
    for item in items:
        existing = merged.get(item.department)
        if existing is None:
            merged[item.department] = item
            continue
        counts = [c for c in (existing.doctorCount, item.doctorCount) if c is not None]
        duties = [d for d in (existing.onDuty, item.onDuty) if d is not None]
        merged[item.department] = Specialty(
            department=item.department,
            doctorCount=max(counts) if counts else None,
            procedureTags=sorted(set(existing.procedureTags) | set(item.procedureTags)),
            onDuty=any(duties) if duties else None,
        )
    return [merged[name] for name in sorted(merged)]
