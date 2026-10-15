"""“우리 아이, 지금 어떻게 하죠” — 보호자용 웹 프로토타입 생성기.

새벽 2시에 아이가 아플 때 여는 화면 하나. 서버 없이 도는 자가완결 HTML이고,
네트워크 요청도 저장도 하지 않는다.

**이 서비스가 하는 일은 전화를 없애는 게 아니라 헛전화를 빼는 것이다.**
당직 정보는 공개 데이터에 없다 — 소아과 전문의가 5명이어도 오늘 밤 누가 있는지는
알 수 없다. 그래서 "여기로 가세요"가 아니라 "여기는 아닙니다"를 줄여 주고,
마지막 확인 전화는 보호자가 직접 건다. 병원은 평소대로 받을 뿐이라
**병원 참여가 0명**이고, 그게 이 서비스의 유일한 장점이라 반드시 지킨다.

설계 원칙 (바꾸기 전에 이유를 적을 것)
  1. **119가 먼저다.** 늘 화면에 떠 있고 우리 목록보다 크다. 중증 아동이 이
     화면을 보고 자가 이송하는 것이 이 서비스가 낼 수 있는 최악의 결과다.
  2. **판단은 규칙으로 한다.** MF_BERT는 성인 119 통화로 학습돼 소아 보호자
     발화로 검증된 적이 없다. 안전 판정을 모델에 맡기지 않는다 — 규칙이 먼저
     거르고, 모델은 나중에 앱에서 보조로만 얹는다.
  3. **입력은 탭 두 번.** 아이를 안고 한 손으로 조작한다. 문장을 치게 하지
     않는다. 그리고 탭이면 증상이 기기 밖으로 나갈 일이 없다.
  4. **모르는 건 모른다고 쓴다.** 소아 병상(hv28)은 전국 416곳 중 95곳(23%)만
     값이 오고 폴링마다 7%만 바뀐다 — 실시간이 아니라 쓰지 않는다. 응급실 전체
     포화도(hvec)는 100% 커버에 실제로 움직여서 쓰되 **수집 시각을 함께** 적는다.
  5. **추천이 아니라 순서다.** 순위 이유를 카드마다 한 줄로 밝힌다.
  6. **아무것도 저장하지 않는다.** 로그인·쿠키·외부 요청이 없고 위치는 기기
     안에서만 쓴다. 약속이 아니라 구조로 막는다.

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

PED_DEPT = "소아청소년과"
MSG_CACHE = os.path.join(HERE, "data", "acceptance_messages.json")

#: 보호자에게 보일 공지를 고르는 기준. 성형외과·안과 공지는 소음이라 버린다.
#: 자유 텍스트를 우리가 해석하지 않는다 — 고르기만 하고 문장은 그대로 보여준다.
PED_WORDS = re.compile(r"소아|신생아|NICU|영유아|유아|아동|소청과|미숙아|분만|산모")
#: 중증질환 메시지 중 영유아 항목 코드 (egen/messages.py의 대응표와 같은 체계)
PED_SEVERE_CODES = {"Y0070", "Y0082", "Y0092", "Y0100", "Y0172"}
#: 공지가 "제한"인지 "안내"인지. 실제로 "소아청소년과 : 24시간 진료 가능" 같은 안내가
#: 섞여 오는데(E-Gen은 전부 '차단' 유형으로 내보낸다) 이걸 제한으로 보면 멀쩡한 병원이
#: 뒤로 밀린다. 순위를 건드리는 건 제한으로 읽히는 문구가 있을 때만이다.
BLOCK_WORDS = re.compile(r"불가|제한|중단|부재|미운영|축소|휴진|어렵|없어|없음")


def load_messages() -> dict[str, list[list]]:
    """hpid -> [[유형, 진료과, 문장, 시작, 종료], …]. 캐시가 없으면 조용히 빈 값.

    시간으로 거르지 않고 그대로 싣는다 — 화면이 **열람 시각 기준으로** 다시
    거른다(정적 파일이라 만든 시점으로 굳으면 안 된다).
    """
    try:
        with open(MSG_CACHE, encoding="utf-8") as fp:
            cache = json.load(fp)
    except FileNotFoundError:
        return {}
    out: dict[str, list[list]] = {}
    for r in cache.get("items", []):
        text = (r.get("symBlkMsg") or "").strip()
        dept = (r.get("trtPrtCodMag") or r.get("symTypCodMag") or "").strip()
        code = (r.get("symTypCod") or "").strip()
        blob = f"{text} {dept}"
        if not (dept == PED_DEPT or PED_WORDS.search(blob) or code in PED_SEVERE_CODES):
            continue
        hpid = r.get("hpid")
        if not hpid or not text:
            continue
        out.setdefault(hpid, []).append(
            [
                "중증" if r.get("symBlkMsgTyp") == "중증" else "응급",
                dept,
                text[:160],
                (r.get("symBlkSttDtm") or "")[:14],
                (r.get("symBlkEndDtm") or "")[:14],
                1 if BLOCK_WORDS.search(text) else 0,
            ]
        )
    return out


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

    listing = None
    for p in reversed(files):
        for line in open(p, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("operation") == "getEgytListInfoInqire" and rec.get("items"):
                listing = rec["items"]
                break
        if listing:
            break

    beds, severe, stamp = {}, {}, ""
    for line in open(latest, encoding="utf-8"):
        rec = json.loads(line)
        if not rec.get("items"):
            continue
        if rec["operation"] == "getEmrrmRltmUsefulSckbdInfoInqire":
            stamp = rec.get("ts", "")[:16].replace("T", " ")
            for it in rec["items"]:
                beds[it["hpid"]] = it
        elif rec["operation"] == "getSrsillDissAceptncPosblInfoInqire":
            for it in rec["items"]:
                severe[it["hpid"]] = it

    try:
        spec = json.load(open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8"))
    except FileNotFoundError:
        spec = {}

    msgs = load_messages()
    infant_items = [i.no for i in V.ITEMS if i.age == V.AGE_INFANT]
    rows = []
    for h in listing:
        try:
            lat, lng = float(h["wgs84Lat"]), float(h["wgs84Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        hpid = h["hpid"]
        bed = beds.get(hpid, {})
        avail, cap = iv(bed.get("hvec")), iv(bed.get("hvs01"))
        occ = None
        if avail is not None and cap:
            occ = max(0, min(100, round((cap - avail) / cap * 100)))
        sev = severe.get(hpid, {})
        addr = h.get("dutyAddr") or ""
        rows.append(
            {
                "n": h.get("dutyName") or hpid,
                "t": (h.get("dutyTel3") or h.get("dutyTel1") or "").strip(),
                "y": round(lat, 5),
                "x": round(lng, 5),
                "g": (h.get("dutyEmclsName") or "").replace("응급의료", ""),
                "a": " ".join(addr.split()[:2]),
                "pd": next(
                    (iv(x.get("dtlSdrCnt")) or 0 for x in spec.get(hpid, []) if x.get("dgsbjtCdNm") == PED_DEPT),
                    0,
                ),
                "pc": iv(bed.get("hvs02")) or 0,
                "ni": 1 if (iv(bed.get("hvs19")) or 0) > 0 else 0,
                "iy": sum(
                    1 for n in infant_items if V.normalize_accept(sev.get(f"MKioskTy{n}")) == V.ACCEPT_YES
                ),
                "oc": occ,
                "ms": msgs.get(hpid, []),
            }
        )
    return rows, stamp


CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{
  color-scheme:light;
  --bg:#f7f7f5; --card:#fff; --ink:#111; --ink2:#595953; --muted:#8b8b84;
  --line:#e4e3dd; --accent:#1c5cab; --accentbg:#eaf1fb; --accentline:#bcd4f2;
  --urgent:#b3261e; --urgentbg:#fdecea;
  --warn:#9a6400; --warnbg:#fdf3e0;
  --ok:#0b7a3b; --okbg:#e8f5ec;
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --bg:#101010; --card:#1a1a19; --ink:#fff; --ink2:#c7c6bd; --muted:#8e8d86;
  --line:#2d2d2a; --accent:#7fb2f0; --accentbg:#16283f; --accentline:#2b4straight;
  --accentline:#2b4straight; --urgent:#ff8a80; --urgentbg:#3a1a18;
  --warn:#f0c070; --warnbg:#332512;
  --ok:#6fd392; --okbg:#13291c;
}}
html,body{margin:0;background:var(--bg)}
body{font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
     max-width:540px;margin:0 auto;padding:16px 14px 60px}
h1{font-size:21px;margin:2px 0 2px;letter-spacing:-.02em}
.tag{color:var(--muted);font-size:12.5px;margin:0 0 14px;line-height:1.5}
.call119{display:block;background:var(--urgent);color:#fff;text-align:center;
  font-size:20px;font-weight:700;padding:15px;border-radius:12px;text-decoration:none;margin-bottom:8px}
.always{font-size:12.5px;color:var(--ink2);text-align:center;margin:0 0 18px}
h2{font-size:15px;margin:20px 0 9px;color:var(--ink2);font-weight:600}
.opts{display:flex;flex-wrap:wrap;gap:8px}
.opt{font:inherit;font-size:15px;padding:12px 15px;border-radius:11px;border:1.5px solid var(--line);
     background:var(--card);color:var(--ink);cursor:pointer;line-height:1.2}
.opt[aria-pressed=true]{background:var(--accentbg);border-color:var(--accent);color:var(--accent);font-weight:650}
#result{margin-top:22px}
.verdict{border-radius:14px;padding:17px;margin-bottom:14px;border:1.5px solid}
.v1{background:var(--urgentbg);border-color:var(--urgent)}
.v2{background:var(--warnbg);border-color:var(--warn)}
.v3{background:var(--okbg);border-color:var(--ok)}
.verdict .big{font-size:19px;font-weight:700;margin:0 0 7px;line-height:1.35}
.v1 .big{color:var(--urgent)} .v2 .big{color:var(--warn)} .v3 .big{color:var(--ok)}
.verdict p{margin:0;font-size:14.5px;color:var(--ink2);line-height:1.55}
.verdict .why{margin-top:9px;font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin-bottom:10px}
.row1{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.name{font-size:17px;font-weight:650;letter-spacing:-.01em;line-height:1.35}
.dist{font-size:14px;color:var(--accent);font-weight:650;white-space:nowrap}
.sub{font-size:12.5px;color:var(--muted);margin:3px 0 0}
.reason{font-size:13px;color:var(--ink2);margin:9px 0 0;padding-left:9px;border-left:2px solid var(--accentbg)}
.notice{background:var(--urgentbg);border-left:3px solid var(--urgent);border-radius:0 8px 8px 0;
        padding:9px 11px;margin:10px 0 0;font-size:13px;line-height:1.5;color:var(--ink)}
.notice b{color:var(--urgent);display:block;font-size:12px;margin-bottom:3px}
.notice.info{background:var(--accentbg);border-left-color:var(--accent)}
.notice.info b{color:var(--accent)}
.notice p{margin:0 0 5px}.notice p:last-child{margin:0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 0}
.chip{font-size:12px;padding:4px 9px;border-radius:999px;background:var(--accentbg);color:var(--accent);white-space:nowrap}
.chip.ok{background:var(--okbg);color:var(--ok)}
.chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.none{background:transparent;color:var(--muted);border:1px dashed var(--line)}
.acts{display:flex;gap:8px;margin-top:12px}
.acts a{flex:1;text-align:center;text-decoration:none;font-size:15px;font-weight:600;
        padding:12px;border-radius:10px;border:1px solid var(--line);color:var(--ink)}
.acts a.tel{background:var(--accent);border-color:var(--accent);color:#fff}
.ask{font-size:13px;color:var(--ink2);background:var(--card);border:1px dashed var(--line);
     border-radius:12px;padding:13px 14px;margin:4px 0 14px;line-height:1.6}
.ask b{color:var(--ink)}
button.ghost{font:inherit;font-size:13.5px;padding:10px 13px;border-radius:10px;border:1px solid var(--line);
             background:transparent;color:var(--ink2);cursor:pointer}
#status{font-size:13px;color:var(--muted);margin:10px 2px 0;min-height:18px}
.note{font-size:12.5px;color:var(--muted);line-height:1.65;margin-top:26px;border-top:1px solid var(--line);padding-top:16px}
.note strong{color:var(--ink2)} .note ul{padding-left:18px;margin:8px 0 0} .note li{margin:5px 0}
details summary{cursor:pointer;color:var(--ink2);font-size:13px;padding:4px 0}
"""

