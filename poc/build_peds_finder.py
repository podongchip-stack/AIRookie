"""“지금 아이를 데려갈 수 있는 곳” — 보호자용 웹 프로토타입 생성기.

새벽 2시에 아이가 아플 때 보호자가 여는 화면 하나. 서버 없이 도는 자가완결
HTML이고, 네트워크 요청도 저장도 하지 않는다.

설계 원칙 (바꾸기 전에 반드시 이유를 적을 것)
  1. **119가 먼저다.** 맨 위에 두고, 우리 목록보다 크게 둔다. 우리 트래픽을
     깎더라도 그게 맞다 — 중증 아동이 이 화면을 보고 자가 이송하는 것이 이
     서비스가 낼 수 있는 최악의 결과다.
  2. **추천하지 않는다. 보여준다.** 정렬은 거리순뿐이고 "여기로 가세요"를 쓰지
     않는다. 틀리면 사람이 다치는 영역에서 판단을 대신하지 않는다.
  3. **모르는 건 모른다고 쓴다.** 소아 병상(hv28)은 전국 416곳 중 95곳(23%)만
     값이 오고 폴링마다 7%만 바뀐다 — 실시간이 아니다. 그래서 **실시간 병상을
     아예 쓰지 않고** 정적 역량(전문의·정원 보유)만 보여주며, 없는 곳은 빈칸을
     그럴듯하게 채우지 않고 "소아 정보 없음"으로 남긴다.
  4. **아무것도 저장하지 않는다.** 위치는 브라우저 안에서만 쓰고 보내지 않는다.
     로그인·쿠키·분석 스크립트·외부 요청이 없다. 나중에 무엇을 붙이더라도 이
     기록이 존재하지 않아야 한다 — 약속이 아니라 구조로 막는다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다.

실행:
    conda activate dev
    cd poc && python build_peds_finder.py
산출물:
    poc/out/peds_finder.html
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

from report_base import esc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
SNAP_DIR = os.path.join(INFO, "data", "snapshots_nationwide")
HIRA_DIR = os.path.join(INFO, "data", "hira")
OUT = os.path.join(HERE, "out", "peds_finder.html")

sys.path.insert(0, INFO)
from hospital_score import vocabulary as V  # noqa: E402

MK = re.compile(r"^MKioskTy\d+$")
PED_DEPT = "소아청소년과"


def iv(x) -> int | None:
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def load() -> tuple[list[dict], str]:
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.jsonl")))
    if not files:
        raise SystemExit(f"스냅샷이 없다: {SNAP_DIR}")
    latest = files[-1]
    day = os.path.basename(latest)[:10]

    listing = None
    for p in reversed(files):
        for line in open(p, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("operation") == "getEgytListInfoInqire" and rec.get("items"):
                listing = rec["items"]
                break
        if listing:
            break

    beds, severe = {}, {}
    for line in open(latest, encoding="utf-8"):
        rec = json.loads(line)
        if not rec.get("items"):
            continue
        if rec["operation"] == "getEmrrmRltmUsefulSckbdInfoInqire":
            for it in rec["items"]:
                beds[it["hpid"]] = it
        elif rec["operation"] == "getSrsillDissAceptncPosblInfoInqire":
            for it in rec["items"]:
                severe[it["hpid"]] = it

    try:
        spec = json.load(open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8"))
    except FileNotFoundError:
        spec = {}

    infant_items = [i.no for i in V.ITEMS if i.age == V.AGE_INFANT]
    rows = []
    for h in listing:
        try:
            lat, lng = float(h["wgs84Lat"]), float(h["wgs84Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        hpid = h["hpid"]
        bed = beds.get(hpid, {})
        ped_doc = next(
            (iv(x.get("dtlSdrCnt")) or 0 for x in spec.get(hpid, []) if x.get("dgsbjtCdNm") == PED_DEPT),
            0,
        )
        ped_cap = iv(bed.get("hvs02")) or 0            # 소아 응급실 정원
        nicu = (iv(bed.get("hvs19")) or 0) > 0         # 신생아중환자실 정원 보유
        sev = severe.get(hpid, {})
        infant_yes = sum(
            1 for n in infant_items if V.normalize_accept(sev.get(f"MKioskTy{n}")) == V.ACCEPT_YES
        )
        addr = h.get("dutyAddr") or ""
        rows.append(
            {
                "n": h.get("dutyName") or hpid,
                "t": (h.get("dutyTel3") or h.get("dutyTel1") or "").strip(),
                "y": round(lat, 5),
                "x": round(lng, 5),
                "g": (h.get("dutyEmclsName") or "").replace("응급의료", "").replace("기관", "기관"),
                "a": " ".join(addr.split()[:2]),
                "pd": ped_doc,
                "pc": ped_cap,
                "ni": 1 if nicu else 0,
                "iy": infant_yes,
            }
        )
    return rows, day


CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{
  color-scheme:light;
  --bg:#f7f7f5; --card:#fff; --ink:#111; --ink2:#5a5a56; --muted:#8a8a84;
  --line:#e4e3dd; --accent:#1c5cab; --accentbg:#eaf1fb;
  --urgent:#b3261e; --urgentbg:#fdecea;
  --ok:#0b7a3b; --okbg:#e8f5ec;
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --bg:#101010; --card:#1a1a19; --ink:#fff; --ink2:#c7c6bd; --muted:#8e8d86;
  --line:#2d2d2a; --accent:#7fb2f0; --accentbg:#16283f;
  --urgent:#ff8a80; --urgentbg:#361a18;
  --ok:#6fd392; --okbg:#13291c;
}}
html,body{margin:0;background:var(--bg)}
body{
  font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
  max-width:560px;margin:0 auto;padding:16px 14px 56px;
}
h1{font-size:20px;margin:4px 0 2px;letter-spacing:-.02em}
.tag{color:var(--muted);font-size:13px;margin:0 0 16px}
.urgent{
  background:var(--urgentbg);border:1px solid var(--urgent);border-radius:14px;
  padding:16px;margin-bottom:14px;
}
.urgent p{margin:0 0 12px;font-size:15px;color:var(--ink);font-weight:600;line-height:1.5}
.call119{
  display:block;background:var(--urgent);color:#fff;text-align:center;
  font-size:21px;font-weight:700;padding:16px;border-radius:11px;
  text-decoration:none;letter-spacing:.02em;
}
details.sym{margin-top:12px}
details.sym summary{font-size:14px;color:var(--ink2);cursor:pointer;padding:4px 0}
details.sym ul{margin:8px 0 0;padding-left:20px;font-size:14px;color:var(--ink2)}
details.sym li{margin:5px 0}
.controls{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
button,select{
  font:inherit;font-size:14px;padding:11px 14px;border-radius:10px;
  border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;
}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;flex:1}
.filter{display:flex;align-items:center;gap:8px;font-size:14px;color:var(--ink2);margin:0 2px 14px}
.filter input{width:18px;height:18px;accent-color:var(--accent)}
#status{font-size:13.5px;color:var(--muted);margin:0 2px 12px;min-height:20px}
.card{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:14px 15px;margin-bottom:10px;
}
.row1{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.name{font-size:17px;font-weight:650;letter-spacing:-.01em;line-height:1.35}
.dist{font-size:14px;color:var(--accent);font-weight:650;white-space:nowrap}
.sub{font-size:13px;color:var(--muted);margin:3px 0 0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.chip{font-size:12.5px;padding:4px 9px;border-radius:999px;background:var(--accentbg);color:var(--accent);white-space:nowrap}
.chip.ok{background:var(--okbg);color:var(--ok)}
.chip.none{background:transparent;color:var(--muted);border:1px dashed var(--line)}
.acts{display:flex;gap:8px;margin-top:12px}
.acts a{
  flex:1;text-align:center;text-decoration:none;font-size:15px;font-weight:600;
  padding:12px;border-radius:10px;border:1px solid var(--line);color:var(--ink);background:transparent;
}
.acts a.tel{background:var(--accent);border-color:var(--accent);color:#fff}
.note{font-size:12.5px;color:var(--muted);line-height:1.65;margin-top:22px;
      border-top:1px solid var(--line);padding-top:16px}
.note strong{color:var(--ink2)}
.note ul{padding-left:18px;margin:8px 0 0}
"""

