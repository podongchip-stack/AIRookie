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
  6. **아무것도 저장하지 않는다.** 지도도 타일을 받지 않아 위치가 외부로
     새지 않는다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다.

실행:
    conda activate dev
    cd poc
    python fetch_messages.py      # 병원 공지 (E-Gen 키 필요, 전국 1회)
    python build_peds_finder.py   # 신뢰도 엔진 적재에 20초쯤
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
SNAP_DIR = os.path.join(INFO, "data", "snapshots_nationwide")
HIRA_DIR = os.path.join(INFO, "data", "hira")
MSG_CACHE = os.path.join(HERE, "data", "acceptance_messages.json")
OUT = os.path.join(HERE, "out", "peds_finder.html")

sys.path.insert(0, INFO)
from hospital_score import vocabulary as V  # noqa: E402

KST = timezone(timedelta(hours=9))
PED_DEPT = "소아청소년과"
PED_WORDS = re.compile(r"소아|신생아|NICU|영유아|유아|아동|소청과|미숙아|분만|산모")
PED_SEVERE_CODES = {"Y0070", "Y0082", "Y0092", "Y0100", "Y0172"}
#: 공지가 "제한"인지 "안내"인지. E-Gen은 전부 '차단' 유형으로 내보내서
#: "소아청소년과 : 24시간 진료 가능" 같은 안내가 섞인다.
BLOCK_WORDS = re.compile(r"불가|제한|중단|부재|미운영|축소|휴진|어렵|없어|없음")


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
            1 if BLOCK_WORDS.search(text) else 0,
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

    try:
        spec = json.load(open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8"))
    except FileNotFoundError:
        spec = {}

    msgs = load_messages()
    rel, model_tag = load_reliability(as_of.astimezone(timezone.utc))
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
    meta = {
        "asOf": as_of.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "modelTag": model_tag,
        "relCount": len(rel),
        "msgCount": sum(1 for r in rows if r["ms"]),
    }
    return rows, meta


CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{
  color-scheme:light;
  --bg:#fff; --soft:#f7f8fa; --card:#fff; --ink:#0d1117; --ink2:#4a5260; --muted:#8a919e;
  --line:#e6e8ec; --accent:#1f5fd0; --accentbg:#eef3fd;
  --urgent:#c0392b; --urgentbg:#fdeeec;
  --warn:#8a5a00; --warnbg:#fdf4e3;
  --ok:#0b7a3b; --okbg:#eaf6ee;
  --mapbg:#fbfcfe; --mapring:#e3e7ee; --mapdim:#c3cedf; --maptext:#5b6779;
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --bg:#0d0f13; --soft:#14171d; --card:#14171d; --ink:#f2f4f8; --ink2:#b9c0cc; --muted:#848b98;
  --line:#242830; --accent:#7fb2f0; --accentbg:#15253c;
  --urgent:#ff8a80; --urgentbg:#361b19;
  --warn:#f0c070; --warnbg:#312310;
  --ok:#6fd392; --okbg:#102719;
  --mapbg:#0f131a; --mapring:#232935; --mapdim:#3a4454; --maptext:#8d97a8;
}}
html,body{margin:0;background:var(--bg)}
body{font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
     -webkit-font-smoothing:antialiased}
.wrap{max-width:600px;margin:0 auto;padding:0 18px 72px}

/* 상단바 */
.bar{border-bottom:1px solid var(--line);background:var(--bg);position:sticky;top:0;z-index:5}
.bar .in{max-width:600px;margin:0 auto;padding:12px 18px;display:flex;align-items:center;gap:10px}
.bar .mark{font-size:14.5px;font-weight:700;letter-spacing:-.02em;flex:1}
.bar .mark span{color:var(--accent)}
.bar a{font-size:13px;font-weight:650;color:var(--urgent);text-decoration:none;
       border:1px solid var(--urgent);border-radius:8px;padding:6px 11px}

/* 히어로 — 밝고 여백 넉넉하게 */
.hero{max-width:600px;margin:0 auto;padding:40px 18px 26px}
.hero h1{font-size:30px;line-height:1.28;margin:0 0 12px;letter-spacing:-.033em;font-weight:720}
.hero .lead{font-size:15.5px;color:var(--ink2);margin:0 0 22px;line-height:1.6;max-width:30em}
.ctas{display:flex;gap:9px;flex-wrap:wrap}
.call119{flex:1;min-width:190px;background:var(--urgent);color:#fff;text-align:center;font-size:17px;
  font-weight:700;padding:15px;border-radius:12px;text-decoration:none}
