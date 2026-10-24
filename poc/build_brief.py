"""첫 연락에 첨부할 3쪽 분석 요약자료 생성기.

이 파일은 **측정하지 않는다.** 숫자는 전부 `IR_NUMBERS.md` 정본에서 손으로 옮긴 값이고,
계산 근거는 첨부할 두 리포트(`out/gyeongnam.html`·`out/jinju_replay.html`)가 진다.
그래서 여기는 데이터 파일을 읽지 않는다 — 읽는 순간 정본이 둘이 된다.

숫자를 고칠 일이 생기면 **`IR_NUMBERS.md`를 먼저 고치고 아래 N 상수로 옮긴다.**

쓰지 않는 것 (첫 연락에서 의도적으로 뺀 것):
  · 거미줄 분배 모델 · MCI 시뮬레이션 수치 · 구체 AI 모델명
    → 면담이 성사되면 기술 자료로 설명한다. 첫 장에서는 "문제를 확인하고 싶다"는
      요청의 무게를 깎는다.
  · "병상은 병목이 아니다" 같은 단정 → 관측된 분포만 적는다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다.

    conda activate dev
    cd poc && python build_brief.py      # API 호출 0회 · 데이터 파일 읽지 않음
"""

from __future__ import annotations

import os

from report_base import esc, page

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "brief_gyeongnam.html")

# ── 정본에서 옮긴 숫자 (출처: IR_NUMBERS.md, 기준일 2026-10-12 스냅샷) ───────────
N = {
    "기준일": "2026-10-12",
    "구간": "2026-08-12 ~ 10-12",
    "달력일": 62,
    "관측일": 42,
    "결측": "2026-08-17 ~ 09-05",
    "폴링": "2,984",
    "전국목록": 530,
    "전국병상응답": 416,
    "hvec커버": "100%",
    "정원커버": "99.8%",
    "경남기관": 48,
    "경남만실중앙": "0.3%",
    "경남만실최대": "14%",
    "변화율": "28 ~ 50%",
    "경남공백": 84,
    "고립수": 16,
    "고립공백": 96,
    "고립센터거리": "23.1",
    "그외공백": 78,
    "그외센터거리": "4.5",
    "진주기관": 8,
    "진주공백": 80,
    "진주칸": "224칸 중 180칸",
    "진주거리중앙": "1.86",
    "진주쌍": "28쌍 중 27쌍",
    "진주만실": "0.0 ~ 2.4%",
    "진주센터밖": 42,
    "진주구급차": 10,
}

# 등급별 공백 — (등급, 기관 수, 공백 %)
GRADES = [
    ("권역응급의료센터", 3, 13),
    ("지역응급의료센터", 8, 58),
    ("지역응급의료기관", 24, 93),
    ("응급실운영신고기관", 13, 99),
]

# 진주 밖으로 나가야 하는 곳 (고립 16곳 중 센터가 경남 밖인 7곳)
OUT_OF_PROVINCE = "거제 · 거창 · 남해 · 창녕 · 하동 · 함양 · 합천"

EXTRA_CSS = """
<style>
.viz-root{max-width:760px}
.brief-head{border-bottom:1px solid var(--border);padding-bottom:14px;margin-bottom:22px}
.brief-head .kicker{font-size:13px;color:var(--muted);letter-spacing:.02em}
.brief-head h1{margin:6px 0 10px;font-size:25px;line-height:1.3}
.brief-head .meta{font-size:13px;color:var(--ink2);line-height:1.7}
.lede{font-size:15px;line-height:1.75;border-left:3px solid var(--series);
      padding:2px 0 2px 16px;margin:0 0 24px}
.caveat{background:var(--surface);border:1px solid var(--border);border-radius:8px;
        padding:14px 16px;font-size:13.5px;line-height:1.7;color:var(--ink2);margin:16px 0}
.caveat b{color:var(--ink)}
.bars{margin:14px 0 6px}
.bar-row{display:grid;grid-template-columns:132px 1fr 46px;align-items:center;
         gap:10px;margin:7px 0;font-size:13.5px}
.bar-row .track{background:var(--grid);border-radius:3px;height:16px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:3px}
.bar-row .pct{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.bar-row .lab{color:var(--ink2)}
.bar-row .n{color:var(--muted);font-size:12px}
.flow{font-size:13.5px;line-height:2;margin:10px 0 0;padding-left:18px}
.ask{border-left:3px solid var(--good);padding:2px 0 2px 16px;margin:14px 0 0}
.ask ol{margin:6px 0 0;padding-left:20px;font-size:14px;line-height:1.85}
.foot{margin-top:28px;padding-top:14px;border-top:1px solid var(--border);
      font-size:12.5px;color:var(--muted);line-height:1.8}
@media print{
  .viz-root{max-width:none}
  .pagebreak{page-break-before:always}
  h2{page-break-after:avoid}
  table,.caveat,.bars,.ask{page-break-inside:avoid}
}
</style>
"""