JS_TMPL = """
var DATA=__DATA__, DAY="__DAY__";
var list=document.getElementById('list'), st=document.getElementById('status');
var onlyPeds=document.getElementById('onlyPeds'), sel=document.getElementById('sido');
var here=null;

function km(a,b,c,d){
  var R=6371,p=Math.PI/180;
  var u=(c-a)*p, v=(d-b)*p;
  var h=Math.sin(u/2)*Math.sin(u/2)+Math.cos(a*p)*Math.cos(c*p)*Math.sin(v/2)*Math.sin(v/2);
  return 2*R*Math.asin(Math.sqrt(h));
}
function tier(h){                     // 2 = 소아 대응 확인, 1 = 일부, 0 = 정보 없음
  if(h.pc>0 && h.pd>=2) return 2;
  if(h.pc>0 || h.pd>=1) return 1;
  return 0;
}
function chips(h){
  var c=[];
  if(h.pd>0) c.push('<span class="chip'+(h.pd>=2?' ok':'')+'">소아청소년과 전문의 '+h.pd+'명</span>');
  if(h.pc>0) c.push('<span class="chip ok">소아 응급 병상 '+h.pc+'석 보유</span>');
  if(h.ni)   c.push('<span class="chip">신생아 중환자실</span>');
  if(h.iy>0) c.push('<span class="chip">영유아 중증 '+h.iy+'항목 가능 신고</span>');
  if(!c.length) c.push('<span class="chip none">소아 정보 없음</span>');
  return c.join('');
}
function render(rows){
  if(!rows.length){ list.innerHTML='<p class="sub">해당하는 곳이 없습니다. 아래 필터를 꺼 보세요.</p>'; return; }
  list.innerHTML = rows.slice(0,25).map(function(h){
    var d = h._d!=null ? '<span class="dist">'+h._d.toFixed(1)+'km</span>' : '';
    var map='https://map.kakao.com/link/to/'+encodeURIComponent(h.n)+','+h.y+','+h.x;
    return '<div class="card"><div class="row1"><div class="name">'+h.n+'</div>'+d+'</div>'
      + '<p class="sub">'+h.g+' · '+h.a+'</p>'
      + '<div class="chips">'+chips(h)+'</div>'
      + '<div class="acts">'
      + (h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
      + '<a href="'+map+'" target="_blank" rel="noopener">길찾기</a>'
      + '</div></div>';
  }).join('');
}
function apply(){
  var rows=DATA.slice();
  if(here){ rows.forEach(function(h){ h._d=km(here[0],here[1],h.y,h.x); }); rows.sort(function(a,b){return a._d-b._d;}); }
  else if(sel.value){ rows=rows.filter(function(h){return h.a.indexOf(sel.value)===0;}); rows.forEach(function(h){h._d=null;}); }
  else { rows=[]; }
  if(onlyPeds.checked) rows=rows.filter(function(h){return tier(h)>0;});
  render(rows);
}
document.getElementById('loc').onclick=function(){
  if(!navigator.geolocation){ st.textContent='이 브라우저에서는 위치를 쓸 수 없습니다. 아래에서 지역을 고르세요.'; return; }
  st.textContent='위치 확인 중…';
  navigator.geolocation.getCurrentPosition(function(p){
    here=[p.coords.latitude,p.coords.longitude];
    st.textContent='가까운 순으로 보여 드립니다. 직선거리 기준이라 실제 이동 거리와 다릅니다.';
    sel.value=''; apply();
  },function(){
    st.textContent='위치를 가져오지 못했습니다. 아래에서 지역을 고르세요.';
  },{timeout:8000,maximumAge:60000});
};
sel.onchange=function(){ here=null; st.textContent = sel.value? '지역 기준 목록입니다. 가까운 순이 아닙니다.' : ''; apply(); };
onlyPeds.onchange=apply;
st.textContent='';
"""


