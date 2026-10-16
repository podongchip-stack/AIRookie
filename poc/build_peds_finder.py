"""“우리 아이, 지금 어떻게 하죠” — 보호자용 웹 프로토타입 생성기.

새벽 2시에 아이가 아플 때 여는 화면 하나. 서버 없이 도는 자가완결 HTML이고,
위치·증상은 기기 밖으로 나가지 않는다.

**이 서비스가 하는 일은 전화를 없애는 게 아니라 헛전화를 빼는 것이다.**
당직 정보는 공개 데이터에 없다 — 소아과 전문의가 5명이어도 오늘 밤 누가 있는지는
알 수 없다. 그래서 "여기로 가세요"가 아니라 "여기는 아닙니다"를 줄여 주고,
마지막 확인 전화는 보호자가 직접 건다. 병원은 평소대로 받을 뿐이라
**병원 참여가 0명**이고, 그게 이 트랙의 유일한 장점이라 지킨다.

쓰는 모델 두 가지 (그리고 쓰지 않는 것)
  · **거미줄(spider) — 줄 길이와 그림만.** 줄 길이 = 추정 이동분 − 역량 이득
    + 혼잡 가산. 지도의 각도는 실제 방위, 반경은 이 **줄 길이**라서 "가깝지만
    먼 병원"이 실제로 멀리 그려진다. ⚠ 거미줄의 본체인 τ 창 충돌·양보·재투척은
    **쓰지 않는다** — 동시 요청자가 여럿일 때의 규칙이라 보호자 한 명에겐
    성립하지 않는다. 그걸 쓰는 척하면 거짓이다.
  · **infosurv(병상 신뢰도) — 응급실 hvec 기준.** "출발해서 도착할 때도 지금과
    비슷할 가능성". hvec은 커버리지 100%에 실시간이라 모델이 설계된 그대로다.
    소아 병상(hv28)은 23% 커버·폴링당 7% 변화라 **쓰지 않는다.**

설계 원칙 (바꾸기 전에 이유를 적을 것)
  1. **119가 먼저다.** 늘 화면에 떠 있고 우리 목록보다 크다.
  2. **판단은 규칙으로 한다.** MF_BERT는 성인 119 통화로 학습돼 소아 보호자
     발화로 검증된 적이 없다. 안전 판정을 모델에 맡기지 않는다.
  3. **입력은 탭 두 번.** 아이를 안고 한 손으로 조작한다.
  4. **모르는 건 모른다고 쓴다.** 그리고 **언제 기준인지**를 같이 적는다.
  5. **해석하지 않는다.** 병원 공지는 문장을 그대로 보여 주고 순위를 건드리지
     않는다(분과 단위 제한을 전면 차단으로 오인하면 더 위험하다).
  6. **아무것도 저장하지 않는다.** 로그인·쿠키·기록이 없다.
     ⚠ 다만 2026-10-16부터 **어두운 지도 타일을 외부(Esri)에서 받는다** — 보고 있는
     지역이 지도 제공자에게 전달된다. "아무것도 외부로 안 보낸다"가 여기서 깨졌으므로
     화면 설명과 FAQ를 같이 고쳤다. 정확한 좌표·고른 내용은 여전히 보내지 않는다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다.

실행 (순서가 중요하다):
    conda activate dev
    # 0) 클라우드에 5분마다 쌓이는 스냅샷을 이 장비로 내려받는다. **이걸 건너뛰면
    #    로컬 사본 시각으로 굳은 화면이 나온다** — 신뢰도가 전부 0%에 가깝게 찍히고
    #    (모델이 "이 값은 낡았다"고 정확히 말하는 것이다) 혼잡도도 옛날 값이 된다
    cd ../info/Hospital_inform/info && python snapshot_cloud.py --sync
    cd ../../../poc
    python fetch_messages.py      # 병원 공지 (E-Gen 키 필요, 전국 1회, 매일 바뀐다)
    python build_peds_finder.py   # 신뢰도 엔진 적재 포함 30초쯤
산출물:
    poc/out/peds_finder.html
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from report_base import esc
from site_css import CSS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
SNAP_DIR = os.path.join(INFO, "data", "snapshots_nationwide")
HIRA_DIR = os.path.join(INFO, "data", "hira")
MSG_CACHE = os.path.join(HERE, "data", "acceptance_messages.json")
MOON_CACHE = os.path.join(HERE, "data", "moonlight.json")
OUT = os.path.join(HERE, "out", "peds_finder.html")

sys.path.insert(0, INFO)
from hospital_score import vocabulary as V  # noqa: E402

KST = timezone(timedelta(hours=9))
PED_DEPT = "소아청소년과"
PED_WORDS = re.compile(r"소아|신생아|NICU|영유아|유아|아동|소청과|미숙아|분만|산모")
PED_SEVERE_CODES = {"Y0070", "Y0082", "Y0092", "Y0100", "Y0172"}
#: 공지를 세 갈래로 읽는다. E-Gen은 전부 '차단' 유형으로 내보내지만 내용은 섞여 있다 —
#: 실제로 "소아청소년과 : 24시간 진료 가능"도 '차단'으로 온다.
#:   2 제한  "진료불가", "수용 어려움"          → 그 아이는 못 받을 수 있다
#:   1 조건  "사전 문의", "요일별 상이"          → 전화로 먼저 물어보라는 뜻
#:   0 안내  나머지                              → 받는다는 쪽
#: ⚠ '어렵'만 보면 "수용 어려움"이 안 잡힌다. 어간으로 끊을 것.
BLOCK_WORDS = re.compile(r"불가|제한|중단|부재|미운영|축소|휴진|어려|없어|없음|못\s*받")
COND_WORDS = re.compile(r"사전\s*문의|문의\s*후|사전\s*확인|사전\s*연락|문의\s*바랍|"
                        r"확인\s*바랍|상이|요일\s*별|요일별|문의 후")


def iv(x) -> int | None:
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def load_messages() -> dict[str, list[list]]:
    """hpid -> [[유형, 진료과, 문장, 시작, 종료, 제한여부], …]."""
    try:
        with open(MSG_CACHE, encoding="utf-8") as fp:
            cache = json.load(fp)
    except FileNotFoundError:
        return {}
    out: dict[str, list[list]] = {}
    for r in cache.get("items", []):
        text = (r.get("symBlkMsg") or "").strip()
        dept = (r.get("trtPrtCodMag") or r.get("symTypCodMag") or "").strip()
        if not text or not r.get("hpid"):
            continue
        if not (dept == PED_DEPT or PED_WORDS.search(f"{text} {dept}")
                or (r.get("symTypCod") or "").strip() in PED_SEVERE_CODES):
            continue
        out.setdefault(r["hpid"], []).append([
            "중증" if r.get("symBlkMsgTyp") == "중증" else "응급",
            dept, text[:160],
            (r.get("symBlkSttDtm") or "")[:14], (r.get("symBlkEndDtm") or "")[:14],
            2 if BLOCK_WORDS.search(text) else (1 if COND_WORDS.search(text) else 0),
        ])
    return out


def load_reliability(as_of: datetime) -> tuple[dict[str, list], str]:
    """hpid -> [예측 생존초, 버전 나이(초), σ]. 엔진이 없으면 조용히 비운다.

    예측 시각을 **스냅샷 마지막 시각**으로 둔다. 벽시계로 두면 수집이 며칠
    멈춘 장비에서 전부 0%가 되는데, 그건 "자리가 없다"가 아니라 "우리 데이터가
    낡았다"는 뜻이라 보호자에게 그대로 보이면 안 된다. 대신 기준 시각을 화면에
    밝힌다.
    """
    try:
        from reliability.engine import BedReliabilityEngine
    except Exception as exc:  # 모델·xgboost 없으면 이 섹션만 빠진다
        print(f"  [reliability] 생략 — {type(exc).__name__}")
        return {}, ""
    engine = BedReliabilityEngine(warmup_days=14)
    preds = engine.predict(as_of).get("hvec", {})
    out = {
        hpid: [round(p.pred_t_sec), round((as_of - p.born).total_seconds()), round(p.sigma, 4)]
        for hpid, p in preds.items()
    }
    tag = preds[next(iter(preds))].model_tag if preds else ""
    return out, tag


def load_moonlight() -> list[dict]:
    """달빛어린이병원 — 응급실이 아니라 **야간·휴일 소아 외래**다.

    경증 아이를 응급실로 보내지 않으려고 만든 제도라, 우리가 "응급실로 가세요"만
    말하면 그 제도를 거스르게 된다(hub의 "경증은 센터를 아껴라"와 같은 원칙).
    그래서 응급실 목록과 **섞지 않고 따로** 보여준다.
    """
    try:
        with open(MOON_CACHE, encoding="utf-8") as fp:
            return json.load(fp).get("items", [])
    except FileNotFoundError:
        return []


def load_specialists() -> dict:
    """심평원 전문과목 전문의 수 캐시. 몇 달 단위로만 바뀌어 정적으로 둔다."""
    try:
        with open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return {}


def assemble(listing: list[dict], beds, severe, msgs: dict, rel: dict,
             spec: dict | None = None) -> list[dict]:
    """화면이 쓰는 병원 행을 만든다 — 스냅샷에서 오든 실시간 API에서 오든 같은 규칙.

    정적 빌드(build_peds_finder)와 상시 갱신(serve_data)이 **같은 함수**를 쓴다.
    조립 규칙이 두 벌이 되면 화면과 갱신본이 조용히 달라진다.
    """
    if spec is None:
        spec = load_specialists()
    if isinstance(beds, list):
        beds = {it["hpid"]: it for it in beds if it.get("hpid")}
    if isinstance(severe, list):
        severe = {it["hpid"]: it for it in severe if it.get("hpid")}
    infant = [i.no for i in V.ITEMS if i.age == V.AGE_INFANT]

    rows = []
    for h in listing:
        try:
            lat, lng = float(h["wgs84Lat"]), float(h["wgs84Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        hpid = h["hpid"]
        bed = beds.get(hpid, {})
        avail, cap = iv(bed.get("hvec")), iv(bed.get("hvs01"))
        sev = severe.get(hpid, {})
        addr = h.get("dutyAddr") or ""
        rows.append({
            "n": h.get("dutyName") or hpid,
            "t": (h.get("dutyTel3") or h.get("dutyTel1") or "").strip(),
            "y": round(lat, 5), "x": round(lng, 5),
            "g": (h.get("dutyEmclsName") or "").replace("응급의료", ""),
            "a": " ".join(addr.split()[:2]),
            "pd": next((iv(x.get("dtlSdrCnt")) or 0 for x in spec.get(hpid, [])
                        if x.get("dgsbjtCdNm") == PED_DEPT), 0),
            "pc": iv(bed.get("hvs02")) or 0,
            "ni": 1 if (iv(bed.get("hvs19")) or 0) > 0 else 0,
            "av": avail,
            "oc": None if (avail is None or not cap) else max(0, min(100, round((cap - avail) / cap * 100))),
            "iy": sum(1 for n in infant
                      if V.normalize_accept(sev.get(f"MKioskTy{n}")) == V.ACCEPT_YES),
            "ms": msgs.get(hpid, []),
            "rl": rel.get(hpid),
        })
    return rows


def load() -> tuple[list[dict], dict]:
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

    beds, severe, as_of = {}, {}, None
    for line in open(latest, encoding="utf-8"):
        rec = json.loads(line)
        if not rec.get("items"):
            continue
        if rec["operation"] == "getEmrrmRltmUsefulSckbdInfoInqire":
            as_of = datetime.fromisoformat(rec["ts"])
            for it in rec["items"]:
                beds[it["hpid"]] = it
        elif rec["operation"] == "getSrsillDissAceptncPosblInfoInqire":
            for it in rec["items"]:
                severe[it["hpid"]] = it
    as_of = as_of or datetime.now(KST)

    spec = load_specialists()

    rel, model_tag = load_reliability(as_of.astimezone(timezone.utc))
    rows = assemble(listing, beds, severe, load_messages(), rel, spec)
    moon = load_moonlight()
    meta = {
        "moon": moon,
        "moonCount": len(moon),
        "asOf": as_of.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "modelTag": model_tag,
        "relCount": len(rel),
        "msgCount": sum(1 for r in rows if r["ms"]),
    }
    return rows, meta


RULES_AGE = ["3개월 미만", "3~12개월", "1~3세", "3세 이상"]
RULES_SYM = [
    ("breath", "숨쉬기가 힘들어요"), ("seizure", "경련을 해요"),
    ("limp", "축 처지거나 반응이 없어요"), ("fever", "열이 나요"),
    ("head", "머리를 부딪혔어요"), ("hurt", "다쳤어요"),
    ("vomit", "토하거나 설사해요"), ("other", "그 밖에 걱정돼요"),
]

JS_TMPL = r"""
var DATA=__DATA__, MOON=__MOON__, ASOF="__ASOF__";
/* "집계 때"는 우리 말이다. 보호자에겐 몇 시 기준인지를 직접 보여준다 */
var STAMP=ASOF.slice(5);                 /* 2026-10-12 01:25 → 10-12 01:25 */
var ICON_ALERT=__ICON_ALERT__, ICON_INFO=__ICON_INFO__;
var hit=[], selKey=null;   /* 지도에서 누를 수 있는 점들과 고른 점 */
/* 위치를 허용하지 않아도 화면이 비어 있지 않게 서울 중심을 기본으로 둔다.
   다만 **예시라고 분명히 적는다** — 부산에 있는 사람에게 서울 병원을
   "내 주변"이라고 보여주면 안 된다. 허용하면 진짜 내 위치로 바뀐다 */