# ── 판단 규칙 (전문의 검토 전 초안) ──────────────────────────────
# 안전 쪽으로 기운다: 여러 개를 고르면 가장 높은 단계를 따른다.
# 숫자가 아니라 행동으로만 말한다 — 보호자에게 KTAS 등급은 의미가 없다.
RULES = {
    "age": ["3개월 미만", "3~12개월", "1~3세", "3세 이상"],
    "sym": [
        ("breath", "숨쉬기가 힘들어요"),
        ("seizure", "경련을 해요"),
        ("limp", "축 처지거나 반응이 없어요"),
        ("fever", "열이 나요"),
        ("head", "머리를 부딪혔어요"),
        ("hurt", "다쳤어요"),
        ("vomit", "토하거나 설사해요"),
        ("other", "그 밖에 걱정돼요"),
    ],
}

JS_TMPL = """
var DATA=__DATA__, STAMP="__STAMP__";
var age=null, sym={}, here=null;

/* 규칙 — 숫자가 아니라 행동으로. 여러 개면 가장 높은 단계를 따른다 */
function judge(){
  var r={lv:3,why:[]};
  function up(lv,why){ if(lv<r.lv) r.lv=lv; r.why.push(why); }
  if(sym.breath)  up(1,'숨쉬기가 힘든 것은 기다리면 안 되는 신호입니다');
  if(sym.seizure) up(1,'경련은 지금 119입니다');
  if(sym.limp)    up(1,'축 처지거나 반응이 없는 것은 지금 119입니다');
  if(sym.fever && age===0) up(2,'생후 3개월 미만의 열은 지체 없이 진료가 필요합니다');
  if(sym.fever && age===1) up(2,'돌 전 아기의 열은 응급실에서 보는 편이 안전합니다');
  if(sym.head)    up(2,'머리를 부딪힌 뒤에는 진료로 확인하는 편이 안전합니다');
  if(sym.vomit && age<=1) up(2,'돌 전후에는 토·설사로 수분이 빠르게 빠집니다');
  if(sym.hurt)    up(2,'다친 정도는 눈으로 판단하기 어렵습니다');
  if(sym.fever && age>=2) up(3,'열만 있고 잘 먹고 논다면 서두르지 않아도 됩니다');
  if(!r.why.length) up(3,'고르신 내용만으로는 급한 신호가 보이지 않습니다');
  return r;
}
/* 병원 공지는 시작·종료 시각이 있다. 정적 파일이라 만든 시점으로 굳으면 안 되므로
   **열람 시각 기준으로** 다시 거른다. 시각은 E-Gen이 주는 KST 문자열과 같은 자리수로 맞춘다 */
function nowStamp(){
  var d=new Date(), p=function(n){return (n<10?'0':'')+n;};
  return ''+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+p(d.getHours())+p(d.getMinutes())+p(d.getSeconds());
}
function activeMsgs(h){
  var now=nowStamp();
  return (h.ms||[]).filter(function(m){
    if(m[3] && m[3]>now) return false;   // 아직 시작 전
    if(m[4] && m[4]<now) return false;   // 이미 끝남
    return true;
  });
}
function km(a,b,c,d){var R=6371,p=Math.PI/180,u=(c-a)*p,v=(d-b)*p;
  var h=Math.sin(u/2)*Math.sin(u/2)+Math.cos(a*p)*Math.cos(c*p)*Math.sin(v/2)*Math.sin(v/2);
  return 2*R*Math.asin(Math.sqrt(h));}

/* 순위는 점수가 아니라 '분'으로 조정한다 — 구급대 쪽 로직과 같은 방식이라 설명이 된다 */
function rank(h){
  var min = h._d*2.5;                       // 직선거리 → 추정 이동분(도심 가정)
  var why=[];
  if(h.pc>0 && h.pd>=2){ min-=5; why.push('소아 응급 병상과 소아과 전문의를 갖춘 곳'); }
  else if(h.pd>=2){ min-=3; why.push('소아과 전문의가 여러 명 있는 곳'); }
  else if(h.pd>=1){ min-=1; why.push('소아과 전문의가 있는 곳'); }
  if(age===0 && h.ni){ min-=2; why.push('신생아 중환자실이 있는 곳'); }
  if(h.oc!=null && h.oc>=80){ min+=5; why.push('마지막 집계에서 응급실이 거의 찼던 곳'); }
  else if(h.oc!=null && h.oc>=50){ min+=2; why.push('마지막 집계에서 응급실이 붐볐던 곳'); }
  /* 병원이 직접 올린 공지는 **순위를 건드리지 않는다.** 한때 뒤로 밀어 봤는데,
     "소아신경분과 진료불가" 같은 분과 단위 제한 때문에 2km 병원이 5km 병원보다
     뒤로 갔다 — 열이 난 아기와는 상관없는 제한이다. 우리는 그 공지가 이 아이에게
     해당되는지 판별할 능력이 없고, 판별하는 척하면 더 위험하다.
     그래서 문장을 눈에 띄게 보여 주기만 하고 판단은 보호자가 한다 */
  h._ms=activeMsgs(h);
  h._blk=h._ms.filter(function(m){return m[5];});
  h._m=min; h._why=why;
  return min;
}
function chips(h){
  var c=[];
  if(h.pd>0) c.push('<span class="chip'+(h.pd>=2?' ok':'')+'">소아과 전문의 '+h.pd+'명</span>');
  if(h.pc>0) c.push('<span class="chip ok">소아 응급 병상 '+h.pc+'석</span>');
  if(h.ni)   c.push('<span class="chip">신생아 중환자실</span>');
  /* "0% 찼었음"처럼 읽히지 않게, 붐빈 곳만 숫자를 보인다 */
  if(h.oc!=null) c.push(h.oc>=50
      ? '<span class="chip warn">집계 때 응급실 '+h.oc+'% 참</span>'
      : '<span class="chip">집계 때 응급실 여유</span>');
  if(!h.pd && !h.pc && !h.ni) c.push('<span class="chip none">소아 정보 없음</span>');
  return c.join('');
}
function places(){
  if(!here) return '<p class="sub">위치를 허용하시면 가까운 곳을 찾아 드립니다.</p>';
  var rows=DATA.slice();
  rows.forEach(function(h){ h._d=km(here[0],here[1],h.y,h.x); });
  rows=rows.filter(function(h){return h._d<60;});
  var ped=rows.filter(function(h){return h.pd>0||h.pc>0;});
  if(ped.length>=3) rows=ped;
  rows.forEach(rank); rows.sort(function(a,b){return a._m-b._m;});
  if(!rows.length) return '<p class="sub">가까운 곳을 찾지 못했습니다. 119에 물어보세요.</p>';
  return rows.slice(0,3).map(function(h){
    var map='https://map.kakao.com/link/to/'+encodeURIComponent(h.n)+','+h.y+','+h.x;
    return '<div class="card"><div class="row1"><div class="name">'+h.n+'</div>'
      +'<span class="dist">'+h._d.toFixed(1)+'km</span></div>'
      +'<p class="sub">'+h.g+' · '+h.a+'</p>'
      +'<div class="chips">'+chips(h)+'</div>'
      +(h._ms.length
         ? '<div class="notice'+(h._blk.length?'':' info')+'"><b>'
           + (h._blk.length?'이 병원이 올린 진료 제한 공지':'이 병원이 올린 안내')+'</b>'
           + h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')
           + (h._ms.length>2?'<p style="color:var(--muted)">외 '+(h._ms.length-2)+'건</p>':'')
           + '</div>'
         : '')
      +(h._why.length?'<p class="reason">'+h._why.join(' · ')+'</p>':'')
      +'<div class="acts">'+(h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
      +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
  }).join('');
}
function show(){
  var el=document.getElementById('result');
  if(age===null || !Object.keys(sym).some(function(k){return sym[k];})){ el.innerHTML=''; return; }
  var j=judge(), h='';
  if(j.lv===1){
    h='<div class="verdict v1"><p class="big">지금 119에 전화하세요</p>'
     +'<p>병원을 고르는 것보다 빠릅니다. 구급대원이 상태를 보고 받아 줄 병원을 찾아 줍니다.</p>'
     +'<p class="why">'+j.why[0]+'</p></div>';
  }else if(j.lv===2){
    h='<div class="verdict v2"><p class="big">응급실로 가시는 편이 좋겠습니다</p>'
     +'<p>아래는 가까운 곳입니다. <b>출발 전에 전화로 지금 소아 진료가 되는지 확인하세요</b> — '
     +'당직 의사가 누구인지는 공개된 정보에 없습니다.</p>'
     +'<p class="why">'+j.why[0]+'</p></div>'
     +'<div class="ask">전화로 이렇게만 물어보시면 됩니다<br>'
     +'<b>“○개월 아기가 △△한데, 지금 소아 진료 되나요?”</b></div>'
     + places();
  }else{
    h='<div class="verdict v3"><p class="big">내일 외래로도 괜찮아 보입니다</p>'
     +'<p>다만 아래 중 하나라도 생기면 바로 119입니다 — 숨쉬기 힘들어함, 축 처짐, '
     +'경련, 입술이 파래짐.</p><p class="why">'+j.why[0]+'</p></div>'
     +'<details><summary>그래도 지금 갈 수 있는 곳을 보고 싶어요</summary>'+places()+'</details>';
  }
  el.innerHTML=h;
}
document.querySelectorAll('[data-age]').forEach(function(b){
  b.onclick=function(){
    age=+b.dataset.age;
    document.querySelectorAll('[data-age]').forEach(function(x){x.setAttribute('aria-pressed',x===b);});
    show();
  };
});
document.querySelectorAll('[data-sym]').forEach(function(b){
  b.onclick=function(){
    var k=b.dataset.sym; sym[k]=!sym[k];
    b.setAttribute('aria-pressed',!!sym[k]);
    show();
  };
});
document.getElementById('loc').onclick=function(){
  var st=document.getElementById('status');
  if(!navigator.geolocation){ st.textContent='이 브라우저에서는 위치를 쓸 수 없습니다.'; return; }
  st.textContent='위치 확인 중…';
  navigator.geolocation.getCurrentPosition(function(p){
    here=[p.coords.latitude,p.coords.longitude];
    st.textContent='가까운 곳을 찾았습니다. 거리는 직선거리입니다.';
    show();
  },function(){ st.textContent='위치를 가져오지 못했습니다. 119에 물어보시는 편이 빠릅니다.'; },
  {timeout:8000,maximumAge:60000});
};
"""