button.ghost{flex:1;min-width:190px;font:inherit;font-size:16px;font-weight:650;padding:15px;
  border-radius:12px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.sub119{font-size:12.5px;color:var(--muted);margin:12px 0 0;line-height:1.55}

h2{font-size:14px;margin:30px 0 10px;color:var(--muted);font-weight:650;letter-spacing:.01em}
.opts{display:flex;flex-wrap:wrap;gap:8px}
.opt{font:inherit;font-size:15px;padding:12px 15px;border-radius:11px;border:1.5px solid var(--line);
     background:var(--card);color:var(--ink);cursor:pointer;line-height:1.2}
.opt[aria-pressed=true]{background:var(--accentbg);border-color:var(--accent);color:var(--accent);font-weight:650}
#status{font-size:13px;color:var(--muted);margin:10px 2px 0;min-height:18px}

.verdict{border-radius:14px;padding:17px;margin:20px 0 14px;border:1.5px solid}
.v1{background:var(--urgentbg);border-color:var(--urgent)}
.v2{background:var(--warnbg);border-color:var(--warn)}
.v3{background:var(--okbg);border-color:var(--ok)}
.verdict .big{font-size:19px;font-weight:700;margin:0 0 7px;line-height:1.35}
.v1 .big{color:var(--urgent)} .v2 .big{color:var(--warn)} .v3 .big{color:var(--ok)}
.verdict p{margin:0;font-size:14.5px;color:var(--ink2);line-height:1.55}
.verdict .why{margin-top:9px;font-size:13px;color:var(--muted)}

/* 거미줄 지도 — abto의 대시보드 자리. 히어로 바로 아래가 주인공이다 */
.panel{background:var(--mapbg);border:1px solid var(--line);border-radius:18px;
       padding:16px 16px 13px;margin:22px 0 0}
.panel .head{display:flex;align-items:baseline;gap:9px;margin:0 0 12px}
.panel .head b{font-size:15px;font-weight:680;letter-spacing:-.015em}
.panel .head span{font-size:12px;color:var(--muted);margin-left:auto}
.panel canvas{display:block;width:100%;height:auto}
.maplabel{font-size:12px;color:var(--muted);margin:11px 2px 0;line-height:1.55}
.legend{display:flex;flex-wrap:wrap;gap:13px;margin:11px 2px 0;font-size:11.5px;color:var(--muted)}
.legend i{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:-1px}

.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin-bottom:10px}
.row1{display:flex;align-items:baseline;gap:9px}
.num{flex:none;width:21px;height:21px;border-radius:7px;background:var(--accent);color:#fff;
     font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}