def bar(label: str, n: int, pct: int, color: str) -> str:
    return (
        '<div class="bar-row">'
        f'<div class="lab">{esc(label)}<br><span class="n">{n}곳</span></div>'
        f'<div class="track"><div class="fill" style="width:{pct}%;background:{color}"></div></div>'
        f'<div class="pct">{pct}%</div>'
        "</div>"
    )


def build() -> str:
    o: list[str] = []
    A = o.append

    # ── 1쪽 ───────────────────────────────────────────────────────────────
    A('<div class="brief-head">')
    A('<div class="kicker">공개 데이터 분석 요약 · 자문 요청 자료</div>')
    A("<h1>응급환자 이송 과정의 정보 공백<br>경상남도 공개 데이터 관측 결과</h1>")
    A(
        '<div class="meta">'
        f'Playground · 골든링크(GoldenLink) 개발팀<br>'
        f'기준일 {esc(N["기준일"])} · 수집 구간 {esc(N["구간"])}'
        f'(달력 {N["달력일"]}일 중 관측일 {N["관측일"]}일)<br>'
        "자료원: 국립중앙의료원 E-Gen 공개 API · 건강보험심사평가원 공개 API · 소방청 119안전센터 현황"
        "</div>"
    )
    A("</div>")

    A(
        '<p class="lede">저희가 확인하고 싶은 것은 <b>병상의 수가 아니라, 개별 환자를 '
        "수용할 수 있는지 판단하는 데 필요한 정보</b>입니다. 공개 데이터에서는 그 정보가 "
        f'경남 {N["경남기관"]}개 기관 기준 <b>약 {N["경남공백"]}%</b> 비어 있었고, '
        f'주변에 대안이 없는 {N["고립수"]}개 기관에서는 <b>약 {N["고립공백"]}%</b>였습니다. '
        "이 관측이 실제 현장에서 어떤 의미를 가지는지 의견을 구하고자 정리하였습니다.</p>"
    )

    A("<h2>1. 무엇을 어떻게 보았는가</h2>")
    A("<table>")
    A("<tr><th>항목</th><th>내용</th></tr>")
    A(
        "<tr><td>자료원</td><td>E-Gen 공개 API 3종(기관 목록 · 실시간 가용병상 · "
        "중증질환 수용가능 신고), 심평원 공개 API 3종(병원정보 · 의료기관별 상세 · "
        "전문병원 지정), 소방청 119안전센터 현황</td></tr>"
    )
    A(
        f'<tr><td>관측 기간</td><td>{esc(N["구간"])} · 달력 {N["달력일"]}일 중 '
        f'<b>관측일 {N["관측일"]}일</b>(자체 수집 중단으로 {esc(N["결측"])} 결측)</td></tr>'
    )
    A(f'<tr><td>관측 횟수</td><td>응급실 병상 {esc(N["폴링"])}회</td></tr>')
    A(
        "<tr><td>환자 자료</td><td><b>사용하지 않았습니다.</b> 환자 정보는 한 건도 "
        "포함되어 있지 않습니다</td></tr>"
    )
    A("<tr><td>재현</td><td>저장소 코드로 추가 API 호출 없이 재현됩니다</td></tr>")
    A("</table>")

    A(
        '<div class="caveat">'
        "<b>E-Gen은 과거 이력을 제공하지 않습니다.</b> 시점 간 변화를 보려면 직접 쌓아야 하므로 "
        "자체 수집기를 두고 축적하였습니다. 특정 기관을 평가하기 위한 자료가 아니며, 아래 수치는 "
        "모두 <b>공개된 신고 정보의 분포</b>입니다."
        "</div>"
    )

    A("<h2>2. 가용 병상 정보는 비교적 충실하게 제공되고 있습니다</h2>")
    A("<table>")
    A("<tr><th>지표</th><th>값</th></tr>")
    A(f'<tr><td>전국 응급의료기관 목록</td><td>{N["전국목록"]}곳</td></tr>')
    A(
        f'<tr><td>실시간 병상 응답이 오는 곳</td><td>{N["전국병상응답"]}곳 '
        f'({round(N["전국병상응답"] / N["전국목록"] * 100)}%)</td></tr>'
    )
    A(f'<tr><td>응급실 가용 병상 값 커버리지</td><td>{esc(N["hvec커버"])}</td></tr>')
    A(f'<tr><td>응급실 정원 값 커버리지</td><td>{esc(N["정원커버"])}</td></tr>')
    A(
        f'<tr><td>경남, 가용 병상 0 이하였던 시간 비율</td>'
        f'<td>중앙 <b>{esc(N["경남만실중앙"])}</b> · 최대 {esc(N["경남만실최대"])}</td></tr>'
    )
    A(f'<tr><td>관측 시점마다 값이 바뀐 비율</td><td>{esc(N["변화율"])}</td></tr>')
    A("</table>")

    A(
        '<div class="caveat">'
        "<b>이것을 병상이 부족하지 않다는 뜻으로 읽지 않았습니다.</b> 저희가 본 것은 신고된 "
        "숫자의 분포이고, 환자 수용이 어려워지는 원인을 규명한 것이 아닙니다. 또한 중환자실 · "
        "수술실 등 배후 진료 역량 항목은 갱신 양상이 응급실과 다릅니다. "
        "<b>이 해석이 현장과 맞는지가 저희가 가장 먼저 여쭙고 싶은 부분입니다.</b>"
        "</div>"
    )

    # ── 2쪽 ───────────────────────────────────────────────────────────────
    A('<h2 class="pagebreak">3. 비어 있는 것은 "이 환자를 받을 수 있는가"입니다</h2>')
    A(
        f'<p>중증질환 수용가능 신고 28항목 기준, 경남 {N["경남기관"]}개 기관 전체를 분모로 한 '
        f'"알 수 없음" 비율은 <b>{N["경남공백"]}%</b>입니다. 등급에 따라 계단 모양으로 나타납니다.</p>'
    )
    A('<div class="bars">')
    for i, (name, n, pct) in enumerate(GRADES):
        A(bar(name, n, pct, f"var(--g-{i})"))
    A("</div>")
    A(
        f'<p>구급대가 가장 자주 상대하는 아래쪽 등급에서 공백이 가장 넓습니다. '
        f'다만 <b>"알 수 없음"은 "수용 불가"가 아니라 미신고를 뜻합니다.</b> 또한 본 항목 '
        f"28칸만 세므로, 동반 메시지 칸에 내용을 적어 둔 기관이 있어 이 비율은 실제보다 "
        f"<b>높게 잡힌 보수적인 값</b>입니다.</p>"
    )

    A("<h2>4. 주변에 대안이 없는 지역에서 공백이 더 넓습니다</h2>")
    A(
        "<p>반경 5km 안에 다른 응급실이 하나도 없는 기관과 그 외를 비교하였습니다"
        "(거리는 직선거리이며 도 경계를 무시하고 계산하였습니다).</p>"
    )
    A("<table>")
    A(
        "<tr><th></th><th>기관 수</th><th>신고 공백</th>"
        "<th>응급의학과<br>전문의 1명 이하</th><th>가장 가까운<br>응급의료센터</th></tr>"
    )
    A(
        f'<tr><td><b>반경 5km 안 대안 없음</b></td><td>{N["고립수"]}</td>'
        f'<td><b>{N["고립공백"]}%</b></td><td><b>16/16</b></td>'
        f'<td><b>중앙 {esc(N["고립센터거리"])}km</b></td></tr>'
    )
    A(
        f'<tr><td>그 외</td><td>32</td><td>{N["그외공백"]}%</td><td>19/32</td>'
        f'<td>중앙 {esc(N["그외센터거리"])}km</td></tr>'
    )
    A("</table>")
    A(
        f'<p>이 {N["고립수"]}곳 중 <b>7곳은 가장 가까운 응급의료센터가 경남 밖</b>입니다'
        f"({esc(OUT_OF_PROVINCE)}). 가장 먼 곳은 거창 53km(김천) · 합천 43km(대구) · "
        f"통영 38km · 함양 31km(남원)이고, 센터까지 30km를 넘는 곳이 9곳입니다. "
        f"<b>정보가 비어 있는 지역과 대안이 없는 지역이 같은 곳에서 겹칩니다.</b></p>"
    )
    A(
        '<div class="caveat">'
        "<b>전문의 수는 보유 인원이고 특정 시각의 당직이 아닙니다.</b> 당직 정보는 공개 "
        '데이터에 없습니다. 저희는 "역량의 성격이 다르다"는 관측만 하였고, '
        '"수용할 수 없다"는 판단은 하지 않았습니다.'
        "</div>"
    )

    # ── 3쪽 ───────────────────────────────────────────────────────────────
    A('<h2 class="pagebreak">5. 진주 지역을 검토 후보로 생각하는 이유</h2>')
    A("<table>")
    A("<tr><th>지표</th><th>값</th></tr>")
    A(
        f'<tr><td>응급의료기관</td><td>{N["진주기관"]}곳 '
        "(권역 1 · 지역센터 2 · 지역기관 3 · 신고기관 2)</td></tr>"
    )
    A(
        f'<tr><td>기관 상호 거리</td><td>중앙 {esc(N["진주거리중앙"])}km · '
        f'{esc(N["진주쌍"])}이 5km 이내</td></tr>'
    )
    A(
        f'<tr><td>중증질환 신고 공백</td><td><b>{N["진주공백"]}%</b> '
        f'(8곳 × 28항목 {esc(N["진주칸"])})</td></tr>'
    )
    A(f'<tr><td>가용 병상 0 이하였던 시간 비율</td><td>{esc(N["진주만실"])}</td></tr>')
    A("<tr><td>응급의학과 전문의 3명 이상</td><td>8곳 중 <b>3곳</b></td></tr>")
    A(
        f'<tr><td>진주 밖 가장 가까운 응급의료센터</td>'
        f'<td>직선 <b>{N["진주센터밖"]}km</b></td></tr>'
    )
    A(f'<tr><td>진주소방서 구급차</td><td>{N["진주구급차"]}대 (경남 공동 1위)</td></tr>')
    A("</table>")
    A(
        f'<p>경남 {N["경남기관"]}개 기관 가운데 <b>진주 {N["진주기관"]}곳만 반경 5km 안에 '
        f"서로 다 들어옵니다.</b> 여러 기관에 동시에 정보를 전달하는 방식을 확인할 수 있는 "
        f"최소 단위가 여기서 성립하고, 권역응급의료센터가 그 안에 있습니다. 또한 2절과 3절의 "
        f"관측이 한 지역에서 같이 보입니다. 병상은 관측 기간 내내 여유가 있었는데"
        f'({esc(N["진주만실"])}) 수용가능 신고는 {N["진주공백"]}%가 비어 있고, 응급의학과 '
        f"전문의 3명 이상인 곳은 3곳인데 공개 화면에서는 8곳이 모두 같은 "
        f'"응급의료기관"으로 보입니다.</p>'
    )

    A("<h2>6. 저희가 구현한 것</h2>")
    A("<p>위 관측이 요구한 것은 세 가지였습니다.</p>")
    A("<table>")
    A("<tr><th>관측</th><th>구현</th></tr>")
    A(
        "<tr><td>구급대원이 통화하면서 입력까지 할 수 없다</td>"
        "<td>통화 내용을 AI가 인식하고 구조화합니다. 구급대원은 <b>확인과 수정만</b> 합니다</td></tr>"
    )
    A(
        "<tr><td>순차적으로 전화를 거는 데 시간이 든다</td>"
        "<td>권역 안 후보 기관에 <b>동시에</b> 전달합니다</td></tr>"
    )
    A(
        "<tr><td>수용가능 여부를 알려 주는 정보가 비어 있다</td>"
        "<td>공개 역량 자료를 결합해 보완하고, <b>보완에 사용한 근거를 화면에 함께 표시</b>합니다</td></tr>"
    )
    A("</table>")
    A(
        '<div class="caveat">'
        "<b>AI는 정보의 추출과 구조화만 담당합니다.</b> 후보 기관의 순위는 규칙으로 정하고 "
        '"왜 이 순서인지"를 화면에 함께 적으며, 최종적인 확인과 이송 결정은 현장 관계자가 '
        "수행합니다. 음성 인식과 구조화는 기기 안에서 처리하여 환자 음성이 외부로 나가지 "
        "않도록 하였습니다."
        "</div>"
    )

    A("<h2>7. 여쭙고 싶은 것</h2>")
    A('<div class="ask">')
    A("<ol>")
    A(
        "<li>저희가 공개 데이터에서 확인한 정보 공백이 실제 지역 응급의료체계에서 "
        "어떤 의미를 가지는지, 그리고 저희가 놓치고 있는 공백은 무엇인지</li>"
    )
    A(
        "<li>현재 구현한 기능 가운데 현장에 도움이 될 수 있는 부분과, 덜어내야 할 부분은 "
        "무엇인지</li>"
    )
    A(
        "<li>필요성이 확인될 경우, 진주 지역을 중심으로 <b>업무 절차를 바꾸지 않는</b> "
        "관찰 단계의 검증을 논의할 수 있을지</li>"
    )
    A("</ol>")
    A("</div>")
    A(
        "<p>현 단계에서 시스템 도입이나 환자 데이터 제공을 요청드리는 것은 아닙니다. "
        "저희가 발견한 문제가 현장에서도 해결할 가치가 있는 문제인지 먼저 확인하고 싶습니다. "
        "현장의 판단이 저희 가설과 다르다면 개발 방향을 수정하겠습니다.</p>"
    )

    A(
        '<div class="foot">'
        "<b>한계</b> · 동시 전달의 효과는 실제 사용 환경에서만 측정되므로, 저희는 이송 지연 "
        "개선을 주장할 근거를 아직 가지고 있지 않습니다. 공개 데이터는 현장을 설명하지 "
        '못합니다. "알 수 없음"은 미신고를 뜻하며 수용 불가가 아닙니다. 거리는 모두 '
        "직선거리입니다. 관측 구간에는 결측이 있습니다"
        f'({esc(N["결측"])}).<br>'
        "<b>첨부</b> · 경남 응급의료 정보 현황 리포트 · 진주 지역 상세 리포트"
        "(두 자료 모두 계산 근거를 포함하며, 환자 정보는 한 건도 들어 있지 않습니다)"
        "</div>"
    )

    return EXTRA_CSS + page(
        "응급환자 이송 과정의 정보 공백 — 경상남도 공개 데이터 관측 결과", "\n".join(o)
    )


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build())
    print(f"생성: {OUT}")
    print(f'  기준일 {N["기준일"]} · 경남 공백 {N["경남공백"]}% · '
          f'고립 {N["고립수"]}곳 {N["고립공백"]}% · 진주 {N["진주공백"]}%')
    print("  숫자 출처: IR_NUMBERS.md (이 파일은 측정하지 않는다)")


if __name__ == "__main__":
    main()
