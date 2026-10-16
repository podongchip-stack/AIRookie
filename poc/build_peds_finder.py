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
            "ad": addr,                       # 전체 주소 — 동·도로명 검색용
            "pd": next((iv(x.get("dtlSdrCnt")) or 0 for x in spec.get(hpid, [])
                        if x.get("dgsbjtCdNm") == PED_DEPT), 0),
            "pc": iv(bed.get("hvs02")) or 0,
            "ni": 1 if (iv(bed.get("hvs19")) or 0) > 0 else 0,
            "av": avail,
            "cp": cap,                        # 응급실 정원 — "16/28석"을 쓰려면 필요
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
        #: 병상 숫자가 아예 안 올라오는 기관 수 — 화면에 "미제공"으로 밝힌다
        "noBedCount": sum(1 for r in rows if r.get("av") is None and r.get("oc") is None),
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

/* 차로 걸리는 분 — 직선거리에서 어림한다(실제 도로 안내가 아니다).
   예전엔 거리에 2.5분/km를 곧바로 곱했다. 그 값은 도심 단거리(평균 24km/h)에나 맞아서
   먼 곳이 크게 부풀었다 — 경상국립대 → 삼천포(직선 26km)가 66분으로 떴지만 실제 도로는
   37분이다. 가까울수록 신호·좁은 길에 묶이고 멀수록 국도·고속으로 빠지므로, 거리에 따라
   평균 속도를 24 → 60km/h로 올려 잡고 직선거리에 우회 계수 1.28을 곱한다.
   대조(실제 도로 안내): 26km 37분 → 39분, 3km 9분, 1km 3분. ±10% 안에 든다.
   도로 ETA를 쓰려면 키가 필요하고 목적지 좌표를 바깥에 보내야 해서 쓰지 않는다 */
function driveMin(d){
  var v=24+36*(1-Math.exp(-d/18));     /* km/h — 거리에 따라 24에서 60으로 */
  return d*1.28/v*60;
}
function thread(h){
  var travel=driveMin(h._d), min=travel, why=[], parts=[];
  if(h.pc>0 && h.pd>=2){ min-=5; why.push('소아 응급 병상과 소아과 전문의를 갖춘 곳'); parts.push('소아 여건 −5분'); }
  else if(h.pd>=2){ min-=3; why.push('소아과 전문의가 여러 명 있는 곳'); parts.push('소아 여건 −3분'); }
  else if(h.pd>=1){ min-=1; why.push('소아과 전문의가 있는 곳'); parts.push('소아 여건 −1분'); }
  if(h.oc!=null && h.oc>=80){ min+=5; why.push(STAMP+' 기준 응급실이 거의 찼던 곳'); parts.push('혼잡 +5분'); }
  else if(h.oc!=null && h.oc>=50){ min+=2; why.push(STAMP+' 기준 응급실이 붐볐던 곳'); parts.push('혼잡 +2분'); }
  /* 병원 공지는 순위를 건드리지 않는다 — 분과 단위 제한을 전면 차단으로 오인하면
     2km 병원이 5km 병원보다 뒤로 간다. 문장만 보여 주고 판단은 보호자가 한다 */
  h._ms=activeMsgs(h); h._blk=h._ms.filter(function(m){return m[5]===2;});
  h._travel=travel; h._len=Math.max(1,min); h._why=why;
  /* 순위를 어떻게 냈는지 한 줄로 — "왜 흰 2순위가 초록 3순위보다 위냐"에 답해야 한다 */
  h._calc='차로 약 '+Math.round(travel)+'분'
    + (parts.length?' · '+parts.join(' · '):'')
    + ' → 순위 점수 '+Math.round(h._len)+'분';
  h._r=rArrive(h,travel);
  return h._len;
}
/* 전국 전체를 한 번만 계산해 둔다. 지도를 끌 때마다 530곳을 다시 재면 버벅인다 */
/* 지역 검색 — 외부 지오코딩을 쓰지 않는다. 병원 주소에 이미 "서울특별시 성동구"가
   들어 있어서 그걸 색인하면 키도, 외부 요청도, 위치 유출도 없다.
   고른 지역에 있는 병원들의 평균 좌표를 그 지역의 기준점으로 삼는다 */