var DEFAULT_HERE=[37.5665,126.9780], here=DEFAULT_HERE, usingDefault=true;

/* ── infosurv 생존함수 (hub/bed_reliability.py와 같은 식) ──────────
   S(t) = 1 − Φ((ln t − ln m)/σ) = ½·erfc((ln t − ln m)/(σ√2)) */
function erfc(x){
  var z=Math.abs(x), t=1/(1+z/2);
  var r=t*Math.exp(-z*z-1.26551223+t*(1.00002368+t*(0.37409196+t*(0.09678418+
    t*(-0.18628806+t*(0.27886807+t*(-1.13520398+t*(1.48851587+
    t*(-0.82215223+t*0.17087277)))))))));
  return x>=0?r:2-r;
}
function survival(m,t,s){ if(t<=0) return 1; return 0.5*erfc((Math.log(t)-Math.log(Math.max(m,1e-9)))/(s*Math.SQRT2)); }
function rArrive(h,travelMin){
  if(!h.rl || h.av==null || h.av<=0) return null;   /* 자리가 없으면 확률은 뜻이 없다 */
  return survival(h.rl[0], h.rl[1]+travelMin*60, h.rl[2]);
}

/* ── 거미줄 줄 길이: 이동분 − 역량 이득 + 혼잡 가산 ─────────────── */
function km(a,b,c,d){var R=6371,p=Math.PI/180,u=(c-a)*p,v=(d-b)*p;
  var h=Math.sin(u/2)*Math.sin(u/2)+Math.cos(a*p)*Math.cos(c*p)*Math.sin(v/2)*Math.sin(v/2);
  return 2*R*Math.asin(Math.sqrt(h));}
