"""구간 원문 -> 값. 모델이 찾은 VITALS·AGE·ONSET 구간을 규칙으로 읽는다.

- 숫자: 아라비아 숫자, 한자어 수사(일~구, 십·백·천, 영), 고유어(하나~아흔아홉), 소수("삼십육점팔", "39도 8부")
  - 띄어 쓴 수사("백십 육", "구십 칠")는 이어서 한 수로 읽는다.
- 활력징후: 키워드 뒤의 첫 수. 혈압은 "X에 Y", "X/Y", "X 바이 Y". 혈압 키워드 없이 "X에 Y"만 있어도 혈압이다.
  - "안 잡힘", "측정 안 됨", "측정불가"는 "측정불가"다.
- 나이: "N세/살", "생후 N개월", "N개월", "N대(후반)", "NN년생"(2026년 기준)
- 발생 시각: "N분/시간/일/주 전", "방금", "N시간 반". 시각("오후 3시")이나 "어제 저녁"처럼 기준 시점이 필요한 표현은 None이다.
"""

from __future__ import annotations

import re

CURRENT_YEAR = 2026

_DIGITS = {"영": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_UNITS = {"십": 10, "백": 100, "천": 1000}
_NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_NATIVE_ONES = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "석": 3, "넷": 4, "네": 4, "넉": 4, "다섯": 5, "여섯": 6,
                "일곱": 7, "여덟": 8, "아홉": 9}
_SINO = "영일이삼사오육륙칠팔구십백천"
_NATIVE_TENS_RE = "|".join(sorted(_NATIVE_TENS, key=len, reverse=True))
_NATIVE_ONES_RE = "|".join(sorted(_NATIVE_ONES, key=len, reverse=True))

# 수 하나: 아라비아(소수 포함) | 한자어 수사(띄어쓰기 허용, 점 소수 허용) | 고유어
NUMBER_RE = (
    rf"(?:\d+(?:\.\d+)?"
    rf"|[{_SINO}](?:\s?[{_SINO}])*(?:\s?점\s?[{_SINO}](?:\s?[{_SINO}])*)?"
    rf"|(?:{_NATIVE_TENS_RE})(?:{_NATIVE_ONES_RE})?|(?:{_NATIVE_ONES_RE}))"
)


def _sino_int(s: str) -> int | None:
    s = s.replace(" ", "")
    if not s or any(c not in _SINO for c in s):
        return None
    if all(c in _DIGITS for c in s) and len(s) > 1:  # "구칠" 같은 자릿수 나열
        return int("".join(str(_DIGITS[c]) for c in s))
    total, current = 0, 0
    for c in s:
        if c in _DIGITS:
            current = _DIGITS[c]
        else:
            total += (current or 1) * _UNITS[c]
            current = 0
    return total + current


def to_number(token: str) -> float | None:
    """수 하나를 읽는다. 못 읽으면 None."""
    token = token.strip()
    if not token:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    m = re.fullmatch(rf"({_NATIVE_TENS_RE})?({_NATIVE_ONES_RE})?", token)
    if m and (m.group(1) or m.group(2)):
        return float(_NATIVE_TENS.get(m.group(1), 0) + _NATIVE_ONES.get(m.group(2), 0))
    if "점" in token:
        whole, frac = token.split("점", 1)
        w = _sino_int(whole)
        f = "".join(str(_DIGITS[c]) for c in frac.replace(" ", "") if c in _DIGITS)
        return float(f"{w}.{f}") if w is not None and f else None
    if len(token) > 1 and token[-1] in "이일" and token[-2] in _DIGITS:  # "구십삼이고"의 "이"는 조사
        token = token[:-1]
    value = _sino_int(token)
    return float(value) if value is not None else None


def _as_int(x: float | None) -> int | float | None:
    return int(x) if x is not None and float(x).is_integer() else x


def _first_number(text: str) -> re.Match | None:
    """글 안의 첫 수. "맥박이 100"의 "이"처럼 낱말에 붙은 한 글자 한자어 수사는 건너뛴다."""
    for m in re.finditer(rf"({NUMBER_RE})", text):
        token = m.group(1)
        if len(token) == 1 and not token.isdigit():
            before = text[m.start() - 1] if m.start() > 0 else " "
            after = text[m.end()] if m.end() < len(text) else " "
            if re.match(r"[가-힣]", before) or re.match(r"[가-힣]", after):
                continue
        return m
    return None