var PLACES=null;
function places_index(){
  if(PLACES) return PLACES;
  var out=[], seen={};
  /* ① 시군구 — 그 지역 병원들의 평균 좌표를 기준점으로 */
  var m={};
  DATA.forEach(function(h){
    if(!h.a) return;
    var o=m[h.a]||(m[h.a]={n:0,y:0,x:0}); o.n++; o.y+=h.y; o.x+=h.x;
  });
  Object.keys(m).forEach(function(k){
    var o=m[k];
    out.push({label:k, sub:'응급실 '+o.n+'곳', y:o.y/o.n, x:o.x/o.n, kind:'area'});
  });
  /* ② 읍·면·동 — 전체 주소에서 뽑는다. 같은 이름이 여러 시군구에 있으므로 함께 적는다.
     응급실 주소만 보면 "상암동"처럼 응급실이 없는 동이 안 걸린다. 달빛 주소도 같이 넣는다 */
  var d={};
  function dongs(addr, area, y, x){
    (addr||'').split(/[\s,()]+/).forEach(function(tk){
      if(!/^[가-힣0-9]+(동|읍|면|리|가)$/.test(tk) || tk.length<2) return;
      var k=area+' '+tk, o=d[k]||(d[k]={n:0,y:0,x:0,area:area,tk:tk});
      o.n++; o.y+=y; o.x+=x;
    });
  }
  DATA.forEach(function(h){ dongs(h.ad, h.a, h.y, h.x); });
  (MOON||[]).forEach(function(mm){
    dongs(mm.a, (mm.a||'').split(' ').slice(0,2).join(' '), mm.y, mm.x);
  });
  Object.keys(d).forEach(function(k){
    var o=d[k];
    out.push({label:o.tk, sub:o.area, y:o.y/o.n, x:o.x/o.n, kind:'dong'});
  });
  /* ③ 병원 이름 — 응급실과 달빛 둘 다. 고르면 그 병원이 지도에서 선택된다 */
  DATA.forEach(function(h){
    if(seen[h.n]) return; seen[h.n]=1;
    out.push({label:h.n, sub:h.a+' · 응급실', y:h.y, x:h.x, kind:'er', h:h});
  });
  (MOON||[]).forEach(function(mm){
    if(seen[mm.n]) return; seen[mm.n]=1;
    out.push({label:mm.n, sub:(mm.a||'').split(' ').slice(0,2).join(' ')+' · 달빛어린이병원',
              y:mm.y, x:mm.x, kind:'moon'});
  });
  PLACES=out;
  return PLACES;
}
function place_search(q){
  q=(q||'').trim().replace(/\s+/g,'');
  if(q.length<1) return [];
  var hit=[];
  places_index().forEach(function(p){
    var hay=(p.label+p.sub).replace(/\s+/g,'');
    var i=hay.indexOf(q);
    if(i<0) return;
    /* 앞에서 맞을수록, 지역 → 동 → 병원 순으로 위에 */
    var w=(p.kind==='area'?0:p.kind==='dong'?1:2)*100 + Math.min(i,50);
    hit.push({p:p,w:w});
  });
  hit.sort(function(a,b){ return a.w-b.w; });
  return hit.slice(0,8).map(function(x){ return x.p; });
}
/* 전국 전체를 한 번만 계산해 둔다. 지도를 끌 때마다 530곳을 다시 재면 버벅인다 */
var ALL=null;
function prepare(){
  if(!here){ ALL=[]; return; }
  ALL=DATA.slice();
  ALL.forEach(function(h){ h._d=km(here[0],here[1],h.y,h.x); thread(h); });
  ALL.sort(function(a,b){ return a._len-b._len; });
}
function candidates(){
  if(!ALL) prepare();
  var rows=ALL.filter(function(h){return h._d<60;});
  var ped=rows.filter(function(h){return h.pd>0||h.pc>0;});
  return ped.length>=3 ? ped : rows;
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
/* 보기 상태 — 사용자가 끌거나 확대하면 viewLocked이 켜지고, 그때부터 자동
   맞춤(상위 3곳이 들어오게)을 하지 않는다. [⌖]를 누르면 다시 맞춘다 */
var view=null, viewLocked=false, drag=null;
var onlyGood=false;   /* 지도에 '여건이 두루 좋은 곳'만 보이기 */
var ZMAX=16;          /* 타일 제공자가 주는 상한. 넘어가면 빈 화면이 된다 */
var ZMIN=6;           /* 축소 한계 — 캔버스 크기를 알 때 drawWeb이 다시 잡는다 */
/* 축소는 남한이 화면에 꽉 차는 단계에서 멈춘다 — 그보다 더 빼면 바다와 이웃 나라만
   넓어진다(응급실은 전부 이 안에 있다). 레벨이 정수라 반올림으로 가장 가까운 단계를
   고르고, 캔버스 크기가 화면마다 다르므로 상수로 박지 않고 그릴 때 계산한다 */
var KR={n:38.65,s:33.10,w:125.90,e:129.60};   /* 제주 남단 ~ 최북단 */
function fitZoomKR(W,H){
  var dy=(projY(KR.s,0)-projY(KR.n,0))/256, dx=(projX(KR.e,0)-projX(KR.w,0))/256;
  var z=Math.min(Math.log(H/(256*dy))/Math.LN2, Math.log(W/(256*dx))/Math.LN2);
  return Math.max(5,Math.min(ZMAX,Math.round(z)));
}
function lonAt(px,z){ return px/(256*Math.pow(2,z))*360-180; }
function latAt(py,z){
  var n=Math.PI-2*Math.PI*py/(256*Math.pow(2,z));
  return 180/Math.PI*Math.atan(0.5*(Math.exp(n)-Math.exp(-n)));
}
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
  var W=cv.clientWidth||520, H=Math.min(Math.round(W*0.78),620), r=window.devicePixelRatio||1;
  cv.width=W*r; cv.height=H*r; cv.style.height=H+'px';
  var g=cv.getContext('2d'); g.setTransform(r,0,0,r,0,0);
  hit=[];
  var acc=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  var BLK='#ff6b60', BUSY='#f0a94a', DIM='#7f8b9e', GOOD='#46d07f';

  ZMIN=fitZoomKR(W,H);                 /* 이 크기에서 전국이 꽉 차는 단계 */
  if(view && view.z<ZMIN) view.z=ZMIN; /* 창이 작아져 한계가 올라가면 같이 끌어올린다 */

  var top=rows.slice(0,3);
  if(!view || !viewLocked){            /* 상위 3곳이 들어오는 확대 단계로 맞춘다 */
    var far=0.8;
    top.forEach(function(h){ far=Math.max(far,h._d); });
    var need=Math.min(W,H)/2-40, mpp=156543.03*Math.cos(here[0]*Math.PI/180);
    view={z:Math.max(ZMIN,Math.min(ZMAX,Math.round(Math.log2(need*mpp/(far*1000))))),
          lat:here[0], lon:here[1]};
  }
  var z=view.z;
  var cx=W/2, cy=H/2, ox=projX(view.lon,z)-cx, oy=projY(view.lat,z)-cy;
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

  /* 화면 안에 들어오는 응급실 전부 — 전국까지 축소해도 점이 보이게 */
  (ALL||rows).forEach(function(h){
    if(top.indexOf(h)>=0) return;
    if(onlyGood && !good(h) && key(h)!==selKey) return;   /* 고른 점은 남긴다 */
    var p=px(h.y,h.x);
    if(p[0]<4||p[0]>W-4||p[1]<4||p[1]>H-4) return;
    var rr=3+Math.min(3.5,h.pd/4);
    g.fillStyle=h._blk.length?BLK:(h.oc!=null&&h.oc>=50?BUSY:(good(h)?GOOD:DIM));
    g.globalAlpha=.9; g.beginPath(); g.arc(p[0],p[1],good(h)?rr+1:rr,0,Math.PI*2); g.fill();
    g.strokeStyle='rgba(0,0,0,.55)'; g.lineWidth=1.5; g.stroke(); g.globalAlpha=1;
    hit.push({h:h,x:p[0],y:p[1],r:Math.max(rr,10)});
  });
  top.forEach(function(h,i){
    if(onlyGood && !good(h) && key(h)!==selKey) return;
    var p=px(h.y,h.x), st=h._blk.length?BLK:(h.oc!=null&&h.oc>=50?BUSY:(good(h)?GOOD:null));
    var me=px(here[0],here[1]);
    g.strokeStyle='rgba(138,180,248,.85)'; g.lineWidth=1.5; g.setLineDash([4,3]);
    g.beginPath(); g.moveTo(me[0],me[1]); g.lineTo(p[0],p[1]); g.stroke(); g.setLineDash([]);
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

  /* 내 위치 — **캔버스 중앙이 아니라 실제 좌표**에 그린다.
     중앙에 고정하면 지도를 끌거나 확대할 때 혼자 따라다닌다(실제로 그랬다) */
  var mp=px(here[0],here[1]);
  if(mp[0]>-30 && mp[0]<W+30 && mp[1]>-30 && mp[1]<H+30){
    g.fillStyle='#fff'; g.beginPath(); g.arc(mp[0],mp[1],5,0,Math.PI*2); g.fill();
    g.strokeStyle='rgba(255,255,255,.45)'; g.lineWidth=2;
    g.beginPath(); g.arc(mp[0],mp[1],11,0,Math.PI*2); g.stroke();
    g.font='10px system-ui'; g.textAlign='center';
    var lbl=usingDefault?'서울 중심(예시)':'내 위치';
    g.strokeStyle='rgba(0,0,0,.7)'; g.lineWidth=3;
    g.strokeText(lbl,mp[0],mp[1]+26);
    g.fillStyle='#cfd8e8'; g.fillText(lbl,mp[0],mp[1]+26);
    g.textAlign='left';
  }

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
  function recenter(nox,noy){        /* 픽셀 원점 → 중심 좌표 */
    view.lon=lonAt(nox+cx,z); view.lat=latAt(noy+cy,z); viewLocked=true;
  }
  function zoomAt(mx,my,dir){
    /* 5면 전국이 들어온다. 위는 16까지 — Esri 다크 그레이는 z17부터 빈 타일을 준다
       (응답은 200인데 내용이 없어 지도가 사라진 것처럼 보인다) */
    var nz=Math.max(ZMIN,Math.min(ZMAX,z+dir)); if(nz===z) return;
    var lon0=lonAt(ox+mx,z), lat0=latAt(oy+my,z);
    view.z=nz; viewLocked=true;
    var nox=projX(lon0,nz)-mx, noy=projY(lat0,nz)-my;
    view.lon=lonAt(nox+cx,nz); view.lat=latAt(noy+cy,nz);
    drawWeb(rows);
  }

  cv.onpointerdown=function(ev){
    /* 손가락 하나로는 지도를 끌지 않는다 — 그 제스처는 페이지 스크롤로 넘긴다.
       터치에서 지도 이동·확대는 두 손가락일 때만(아래 touch 처리) */
    if(ev.pointerType==='touch') return;
    /* 포인터 캡처가 실패해도 끌기는 되어야 한다 — 예외가 나면 아래가 통째로 안 돈다 */
    try{ cv.setPointerCapture(ev.pointerId); }catch(e){}
    drag={x:ev.clientX, y:ev.clientY, ox:ox, oy:oy, moved:0};
  };
  cv.onpointermove=function(ev){
    if(!drag){ cv.style.cursor=at(ev)?'pointer':'grab'; return; }
    var dx=ev.clientX-drag.x, dy=ev.clientY-drag.y;
    drag.moved=Math.max(drag.moved, Math.hypot(dx,dy));
    recenter(drag.ox-dx, drag.oy-dy);
    drawWeb(rows);
  };
  cv.onpointerup=function(ev){
    var moved=drag?drag.moved:0; drag=null;
    if(moved>6) return;                       /* 끌었으면 선택으로 치지 않는다 */
    var t=at(ev);
    selKey = t ? (key(t.h)===selKey ? null : key(t.h)) : null;
    renderPick(); drawWeb(rows);
  };
  cv.onpointercancel=function(){ drag=null; };
  cv.onwheel=function(ev){
    ev.preventDefault();
    var b=cv.getBoundingClientRect();
    zoomAt(ev.clientX-b.left, ev.clientY-b.top, ev.deltaY<0?1:-1);
  };
  /* 두 손가락 확대 — 포인터 이벤트만으로는 번거로워 터치 이벤트로 따로 받는다 */
  /* 두 손가락 = 지도 이동 + 확대. 한 손가락은 페이지 스크롤(탭은 선택) */
  var two=null;
  function mid(t){ return [(t[0].clientX+t[1].clientX)/2, (t[0].clientY+t[1].clientY)/2]; }
  function dist(t){ return Math.hypot(t[0].clientX-t[1].clientX, t[0].clientY-t[1].clientY); }
  cv.ontouchstart=function(ev){
    if(ev.touches.length===2){
      drag=null;
      two={d:dist(ev.touches), m:mid(ev.touches), ox:ox, oy:oy};
    }
  };
  cv.ontouchmove=function(ev){
    if(!two || ev.touches.length!==2) return;
    ev.preventDefault();                       /* 두 손가락일 때만 스크롤을 막는다 */
    var m=mid(ev.touches), d=dist(ev.touches);
    recenter(two.ox-(m[0]-two.m[0]), two.oy-(m[1]-two.m[1]));
    drawWeb(rows);
    if(d/two.d>1.4){ two.d=d; two.ox=ox; two.m=m; zoomAt(cx,cy,1); }
    else if(d/two.d<0.72){ two.d=d; two.ox=ox; two.m=m; zoomAt(cx,cy,-1); }
  };
  cv.ontouchend=function(){ two=null; };

  var gf=document.getElementById('gfilter');
  if(gf) gf.onclick=function(){
    onlyGood=!onlyGood;
    gf.setAttribute('aria-pressed', String(onlyGood));
    renderMap();          /* 버튼 글자(개수)도 같이 바뀐다 */
  };
  var zi=document.getElementById('zin'), zo=document.getElementById('zout'), zc=document.getElementById('zfit');
  if(zi){ zi.onclick=function(){ zoomAt(cx,cy,1); }; zi.disabled=(z>=ZMAX); }
  if(zo){ zo.onclick=function(){ zoomAt(cx,cy,-1); }; zo.disabled=(z<=ZMIN); }
  if(zc) zc.onclick=function(){ viewLocked=false; view=null; drawWeb(rows); };
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
    +'<div class="chips">'+(good(h)?'<span class="chip ok">여건이 두루 좋음</span>':'')+chips(h)+'</div>'
    +(pct!=null?'<div class="bar2">도착할 때도 지금처럼 자리가 있을 가능성 <b>'+pct+'%</b>'
       +'<div class="track"><div class="fill" style="width:'+pct+'%"></div></div></div>':'')
    +(h._ms.length?'<div class="notice'+(h._blk.length?'':' info')+'">'
       +'<span class="lab">'+(h._blk.length?ICON_ALERT+'이 병원이 올린 진료 제한 공지'
            :(group(h)===1?ICON_INFO+'전화로 먼저 확인해 달라는 공지':ICON_INFO+'이 병원이 올린 안내'))+'</span>'
       +h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')+'</div>':'')
    +'<div class="acts">'+(h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
    +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
}

/* "이 숫자가 언제 적 것인가" — 병원마다 다르다.
   예전엔 수집 시각(STAMP) 하나를 530곳에 똑같이 붙였다. 그러면 모든 병원이 방금
   갱신한 것처럼 보이는데 사실이 아니다. 실제로는 환자가 오갈 때마다 바뀌는 병원이
   있고, 며칠째 같은 값을 내보내는 병원이 있다. rl[1]이 **그 병원 값이 안 바뀐 채
   지난 시간(초)** — infosurv가 claim 수명을 재는 바로 그 값이라 이미 들어 있다.
   ⚠ 오래 안 바뀐 걸 "안정적"으로 읽으면 안 된다. 자동 연동이 끊긴 병원도 값이
   그대로라서, 나이가 길수록 **덜** 믿어야 한다(하루 넘으면 경고로 뒤집는다) */
function ageText(h){
  if(!h.rl || h.rl[1]==null) return null;
  var s=h.rl[1], m=Math.round(s/60);
  if(m<2)    return {t:'방금 바뀐 값', w:0};
  if(m<60)   return {t:m+'분째 같은 값', w:0};
  var hr=s/3600;
  if(hr<24)  return {t:Math.round(hr)+'시간째 같은 값', w:(hr>=6?1:0)};
  var d=Math.round(hr/24);
  return {t:d+'일째 안 바뀐 값', w:2};
}
function stampOf(h){                 /* 병원별 나이가 있으면 그걸, 없으면 수집 시각 */
  var a=ageText(h);
  return a ? a.t : STAMP+' 수집';
}
function chips(h){
  var c=[], a=ageText(h);
  if(h.pd>0) c.push('<span class="chip'+(h.pd>=2?' ok':'')+'">소아과 전문의 '+h.pd+'명</span>');
  if(h.pc>0) c.push('<span class="chip ok">소아 응급 병상 '+h.pc+'석</span>');
  if(h.ni)   c.push('<span class="chip">신생아 중환자실</span>');
  if(h.av!=null && h.cp){
    var free=Math.max(0,h.av);
    c.push('<span class="chip'+(h.oc>=50?' warn':'')+'">응급실 '+free+'/'+h.cp+'석'
      +(h.av<0?' (정원 초과)':'')+' · '+stampOf(h)+'</span>');
  } else if(h.oc!=null) {
    c.push(h.oc>=50 ? '<span class="chip warn">응급실 '+h.oc+'% 참 · '+stampOf(h)+'</span>'
                    : '<span class="chip">응급실 자리 있었음 · '+stampOf(h)+'</span>');
  }
  /* 하루 넘게 안 바뀐 값은 따로 경고한다 — 숫자만 보면 믿어 버리기 때문 */
  if(a && a.w===2) c.push('<span class="chip warn">자동 갱신이 끊겼을 수 있음</span>');
  /* 병상 숫자가 아예 안 올라오는 곳이 115곳(21.7%)이다. 예전엔 칸을 **그냥 비워**
     둬서 "병상이 없다"인지 "안 알려 준다"인지 구분이 안 됐다. 모르는 건 모른다고
     쓴다 — 자리가 없다는 뜻이 아니므로 순위에서도 안 밀어낸다 */
  var noBed=(h.av==null && h.oc==null), noPed=(!h.pd && !h.pc && !h.ni);
  if(noBed && noPed)
    c.push('<span class="chip none" title="이 병원은 응급실 병상 수와 소아 진료 정보를 '
      +'공개 데이터에 올리지 않습니다. 자리가 없다는 뜻이 아닙니다. 전화로 확인하세요.">'
      +'병상 · 소아 정보 미제공</span>');
  else if(noBed)
    c.push('<span class="chip none" title="이 병원은 응급실 병상 수를 공개 데이터에 '
      +'올리지 않습니다. 자리가 없다는 뜻이 아닙니다. 전화로 확인하세요.">'
      +'병상 정보 미제공</span>');
  else if(noPed) c.push('<span class="chip none">소아 정보 없음</span>');
  return c.join('');
}
function card(h,i){
  var map='https://map.kakao.com/link/to/'+encodeURIComponent(h.n)+','+h.y+','+h.x;
  var pct = h._r==null?null:Math.round(h._r*100);
  var on = (key(h)===selKey ? ' picked' : '') + (good(h) ? ' good' : '');
  return '<div class="card'+on+'" data-k="'+key(h).replace(/"/g,'')+'">'
    +'<div class="row1">'+(i<3?'<span class="num">'+(i+1)+'</span>':'')
    +'<span class="name">'+h.n+'</span><span class="dist">'+h._d.toFixed(1)+'km</span></div>'
    +'<p class="sub">'+h.g+' · '+h.a+' · 차로 약 '+Math.round(h._travel)+'분(추정)</p>'
    +'<div class="chips">'+(good(h)?'<span class="chip ok">여건이 두루 좋음</span>':'')+chips(h)+'</div>'
    +(pct!=null?'<div class="bar2">도착할 때도 지금처럼 자리가 있을 가능성 <b>'+pct+'%</b>'
       +'<div class="track"><div class="fill" style="width:'+pct+'%"></div></div></div>':'')
    +(h._ms.length?'<div class="notice'+(h._blk.length?'':' info')+'">'
       +'<span class="lab">'+(h._blk.length?ICON_ALERT+'이 병원이 올린 진료 제한 공지'
            :(group(h)===1?ICON_INFO+'전화로 먼저 확인해 달라는 공지':ICON_INFO+'이 병원이 올린 안내'))+'</span>'
       +h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')
       +(h._ms.length>2?'<p style="color:var(--muted)">외 '+(h._ms.length-2)+'건</p>':'')+'</div>':'')
    +'<p class="calc">'+h._calc+'</p>'
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
    /* 지도는 접지 않는다 — 이 화면에서 제일 먼저 봐야 할 것이라 늘 펼쳐 둔다 */
    +'<div class="plot">'
    +'<div class="mapwrap"><canvas id="web"></canvas>'
    +'<button class="gfilter" id="gfilter" type="button" aria-pressed="'+(onlyGood?'true':'false')+'">'
      +'<i></i>여건이 두루 좋은 곳만 '+(ALL||[]).filter(good).length+'곳</button>'
    +'<div class="zoom">'
      +'<button id="zin" type="button" aria-label="확대">+</button>'
      +'<button id="zout" type="button" aria-label="축소">−</button>'
      +'<button id="zfit" type="button" aria-label="내 위치로 맞추기">⌖</button>'
    +'</div></div>'
    +'<p class="maplabel">'+(usingDefault
        ? '<b>서울 중심을 기준으로 한 예시입니다.</b> 위 <b>[내 주변 응급실 보기]</b>를 누르면 '
          +'내 위치로 다시 그립니다. ' : '')
    +'<b>점을 누르면 그 병원 정보와 전화번호</b>가 나옵니다. 아래 카드를 눌러도 '
    +'지도에서 같이 표시되고, 길 안내는 [길찾기]를 누르세요. '
    +'지도 배경은 외부에서 받아오므로 <b>보고 있는 지역이 지도 제공자에게 전달됩니다</b> — '
    +'정확한 좌표나 고른 내용은 보내지 않습니다.</p>'
    +'<div id="mapsel"></div>'
    +'<div class="legend">'
    +'<span><i style="background:var(--accent)"></i>①②③ 아래 카드와 같은 순서</span>'
    +'<span><i style="background:#46d07f"></i>여건이 두루 좋은 곳</span>'
    +'<span><i style="background:#d9892b"></i>응급실이 붐볐던 곳(전체 기준)</span>'
    +'<span><i style="background:#e05c54"></i>진료 제한 공지</span>'
    +'<span><i style="background:var(--mapdim)"></i>그 밖의 응급실 · 점 크기는 소아 진료 여건</span>'
    +'</div></div>';
  drawWeb(rows);
  renderPick();   /* 다시 그릴 때마다 칸이 비므로 고른 병원을 복원한다
                     (창 크기·화면 회전·나이 변경 때마다 renderMap이 돈다) */
}
/* 지금 조건이 두루 좋은 곳 — 제한 공지 없고, 소아 여건이 있고, 자리가 있고,
   도착 때도 유지될 가능성이 괜찮은 곳. ⚠ "받아준다는 보장"이 아니다.
   실제 수용 여부는 공개 데이터로 알 수 없고 전화로만 확인된다 */
function good(h){
  if(group(h)!==0) return false;                 /* 제한·조건 공지가 있으면 제외 */
  if(!(h.pd>=2 || h.pc>0)) return false;         /* 소아 진료 여건 */
  if(h.oc!=null && h.oc>=50) return false;       /* 붐비면 제외 */
  if(h._r!=null && h._r<0.6) return false;       /* 도착 때 유지 가능성 */
  return true;
}
function group(h){                    /* 병원이 스스로 말한 것으로 묶는다 */
  if(!h._ms.length) return 0;         /* 공지 없음 */
  return Math.max.apply(null, h._ms.map(function(m){return m[5];}));
}
function places(){
  /* 위치가 없을 때가 이 화면의 첫 상태다 — 지금 누를 것 하나를 또렷하게 말한다.
     가리키는 대상은 바로 위 검색창이다(예전 문구는 히어로 버튼을 가리켰는데,
     검색이 지도 위로 올라오면서 더 가까운 곳에 할 일이 생겼다) */
  if(usingDefault) return '<div class="prompt"><span class="t">아직 내 위치를 모릅니다</span>'
    +'위 <b>검색창</b>에 주소나 동네 이름을 넣거나, 맨 위 <b>[내 주변 응급실 보기]</b>를 눌러 주세요. '
    +'위치는 이 화면 안에서만 쓰이고 저장되지 않습니다.</div>';
  var rows=candidates();
  if(!rows.length) return '<div class="prompt"><span class="t">가까운 곳을 찾지 못했습니다</span>'
    +'119에 물어보시는 편이 빠릅니다.</div>';
  var g=[[],[],[]];
  rows.forEach(function(h){ g[group(h)].push(h); });
  var out='', n=0;
  function block(list,title,desc,limit){
    if(!list.length) return '';
    return '<h3 class="gh">'+title+'<span>'+list.length+'곳</span></h3>'
      +(desc?'<p class="gd">'+desc+'</p>':'')
      +'<div class="cards">'+list.slice(0,limit).map(function(h){ return card(h,n++); }).join('')+'</div>';
  }
  out+=block(g[0],'바로 가 볼 만한 곳',
    '순서는 <b>“가는 데 드는 분”</b>으로 정합니다. 이동 시간에서 소아 진료 여건만큼 빼고 '
    +'붐빈 만큼 더한 값이고, 카드마다 그 계산을 적어 뒀습니다. '
    +'<b>초록색은 순위가 아니라 표시입니다</b> — 여건이 두루 좋아도 더 멀면 아래로 갑니다. '
    +'출발 전 전화로 확인하세요.',12);
  /* 전화에서 뭘 물을지는 [전화] 버튼을 처음 본 다음에 필요한 말이다.
     목록 맨 위에 두면 아직 걸 곳도 없는데 통화법부터 읽게 된다 */
  out+='<p class="ask">전화로는 이렇게만 물어보시면 됩니다 — '
    +'<b>“○개월 아기가 △△한데, 지금 소아 진료 되나요?”</b></p>';
  out+=block(g[1],'전화로 먼저 확인하라고 한 곳','병원이 "사전 문의"를 요청해 둔 곳입니다. 전화가 꼭 필요합니다.',6);
  out+=block(g[2],'지금 제한을 걸어 둔 곳','빼지 않고 보여 드립니다. 제한이 우리 아이에게 해당되는지는 내용을 읽고 판단하세요.',6);
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
    +'<div class="cards">'+ rows.map(function(r){
        var m=r.m, map='https://map.kakao.com/link/to/'+encodeURIComponent(m.n)+','+m.y+','+m.x;
        return '<div class="card moon"><div class="row1"><span class="name">'+m.n+'</span>'
          +'<span class="dist">'+r.d.toFixed(1)+'km</span></div>'
          +'<p class="sub" style="margin-left:0">'+(m.kind||'')+' · '+m.a+'</p>'
          +'<div class="acts">'+(m.t?'<a class="tel" href="tel:'+m.t+'">전화 '+m.t+'</a>':'')
          +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
      }).join('')+'</div>';
}
function show(){
  prepare();
  renderMap();
  var el=document.getElementById('result'); if(!el) return;
  el.innerHTML = places();
}
var q=document.getElementById('q'), sug=document.getElementById('sug');
function pickPlace(p){
  here=[p.y,p.x]; usingDefault=false; viewLocked=false; view=null;
  selKey = (p.kind==='er' && p.h) ? key(p.h) : null;   /* 병원을 고르면 그 점을 선택 */
  q.value=p.label; sug.hidden=true;
  var msg = p.kind==='area' ? p.label+' 한가운데를 기준으로 보여 드립니다.'
          : p.kind==='dong' ? p.sub+' '+p.label+' 근처를 기준으로 보여 드립니다.'
          : p.kind==='addr' ? '그 주소를 기준으로 보여 드립니다.'
          : p.label+' 위치를 기준으로 보여 드립니다.';
  document.getElementById('status').textContent=msg+' 실제 위치와 다를 수 있습니다.';
  show();
}
/* 주소 찾기 — 여기만 바깥에 물어본다.
   병원 주소 색인(place_search)으로는 "진주대로 501" 같은 번지를 풀 수 없다. 키가 필요
   없고 CORS가 열린 곳은 OSM Nominatim뿐이라 그걸 쓴다. 지도 타일에서 이미 대략적 위치가
   타일 서버로 나가므로 "아무것도 안 보낸다"는 이 화면에서 더 이상 성립하지 않고, 대신
   **입력한 글자가 나가는 건 사용자가 검색했을 때만**으로 묶는다(자동 조회 없음).
   정책(초당 1회)을 지키려고 500ms 쉬었다가 한 번, 같은 질의는 기억해 두고 다시 묻지 않는다 */
var GEO_CACHE={}, geoTimer=null, geoSeq=0;
function geocode(term, done){
  var k=term.trim();
  if(GEO_CACHE[k]) { done(GEO_CACHE[k]); return; }
  var url='https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5'
        + '&countrycodes=kr&accept-language=ko&q='+encodeURIComponent(k);
  fetch(url).then(function(r){ return r.ok?r.json():[]; }).then(function(js){
    var out=(js||[]).map(function(o){
      var nm=(o.display_name||'').split(',').map(function(s){return s.trim();});
      /* 표시 이름은 "큰 지역 … 작은 지역" 차례로 뒤집혀 온다 — 앞 두 토막만 쓴다 */
      return {label:nm.slice(0,2).join(' ')||k, sub:nm.slice(2,5).reverse().join(' ')||'주소',
              y:+o.lat, x:+o.lon, kind:'addr'};
    }).filter(function(p){ return isFinite(p.y)&&isFinite(p.x); });
    GEO_CACHE[k]=out; done(out);
  }).catch(function(){ GEO_CACHE[k]=[]; done([]); });
}
/* 번지·도로명이 섞인 입력인가 — 이때는 로컬에 몇 개 걸려도 주소 조회를 같이 띄운다 */
function looksLikeAddress(s){
  return /[0-9]/.test(s) || /(로|길)\s*$/.test(s.trim()) || /(로|길)\s*[0-9]/.test(s);
}
function drawSug(r){
  if(!r.length){ sug.innerHTML=''; sug.hidden=true; return; }   /* 옛 목록을 남기지 않는다 */
  sug.innerHTML=r.map(function(p,i){
    var tag = p.kind==='addr' ? '<span class="geo">주소</span> ' : '';
    return '<button type="button" data-i="'+i+'">'+tag+p.label+' <span>'+p.sub+'</span></button>';
  }).join('');
  sug._r=r; sug.hidden=false;
}
if(q){
  q.oninput=function(){
    var term=q.value, local=place_search(term), mine=++geoSeq;
    drawSug(local);
    if(geoTimer) clearTimeout(geoTimer);
    var wrap=q.parentNode;
    if(term.trim().length<2 || (local.length>=3 && !looksLikeAddress(term))){
      wrap.classList.remove('busy'); return;
    }
    wrap.classList.add('busy');
    geoTimer=setTimeout(function(){
      geocode(term, function(found){
        wrap.classList.remove('busy');
        if(mine!==geoSeq) return;                  /* 그새 더 친 글자가 있으면 버린다 */
        if(found.length) drawSug(local.slice(0,3).concat(found));
      });
    },500);
  };
  q.onkeydown=function(e){
    if(e.key==='Enter'){
      e.preventDefault();
      if(sug._r && sug._r.length && !sug.hidden){ pickPlace(sug._r[0]); return; }
      var r=place_search(q.value);
      if(r.length){ pickPlace(r[0]); return; }
      /* 로컬에 없으면 주소로 한 번 물어본다 — 엔터가 빈손으로 끝나지 않게 */
      q.parentNode.classList.add('busy');
      geocode(q.value, function(found){
        q.parentNode.classList.remove('busy');
        if(found.length) pickPlace(found[0]);
        else document.getElementById('status').textContent=
          '그 주소를 찾지 못했습니다. 동(洞)이나 병원 이름으로도 찾을 수 있습니다.';
      });
    }
    if(e.key==='Escape') sug.hidden=true;
  };
  sug.onclick=function(e){
    var b=e.target.closest('button'); if(!b) return;
    pickPlace(sug._r[+b.dataset.i]);
  };
  document.addEventListener('click',function(e){
    if(!sug.contains(e.target) && e.target!==q) sug.hidden=true;
  });
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
/* 내 위치와 고른 병원이 한 화면에 같이 들어오게 맞춘다.
   예전엔 카드를 눌러도 지도는 그대로여서, 멀리 있는 병원을 고르면 화면 밖에 있어
   아무 일도 안 일어난 것처럼 보였다(지도 아래 병원 정보 칸도 비었다 — 그 칸은
   화면에 그려진 점에서만 찾기 때문). 확대 단계를 한 칸씩 낮추며 둘 다 들어오는
   첫 단계를 고른다 — 로그로 바로 구하면 라벨이 가장자리에 물린다 */
function fitPair(a,b){
  var cv=document.getElementById('web'); if(!cv) return;
  var W=cv.clientWidth||520, H=Math.min(Math.round(W*0.78),620);
  var padX=Math.min(96,W*0.18), padY=Math.min(86,H*0.18);   /* 라벨·버튼이 가리는 만큼 */
  var z=ZMAX;
  for(; z>ZMIN; z--){
    if(Math.abs(projX(a[1],z)-projX(b[1],z))<=W-2*padX &&
       Math.abs(projY(a[0],z)-projY(b[0],z))<=H-2*padY) break;
  }
  view={z:z, lat:latAt((projY(a[0],z)+projY(b[0],z))/2,z), lon:(a[1]+b[1])/2};
  viewLocked=true;     /* 자동 맞춤이 다시 끼어들지 않게. [⌖]로 되돌린다 */
}
/* 카드 ↔ 지도 양방향 — 카드를 누르면 지도에서 그 점이 선택된다 */
document.addEventListener('click',function(e){
  var c=e.target.closest('.card[data-k]'); if(!c) return;
  if(e.target.closest('a')) return;                 /* 전화·길찾기는 그대로 */
  var off=(c.dataset.k===selKey);
  selKey = off ? null : c.dataset.k;
  if(!off && here){
    /* key(h)가 "이름@위도,경도"라 좌표를 되읽을 수 있다 */
    var ll=c.dataset.k.split('@')[1].split(',');
    if(ll.length===2) fitPair(here,[+ll[0],+ll[1]]);
  }
  if(lastRows) drawWeb(lastRows);
  renderPick(); show();
});
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
#: 상단바 마크는 Playground 팀 로고(육각 노드 3개를 잇는 "A"). 로고가 브랜드 그린을
#: 직접 들고 있어서 배경을 깔지 않는다 — `.bar .mark`의 초록 알약을 없앤 이유다.
#: 원본: Desktop/playground-logo.svg. 그라디언트 id는 문서에 한 번만 나오게 둔다.
LOGO = (
    '<svg width="25" height="23" viewBox="0 0 48 44" role="img" aria-label="Playground">'
    '<defs><linearGradient id="pg-logo-grad" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0%" stop-color="#a3e635"/><stop offset="55%" stop-color="#22c55e"/>'
    '<stop offset="100%" stop-color="#0e7a3c"/></linearGradient></defs>'
    '<g stroke="url(#pg-logo-grad)" stroke-linecap="round" stroke-linejoin="round" fill="none">'
    '<path d="M24 8 L8.5 34 M24 8 L39.5 34 M24 8 L24 25 M24 25 L8.5 34 M24 25 L39.5 34" '
    'stroke-width="3.2"/>'
    '<g fill="url(#pg-logo-grad)" stroke-width="3">'
    '<path d="M24 2.5 L28.8 5.25 L28.8 10.75 L24 13.5 L19.2 10.75 L19.2 5.25 Z"/>'
    '<path d="M8.5 28.5 L13.3 31.25 L13.3 36.75 L8.5 39.5 L3.7 36.75 L3.7 31.25 Z"/>'
    '<path d="M39.5 28.5 L44.3 31.25 L44.3 36.75 L39.5 39.5 L34.7 36.75 L34.7 31.25 Z"/>'
    "</g></g></svg>"
)
ICON_SEARCH = ('<svg class="ic" width="17" height="17" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
               'stroke-linejoin="round" aria-hidden="true">'
               '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.9-3.9"/></svg>')
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
DESC = ("지금 아이를 데려갈 수 있는 응급실을 공개 데이터로 찾아 드립니다. "
        "소아 진료 여건과 병원이 올린 공지, 응급실 혼잡도를 같이 봅니다.")


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
        '<p class="lead">지금 아이를 데려갈 수 있는 응급실을 공개 데이터로 찾아 드립니다. '
        "소아 진료 여건과 병원이 올린 공지까지 같이 봅니다.</p>"
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
    # 검색은 지도를 쓰는 자리 바로 위에 둔다 — 히어로에 있을 때는 지도를 보다가
    # 위치를 바꾸려면 화면을 거슬러 올라가야 했다. 초록 테두리로 "여기서 시작"을 알린다.
    A('<div class="find find-map">' + ICON_SEARCH + '<input id="q" type="search" autocomplete="off" '
      # 좁은 화면에서는 예시가 중간에 잘린다 — 한 줄에 들어오는 길이로 줄였다
      'placeholder="주소·지역·병원으로 찾기 (예: 진주대로 501)" '
      'aria-label="주소나 지역으로 찾기"><div id="sug" class="sug" hidden></div></div>')
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
        ("갈 수 있는 곳만 남깁니다",
         "공개된 소아 진료 여건(전문의 수·소아 응급 병상)과 병원이 올린 공지를 보고, "
         "그 아이를 볼 수 없다고 밝힌 곳은 따로 묶습니다. 빼지는 않습니다."),
        ("가는 데 드는 분을 계산합니다",
         "이동 시간에서 소아 진료 여건만큼 빼고, 응급실이 붐빈 만큼 더합니다. "
         "그래서 가까워도 여건이 얕으면 뒤로 갑니다."),
        ("초록색은 순위가 아니라 표시입니다",
         "제한 공지가 없고, 소아 여건이 있고, 자리가 있었고, 도착 때까지 유지될 가능성이 "
         "괜찮으면 초록으로 칠합니다. 순서는 어디까지나 분으로 정하므로, "
         "<b>초록인 곳이 흰 곳보다 아래에 올 수 있습니다.</b> 더 멀면 그렇게 됩니다."),
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
        "<li><strong>초록색은 “받아준다”는 뜻이 아닙니다.</strong> 제한 공지가 없고, "
        "소아 진료 여건이 있고, 마지막 집계에서 자리가 있었고, 도착 시점까지 유지될 "
        "가능성이 괜찮은 곳. <strong>네 조건이 모두 맞아야 붙습니다.</strong> "
        "실제 수용 여부는 공개 데이터로 알 수 없고 전화로만 확인됩니다.</li>"
    )
    A(
        f"<li><strong>“응급실 N% 참”은 소아 혼잡도가 아닙니다.</strong> 그 병원 응급실 전체의 "
        f"(정원 − 남은 자리) ÷ 정원이고 <strong>{esc(meta['asOf'])} 기준</strong>입니다. "
        "소아 자리만 따로 세는 숫자는 공개되지 않습니다.</li>"
    )
    A(
        f"<li><strong>“도착할 때도 자리가 있을 가능성”</strong>은 응급실 전체 병상을 대상으로 한 "
        f"생존 모델(infosurv)의 출력입니다. 지금 값이 도착 시점까지 유지될 확률이고 "
        f"<strong>{esc(meta['asOf'])} 기준</strong>입니다. 소아 전용 수치가 아닙니다."
        + (f" 모델 {esc(meta['modelTag'])}, 적용 {meta['relCount']}곳." if meta.get("modelTag") else "")
        + "</li>"
    )
    A(
        f"<li><strong>병상 수 옆의 시각은 병원마다 다릅니다.</strong> 우리가 받아온 시각이 아니라 "
        f"<strong>그 병원 숫자가 마지막으로 바뀐 때</strong>입니다. 환자가 오갈 때마다 바뀌는 "
        f"병원이 있고 하루 넘게 그대로인 병원이 있습니다. 오래 안 바뀐 값은 안정적이라는 뜻이 "
        f"아니라 <strong>자동 갱신이 끊겼을 수 있다</strong>는 뜻이라 따로 표시합니다.</li>"
    )
    A(
        f"<li><strong>응급실 병상 수를 아예 올리지 않는 기관이 "
        f"{meta.get('noBedCount', 0)}곳</strong>입니다(대부분 응급실운영신고기관). "
        f"<strong>자리가 없다는 뜻이 아닙니다.</strong> 모르는 것이라 “병상 정보 미제공”으로 "
        f"적고, 그걸 이유로 순위에서 밀어내지도 않습니다. 전화로 확인하세요.</li>"
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
