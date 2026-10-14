"""E-Gen 응급실·중증질환 메시지(`getEmrrmSrsillDissMsgInqire`) → 병원별 수용 제한 메시지 (2026-10-07, 규칙 기반).

병원이 E-Gen에 직접 걸어두는 "지금 이런 환자는 못 받는다" 공지다. 실측(2026-10-07): 전국 125곳·805건,
응급실 메시지(`symBlkMsgTyp=응급`, 진료과 단위 자유 텍스트 — "NICU 부재로 모든 산모 수용 불가",
"성형외과 오후 9시까지 가능") 580건과 중증질환 메시지(`중증`, 질환 코드가 붙은 차단 — "의료진 부족")
225건. 모든 건이 시작·종료 시각을 갖고, `symOutDspYon`은 전부 "차단"이었다.

중증질환 메시지의 질환 코드(`symTypCod`)는 중증질환 수용가능정보의 28항목과 같은 체계라서, 여기서
hospital_score의 15개 질환군 이름으로 옮겨 보낸다 — hub는 사건의 질환군과 문자열로만 비교하면 된다.
항목명(`symTypCodMag`)으로 맞추면 "수족지접합"↔"사지접합", "저출생체중아"↔"저체중출생아"처럼 어긋난다.
"""
from __future__ import annotations

from datetime import datetime

from egen.mapper import KST, parse_hvidate
from schema import AcceptanceMessage

#: 중증질환 메시지 질환 코드 → 질환군(hospital_score/vocabulary.py의 GROUPS와 같은 이름).
#: [확인됨 — 2026-10-07 실응답의 코드·항목명 27쌍] 자체 검사가 GROUPS와 대조한다
SEVERE_CODE_TO_GROUP: dict[str, str] = {
    "Y0010": "재관류중재술",  # 심근경색의 재관류중재술
    "Y0020": "재관류중재술",  # 뇌경색의 재관류중재술
    "Y0031": "뇌출혈수술",  # 거미막하 출혈
    "Y0032": "뇌출혈수술",  # 거미막하 출혈 외
    "Y0041": "대동맥응급",  # 흉부
    "Y0042": "대동맥응급",  # 복부
    "Y0051": "담낭담관질환",  # 담낭질환
    "Y0052": "담낭담관질환",  # 담도포함질환
    "Y0060": "복부응급수술",  # 비외상
    "Y0070": "장중첩/폐색",  # 유아
    "Y0081": "응급내시경",  # 위장관(성인)
    "Y0082": "응급내시경",  # 위장관(영유아)
    "Y0091": "응급내시경",  # 기관지(성인)
    "Y0092": "응급내시경",  # 기관지(영유아)
    "Y0100": "저체중출생아",  # 저출생체중아
    "Y0111": "산부인과응급",  # 분만
    "Y0112": "산부인과응급",  # 산과수술
    "Y0113": "산부인과응급",  # 부인과수술
    "Y0120": "중증화상",
    "Y0131": "사지접합",  # 수족지접합
    "Y0132": "사지접합",  # 수족지접합 외
    "Y0141": "응급투석",  # HD
    "Y0142": "응급투석",  # CRRT
    "Y0150": "정신과적응급",  # 응급입원
    "Y0160": "안과적수술",
    "Y0171": "영상의학혈관중재",  # 성인
    "Y0172": "영상의학혈관중재",  # 영유아
}

_KIND = {"응급": "er", "중증": "severe"}


def build_acceptance_messages(
    rows: list[dict], now: datetime | None = None
) -> dict[str, list[AcceptanceMessage]]:
    """hpid -> 지금 유효한 메시지 목록. 이미 끝난 메시지와 모르는 유형은 버린다.

    아직 시작 전인 메시지는 남긴다 — info는 30분마다 보내므로, 그 사이에 시작될 메시지를 hub가
    시작 시각에 맞춰 켤 수 있게 한다(유효 여부는 hub가 매칭 시점에 다시 본다).
    """
    now = now or datetime.now(KST)
    by_hpid: dict[str, list[AcceptanceMessage]] = {}
    for row in rows:
        hpid = (row.get("hpid") or "").strip()
        kind = _KIND.get((row.get("symBlkMsgTyp") or "").strip())
        text = (row.get("symBlkMsg") or "").strip()
        if not hpid or kind is None or not text:
            continue
        end_at = parse_hvidate(row.get("symBlkEndDtm"))
        if end_at is not None and datetime.fromisoformat(end_at) <= now:
            continue
        code = (row.get("symTypCod") or "").strip()
        severe = kind == "severe"
        by_hpid.setdefault(hpid, []).append(
            AcceptanceMessage(
                kind=kind,
                message=text,
                department=(row.get("trtPrtCodMag") or "").strip() or None,
                diseaseCode=code if severe and code else None,
                diseaseName=((row.get("symTypCodMag") or "").strip() or None) if severe else None,
                diseaseGroup=SEVERE_CODE_TO_GROUP.get(code) if severe else None,
                startAt=parse_hvidate(row.get("symBlkSttDtm")),
                endAt=end_at,
            )
        )
    return by_hpid


if __name__ == "__main__":
    from hospital_score.vocabulary import GROUPS

    assert set(SEVERE_CODE_TO_GROUP.values()) == set(GROUPS), "질환군 이름이 hospital_score와 어긋남"

    now = datetime(2026, 10, 7, 12, 0, tzinfo=KST)
    base = {"hpid": "A1", "symBlkSttDtm": "20261002000000", "symBlkEndDtm": "20261009000000"}
    rows = [
        {**base, "symBlkMsgTyp": "응급", "symTypCod": "Y000", "symTypCodMag": "응급실",
         "trtPrtCodMag": "산부인과", "symBlkMsg": "모든 산모 수용 불가"},
        {**base, "symBlkMsgTyp": "중증", "symTypCod": "Y0131", "symTypCodMag": "수족지접합",
         "trtPrtCodMag": "성형외과", "symBlkMsg": "의료진 부족"},
        {**base, "symBlkMsgTyp": "중증", "symTypCod": "Y0042", "symBlkMsg": "끝난 메시지",
         "symBlkEndDtm": "20261007110000"},
        {**base, "symBlkMsgTyp": "공지", "symBlkMsg": "모르는 유형"},
        {**base, "symBlkMsgTyp": "응급", "symBlkMsg": ""},
    ]
    got = build_acceptance_messages(rows, now)["A1"]
    assert [m.kind for m in got] == ["er", "severe"], got
    assert got[0].diseaseGroup is None and got[0].diseaseName is None and got[0].department == "산부인과"
    assert got[1].diseaseGroup == "사지접합" and got[1].diseaseCode == "Y0131"
    assert got[1].endAt == "2026-10-09T00:00:00+09:00"
    print("egen.messages 자체 검사 통과")