function nowStamp(){var d=new Date(),p=function(n){return(n<10?'0':'')+n;};
  return ''+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+p(d.getHours())+p(d.getMinutes())+p(d.getSeconds());}
function activeMsgs(h){var now=nowStamp();
  return (h.ms||[]).filter(function(m){ if(m[3]&&m[3]>now) return false; if(m[4]&&m[4]<now) return false; return true; });}

function thread(h){
  var travel=h._d*2.5, min=travel, why=[];
  if(h.pc>0 && h.pd>=2){ min-=5; why.push('소아 응급 병상과 소아과 전문의를 갖춘 곳'); }
  else if(h.pd>=2){ min-=3; why.push('소아과 전문의가 여러 명 있는 곳'); }
  else if(h.pd>=1){ min-=1; why.push('소아과 전문의가 있는 곳'); }
  if(h.oc!=null && h.oc>=80){ min+=5; why.push(STAMP+' 기준 응급실이 거의 찼던 곳'); }
  else if(h.oc!=null && h.oc>=50){ min+=2; why.push(STAMP+' 기준 응급실이 붐볐던 곳'); }
  /* 병원 공지는 순위를 건드리지 않는다 — 분과 단위 제한을 전면 차단으로 오인하면
     2km 병원이 5km 병원보다 뒤로 간다. 문장만 보여 주고 판단은 보호자가 한다 */
  h._ms=activeMsgs(h); h._blk=h._ms.filter(function(m){return m[5]===2;});
  h._travel=travel; h._len=Math.max(1,min); h._why=why;
  h._r=rArrive(h,travel);
  return h._len;
}
function candidates(){
  if(!here) return [];
  var rows=DATA.slice();
  rows.forEach(function(h){ h._d=km(here[0],here[1],h.y,h.x); });
  rows=rows.filter(function(h){return h._d<60;});
  var ped=rows.filter(function(h){return h.pd>0||h.pc>0;});
  if(ped.length>=3) rows=ped;
  rows.forEach(thread); rows.sort(function(a,b){return a._len-b._len;});
  return rows;
}

/* ── 지도: 어두운 실제 지도 위에 점 ───────────────────────────────
   거미줄 화면과 같은 어두운 바탕을 쓴다. 라이브러리 없이 캔버스에 타일을 직접
   깐다(웹 메르카토르) — deck.gl·MapLibre를 끌어오면 수 MB가 붙는다.
   ⚠ 타일을 받는 순간 **대략적 위치가 타일 서버로 나간다.** 그 전까지 지키던
   "아무것도 외부로 안 보낸다"가 여기서 깨지므로 화면 설명도 같이 고쳤다.
   타일이 안 와도(망 차단·실패) 어두운 바탕에 점은 그대로 그린다 */
/* Esri 다크 그레이 — 키가 필요 없다. CARTO는 2026년부터 키를 요구해 타일에
   "API KEY REQUIRED" 워터마크가 찍힌다(실제로 겪음). 주소 차례가 {z}/{y}/{x}다.
   바탕(도로·강)과 지명을 따로 받아 겹친다 */
