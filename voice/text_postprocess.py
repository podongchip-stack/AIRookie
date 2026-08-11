# -*- coding: utf-8 -*-
"""STT 출력 텍스트를 오인식 사전으로 교정하는 필터 (정확 일치 기반).

whisper에는 아무것도 붙이지 않는다. STT가 뱉은 텍스트를 받아, corrections.json에
등록된 "오인식 -> 정답" 쌍과 **정확히 일치**하는 구간만 치환하고, 그 결과를 LLM에 넘긴다.

    whisper -> 텍스트 -> [이 필터] -> 교정된 텍스트 -> LLM 요약

정확히 일치할 때만 바꾸므로 등록하지 않은 말은 절대 건드리지 않는다. 즉 오교정이
구조적으로 발생할 수 없고, 유사도 임계값 같은 튜닝 대상도 없다. 대신 **등록한 만큼만
잡힌다** — 통화 녹음에서 오인식을 발견할 때마다 corrections.json에 한 줄씩 추가하는 것이
이 방식의 운영 방법이다.

정확히 일치를 보되, 실제 문장에서 걸리게 하려고 세 가지는 처리한다:
    - 조사 분리: "재세동이"는 조사 "이"를 떼야 "재세동"에 걸린다. 치환 후 다시 붙여
      "제세동이"로 만든다.
    - 공백 정규화: whisper가 "번지 회"처럼 띄어 쓸 수 있어 1~3어절 구간을 붙여서 조회한다.
    - 긴 구간 우선: 겹치는 자리는 더 긴 구간이 가져간다.

사용 예:
    from text_postprocess import postprocess_text

    result = postprocess_text("재세동이 번지회 시행했습니다", "corrections.json")
    print(result.corrected_text)   # 제세동이 2회 시행했습니다
    print(result.corrections)      # [Correction(original="재세동이", corrected="제세동이", ...)]

사전 파일 구조 (corrections.json):
    {"corrections": {"재세동": "제세동", "번지회": "2회"}}
    왼쪽이 STT가 잘못 뱉는 표기, 오른쪽이 정답이다. 왼쪽은 공백 없이 2글자 이상으로
    적는다 (조회 전에 구간의 공백을 제거하므로). 오른쪽은 제약이 없다.

자체 점검:
    사전을 고친 뒤에는 이 파일을 직접 실행한다 (음성 불필요, 1초 안쪽).

        python text_postprocess.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 오인식 사전의 기본 위치. 이 모듈 옆에 두고 손으로 편집한다 — data/ 아래에 두면
# .gitignore의 data/ 규칙에 걸려 저장소에 안 올라간다(사전은 코드처럼 관리해야 함).
CORRECTIONS_PATH = Path(__file__).resolve().parent / "corrections.json"

# 한 용어가 여러 어절로 쪼개져 인식되는 경우("번지 회")까지 잡으려고 구간을 묶는다.
DEFAULT_MAX_NGRAM = 3
# 오인식 표기(사전 왼쪽)의 최소 길이. 1글자를 허용하면 "안" 같은 흔한 말이 통째로
# 치환돼 버린다.
MIN_KEY_LENGTH = 2

# 구간 끝에서 떼어낼 꼬리(조사 + 종결어미) 후보. 떼어낸 형태로도 사전을 조회하고,
# 걸리면 치환 후 다시 붙인다. 긴 것부터 시도한다.
#
# 종결어미까지 넣는 이유: 통화체는 "뇌졸증센터입니다"처럼 어미가 붙어 한 어절이 되는
# 경우가 많아, 조사만 떼서는 "뇌졸증센터"에 걸리지 않는다.
# 사전 키는 정확히 일치할 때만 발동하므로, 꼬리를 넉넉히 떼도 오작동 위험은 없다.
TRAILING_SUFFIXES = (
    "이라고요", "이신가요", "으로부터", "에서부터",
    "이라고", "이라는", "으로는", "에서는", "에게서", "이고요", "인가요",
    "입니다", "습니다", "이에요", "이었고", "이라서",
    "라고", "라는", "으로", "에서", "에게", "부터", "까지", "보다", "처럼",
    "한테", "이나", "이란", "라도", "이며", "이고", "든지", "마저", "조차",
    "이랑", "이가", "인데", "이다", "예요", "이요",
    "랑", "와", "과", "은", "는", "이", "가", "을", "를", "에", "의",
    "도", "만", "로", "나", "요",
)

_TOKEN_RE = re.compile(r"\S+")
_WHITESPACE_RE = re.compile(r"\s+")
# 구간 앞뒤에 붙은 문장부호 — 조회 대상에서 빼고 치환 후 원래 자리에 되돌린다.
_EDGE_PUNCT = " \t\n.,!?;:\"'()[]{}<>·…~-"


# ---------------------------------------------------------------------------
# 1. 사전 로딩 / 검증
# ---------------------------------------------------------------------------


def load_corrections(path: str | Path) -> dict[str, str]:
    """corrections.json을 {오인식: 정답} 딕셔너리로 읽는다.

    오인식 표기(왼쪽)는 공백을 제거해서 담는다. 조회할 때도 구간의 공백을 제거하므로,
    사전에 "지혈 때"로 적든 "지혈때"로 적든 똑같이 동작한다 — STT 출력에서 오인식을
    그대로 복사해 붙여도 되게 하려는 것이다. 정답(오른쪽)은 건드리지 않는다.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    table: dict[str, str] = {}
    for wrong, right in data.get("corrections", {}).items():
        key = _WHITESPACE_RE.sub("", str(wrong))
        value = str(right).strip()
        if key and value:
            table[key] = value
    return table