_UNMEASURABLE = re.compile(
    r"(안\s?잡|잡히지\s?않|측정\S*\s?(?:안|불가|되지\s?않)|체크\S*\s?안|촉지\S*\s?(?:안|않|불가)|안\s?나와|무맥)"
)
_VITAL_KEYS = {
    "hr": r"(?:맥박|심박수?|HR|펄스|pulse)",
    "rr": r"(?:호흡수?|RR)",
    "spo2": r"(?:산소\s?포화도|산소\s?포아도|포화도|새츄레이션|사츄레이션|SpO2|SPO2|산소)",
    "glucose": r"(?:혈당|BST|bst|당\s?수치)",
    "bt": r"(?:체온|열|BT)",
}
_BP_RE = re.compile(rf"(?:혈압|BP)?\s*(?:은|는|이)?\s*({NUMBER_RE})\s*(?:에|/|바이|over)\s*({NUMBER_RE})")


def parse_vitals(text: str) -> dict:
    """활력징후 보고 한 묶음 -> {sbp, dbp, hr, rr, bt, spo2, glucose}. 없는 값은 None."""
    out = {k: None for k in ("sbp", "dbp", "hr", "rr", "bt", "spo2", "glucose")}
    t = text
    bp_key = re.search(r"(혈압|BP)", t)
    if bp_key and _UNMEASURABLE.search(t[bp_key.end(): bp_key.end() + 12]):
        out["sbp"] = out["dbp"] = "측정불가"
    else:
        m = _BP_RE.search(t)
        if m:
            s, d = to_number(m.group(1)), to_number(m.group(2))
            if s is not None and d is not None and s > d:
                out["sbp"], out["dbp"] = _as_int(s), _as_int(d)
    any_key = re.compile("|".join(_VITAL_KEYS.values()) + r"|혈압|BP")
    for key, pattern in _VITAL_KEYS.items():
        for km in re.finditer(pattern, t):
            rest = t[km.end(): km.end() + 30]
            if key == "rr" and km.group(0).startswith("호흡") and re.match(r"\s?(?:곤란|음|기|정지|이\s|을|이\s?얕|이\s?빠)", rest):
                continue  # 호흡곤란·호흡음 등은 호흡수가 아니다
            nxt = any_key.search(rest)
            window = rest[: nxt.start()] if nxt else rest  # 다음 활력징후 키워드 앞까지만 본다
            if _UNMEASURABLE.search(window[:20]) and not re.search(r"\d", window[:20]):
                out[key] = "측정불가"
                break
            nm = None
            if key == "spo2":  # "산소 15리터에 94%"처럼 다른 수가 끼면 %가 붙은 수가 포화도다
                nm = re.search(rf"({NUMBER_RE})\s?(?:%|퍼센트|프로|퍼)", window)
                if nm is None:
                    nm = next((c for c in re.finditer(rf"({NUMBER_RE})", window)
                               if not re.match(r"\s?(?:리터|L|l|ℓ)", window[c.end():])
                               and not (len(c.group(1)) == 1 and not c.group(1).isdigit())), None)
                    if nm and nm.start() > 15:
                        nm = None
            if nm is None:
                # 키워드 뒤 짧은 군말("분당", "재측정 결과는", "실온에서") 다음의 첫 수
                nm = _first_number(window)
                if not nm or nm.start() > 15:
                    continue
            value = to_number(nm.group(1))
            if value is None:
                continue
            if key == "bt":
                bu = re.match(rf"\s?도\s?({NUMBER_RE})\s?부?", window[nm.end():])
                if bu and value == int(value):
                    frac = to_number(bu.group(1))
                    if frac is not None and frac < 10:
                        value = value + frac / 10
                if not 30 <= value <= 43:
                    continue
            out[key] = _as_int(value)
            break
    if out["bt"] is None:  # "36.8도로 정상"처럼 키워드 없이 체온만 말한 경우
        m = re.search(rf"({NUMBER_RE})\s?도(?:\s?({NUMBER_RE})\s?부)?", t)
        value = to_number(m.group(1)) if m else None
        if value is not None and m.group(2):
            value += (to_number(m.group(2)) or 0) / 10
        if value is not None and 34 <= value <= 42:
            out["bt"] = _as_int(value)
    return out


