"""한글·아라비아 숫자 문자열 -> 수치. 모델이 고른 활력징후 구간의 글자를 숫자로 읽는다(vitals.py). 원본 MF_BERT_vitals/ko_number.py 그대로.

통화 전사는 숫자를 '백육십팔'(한자어)·'열여섯'(순우리말)·'8십4'(섞어 쓰기)·'36점8'·'삼십육도 오부'처럼 적는다.
"""
import re

SINO_DIGITS = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
NATIVE_DIGITS = {"하나": 1, "한": 1, "두": 2, "세": 3, "네": 4, "둘": 2, "셋": 3, "넷": 4, "다섯": 5, "여섯": 6,
                 "일곱": 7, "여덟": 8, "아홉": 9}
#: 십의 전사 오타(구심 칠·구시구)도 받는다. 값이 맞아야 쓰이므로 다른 낱말과 겹쳐도 해가 적다
UNITS = {"십": 10, "심": 10, "시": 10, "신": 10, "백": 100, "천": 1000}
NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70,
               "여든": 80, "아흔": 90}
#: 소수점 구실을 하는 글자. '도'는 뒤에 한 자리만 온다 (삼십육도 오부)
DECIMAL_SEPARATORS = ("점", "쩜", "도")

_DIGITS = {**SINO_DIGITS, **NATIVE_DIGITS}
#: 긴 낱말부터 맞춘다 (일곱이 일+곱으로 갈라지지 않게)
_LEXICON = sorted([*_DIGITS, *UNITS, *NATIVE_TENS], key=len, reverse=True)
_ARABIC_RUN = re.compile(r"\d+")
_ARABIC_NUMBER = re.compile(r"\d+(\.\d+)?")


def _tokens(s: str) -> list[tuple[str, int | str]] | None:
    out: list[tuple[str, int | str]] = []
    i = 0
    while i < len(s):
        m = _ARABIC_RUN.match(s, i)
        if m:
            out.append(("digit", m.group()))
            i = m.end()
            continue
        for w in _LEXICON:
            if s.startswith(w, i):
                if w in UNITS:
                    out.append(("unit", UNITS[w]))
                elif w in NATIVE_TENS:
                    out.append(("ten", NATIVE_TENS[w]))
                else:
                    out.append(("digit", str(_DIGITS[w])))
                i += len(w)
                break
        else:
            return None
    return out


def _parse_int(s: str, strict: bool = False) -> int | None:
    """공백 없는 정수 표기. 단위(십백천) 앞의 숫자는 곱하고, 단위 없이 이어진 숫자는 이어 붙인다(구구 -> 99).
    strict면 단위 뒤에 숫자가 둘 이상 이어지는 것('구십팔이' = 구십 + 팔 + 이)을 문법에 안 맞는다고 보고 None을 돌려준다."""
    toks = _tokens(s)
    if not toks:
        return None
    total, pend = 0, ""
    for kind, val in toks:
        if kind == "digit":
            pend += val
        elif kind == "unit":
            if len(pend) > 1:
                return None
            total += (int(pend) if pend else 1) * val
            pend = ""
        else:
            if pend:
                return None
            total += val
    if strict and total and len(pend) > 1:
        return None
    return total + (int(pend) if pend else 0)


def _digit_string(s: str) -> str | None:
    """소수점 뒤 숫자: 낱자 숫자만 이어 붙인다."""
    toks = _tokens(s)
    if not toks or any(k != "digit" for k, _ in toks):
        return None
    return "".join(v for _, v in toks)


def parse_number(s: str, strict: bool = False) -> float | int | None:
    """'백육십팔'·'열여섯'·'삼십 육 점 팔'·'삼십육도 오' -> 168·16·36.8·36.5. 읽을 수 없으면 None.
    strict는 _parse_int의 것에 더해 소수점 뒤를 한 자리로 제한한다(체온 '삼십육점팔이'가 36.82가 되지 않게)."""
    s = s.replace(" ", "")
    if not s:
        return None
    if _ARABIC_NUMBER.fullmatch(s):
        return float(s) if "." in s else int(s)
    for sep in DECIMAL_SEPARATORS:
        head, found, tail = s.partition(sep)
        if not found:
            continue
        head_n = _parse_int(head, strict)
        digits = _digit_string(tail)
        if head_n is None or not digits or ((sep == "도" or strict) and len(digits) != 1):
            return None
        return float(f"{head_n}.{digits}")
    return _parse_int(s, strict)


def parse_temperature(s: str, strict: bool = False) -> float | None:
    """체온 표기. parse_number가 읽는 것 외에, 정수부 '삼십'을 생략한 '육 도 팔'(36.8)과
    소수점을 뺀 '삼십육 팔'·'삼칠육'(37.6)을 읽는다. 35~42도 범위만 인정한다."""
    v = parse_number(s, strict)
    if v is not None and 20 <= v < 45:
        return v
    s = s.replace(" ", "")
    for sep in DECIMAL_SEPARATORS:
        head, found, tail = s.partition(sep)
        if found:
            n, digits = _parse_int(head), _digit_string(tail)
            if n is not None and 5 <= n <= 9 and digits and len(digits) == 1:
                return float(f"{30 + n}.{digits}")
            return None
    for k in range(1, len(s)):
        n, digits = _parse_int(s[:k]), _digit_string(s[k:])
        if n is not None and 35 <= n <= 42 and digits and len(digits) == 1:
            return float(f"{n}.{digits}")
    return None


def candidate_spans(text: str, max_len: int = 14, parser=parse_number) -> list[tuple[int, int, float | int]]:
    """text 안에서 parser로 숫자로 읽히는 모든 부분 문자열 (시작, 끝, 값). 양끝은 공백이 아니다."""
    out = []
    n = len(text)
    for i in range(n):
        if text[i] == " ":
            continue
        for j in range(i + 1, min(n, i + max_len) + 1):
            if text[j - 1] == " ":
                continue
            v = parser(text[i:j])
            if v is not None:
                out.append((i, j, v))
    return out