def validate_corrections(path: str | Path) -> list[str]:
    """corrections.json이 교정기가 쓸 수 있는 형태인지 검사한다.

    사전은 사람이 직접 편집하는 데이터 파일인데, 아래 위반은 실행 중에 에러를 내지 않고
    **조용히** 해당 항목이 무시되는 결과로 이어진다. 그래서 따로 잡아준다.

    반환값은 위반 목록 (비어 있으면 정상).
    """
    raw = Path(path).read_text(encoding="utf-8")
    problems: list[str] = []

    # JSON은 중복 키를 조용히 덮어쓴다 -> 파싱 단계에서 직접 세어야 보인다
    seen: dict[str, int] = {}

    def count_keys(pairs: list[tuple[str, object]]) -> dict:
        for key, _ in pairs:
            seen[key] = seen.get(key, 0) + 1
        return dict(pairs)

    data = json.loads(raw, object_pairs_hook=count_keys)
    table = data.get("corrections", {})

    for key, times in seen.items():
        if times > 1 and key in table:
            problems.append(f'"{key}": 같은 항목이 {times}번 있다 (뒤엣것만 적용된다)')

    # 공백을 제거하면 같아지는 항목끼리도 충돌한다 ("지혈 때"와 "지혈때")
    normalized: dict[str, str] = {}

    for wrong, right in table.items():
        wrong, right = str(wrong), str(right)
        key = _WHITESPACE_RE.sub("", wrong)
        if not key:
            problems.append("오인식 표기가 비어 있다")
        elif len(key) < MIN_KEY_LENGTH:
            problems.append(f'"{wrong}": {MIN_KEY_LENGTH}글자 미만은 과잉 치환 위험이 크다')
        elif key in normalized:
            problems.append(
                f'"{wrong}": 공백을 빼면 "{normalized[key]}"와 같다 (하나만 적용된다)'
            )
        else:
            normalized[key] = wrong

        if not right.strip():
            problems.append(f'"{wrong}": 정답이 비어 있다')
        elif key == _WHITESPACE_RE.sub("", right):
            problems.append(f'"{wrong}": 오인식과 정답이 같다 (교정할 게 없다)')

    return problems


# ---------------------------------------------------------------------------
# 2. 구간 조회
# ---------------------------------------------------------------------------


def _josa_variants(core: str) -> list[tuple[str, str]]:
    """(조회할 몸통, 되붙일 조사) 후보. 조사 없는 원형을 먼저, 그다음 긴 조사부터."""
    variants = [(core, "")]
    matched = [j for j in TRAILING_SUFFIXES if core.endswith(j) and len(core) > len(j)]
    matched.sort(key=len, reverse=True)
    variants.extend((core[: -len(j)], j) for j in matched)
    return variants