.name{font-size:17px;font-weight:650;letter-spacing:-.01em;line-height:1.35;flex:1}
.dist{font-size:13.5px;color:var(--accent);font-weight:650;white-space:nowrap}
.sub{font-size:12.5px;color:var(--muted);margin:4px 0 0 30px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.chip{font-size:12px;padding:4px 9px;border-radius:999px;background:var(--accentbg);color:var(--accent);white-space:nowrap}
.chip.ok{background:var(--okbg);color:var(--ok)}
.chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.none{background:transparent;color:var(--muted);border:1px dashed var(--line)}
.bar{margin:11px 0 0;font-size:12.5px;color:var(--ink2)}
.bar .track{height:7px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:5px}
.bar .fill{height:100%;background:var(--accent);border-radius:4px}
.reason{font-size:13px;color:var(--ink2);margin:10px 0 0;padding-left:9px;border-left:2px solid var(--accentbg)}
.notice{background:var(--urgentbg);border-left:3px solid var(--urgent);border-radius:0 8px 8px 0;
        padding:9px 11px;margin:10px 0 0;font-size:13px;line-height:1.5;color:var(--ink)}
.notice b{color:var(--urgent);display:block;font-size:12px;margin-bottom:3px}
.notice p{margin:0 0 5px}.notice p:last-child{margin:0}
.notice.info{background:var(--accentbg);border-left-color:var(--accent)}
.notice.info b{color:var(--accent)}
.acts{display:flex;gap:8px;margin-top:12px}
.acts a{flex:1;text-align:center;text-decoration:none;font-size:15px;font-weight:600;
        padding:12px;border-radius:10px;border:1px solid var(--line);color:var(--ink)}
.acts a.tel{background:var(--accent);border-color:var(--accent);color:#fff}
.ask{font-size:13px;color:var(--ink2);background:var(--card);border:1px dashed var(--line);
     border-radius:12px;padding:13px 14px;margin:0 0 14px;line-height:1.6}
.ask b{color:var(--ink)}
.stale{font-size:12.5px;background:var(--warnbg);color:var(--warn);border-radius:10px;
       padding:10px 12px;margin:0 0 14px;line-height:1.5}
/* 랜딩 섹션 — 도구 아래. abto의 "문제 → 가치 → 과정 → FAQ" 순서 */
.sec{margin-top:52px}
.sec h3{font-size:21px;letter-spacing:-.025em;margin:0 0 8px;font-weight:700}
.sec .desc{font-size:14.5px;color:var(--ink2);margin:0 0 18px;line-height:1.6}
.facts{display:grid;gap:11px}
.fact{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:16px 17px}
.fact .big{font-size:27px;font-weight:720;letter-spacing:-.03em;color:var(--accent);line-height:1.1}
.fact .cap{font-size:13.5px;color:var(--ink2);margin-top:7px;line-height:1.55}
.steps{display:grid;gap:10px;counter-reset:s}
.step{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.step .k{flex:none;width:23px;height:23px;border-radius:8px;background:var(--accentbg);color:var(--accent);
         font-size:12.5px;font-weight:700;display:flex;align-items:center;justify-content:center}
.step b{display:block;font-size:14.5px;font-weight:650;margin-bottom:3px}
.step p{margin:0;font-size:13.5px;color:var(--ink2);line-height:1.55}
.faq{border-top:1px solid var(--line)}
.faq details{border-bottom:1px solid var(--line);padding:3px 0}
.faq summary{font-size:15px;font-weight:600;color:var(--ink);padding:14px 2px;list-style:none}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:'+';float:right;color:var(--muted);font-weight:400}
.faq details[open] summary::after{content:'−'}
.faq p{margin:0 2px 15px;font-size:14px;color:var(--ink2);line-height:1.65}
footer{margin-top:56px;border-top:1px solid var(--line);padding:22px 0 0;font-size:12.5px;color:var(--muted);line-height:1.7}
footer b{color:var(--ink2)}
.note{font-size:12.5px;color:var(--muted);line-height:1.65;margin-top:28px;border-top:1px solid var(--line);padding-top:16px}
.note strong{color:var(--ink2)} .note ul{padding-left:18px;margin:8px 0 0} .note li{margin:6px 0}
details summary{cursor:pointer;color:var(--ink2);font-size:13px;padding:5px 0}
"""

RULES_AGE = ["3개월 미만", "3~12개월", "1~3세", "3세 이상"]
RULES_SYM = [
    ("breath", "숨쉬기가 힘들어요"), ("seizure", "경련을 해요"),
    ("limp", "축 처지거나 반응이 없어요"), ("fever", "열이 나요"),
    ("head", "머리를 부딪혔어요"), ("hurt", "다쳤어요"),
    ("vomit", "토하거나 설사해요"), ("other", "그 밖에 걱정돼요"),
]

JS_TMPL = r"""
var DATA=__DATA__, ASOF="__ASOF__";
var age=null, sym={}, here=null;

/* ── 판단: 규칙만. 여러 개면 가장 높은 단계를 따른다 ───────────────── */
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
  if(age===0 && h.ni){ min-=2; why.push('신생아 중환자실이 있는 곳'); }
  if(h.oc!=null && h.oc>=80){ min+=5; why.push('집계 때 응급실이 거의 찼던 곳'); }
  else if(h.oc!=null && h.oc>=50){ min+=2; why.push('집계 때 응급실이 붐볐던 곳'); }
  /* 병원 공지는 순위를 건드리지 않는다 — 분과 단위 제한을 전면 차단으로 오인하면
     2km 병원이 5km 병원보다 뒤로 간다. 문장만 보여 주고 판단은 보호자가 한다 */
  h._ms=activeMsgs(h); h._blk=h._ms.filter(function(m){return m[5];});
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

/* ── 거미줄 지도: 각도는 실제 방위, 반경은 '줄 길이' ───────────────── */
function drawWeb(rows){
  var cv=document.getElementById('web'); if(!cv) return;
  var W=cv.clientWidth||520, H=Math.round(W*0.82), r=window.devicePixelRatio||1;
  cv.width=W*r; cv.height=H*r; cv.style.height=H+'px';
  var g=cv.getContext('2d'); g.setTransform(r,0,0,r,0,0); g.clearRect(0,0,W,H);
  var cx=W/2, cy=H/2+6, maxMin=Math.max(12, rows.length?rows[Math.min(rows.length,11)-1]._len:30);
  var R=Math.min(W,H)/2-26;
  /* 반경은 제곱근으로 편다 — 선형이면 가까운 상위 후보들이 가운데 뭉쳐 겹친다 */
  function pos(h){
    var ang=Math.atan2(h.x-here[1], h.y-here[0]);          /* 실제 방위 유지 */
    var rad=Math.sqrt(Math.min(1,h._len/maxMin))*R;
    return [cx+Math.sin(ang)*rad, cy-Math.cos(ang)*rad];
  }
  var C=function(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();};
  var ring=C('--mapring'), dim=C('--mapdim'), tx=C('--maptext'), acc=C('--accent'), ink=C('--ink');
  var BLK='#e05c54', BUSY='#d9892b';

  g.strokeStyle=ring; g.lineWidth=1;
  [1/3,2/3,1].forEach(function(f){                 /* 반경이 √이므로 눈금값은 f² */
    g.beginPath(); g.arc(cx,cy,R*f,0,Math.PI*2); g.stroke();
    g.fillStyle=tx; g.font='10px system-ui';
    g.fillText(Math.round(maxMin*f*f)+'분', cx+5, cy-R*f+13);
  });
  var top=rows.slice(0,3);
  top.forEach(function(h,i){                                  /* 줄 */
    var p=pos(h), grd=g.createLinearGradient(cx,cy,p[0],p[1]);
    grd.addColorStop(0,acc); grd.addColorStop(1,dim);
    g.strokeStyle=grd; g.lineWidth=3.5-i*0.9; g.lineCap='round';
    g.beginPath(); g.moveTo(cx,cy); g.lineTo(p[0],p[1]); g.stroke();
  });
  rows.slice(0,40).forEach(function(h){
    var p=pos(h), isTop=top.indexOf(h)>=0;
    var size=3+Math.min(4.5,h.pd/3)+(h.pc>0?1.8:0);
    g.fillStyle = h._blk.length ? BLK : (h.oc!=null&&h.oc>=50 ? BUSY : (isTop?acc:dim));
    g.beginPath(); g.arc(p[0],p[1],isTop?0.1:size,0,Math.PI*2); g.fill();
  });
  /* 상위 3곳은 이름 대신 번호 배지 — 가운데 몰리면 이름표가 서로 겹친다.
     아래 카드가 같은 번호를 달고 있어 이름은 거기서 읽으면 된다 */
  top.forEach(function(h,i){
    var p=pos(h), st=h._blk.length?BLK:(h.oc!=null&&h.oc>=50?BUSY:null);
    g.fillStyle=acc; g.beginPath(); g.arc(p[0],p[1],11,0,Math.PI*2); g.fill();
    g.strokeStyle=C('--mapbg'); g.lineWidth=2.5; g.stroke();
    if(st){ g.strokeStyle=st; g.lineWidth=2.5;      /* 배지는 순서, 테두리는 상태 */
            g.beginPath(); g.arc(p[0],p[1],14,0,Math.PI*2); g.stroke(); }
    g.fillStyle='#fff'; g.font='700 12px system-ui'; g.textAlign='center'; g.textBaseline='middle';
    g.fillText(String(i+1), p[0], p[1]+0.5);
    g.textAlign='left'; g.textBaseline='alphabetic';
  });
  g.fillStyle=ink; g.beginPath(); g.arc(cx,cy,5,0,Math.PI*2); g.fill();
  g.strokeStyle=dim; g.lineWidth=1.5;
  g.beginPath(); g.arc(cx,cy,10.5,0,Math.PI*2); g.stroke();
  g.fillStyle=tx; g.font='10px system-ui'; g.fillText('내 위치', cx+15, cy+4);
}

function chips(h){
  var c=[];
  if(h.pd>0) c.push('<span class="chip'+(h.pd>=2?' ok':'')+'">소아과 전문의 '+h.pd+'명</span>');
  if(h.pc>0) c.push('<span class="chip ok">소아 응급 병상 '+h.pc+'석</span>');
  if(h.ni)   c.push('<span class="chip">신생아 중환자실</span>');
  if(h.oc!=null) c.push(h.oc>=50?'<span class="chip warn">집계 때 응급실 '+h.oc+'% 참</span>'
                                :'<span class="chip">집계 때 응급실 여유</span>');
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
    +(pct!=null?'<div class="bar">도착할 때도 지금처럼 자리가 있을 가능성 <b>'+pct+'%</b>'
       +'<div class="track"><div class="fill" style="width:'+pct+'%"></div></div></div>':'')
    +(h._ms.length?'<div class="notice'+(h._blk.length?'':' info')+'"><b>'
       +(h._blk.length?'이 병원이 올린 진료 제한 공지':'이 병원이 올린 안내')+'</b>'
       +h._ms.slice(0,2).map(function(m){return '<p>'+m[2]+'</p>';}).join('')
       +(h._ms.length>2?'<p style="color:var(--muted)">외 '+(h._ms.length-2)+'건</p>':'')+'</div>':'')
    +(h._why.length?'<p class="reason">'+h._why.join(' · ')+'</p>':'')
    +'<div class="acts">'+(h.t?'<a class="tel" href="tel:'+h.t+'">전화 '+h.t+'</a>':'')
    +'<a href="'+map+'" target="_blank" rel="noopener">길찾기</a></div></div>';
}
/* 지도는 선택과 무관하게 위치만 있으면 바로 그린다 — 히어로 바로 아래가 주인공 자리다 */
function renderMap(){
  var box=document.getElementById('mapPanel'); if(!box) return;
  if(!here){ box.style.display='none'; return; }
  var rows=candidates();
  box.style.display='';
  box.innerHTML='<div class="head"><b>내 주변 응급실</b><span>'+rows.length+'곳 · '+ASOF+' 기준</span></div>'
    +'<canvas id="web"></canvas>'
    +'<p class="maplabel">가운데가 내 위치입니다. 방향은 실제 방위이고, <b>거리는 km가 아니라 '
    +'“가는 데 드는 분”</b>입니다 — 가까워도 소아 진료 여건이 얕거나 붐비면 더 멀리 그려집니다.</p>'
    +'<div class="legend">'
    +'<span><i style="background:var(--accent)"></i>①②③ 아래 카드와 같은 순서</span>'
    +'<span><i style="background:#d9892b"></i>집계 때 붐빔</span>'
    +'<span><i style="background:#e05c54"></i>진료 제한 공지</span>'
    +'<span><i style="background:var(--mapdim)"></i>그 밖의 응급실 · 점 크기는 소아 진료 여건</span>'
    +'</div>';
  drawWeb(rows);
}
function places(){
  var rows=candidates();
  if(!here) return '<p class="sub" style="margin-left:0">위 버튼으로 위치를 허용하시면 가까운 곳을 찾아 드립니다.</p>';
  if(!rows.length) return '<p class="sub" style="margin-left:0">가까운 곳을 찾지 못했습니다. 119에 물어보세요.</p>';
  return rows.slice(0,3).map(card).join('');
}
function show(){
  renderMap();
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
     +'당직 의사가 누구인지는 공개된 정보에 없습니다.</p><p class="why">'+j.why[0]+'</p></div>'
     +'<div class="ask">전화로 이렇게만 물어보시면 됩니다<br>'
     +'<b>“○개월 아기가 △△한데, 지금 소아 진료 되나요?”</b></div>'+places();
  }else{
    h='<div class="verdict v3"><p class="big">내일 외래로도 괜찮아 보입니다</p>'
     +'<p>다만 아래 중 하나라도 생기면 바로 119입니다 — 숨쉬기 힘들어함, 축 처짐, 경련, 입술이 파래짐.</p>'
     +'<p class="why">'+j.why[0]+'</p></div>'
     +'<details><summary>그래도 지금 갈 수 있는 곳을 보고 싶어요</summary>'+places()+'</details>';
  }
  el.innerHTML=h;
}
document.querySelectorAll('[data-age]').forEach(function(b){ b.onclick=function(){
  age=+b.dataset.age;
  document.querySelectorAll('[data-age]').forEach(function(x){x.setAttribute('aria-pressed',x===b);});
  show(); };});
document.querySelectorAll('[data-sym]').forEach(function(b){ b.onclick=function(){
  sym[b.dataset.sym]=!sym[b.dataset.sym]; b.setAttribute('aria-pressed',!!sym[b.dataset.sym]); show(); };});
document.getElementById('loc').onclick=function(){
  var st=document.getElementById('status');
  if(!navigator.geolocation){ st.textContent='이 브라우저에서는 위치를 쓸 수 없습니다.'; return; }
  st.textContent='위치 확인 중…';
  navigator.geolocation.getCurrentPosition(function(p){
    here=[p.coords.latitude,p.coords.longitude];
    st.textContent='가까운 곳을 찾았습니다.'; show();
  },function(){ st.textContent='위치를 가져오지 못했습니다. 119에 물어보시는 편이 빠릅니다.'; },
  {timeout:8000,maximumAge:60000});
};
addEventListener('resize',function(){ if(here) show(); });

/* 배포본은 data.json을 따로 올려 주기적으로 갱신한다. 그게 있으면 그걸 쓰고,
   없으면(로컬 파일로 열었을 때 등) HTML에 박아 둔 값으로 그대로 돈다 — 그래서
   서버 없이도 열리고, 올려 두면 최신으로 뜬다 */
fetch('data.json',{cache:'no-store'}).then(function(r){ return r.ok?r.json():null; })
 .then(function(j){
   if(!j||!j.rows||!j.rows.length) return;
   DATA=j.rows; ASOF=j.asOf||ASOF;
   document.querySelectorAll('[data-asof]').forEach(function(e){ e.textContent=ASOF; });
   if(here) show();
 }).catch(function(){});
"""


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
    A('<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme:light)">')
    A('<meta name="theme-color" content="#0d0f13" media="(prefers-color-scheme:dark)">')
    A('<meta name="robots" content="index,follow">')
    A(f"<style>{CSS}</style></head><body>")

    A('<nav class="bar"><div class="in"><div class="mark">우리 아이 <span>응급 길잡이</span></div>')
    A('<a href="tel:119">119</a></div></nav>')

    A('<header class="hero">')
    A("<h1>아이가 아픈데,<br>어디로 가야 할까요</h1>")
    A(
        '<p class="lead">두 가지만 고르면 지금 무엇을 해야 할지 알려 드립니다. '
        "고른 내용과 위치는 이 화면 밖으로 나가지 않습니다.</p>"
    )
    A('<div class="ctas"><a class="call119" href="tel:119">119 전화하기</a>')
    A('<button class="ghost" id="loc">내 주변 응급실 보기</button></div>')
    A('<p class="sub119">숨을 못 쉬거나 · 반응이 없거나 · 경련이 멈추지 않으면 고르지 말고 지금 119입니다</p>')
    A('<p id="status"></p>')
    A("</header>")

    A('<div class="wrap">')
    A('<div class="panel" id="mapPanel" style="display:none"></div>')
    A(
        f'<p class="stale" style="margin-top:22px">이 화면은 <b>{esc(meta["asOf"])}</b>에 받은 공개 '
        "데이터로 만든 시연본입니다. 실제 서비스는 5분마다 다시 받습니다 — 지금과 다를 수 있습니다.</p>"
    )

    A('<h2>아이 나이</h2><div class="opts">')
    for i, label in enumerate(RULES_AGE):
        A(f'<button class="opt" data-age="{i}" aria-pressed="false">{esc(label)}</button>')
    A("</div>")

    A('<h2>무슨 일인가요 · 여러 개 고르셔도 됩니다</h2><div class="opts">')
    for key, label in RULES_SYM:
        A(f'<button class="opt" data-sym="{key}" aria-pressed="false">{esc(label)}</button>')
    A("</div>")

    A('<div id="result"></div>')

    # ── 랜딩: 왜 필요한가 (전부 우리가 직접 잰 공개 데이터 수치) ──
    A('<section class="sec"><h3>왜 이런 걸 만들었나</h3>')
    A(
        '<p class="desc">아이가 아플 때 보호자가 가장 먼저 부딪히는 건 "어디로 가야 하나"입니다. '
        "그런데 공개된 정보만으로는 답하기 어렵게 돼 있습니다. 직접 세어 봤습니다.</p>"
    )
    A('<div class="facts">')
    for big, cap in [
        (f"{tier2}곳",
         "전국 응급의료기관 가운데 <b>소아 응급 병상과 소아청소년과 전문의 2명</b>을 함께 갖춘 곳. "
         "서울 22 · 경기 16인 반면 울산 1 · 충북 1 · 세종 0입니다."),
        ("23%",
         "소아 병상 수가 실제로 올라오는 응급실 비율(416곳 중 95곳). 그마저 거의 갱신되지 않아 "
         "<b>“지금 몇 자리”는 누구도 알 수 없습니다.</b>"),
        ("75곳",
         "“지금 이런 환자는 못 받는다”를 직접 공지해 둔 병원. "
         "<b>3개월 이하 발열 진료불가</b> 같은 내용이 공개돼 있는데도 보호자에게는 보이지 않습니다."),
    ]:
        A(f'<div class="fact"><div class="big">{big}</div><p class="cap">{cap}</p></div>')
    A("</div></section>")

    # ── 랜딩: 어떻게 고르나 ──
    A('<section class="sec"><h3>어떻게 고르나요</h3>')
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
    A("</div></section>")

    # ── FAQ ──
    A('<section class="sec"><h3>자주 묻는 것</h3><div class="faq">')
    for q, a in [
        ("지금 자리가 있는지 알 수 있나요?",
         "응급실 전체 혼잡도는 보여 드리지만 <b>소아 병상은 알 수 없습니다.</b> "
         "전국 응급실의 23%만 소아 병상 수를 올리고 그마저 거의 갱신되지 않습니다. "
         "모르는 것을 아는 척하지 않으려고 숫자를 지어내지 않았습니다."),
        ("전화를 꼭 해야 하나요?",
         "네. <b>오늘 밤 소아과 당직이 누구인지는 공개된 데이터 어디에도 없습니다.</b> "
         "이 화면은 갈 필요가 없는 곳을 줄여서 전화 횟수를 줄이는 것까지만 합니다."),
        ("제 위치나 증상이 저장되나요?",
         "아니요. 로그인·쿠키·접속 기록이 없고 외부로 아무것도 보내지 않습니다. "
         "지도도 외부에서 타일을 받지 않아 <b>위치가 서버로 나가지 않습니다.</b>"),
        ("병원을 추천해 주는 건가요?",
         "아닙니다. 거리와 소아 진료 여건으로 정한 <b>순서</b>일 뿐이고 어디가 더 낫다는 추천이 아닙니다. "
         "판단 기준도 의사가 검토하기 전의 초안입니다. 헷갈리시면 119에 전화해 물어보셔도 됩니다 — "
         "119는 상담도 합니다."),
    ]:
        A(f"<details><summary>{q}</summary><p>{a}</p></details>")
    A("</div></section>")

    A('<div class="note"><p><strong>이 화면이 할 수 있는 일과 못 하는 일</strong></p><ul>')
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
    A("<li>출처: 중앙응급의료센터 E-Gen 공개 API, 건강보험심사평가원 공개 API.</li>")
    A(
        "<li>아무것도 저장하지 않습니다 — 로그인·쿠키·접속 기록이 없고, 지도도 외부에서 "
        "타일을 받지 않아 <strong>위치가 서버로 나가지 않습니다.</strong></li>"
    )
    A("</ul></div>")
    A(
        "<footer><b>우리 아이 응급 길잡이</b> — 중앙응급의료센터 E-Gen·건강보험심사평가원 "
        f"공개 API로 만든 비영리 시연 서비스입니다. 데이터 기준 {esc(meta['asOf'])}.<br>"
        "응급 상황에서는 <b>먼저 119</b>에 전화하세요. 이 화면은 의료 조언이 아닙니다."
        "</footer>"
    )
    A("</div>")

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    A("<script>" + JS_TMPL.replace("__DATA__", data).replace("__ASOF__", meta["asOf"]) + "</script>")
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
        json.dump({"asOf": meta["asOf"], "rows": rows}, fp, ensure_ascii=False, separators=(",", ":"))
    print(f"생성: {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    print(f"      {data_path}  ({os.path.getsize(data_path)/1024:.0f} KB)")
    print(f"  전국 {len(rows)}곳 · 기준 {meta['asOf']}")
    print(f"  병원 공지 {meta['msgCount']}곳 · 신뢰도 {meta['relCount']}곳 ({meta['modelTag'] or '없음'})")


if __name__ == "__main__":
    main()