def build(rows: list[dict], day: str) -> str:
    sidos = sorted({r["a"].split()[0] for r in rows})
    tier2 = sum(1 for r in rows if r["pc"] > 0 and r["pd"] >= 2)

    o = []
    A = o.append
    A("<title>지금 아이를 데려갈 수 있는 곳</title>")
    A('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
    A(f"<style>{CSS}</style>")

    A("<h1>지금 아이를 데려갈 수 있는 곳</h1>")
    A(
        f'<p class="tag">전국 응급의료기관 {len(rows)}곳 · 공공 데이터 기준 {esc(day)} · '
        f"위치는 이 화면 안에서만 쓰이고 저장되지 않습니다</p>"
    )

    A('<div class="urgent">')
    A("<p>숨을 제대로 못 쉬거나, 의식이 없거나, 경련이 멈추지 않으면<br>병원을 찾지 말고 지금 119입니다.</p>")
    A('<a class="call119" href="tel:119">119 전화하기</a>')
    A('<details class="sym"><summary>바로 119를 불러야 하는 경우 더 보기</summary><ul>')
    for s in [
        "숨소리가 이상하거나 가슴이 쑥쑥 들어가며 숨 쉴 때",
        "입술·얼굴이 창백하거나 파랗게 될 때",
        "불러도 반응이 없거나 축 늘어질 때",
        "경련이 5분 넘게 이어지거나 반복될 때",
        "생후 3개월 미만 아기가 열이 날 때",
        "머리를 심하게 부딪힌 뒤 토하거나 처질 때",
        "피가 멈추지 않거나 삼킨 것이 의심될 때",
    ]:
        A(f"<li>{esc(s)}</li>")
    A("</ul></details></div>")

    A('<div class="controls">')
    A('<button class="primary" id="loc">내 위치로 가까운 곳 찾기</button>')
    A('<select id="sido" aria-label="지역 선택"><option value="">지역 선택</option>')
    for s in sidos:
        A(f'<option value="{esc(s)}">{esc(s)}</option>')
    A("</select></div>")
    A(
        '<label class="filter"><input type="checkbox" id="onlyPeds" checked>'
        "소아 진료 정보가 있는 곳만 보기</label>"
    )
    A('<p id="status">위치를 허용하면 가까운 순으로 보여 드립니다.</p>')
    A('<div id="list"></div>')

    A('<div class="note">')
    A(
        "<p><strong>이 화면이 보여주는 것과 보여주지 않는 것</strong></p><ul>"
        "<li><strong>실시간 빈 병상이 아닙니다.</strong> 소아 병상은 전국 응급실 416곳 가운데 "
        "95곳(23%)만 값이 올라오고, 그마저 거의 갱신되지 않아 “지금 몇 자리”를 말할 수 없습니다. "
        "그래서 숫자를 지어내지 않고, <strong>평소 갖추고 있는 것</strong>만 보여 드립니다.</li>"
        "<li>전문의 수는 그 병원에 소속된 인원이고 <strong>지금 당직인지는 알 수 없습니다.</strong> "
        "가시기 전에 전화로 확인하세요.</li>"
        f"<li>초록색 칩은 <strong>소아 응급 병상을 갖추고 소아청소년과 전문의가 2명 이상</strong>인 곳으로, "
        f"전국 <strong>{tier2}곳</strong>뿐입니다. 체크를 끄면 소아 정보가 없는 응급실까지 모두 보입니다 — "
        "정보가 없다고 아이를 못 보는 것은 아닙니다.</li>"
        "<li>순서는 <strong>거리순일 뿐</strong>이며 어디가 더 낫다는 추천이 아닙니다. 거리는 직선거리입니다.</li>"
        "<li>출처: 중앙응급의료센터 E-Gen 공개 API, 건강보험심사평가원 공개 API.</li>"
        "<li>이 페이지는 아무것도 저장하지 않습니다 — 로그인·쿠키·접속 기록·외부 전송이 없고, "
        "위치는 기기 안에서만 계산에 쓰입니다.</li>"
        "</ul>"
    )
    A("</div>")

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    js = JS_TMPL.replace("__DATA__", data).replace("__DAY__", day)
    A(f"<script>{js}</script>")
    return "\n".join(o)


def main() -> None:
    rows, day = load()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build(rows, day))
    t2 = sum(1 for r in rows if r["pc"] > 0 and r["pd"] >= 2)
    t1 = sum(1 for r in rows if (r["pc"] > 0 or r["pd"] >= 1) and not (r["pc"] > 0 and r["pd"] >= 2))
    size = os.path.getsize(OUT) / 1024
    print(f"생성: {OUT}  ({size:.0f} KB)")
    print(f"  전국 {len(rows)}곳 · 소아 확인 {t2}곳 · 일부 {t1}곳 · 정보 없음 {len(rows)-t2-t1}곳")


if __name__ == "__main__":
    main()