def _match_span(span: str, table: dict[str, str]) -> str | None:
    """구간 하나를 사전에서 조회한다. 걸리면 치환 문자열을, 아니면 None을 반환한다.

    앞뒤 문장부호는 조회에서 빼고 치환 후 되돌린다. 구간 안의 공백은 제거하고
    조회한다 — STT가 한 용어를 여러 어절로 쪼갠 경우를 잡기 위함이다.
    """
    lead_len = len(span) - len(span.lstrip(_EDGE_PUNCT))
    lead, rest = span[:lead_len], span[lead_len:]
    trail_len = len(rest) - len(rest.rstrip(_EDGE_PUNCT))
    core_raw = rest[: len(rest) - trail_len] if trail_len else rest
    trail = rest[len(rest) - trail_len :] if trail_len else ""

    core = _WHITESPACE_RE.sub("", core_raw)
    if len(core) < MIN_KEY_LENGTH:
        return None

    for body, josa in _josa_variants(core):
        right = table.get(body)
        if right is not None:
            return f"{lead}{right}{josa}{trail}"
    return None


# ---------------------------------------------------------------------------
# 3. 교정
# ---------------------------------------------------------------------------


@dataclass
class Correction:
    """교정 한 건. start/end는 원본 텍스트의 문자 위치다."""

    original: str  # 교정 전 구간 (원문 그대로)
    corrected: str  # 교정 후 구간 (조사·문장부호 복원 포함)
    start: int
    end: int
    ngram: int  # 몇 어절짜리 구간이었는지


@dataclass
class TextPostprocessResult:
    raw_text: str  # 교정 전 원본 (감사 추적용, 항상 보존)
    corrected_text: str  # 교정 반영된 최종 텍스트 (LLM 입력용)
    corrections: list[Correction]
    llm_notice: str  # 교정 내역을 사람이 읽을 수 있게 요약한 안내문