_BAND_RE = re.compile(rf"({NUMBER_RE})\s?대")


def parse_age(text: str) -> dict:
    """나이 구간 -> {years, months, band}. 연령대만 말하면 band만."""
    t = text
    if re.search(r"10\s?세\s?미만", t):
        return {"years": None, "months": None, "band": "10세 미만"}
    m = re.search(rf"({NUMBER_RE})\s?년생", t)
    if m:
        n = to_number(m.group(1))
        if n is not None:
            year = int(n) + (1900 if n > CURRENT_YEAR % 100 else 2000) if n < 100 else int(n)
            return {"years": CURRENT_YEAR - year, "months": None, "band": None}
    m = re.search(rf"생후\s?({NUMBER_RE})\s?(개월|일|주)", t) or re.search(rf"({NUMBER_RE})\s?(개월)", t)
    if m:
        n = to_number(m.group(1))
        if n is not None:
            return {"years": None, "months": int(n) if m.group(2) == "개월" else 0, "band": None}
    if re.search(r"(신생아|출생|태어난|갓\s?난|방금\s?낳)", t):
        return {"years": None, "months": 0, "band": None}
    for m in re.finditer(rf"({NUMBER_RE})\s?(?:세|살)", t):
        token = m.group(1)
        # "여성분이세요"의 "이"처럼 낱말 속 한 글자는 수가 아니다
        if len(token) == 1 and not token.isdigit() and m.start() > 0 and re.match(r"[가-힣]", t[m.start() - 1]):
            continue
        n = to_number(token)
        if n is not None and n < 130:
            return {"years": int(n), "months": None, "band": None}
    m = _BAND_RE.search(t)
    if m:
        n = to_number(m.group(1))
        if n is not None and n % 10 == 0 and 10 <= n <= 100:
            return {"years": None, "months": None, "band": "90대 이상" if n >= 90 else f"{int(n)}대"}
    if re.search(r"(애기|아기|영아|유아|남아|여아|신생아)", t):
        return {"years": None, "months": None, "band": "10세 미만"}
    return {"years": None, "months": None, "band": None}


_ONSET_UNITS = {"분": 1, "시간": 60, "일": 1440, "주일": 10080, "주": 10080, "달": 43200, "개월": 43200}
_NATIVE_DAYS = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "열흘": 10, "보름": 15}


def parse_onset(text: str) -> int | None:
    """발생 시각 구간 -> 몇 분 전. 계산할 수 없으면 None.

    "N시간 M분"은 더한다. "N시간 반"은 30분을 더한다. 하루·이틀·사흘 같은 고유어 날수도 읽는다.
    "오후 3시", "어제 저녁"처럼 기준 시점이 필요한 표현은 None.
    """
    t = re.sub(rf"({NUMBER_RE})\s?시\s?({NUMBER_RE})\s?분", " ", text)  # 시각(오후 2시 15분)은 경과 시간이 아니다
    t = t.replace("일주일", "1주일")
    if re.search(r"(방금|막\s?전)", t):
        return 0
    if "반나절" in t:
        return 720
    if re.search(r"(엊그제|그저께|그제)", t):
        return 2880
    m = re.search("(" + "|".join(_NATIVE_DAYS) + r")(?!\s?종일)", t)
    if m:
        return _NATIVE_DAYS[m.group(1)] * 1440
    m = re.search(rf"({NUMBER_RE})\s?(시간|분|주일|일|주|달|개월)(?!\s?(?:후|뒤))(\s?반)?(?:\s?({NUMBER_RE})\s?분)?", t)
    if not m:
        return None
    n = to_number(m.group(1))
    if n is None:
        return None
    unit = _ONSET_UNITS[m.group(2)]
    minutes = n * unit
    if m.group(3):
        minutes += unit / 2
    if m.group(4) and m.group(2) == "시간":
        minutes += to_number(m.group(4)) or 0
    return int(minutes)