def build(rows: list[dict], stamp: str) -> str:
    tier2 = sum(1 for r in rows if r["pc"] > 0 and r["pd"] >= 2)
    o = []
    A = o.append
    A("<title>우리 아이, 지금 어떻게 하죠</title>")
    A('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
    A(f"<style>{CSS}</style>")

    A("<h1>우리 아이, 지금 어떻게 하죠</h1>")
    A(
        '<p class="tag">두 가지만 고르면 지금 무엇을 해야 할지 알려 드립니다. '
        "입력한 내용과 위치는 이 화면 밖으로 나가지 않습니다.</p>"
    )
    A('<a class="call119" href="tel:119">119 전화하기</a>')
    A('<p class="always">숨을 못 쉬거나 · 반응이 없거나 · 경련이 멈추지 않으면 고르지 말고 지금 누르세요</p>')

    A("<h2>아이 나이</h2><div class=\"opts\">")
    for i, label in enumerate(RULES["age"]):
        A(f'<button class="opt" data-age="{i}" aria-pressed="false">{esc(label)}</button>')
    A("</div>")

    A('<h2>무슨 일인가요 <span style="font-weight:400;color:var(--muted)">· 여러 개 고르셔도 됩니다</span></h2>')
    A('<div class="opts">')
    for key, label in RULES["sym"]:
        A(f'<button class="opt" data-sym="{key}" aria-pressed="false">{esc(label)}</button>')
    A("</div>")

    A('<div style="margin-top:14px"><button class="ghost" id="loc">내 위치로 가까운 곳 찾기</button></div>')
    A('<p id="status"></p>')
    A('<div id="result"></div>')

    A('<div class="note">')
    A("<p><strong>이 화면이 할 수 있는 일과 못 하는 일</strong></p><ul>")
    A(
        "<li><strong>전화를 대신하지 못합니다.</strong> 오늘 밤 소아과 당직이 누구인지는 "
        "공개된 데이터 어디에도 없습니다. 이 화면은 <strong>갈 필요가 없는 곳을 빼 주는 것</strong>까지만 "
        "합니다. 마지막 확인 전화는 직접 거셔야 합니다.</li>"
    )
    A(
        "<li><strong>실시간 소아 병상이 아닙니다.</strong> 소아 병상은 전국 응급실 416곳 중 "
        "95곳(23%)만 값이 올라오고 거의 갱신되지 않아 “지금 몇 자리”를 말할 수 없습니다. "
        "그래서 숫자를 지어내지 않고 평소 갖춘 것만 보여 드립니다.</li>"
    )
    A(
        f"<li>응급실 혼잡도는 전체 응급실 기준이고 <strong>{esc(stamp)} 집계</strong>입니다. "
        "소아만의 혼잡도가 아니며 지금과 다를 수 있습니다.</li>"
    )
    A(
        "<li>전문의 수는 그 병원 소속 인원이고 <strong>지금 당직인지는 알 수 없습니다.</strong> "
        f"소아 응급 병상과 소아과 전문의 2명을 함께 갖춘 곳은 전국 <strong>{tier2}곳</strong>뿐입니다.</li>"
    )
    A(
        "<li>판단 기준은 <strong>의사가 검토하기 전의 초안</strong>입니다. 규칙으로만 동작하며 "
        "AI가 진단하지 않습니다. 헷갈리시면 119에 전화해 물어보셔도 됩니다 — 119는 상담도 합니다.</li>"
    )
    A("<li>순서는 거리와 소아 진료 여건으로 정한 것이고 어디가 더 낫다는 추천이 아닙니다. 거리는 직선거리입니다.</li>")
    A("<li>출처: 중앙응급의료센터 E-Gen 공개 API, 건강보험심사평가원 공개 API.</li>")
    A(
        "<li>이 페이지는 아무것도 저장하지 않습니다 — 로그인·쿠키·접속 기록·외부 전송이 없습니다.</li>"
    )
    A("</ul></div>")

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    A("<script>" + JS_TMPL.replace("__DATA__", data).replace("__STAMP__", stamp) + "</script>")
    return "\n".join(o)


def main() -> None:
    rows, stamp = load()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build(rows, stamp))
    print(f"생성: {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    print(f"  전국 {len(rows)}곳 · 혼잡도 집계 {stamp}")
    withmsg = [r for r in rows if r["ms"]]
    blk = sum(1 for r in withmsg if any(m[5] for m in r["ms"]))
    if withmsg:
        print(f"  병원 공지: {len(withmsg)}곳 (제한 {blk}곳 · 안내 {len(withmsg)-blk}곳)")
    else:
        print("  ⚠ 병원 공지 캐시가 없다 — `python fetch_messages.py` 먼저 (E-Gen 키 필요)")


if __name__ == "__main__":
    main()