def find_corrections(
    text: str, table: dict[str, str], max_ngram: int = DEFAULT_MAX_NGRAM
) -> list[Correction]:
    """텍스트를 1~max_ngram 어절 구간으로 훑어 사전에 걸리는 자리를 찾는다.

    긴 구간부터 먼저 자리를 차지한다 — "번지 회"가 사전에 있으면 그쪽이 이기고,
    이미 쓰인 어절은 짧은 구간이 다시 가져가지 못한다.
    반환 목록은 텍스트 등장 순서(start 오름차순)다.
    """
    tokens = [(m.group(), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    taken: set[int] = set()
    accepted: list[Correction] = []

    for n in range(max_ngram, 0, -1):
        for i in range(len(tokens) - n + 1):
            if any(j in taken for j in range(i, i + n)):
                continue
            start, end = tokens[i][1], tokens[i + n - 1][2]
            span = text[start:end]
            replacement = _match_span(span, table)
            if replacement is None or replacement == span:
                continue
            taken.update(range(i, i + n))
            accepted.append(
                Correction(
                    original=span, corrected=replacement, start=start, end=end, ngram=n
                )
            )

    accepted.sort(key=lambda c: c.start)
    return accepted


def apply_corrections(text: str, corrections: list[Correction]) -> str:
    """교정 목록을 원본 텍스트에 적용한다 (corrections는 start 오름차순 가정)."""
    out: list[str] = []
    cursor = 0
    for c in corrections:
        out.append(text[cursor : c.start])
        out.append(c.corrected)
        cursor = c.end
    out.append(text[cursor:])
    return "".join(out)


def build_llm_notice(corrections: list[Correction]) -> str:
    """corrected_text와 함께 LLM 프롬프트에 덧붙일 참고 안내문을 만든다."""
    if not corrections:
        return ""
    lines = [
        "[STT 후처리 참고 정보]",
        "다음 구간은 오인식 사전 기준으로 자동 교정되었습니다:",
    ]
    lines += [f'  - "{c.original}" -> "{c.corrected}"' for c in corrections]
    return "\n".join(lines)


def postprocess_text(
    text: str,
    corrections: dict[str, str] | str | Path,
    max_ngram: int = DEFAULT_MAX_NGRAM,
) -> TextPostprocessResult:
    """STT 텍스트 -> 교정된 텍스트 + 교정 로그 + LLM 참고 안내문.

    Args:
        text: STT가 뱉은 원본 텍스트.
        corrections: {오인식: 정답} 딕셔너리 또는 corrections.json 경로.
        max_ngram: 몇 어절까지 한 구간으로 묶어 조회할지.
    """
    table = (
        corrections
        if isinstance(corrections, dict)
        else load_corrections(corrections)
    )
    found = find_corrections(text, table, max_ngram=max_ngram)
    return TextPostprocessResult(
        raw_text=text,
        corrected_text=apply_corrections(text, found),
        corrections=found,
        llm_notice=build_llm_notice(found),
    )


# ---------------------------------------------------------------------------
# 4. 자체 점검 (python text_postprocess.py 로 실행)
# ---------------------------------------------------------------------------

# 02_단문_심정지_CPR.wav를 faster-whisper small로 돌린 실제 출력.
# "제세동 2회"를 "재세동이 번지회"로, "70대"를 "1흔대"로 오인식했다.
_SELFCHECK_WRONG_TEXT = (
    "여기는 서초소방서 구급대입니다. 1흔대 남성 심정지 환자, 현재 CPR 시행하며 "
    "이송 중입니다. 목격된 심정지인가요? 네, 목격자 심정지이고 재세동이 번지회 "
    "시행했습니다. 아직 자발순환은 회복 안 됐습니다. 알겠습니다. 소생실 "
    "준비하겠습니다. 도착까지 얼마나 걸리나요? 3분 후 도착합니다."
)

# 오인식이 없는 정상 통화 문장. 정확 일치 방식에서는 여기서 교정이 나오면 곧 오교정이다
# (정상 단어를 실수로 오인식 표기에 등록한 경우 여기서 걸린다).
_SELFCHECK_CLEAN_TEXT = (
    "왼쪽 팔까지 통증이 뻗친다고 하시고 식은땀도 흘리고 있어서 심근경색을 의심하고 "
    "있습니다. 예전에 협심증 진단받은 적 있다고 합니다. 지금 심전도 모니터링 중인데 "
    "부정맥 소견 보이고 있습니다. 혈압은 100에 68이고 맥박 104회로 빈맥 소견입니다. "
    "호흡수 20회, 산소포화도 95%고 청색증은 없는 상태입니다. 산소마스크로 산소요법 "
    "시행 중이고 정맥로 확보해 놓았습니다. 세동제거기도 미리 부착해 두었습니다. "
    "도착 예정 시간은 약 6분 후입니다. 상태 악화되면 다시 연락드리겠습니다."
)


def _self_check() -> None:
    """사전과 교정 동작을 점검한다. 사전을 고친 뒤 반드시 돌릴 것."""
    dict_path = CORRECTIONS_PATH

    def section(title: str) -> None:
        print(f"\n{'=' * 10} {title} {'=' * 10}")

    section("1. 사전 형식 검사")
    problems = validate_corrections(dict_path)
    if problems:
        print(f"위반 {len(problems)}건:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print(f"이상 없음 — 등록된 오인식 {len(load_corrections(dict_path))}개")

    section("2. 교정 동작 — 오인식이 든 실측 STT 출력")
    wrong = postprocess_text(_SELFCHECK_WRONG_TEXT, dict_path)
    print("교정 후:", wrong.corrected_text)
    print(f"교정 {len(wrong.corrections)}건:")
    for c in wrong.corrections:
        print(f'  "{c.original}" -> "{c.corrected}" ({c.ngram}어절)')

    section("3. 무교정 확인 — 정상 통화 문장")
    clean = postprocess_text(_SELFCHECK_CLEAN_TEXT, dict_path)
    print(f"교정 {len(clean.corrections)}건 (0건이어야 정상)")
    for c in clean.corrections:
        print(f'  "{c.original}" -> "{c.corrected}"')

    fixed = {c.original: c.corrected for c in wrong.corrections}
    assert fixed.get("재세동이") == "제세동이", "조사 '이'를 보존하며 교정해야 한다"
    assert fixed.get("번지회") == "2회", "숫자 오인식도 등록돼 있으면 교정해야 한다"
    assert fixed.get("1흔대") == "70대", "나이 오인식도 등록돼 있으면 교정해야 한다"
    assert "심정지" in wrong.corrected_text, "정상 인식된 말은 그대로 남아야 한다"
    assert "여기는" not in fixed, "등록하지 않은 말은 건드리지 않아야 한다"

    assert not problems, (
        f"corrections.json에 위반이 {len(problems)}건 있다 (1번 참고). "
        "이 상태로는 해당 항목이 조용히 무시된다"
    )
    assert not clean.corrections, (
        "정상 문장을 고쳤다 — 정상 단어가 오인식 표기로 등록돼 있다"
    )

    section("점검 통과")
    print("모든 검사 통과")


if __name__ == "__main__":
    # Windows 기본 콘솔은 cp949라 점검 출력의 em dash에서 UnicodeEncodeError로
    # 죽는다. 라이브러리로 import될 때는 전역 stdout을 건드리면 안 되므로
    # 직접 실행하는 이 경로에서만 UTF-8로 바꾼다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _self_check()