var TILE_BASE='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/';
var TILE_REF='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/';
var tiles={}, lastRows=null;
function tile(url,z,x,y,onload){
  var k=url+z+'/'+x+'/'+y, im=tiles[k];
  if(im) return im;
  im=new Image(); im.crossOrigin='anonymous';
  im.onload=onload; im.onerror=function(){ im.bad=true; };
  im.src=url+z+'/'+y+'/'+x;
  tiles[k]=im; return im;
}
function projX(lon,z){ return (lon+180)/360*256*Math.pow(2,z); }
function projY(lat,z){
  var r=lat*Math.PI/180;
  return (1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*256*Math.pow(2,z);
}

function drawWeb(rows){
  var cv=document.getElementById('web'); if(!cv) return;
  lastRows=rows;
  var W=cv.clientWidth||520, H=Math.min(Math.round(W*0.68),430), r=window.devicePixelRatio||1;
  cv.width=W*r; cv.height=H*r; cv.style.height=H+'px';
  var g=cv.getContext('2d'); g.setTransform(r,0,0,r,0,0);
  hit=[];
  var acc=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  var BLK='#ff6b60', BUSY='#f0a94a', DIM='#7f8b9e';

  var top=rows.slice(0,3);
  /* 상위 3곳이 화면 안에 들어오는 가장 가까운 확대 단계를 고른다 */
  var far=0.8;
  top.forEach(function(h){ far=Math.max(far,h._d); });
  var need=Math.min(W,H)/2-34, mpp=156543.03*Math.cos(here[0]*Math.PI/180);
  var z=Math.round(Math.log2(need*mpp/(far*1000)));
  z=Math.max(9,Math.min(15,z));

  var cx=W/2, cy=H/2, ox=projX(here[1],z)-cx, oy=projY(here[0],z)-cy;
  function px(lat,lon){ return [projX(lon,z)-ox, projY(lat,z)-oy]; }

  g.fillStyle='#0b0f14'; g.fillRect(0,0,W,H);            /* 타일이 늦거나 막혀도 바탕은 어둡게 */
  var redraw=function(){ if(lastRows) drawWeb(lastRows); };
  var n=Math.pow(2,z);
  for(var tx=Math.floor(ox/256); tx<=Math.floor((ox+W)/256); tx++){
    for(var ty=Math.floor(oy/256); ty<=Math.floor((oy+H)/256); ty++){
      if(ty<0||ty>=n) continue;
      var xx=((tx%n)+n)%n;
      var base=tile(TILE_BASE,z,xx,ty,redraw), ref=tile(TILE_REF,z,xx,ty,redraw);
      if(base.complete && !base.bad) g.drawImage(base, tx*256-ox, ty*256-oy, 256, 256);
      if(ref.complete && !ref.bad)  g.drawImage(ref,  tx*256-ox, ty*256-oy, 256, 256);
    }
  }

  /* 주변 응급실 → 상위 3곳 */
  rows.slice(0,80).forEach(function(h){
    if(top.indexOf(h)>=0) return;
    var p=px(h.y,h.x);
    if(p[0]<4||p[0]>W-4||p[1]<4||p[1]>H-4) return;
    var rr=3+Math.min(3.5,h.pd/4);
    g.fillStyle=h._blk.length?BLK:(h.oc!=null&&h.oc>=50?BUSY:DIM);
    g.globalAlpha=.9; g.beginPath(); g.arc(p[0],p[1],rr,0,Math.PI*2); g.fill();
    g.strokeStyle='rgba(0,0,0,.55)'; g.lineWidth=1.5; g.stroke(); g.globalAlpha=1;
    hit.push({h:h,x:p[0],y:p[1],r:Math.max(rr,10)});
  });
  top.forEach(function(h,i){
    var p=px(h.y,h.x), st=h._blk.length?BLK:(h.oc!=null&&h.oc>=50?BUSY:null);
    g.strokeStyle='rgba(138,180,248,.85)'; g.lineWidth=1.5; g.setLineDash([4,3]);
    g.beginPath(); g.moveTo(cx,cy); g.lineTo(p[0],p[1]); g.stroke(); g.setLineDash([]);
    g.fillStyle='#2a4bd0'; g.beginPath(); g.arc(p[0],p[1],12,0,Math.PI*2); g.fill();
    g.strokeStyle='rgba(255,255,255,.9)'; g.lineWidth=2; g.stroke();
    if(st){ g.strokeStyle=st; g.lineWidth=2.5; g.beginPath(); g.arc(p[0],p[1],16,0,Math.PI*2); g.stroke(); }
    g.fillStyle='#fff'; g.font='700 12px system-ui'; g.textAlign='center'; g.textBaseline='middle';
    g.fillText(String(i+1), p[0], p[1]+0.5);
    g.font='600 11.5px system-ui'; g.textBaseline='alphabetic';
    var lb=(h.a||'').split(' ').slice(-1)[0]+' '+h._d.toFixed(1)+'km';
    g.strokeStyle='rgba(0,0,0,.75)'; g.lineWidth=3; g.strokeText(lb,p[0],p[1]+29);
    g.fillStyle='#e8eefc'; g.fillText(lb,p[0],p[1]+29); g.textAlign='left';
    hit.push({h:h,x:p[0],y:p[1],r:15});
  });

  /* 내 위치 */
  g.fillStyle='#fff'; g.beginPath(); g.arc(cx,cy,5,0,Math.PI*2); g.fill();
  g.strokeStyle='rgba(255,255,255,.45)'; g.lineWidth=2;
  g.beginPath(); g.arc(cx,cy,11,0,Math.PI*2); g.stroke();
  g.fillStyle='#cfd8e8'; g.font='10px system-ui'; g.textAlign='center';
  g.strokeStyle='rgba(0,0,0,.7)'; g.lineWidth=3;
  var me=usingDefault?'서울 중심(예시)':'내 위치';
  g.strokeText(me,cx,cy+26); g.fillText(me,cx,cy+26); g.textAlign='left';

  /* 출처 표기 — 타일 제공자 약관상 필요하다 */
  g.fillStyle='rgba(255,255,255,.45)'; g.font='9.5px system-ui';
  g.fillText('© Esri · OpenStreetMap contributors', 8, H-7);

  if(selKey){
    var sel=hit.filter(function(t){return key(t.h)===selKey;})[0];
    if(sel){ g.strokeStyle='#fff'; g.lineWidth=2;
      g.beginPath(); g.arc(sel.x,sel.y,sel.r+7,0,Math.PI*2); g.stroke(); }
  }
  function at(ev){
    var b=cv.getBoundingClientRect(), mx=ev.clientX-b.left, my=ev.clientY-b.top, best=null, bd=1e9;
    hit.forEach(function(t){ var d=Math.hypot(t.x-mx,t.y-my); if(d<t.r+8&&d<bd){bd=d;best=t;} });
    return best;
  }
  cv.onclick=function(ev){
    var t=at(ev);
    selKey = t ? (key(t.h)===selKey ? null : key(t.h)) : null;
    renderPick(); drawWeb(rows);
  };
  cv.onmousemove=function(ev){ cv.style.cursor=at(ev)?'pointer':'default'; };
}

function key(h){ return h.n+'@'+h.y+','+h.x; }

/* 지도에서 고른 병원의 정보 — 지도 바로 아래 */
function renderPick(){
  var box=document.getElementById('mapsel'); if(!box) return;
  if(!selKey){ box.innerHTML=''; return; }
  var t=hit.filter(function(x){return key(x.h)===selKey;})[0];
  if(!t){ box.innerHTML=''; return; }
  var h=t.h, map='https://map.kakao.com/link/to/'+encodeURIComponent(h.n)+','+h.y+','+h.x;
  var pct = h._r==null?null:Math.round(h._r*100);
  box.innerHTML='<div class="card picked"><div class="row1"><span class="name">'+h.n+'</span>'
    +'<span class="dist">'+h._d.toFixed(1)+'km</span></div>'
    +'<p class="sub" style="margin-left:0">'+h.g+' · '+h.a+' · 차로 약 '+Math.round(h._travel)+'분(추정)</p>'
    +'<div class="chips">'+chips(h)+'</div>'
    +(pct!=null?'<div class="bar2">도착할 때도 지금처럼 자리가 있을 가능성 <b>'+pct+'%</b>'
       +'<div class="track"><div class="fill" style="width:'+pct+'%"></div></div></div>':'')
    +(h._ms.length?'<div class="notice'+(h._blk.length?'':' info')+'">'
       +'<span class="lab">'+(h._blk.length?ICON_ALERT+'이 병원이 올린 진료 제한 공지'
            :(group(h)===1?ICON_INFO+'전화로 먼저 확인해 달라는 공지':ICON_INFO+'이 병원이 올린 안내'))+'</span>'
       +h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')+'</div>':'')
    +'<div class="acts">'+(h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
    +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
}

function chips(h){
  var c=[];
  if(h.pd>0) c.push('<span class="chip'+(h.pd>=2?' ok':'')+'">소아과 전문의 '+h.pd+'명</span>');
  if(h.pc>0) c.push('<span class="chip ok">소아 응급 병상 '+h.pc+'석</span>');
  if(h.ni)   c.push('<span class="chip">신생아 중환자실</span>');
  if(h.oc!=null) c.push(h.oc>=50
      ? '<span class="chip warn">응급실 '+h.oc+'% 참 · '+STAMP+'</span>'
      : '<span class="chip">응급실 자리 있었음 · '+STAMP+'</span>');
  if(!h.pd && !h.pc && !h.ni) c.push('<span class="chip none">소아 정보 없음</span>');
  return c.join('');
}
function card(h,i){
  var map='https://map.kakao.com/link/to/'+encodeURIComponent(h.n)+','+h.y+','+h.x;
  var pct = h._r==null?null:Math.round(h._r*100);
  return '<div class="card"><div class="row1"><span class="num">'+(i+1)+'</span>'
    +'<span class="name">'+h.n+'</span><span class="dist">'+h._d.toFixed(1)+'km</span></div>'
    +'<p class="sub">'+h.g+' · '+h.a+' · 차로 약 '+Math.round(h._travel)+'분(추정)</p>'
    +'<div class="chips">'+chips(h)+'</div>'
    +(pct!=null?'<div class="bar2">도착할 때도 지금처럼 자리가 있을 가능성 <b>'+pct+'%</b>'
       +'<div class="track"><div class="fill" style="width:'+pct+'%"></div></div></div>':'')
    +(h._ms.length?'<div class="notice'+(h._blk.length?'':' info')+'">'
       +'<span class="lab">'+(h._blk.length?ICON_ALERT+'이 병원이 올린 진료 제한 공지'
            :(group(h)===1?ICON_INFO+'전화로 먼저 확인해 달라는 공지':ICON_INFO+'이 병원이 올린 안내'))+'</span>'
       +h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')
       +(h._ms.length>2?'<p style="color:var(--muted)">외 '+(h._ms.length-2)+'건</p>':'')+'</div>':'')
    +(h._why.length?'<p class="reason">'+h._why.join(' · ')+'</p>':'')
    +'<div class="acts">'+(h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
    +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
}
/* 지도는 선택과 무관하게 위치만 있으면 바로 그린다 — 히어로 바로 아래가 주인공 자리다 */
function renderMap(){
  var box=document.getElementById('mapPanel'); if(!box) return;
  var rows=candidates();
  /* 타일은 거른 목록이 아니라 60km 안 전체에서 센다 — candidates()는 소아 정보가
     있는 곳으로 좁혀 놔서, 그대로 세면 "응급실 123 / 소아 정보 123"처럼 같은 수가 나온다 */
  var near=DATA.filter(function(h){return km(here[0],here[1],h.y,h.x)<60;});
  var ped=near.filter(function(h){return h.pd>0||h.pc>0;}).length;
  var busy=near.filter(function(h){return h.oc!=null&&h.oc>=50;}).length;
  var blk=near.filter(function(h){return activeMsgs(h).filter(function(m){return m[5];}).length;}).length;
  function tile(k,v,t,col,on){
    return '<div'+(on?' class="on"':'')+'><div class="k">'+k+'</div><div class="v">'+v+'</div>'
      +'<div class="t"><i style="background:'+col+'"></i>'+t+'</div></div>';
  }
  box.innerHTML='<div class="tiles">'
    + tile('60km 안 응급실', near.length, '전부', 'var(--mapdim)')
    + tile('소아 진료 정보 있음', ped, '추천은 이 안에서', 'var(--accent)', true)
    + tile('응급실이 붐볐던 곳', busy, '전체 응급실 기준 · '+STAMP, '#d9892b')
    + tile('진료 제한 공지', blk, '내용을 읽어 보세요', '#e05c54')
    + '</div>'
    +'<details class="plot" open><summary>어디쯤에 있는지 보기</summary>'
    +'<canvas id="web"></canvas>'
    +'<p class="maplabel">'+(usingDefault
        ? '<b>서울 중심을 기준으로 한 예시입니다.</b> 위 <b>[내 주변 응급실 보기]</b>를 누르면 '
          +'내 위치로 다시 그립니다. ' : '')
    +'북쪽이 위입니다. <b>점을 누르면 그 병원 정보와 전화번호가 나옵니다.</b> '
    +'<b>점을 누르면 그 병원 정보와 전화번호</b>가 나오고, 길 안내는 [길찾기]를 누르세요. '
    +'지도 배경은 외부에서 받아오므로 <b>보고 있는 지역이 지도 제공자에게 전달됩니다</b> — '
    +'정확한 좌표나 고른 내용은 보내지 않습니다.</p>'
    +'<div id="mapsel"></div>'
    +'<div class="legend">'
    +'<span><i style="background:var(--accent)"></i>①②③ 아래 카드와 같은 순서</span>'
    +'<span><i style="background:#d9892b"></i>응급실이 붐볐던 곳(전체 기준)</span>'
    +'<span><i style="background:#e05c54"></i>진료 제한 공지</span>'
    +'<span><i style="background:var(--mapdim)"></i>그 밖의 응급실 · 점 크기는 소아 진료 여건</span>'
    +'</div></details>';
  drawWeb(rows);
  renderPick();   /* 다시 그릴 때마다 칸이 비므로 고른 병원을 복원한다
                     (창 크기·화면 회전·나이 변경 때마다 renderMap이 돈다) */
}
function group(h){                    /* 병원이 스스로 말한 것으로 묶는다 */
  if(!h._ms.length) return 0;         /* 공지 없음 */
  return Math.max.apply(null, h._ms.map(function(m){return m[5];}));
}
function places(){
  if(usingDefault) return '<div class="ask">갈 수 있는 곳을 찾아 드리려면 위치가 필요합니다. '
    +'위 <b>[내 주변 응급실 보기]</b>를 눌러 주세요 — 위치는 이 화면 안에서만 쓰이고 저장되지 않습니다.</div>';
  var rows=candidates();
  if(!rows.length) return '<div class="ask">가까운 곳을 찾지 못했습니다. 119에 물어보세요.</div>';
  var g=[[],[],[]];
  rows.forEach(function(h){ g[group(h)].push(h); });
  var out='', n=0;
  function block(list,title,desc,limit){
    if(!list.length) return '';
    var h2='<h3 class="gh">'+title+'<span>'+list.length+'곳</span></h3>'
      +(desc?'<p class="gd">'+desc+'</p>':'');
    return h2+list.slice(0,limit).map(function(h){ return card(h,n++); }).join('');
  }
  out+=block(g[0],'바로 가 볼 만한 곳','병원이 지금 걸어 둔 제한 공지가 없는 곳입니다. 그래도 출발 전 전화로 확인하세요.',3);
  out+=block(g[1],'전화로 먼저 확인하라고 한 곳','병원이 "사전 문의"를 요청해 둔 곳입니다. 전화가 꼭 필요합니다.',2);
  out+=block(g[2],'지금 제한을 걸어 둔 곳','빼지 않고 보여 드립니다 — 제한이 우리 아이에게 해당되는지는 내용을 읽고 판단하세요.',2);
  out+=moonlight();
  return out;
}

/* 달빛어린이병원 — 응급실이 아니라 야간·휴일 소아 외래.
   응급실 목록과 **섞지 않는다.** 경증이 응급실을 채우지 않게 하려고 만든 제도인데
   우리가 한 줄에 늘어놓으면 그 구분이 사라진다 */
function moonlight(){
  if(!MOON.length || !here) return '';
  var rows=MOON.map(function(m){
    return {m:m, d:km(here[0],here[1],m.y,m.x)};
  }).filter(function(r){return r.d<30;}).sort(function(a,b){return a.d-b.d;}).slice(0,3);
  if(!rows.length) return '';
  return '<h3 class="gh">응급실 말고 — 야간·휴일 소아 외래<span>달빛어린이병원</span></h3>'
    +'<p class="gd">열이나 감기처럼 급하지 않은 증상이면 응급실보다 이쪽이 맞습니다. '
    +'<b>평일 밤 11~12시, 주말·공휴일 오후 6시까지</b>가 제도 기준이지만 병원마다 다르고 '
    +'임시 휴진도 있어 <b>가시기 전에 꼭 전화로 확인하세요.</b></p>'
    + rows.map(function(r){
        var m=r.m, map='https://map.kakao.com/link/to/'+encodeURIComponent(m.n)+','+m.y+','+m.x;
        return '<div class="card moon"><div class="row1"><span class="name">'+m.n+'</span>'
          +'<span class="dist">'+r.d.toFixed(1)+'km</span></div>'
          +'<p class="sub" style="margin-left:0">'+(m.kind||'')+' · '+m.a+'</p>'
          +'<div class="acts">'+(m.t?'<a class="tel" href="tel:'+m.t+'">전화 '+m.t+'</a>':'')
          +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
      }).join('');
}
function show(){
  renderMap();
  var el=document.getElementById('result'); if(!el) return;
  el.innerHTML = '<div class="ask">전화로 이렇게만 물어보시면 됩니다<br>'
    + '<b>“○개월 아기가 △△한데, 지금 소아 진료 되나요?”</b></div>'
    + places();
}
document.getElementById('loc').onclick=function(){
  var st=document.getElementById('status');
  if(!navigator.geolocation){ st.textContent='이 브라우저에서는 위치를 쓸 수 없습니다.'; return; }
  st.textContent='위치 확인 중…';
  navigator.geolocation.getCurrentPosition(function(p){
    here=[p.coords.latitude,p.coords.longitude]; usingDefault=false;
    st.textContent='가까운 곳을 찾았습니다.'; show();
  },function(){ st.textContent='위치를 가져오지 못했습니다. 119에 물어보시는 편이 빠릅니다.'; },
  {timeout:8000,maximumAge:60000});
};
addEventListener('resize',function(){ show(); });
show();   /* 위치를 묻기 전에도 지도가 먼저 떠 있게 한다 */

/* 화면 밝기 토글. OS 설정을 따라가지 않고 사용자가 고른다.
   고른 값은 **저장하지 않는다** — 쿠키·기록을 남기지 않는다는 약속을 지키려고,
   새로 열면 다시 밝은 화면에서 시작한다 */
document.getElementById('theme').onclick=function(){
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  document.documentElement.setAttribute('data-theme', dark?'light':'dark');
  this.setAttribute('aria-pressed', String(!dark));
  this.setAttribute('aria-label', dark?'어두운 화면으로 바꾸기':'밝은 화면으로 바꾸기');
  show();                               /* 그림은 CSS 변수를 읽으므로 다시 그린다 */
};

/* 값은 바깥 data.json에서 가져온다. 그게 있으면 그걸 쓰고, 없으면(로컬 파일로
   열었을 때 등) HTML에 박아 둔 값으로 그대로 돈다 — 서버 없이도 열리고,
   올려 두면 최신으로 뜬다.
   **열어 둔 탭도 5분마다 다시 가져온다** — 새벽에 띄워 놓고 한참 보는 화면이라
   숫자가 굳어 있으면 안 된다 */
var DATA_URL=__DATA_URL__;
function pull(){
  fetch(DATA_URL,{cache:'no-store'}).then(function(r){ return r.ok?r.json():null; })
   .then(function(j){
     if(!j||!j.rows||!j.rows.length) return;
     DATA=j.rows; ASOF=j.asOf||ASOF; STAMP=ASOF.slice(5); if(j.moon) MOON=j.moon;
     show();
   }).catch(function(){});
}
pull();
setInterval(pull, 300000);
"""


#: 아이콘은 그린다 — 이모지를 아이콘 자리에 쓰지 않는다. 획 두께 1.6으로 통일.
LOGO = ('<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#fff" '
        'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M12 21s-7-4.6-7-10a4.6 4.6 0 0 1 7-3.9A4.6 4.6 0 0 1 19 11c0 5.4-7 10-7 10Z"/>'
        '<path d="M12 10v4M10 12h4"/></svg>')
ICON_ALERT = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'
              '<path d="M12 9v4M12 17h.01"/></svg>')
ICON_INFO = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
             'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
             '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>')

ICON_MOON = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
             'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
             '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>')

TITLE = "아이가 아픈데 어디로 가야 할까요"
DESC = ("아이 나이와 증상을 두 번만 고르면 지금 119인지 응급실인지 알려 드립니다. "
        "소아 진료가 되는 응급실을 공개 데이터로 찾아 드립니다.")


def build(rows: list[dict], meta: dict) -> str:
    tier2 = sum(1 for r in rows if r["pc"] > 0 and r["pd"] >= 2)
    o = []
    A = o.append
    A("<!doctype html>")
    A('<html lang="ko"><head><meta charset="utf-8">')
    A(f"<title>{esc(TITLE)}</title>")
    A('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
    A(f'<meta name="description" content="{esc(DESC)}">')
    A(f'<meta property="og:title" content="{esc(TITLE)}"><meta property="og:description" content="{esc(DESC)}">')
    A('<meta property="og:type" content="website">')
    A('<meta name="theme-color" content="#ffffff">')
    A('<meta name="robots" content="index,follow">')
    A(f"<style>{CSS}</style></head><body>")

    A('<nav class="bar"><div class="in"><span class="logo"><span class="mark">' + LOGO + "</span>우리 아이 응급 길잡이</span>")
    A('<nav><a href="#tool">지금 어떻게 하죠</a><a href="#why">왜 만들었나</a>'
      '<a href="#how">어떻게 고르나</a><a href="#faq">자주 묻는 것</a></nav>')
    A('<button class="theme" id="theme" aria-label="어두운 화면으로 바꾸기" '
      'aria-pressed="false">' + ICON_MOON + '</button>')
    A('<a class="cta" href="tel:119">119 전화하기</a></div></nav>')

    A('<header class="hero">')
    A("<h1>아이가 아픈데,<br><em>어디로</em> 가야 할까요?</h1>")
    A(
        '<p class="lead">아이 나이와 증상을 두 번만 고르면 지금 무엇을 해야 할지 알려 드립니다. '
        "고른 내용과 위치는 이 화면 밖으로 나가지 않습니다.</p>"
    )
    A('<div class="ctas"><button class="btn btn-ghost" id="loc">내 주변 응급실 보기</button>')
    A('<a class="btn btn-call" href="tel:119">119 전화하기</a></div>')
    A('<p class="fine">숨을 못 쉬거나 · 반응이 없거나 · 경련이 멈추지 않으면 고르지 말고 지금 119입니다</p>')
    A('<p id="status"></p>')
    A("</header>")

    # ── 창 모양 프레임: 선택 → 지표 → 그림. 앱토의 대시보드 자리 ──
    A('<section class="frame" id="tool"><div class="win">')
    A('<div class="chrome"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i>'
      '<i style="background:#28c840"></i><span class="path">우리아이응급길잡이 / 내 주변</span></div>')
    A('<div class="body">')
    A('<div class="topline"><span class="crumb">내 주변 <b>갈 수 있는 곳</b></span>'
      f'<span class="stamp">{esc(meta["asOf"])} 기준</span></div>')
    A('<div id="mapPanel"></div>')
    A("</div></div></section>")

    A('<div class="results"><div class="in reveal" id="result"></div></div>')

    # ── 랜딩: 왜 필요한가 (전부 우리가 직접 잰 공개 데이터 수치) ──
    A('<section class="sec" id="why"><div class="in"><h2 class="st">왜 이런 걸 만들었나</h2>')
    A(
        '<p class="desc">아이가 아플 때 보호자가 가장 먼저 부딪히는 건 "어디로 가야 하나"입니다. '
        "그런데 공개된 정보만으로는 답하기 어렵게 돼 있습니다. 직접 세어 봤습니다.</p>"
    )
    A(
        f'<p class="lede">전국 응급의료기관 가운데 소아 응급 병상과 소아청소년과 전문의 2명을 '
        f'함께 갖춘 곳은 <span class="n">{tier2}</span>곳뿐입니다. 서울 22곳 · 경기 16곳인 반면 '
        "<b>울산 1곳 · 충북 1곳 · 세종은 한 곳도 없습니다.</b></p>"
    )
    A(
        '<p class="lede">소아 병상 수가 실제로 올라오는 응급실은 <span class="n">23</span>%'
        "(416곳 중 95곳)입니다. 그마저 거의 갱신되지 않아 <b>“지금 몇 자리”는 누구도 알 수 "
        "없습니다.</b> 그래서 저희도 그 숫자를 만들어 내지 않았습니다.</p>"
    )
    A(
        f'<p class="lede">반대로 <span class="n">{meta.get("msgCount", 75)}</span>곳은 '
        "“지금 이런 환자는 못 받는다”를 이미 공개해 두었습니다. "
        "<b>3개월 이하 발열 진료불가</b> 같은 문장이 공개돼 있는데도 "
        "정작 그 아기를 안고 있는 보호자에게는 보이지 않습니다.</p>"
    )
    A("</div></section>")

    # ── 랜딩: 어떻게 고르나 ──
    A('<section class="sec" id="how"><div class="in"><h2 class="st">어떻게 고르나요</h2>')
    A('<p class="desc">점수가 아니라 <b>분(分)</b>으로 계산합니다. 그래야 왜 이 순서인지 설명할 수 있습니다.</p>')
    A('<div class="steps">')
    for i, (t, d) in enumerate([
        ("지금 119인지 먼저 가립니다",
         "숨쉬기·경련·축 처짐이면 병원 목록을 보여 주지 않고 119만 안내합니다. "
         "규칙으로만 판단하며 AI가 진단하지 않습니다."),
        ("가는 데 드는 분을 계산합니다",
         "이동 시간에서 소아 진료 여건만큼 빼고, 응급실이 붐빈 만큼 더합니다. "
         "그래서 가까워도 여건이 얕으면 뒤로 갑니다."),
        ("병원이 올린 공지를 그대로 보여 드립니다",
         "순서에는 반영하지 않습니다. 일부 분과만의 제한일 수 있어, "
         "그 공지가 우리 아이에게 해당되는지는 저희가 판단하지 않습니다."),
    ]):
        A(f'<div class="step"><div class="k">{i+1}</div><div><b>{t}</b><p>{d}</p></div></div>')
    A("</div></div></section>")

    # ── FAQ ──
    A('<section class="sec" id="faq"><div class="in"><h2 class="st">자주 묻는 것</h2><div class="faq">')
    for q, a in [
        ("지금 자리가 있는지 알 수 있나요?",
         "응급실 전체 혼잡도는 보여 드리지만 <b>소아 병상은 알 수 없습니다.</b> "
         "전국 응급실의 23%만 소아 병상 수를 올리고 그마저 거의 갱신되지 않습니다. "
         "모르는 것을 아는 척하지 않으려고 숫자를 지어내지 않았습니다."),
        ("전화를 꼭 해야 하나요?",
         "네. <b>오늘 밤 소아과 당직이 누구인지는 공개된 데이터 어디에도 없습니다.</b> "
         "이 화면은 갈 필요가 없는 곳을 줄여서 전화 횟수를 줄이는 것까지만 합니다."),
        ("제 위치가 저장되나요?",
         "저장은 하지 않습니다 — 로그인·쿠키·접속 기록이 없습니다. 다만 <b>지도 배경을 "
         "외부에서 받아오기 때문에 보고 있는 지역은 지도 제공자에게 전달됩니다.</b> "
         "정확한 좌표는 브라우저 안에서만 쓰이고 저희 쪽으로는 오지 않습니다."),
        ("병원을 추천해 주는 건가요?",
         "아닙니다. 거리와 소아 진료 여건으로 정한 <b>순서</b>일 뿐이고 어디가 더 낫다는 추천이 아닙니다. "
         "판단 기준도 의사가 검토하기 전의 초안입니다. 헷갈리시면 119에 전화해 물어보셔도 됩니다 — "
         "119는 상담도 합니다."),
    ]:
        A(f"<details><summary>{q}</summary><p>{a}</p></details>")
    A("</div></div></section>")

    A('<section class="sec"><div class="in"><div class="note"><p><strong>이 화면이 할 수 있는 일과 못 하는 일</strong></p><ul>')
    A(
        "<li><strong>전화를 대신하지 못합니다.</strong> 오늘 밤 소아과 당직이 누구인지는 공개된 "
        "데이터 어디에도 없습니다. 이 화면은 <strong>갈 필요가 없는 곳을 줄여 주는 것</strong>까지만 "
        "합니다. 마지막 확인 전화는 직접 거셔야 합니다.</li>"
    )
    A(
        "<li><strong>실시간 소아 병상이 아닙니다.</strong> 소아 병상은 전국 응급실 416곳 중 "
        "95곳(23%)만 값이 올라오고 거의 갱신되지 않아 “지금 몇 자리”를 말할 수 없습니다.</li>"
    )
    A(
        f"<li><strong>“응급실 N% 참”은 소아 혼잡도가 아닙니다.</strong> 그 병원 응급실 전체의 "
        f"(정원 − 남은 자리) ÷ 정원이고 <strong>{esc(meta['asOf'])} 기준</strong>입니다. "
        "소아 자리만 따로 세는 숫자는 공개되지 않습니다.</li>"
    )
    A(
        f"<li><strong>“도착할 때도 자리가 있을 가능성”</strong>은 응급실 전체 병상을 대상으로 한 "
        f"생존 모델(infosurv)의 출력입니다 — 지금 값이 도착 시점까지 유지될 확률이고, "
        f"<strong>{esc(meta['asOf'])} 기준</strong>입니다. 소아 전용 수치가 아닙니다."
        + (f" 모델 {esc(meta['modelTag'])}, 적용 {meta['relCount']}곳." if meta.get("modelTag") else "")
        + "</li>"
    )
    A(
        "<li><strong>지도의 거리는 km가 아닙니다.</strong> 방향은 실제 방위이고 거리는 "
        "“가는 데 드는 분”으로, 이동 시간에서 소아 진료 여건만큼 빼고 혼잡한 만큼 더한 값입니다. "
        "가까워도 여건이 얕으면 멀리 그려집니다.</li>"
    )
    A(
        "<li><strong>병원 공지는 순서에 반영하지 않습니다.</strong> “소아신경분과 진료불가”처럼 "
        "일부 분과만의 제한일 수 있어, 그 공지가 우리 아이에게 해당되는지는 저희가 판단하지 "
        "않습니다. 문장을 그대로 보여 드리니 직접 읽고 판단하세요."
        + (f" (적용 {meta['msgCount']}곳)" if meta.get("msgCount") else "")
        + "</li>"
    )
    A(
        "<li>전문의 수는 그 병원 소속 인원이고 <strong>지금 당직인지는 알 수 없습니다.</strong> "
        f"소아 응급 병상과 소아과 전문의 2명을 함께 갖춘 곳은 전국 <strong>{tier2}곳</strong>뿐입니다.</li>"
    )
    A(
        "<li>판단 기준은 <strong>의사가 검토하기 전의 초안</strong>이고 규칙으로만 동작합니다. "
        "AI가 진단하지 않습니다. 헷갈리시면 119에 전화해 물어보셔도 됩니다 — 119는 상담도 합니다.</li>"
    )
    A(
        f"<li><strong>달빛어린이병원은 응급실이 아닙니다.</strong> 야간·휴일에 경증 소아를 보는 "
        f"외래로, 전국 <strong>{meta.get('moonCount', 0)}곳</strong>입니다(국립중앙의료원 집계). "
        "제도 기준은 평일 밤 11~12시·주말 공휴일 오후 6시까지이지만 <strong>병원마다 다르고 "
        "임시 휴진도 있어</strong> 운영시간은 공개되지 않습니다 — 반드시 전화로 확인하세요.</li>"
    )
    A("<li>출처: 중앙응급의료센터 E-Gen 공개 API, 건강보험심사평가원 공개 API, "
      "국립중앙의료원 달빛어린이병원 목록.</li>")
    A(
        "<li><strong>아무것도 저장하지 않습니다</strong> — 로그인·쿠키·접속 기록이 없습니다. "
        "다만 지도 배경은 외부(Esri·OpenStreetMap)에서 받아오므로 <strong>보고 있는 지역이 "
        "지도 제공자에게 전달됩니다.</strong> 정확한 좌표나 고른 내용은 보내지 않습니다.</li>"
    )
    A("</ul></div>")
    A(
        "<footer><b>우리 아이 응급 길잡이</b> — 중앙응급의료센터 E-Gen·건강보험심사평가원 "
        f"공개 API로 만든 비영리 시연 서비스입니다. 데이터 기준 {esc(meta['asOf'])}.<br>"
        "응급 상황에서는 <b>먼저 119</b>에 전화하세요. 이 화면은 의료 조언이 아닙니다."
        "</footer>"
    )
    A("</div></section>")

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    moon = json.dumps(meta.get("moon", []), ensure_ascii=False, separators=(",", ":"))
    # 배포본은 공개 URL을 가리킨다(PEDS_DATA_URL). 없으면 같은 폴더의 data.json.
    data_url = os.environ.get("PEDS_DATA_URL", "data.json")
    js = (JS_TMPL.replace("__DATA__", data).replace("__MOON__", moon).replace("__ASOF__", meta["asOf"])
          .replace("__ICON_ALERT__", json.dumps(ICON_ALERT))
          .replace("__ICON_INFO__", json.dumps(ICON_INFO))
          .replace("__DATA_URL__", json.dumps(data_url)))
    A("<script>" + js + "</script>")
    A("</body></html>")
    return "\n".join(o)


def main() -> None:
    rows, meta = load()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build(rows, meta))
    # 배포용으로 데이터를 따로도 떨군다. 이 파일만 주기적으로 다시 올리면
    # HTML은 그대로 두고 내용이 갱신된다(화면이 있으면 data.json을 우선 쓴다).
    data_path = os.path.join(os.path.dirname(OUT), "data.json")
    with open(data_path, "w", encoding="utf-8") as fp:
        json.dump({"asOf": meta["asOf"], "rows": rows, "moon": meta.get("moon", [])}, fp, ensure_ascii=False, separators=(",", ":"))
    print(f"생성: {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    print(f"      {data_path}  ({os.path.getsize(data_path)/1024:.0f} KB)")
    print(f"  전국 {len(rows)}곳 · 기준 {meta['asOf']}")
    print(f"  달빛어린이병원 {meta['moonCount']}곳")
    print(f"  병원 공지 {meta['msgCount']}곳 · 신뢰도 {meta['relCount']}곳 ({meta['modelTag'] or '없음'})")


if __name__ == "__main__":
    main()
