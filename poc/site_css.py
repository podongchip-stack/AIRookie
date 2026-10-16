"""보호자 사이트 스타일 — abto.app을 그대로 따라간다.

팔레트는 **앱토 스크린샷에서 직접 추출한 값**이다(눈으로 맞추지 않았다):
바탕 #ffffff · 프레임 바 #f4f4f5 · 액센트 #3860b3 · 글자 #18181b ·
테두리 #e4e4e7 · 강조 타일 #ebeff7.

구조도 그대로다 — 로고/가운데 링크/오른쪽 알약 네비, 가운데 정렬 큰 헤드라인,
알약 CTA 두 개(외곽선 왼쪽 · 채움 오른쪽), 그리고 **창 모양 프레임**(신호등 +
가운데 경로)에 담긴 대시보드: 선택 줄 → 지표 4칸(세로 머리카락선으로 나누고
하나는 강조) → 그림.

주소 줄에는 **우리 경로**를 적는다. 다른 앱의 스크린샷인 척하지 않으려는 것이고,
앱토도 제 주소(abto.app/compare)를 적는다.

바탕이 흰색인데도 앱토가 평평해 보이지 않는 이유는 거의 모든 요소가 테두리나
옅은 톤을 가진 면 위에 올라가 있기 때문이다 — 빈 흰 공간을 넓게 두지 않는다.
"""

CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{
  color-scheme:light;
  /* 앱토 실측 팔레트 (스크린샷에서 직접 추출) */
  --bg:#fff; --soft:#f4f4f5; --card:#fff; --hl:#ebeff7;
  --ink:#18181b; --ink2:#52525b; --muted:#71717a;
  --line:#e4e4e7; --line2:#f1f1f3;
  --accent:#3860b3; --accent-d:#2d4e95; --accentbg:#eef2fb;
  --urgent:#c42b1c; --urgent-fill:#c42b1c; --urgent-fill-h:#a82316;
  --urgentbg:#fdeeec; --urgentline:#f4d4cf;
  --warn:#8a5300; --warnbg:#fdf4e5; --warnline:#eedcb9;
  --ok:#0a7a3c; --okbg:#eaf6ee;
  --mapbg:#fff; --mapring:#e8eaee; --mapdim:#b6bdca; --maptext:#71717a;
  --ease:cubic-bezier(.16,1,.3,1);
  --col:1200px;
}
/* 다크는 OS가 아니라 사용자가 고른다 (네비 토글). 앱토와 같다 */
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0c0d10; --soft:#15171c; --card:#111317; --hl:#182338;
  --ink:#f4f4f5; --ink2:#b4b9c4; --muted:#80858f;
  --line:#242730; --line2:#1a1d23;
  --accent:#86aaf0; --accent-d:#a6c2f7; --accentbg:#16223a;
  --urgent:#ff8f85; --urgent-fill:#c4301f; --urgent-fill-h:#da3a27;
  --urgentbg:#331917; --urgentline:#552924;
  --warn:#efc271; --warnbg:#2d2111; --warnline:#4a3819;
  --ok:#6fd392; --okbg:#0f2617;
  --mapbg:#111317; --mapring:#242831; --mapdim:#3d4452; --maptext:#868c98;
}

html{caret-color:var(--accent);scrollbar-color:var(--line) transparent}
html,body{margin:0;background:var(--bg)}
body{font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
     -webkit-font-smoothing:antialiased;word-break:keep-all;overflow-wrap:anywhere}
::selection{background:var(--accentbg);color:var(--accent-d)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:99px;border:3px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:var(--mapdim)}
b,strong{font-weight:650}
.col{max-width:var(--col);margin:0 auto;padding:0 24px}

/* 상단바 — 로고 / 가운데 링크 / 오른쪽 알약 */
.bar{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line2)}
.bar .in{max-width:var(--col);margin:0 auto;padding:12px 24px;display:flex;align-items:center;gap:14px}
.bar .logo{display:flex;align-items:center;gap:9px;font-size:16.5px;font-weight:720;letter-spacing:-.03em}
.bar .mark{width:30px;height:30px;border-radius:9px;background:var(--accent);display:flex;
           align-items:center;justify-content:center;flex:none}
.bar nav{display:flex;gap:22px;margin-left:auto}
.bar .theme{width:34px;height:34px;border-radius:999px;border:1px solid var(--line);
            background:var(--card);color:var(--ink2);cursor:pointer;display:flex;
            align-items:center;justify-content:center;flex:none;
            transition:border-color .16s var(--ease),color .16s var(--ease)}
.bar .theme:hover{border-color:var(--mapdim);color:var(--ink)}
.bar nav a{font-size:14px;color:var(--ink2);text-decoration:none;white-space:nowrap}
.bar nav a:hover{color:var(--ink)}
.bar .cta{font-size:14px;font-weight:650;color:#fff;background:var(--urgent-fill);
          text-decoration:none;border-radius:999px;padding:10px 19px;white-space:nowrap;
          transition:background .18s var(--ease)}
.bar .cta:hover{background:var(--urgent-fill-h)}
@media (max-width:860px){.bar nav{display:none}.bar .theme{margin-left:auto}}

/* 히어로 — 가운데, 아주 크게 */
.hero{max-width:var(--col);margin:0 auto;padding:74px 24px 0;text-align:center}
.hero h1{font-size:clamp(33px,5.2vw,58px);line-height:1.22;letter-spacing:-.042em;font-weight:800;
         margin:0 0 20px;color:var(--ink);text-wrap:balance}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero .lead{font-size:16.5px;color:var(--ink2);margin:0 auto 30px;max-width:40em;line-height:1.6}
.ctas{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}
.btn{font:inherit;font-size:16px;font-weight:650;padding:15px 30px;border-radius:999px;cursor:pointer;
     text-decoration:none;display:inline-flex;align-items:center;justify-content:center;
     border:1px solid transparent;transition:background .18s var(--ease),border-color .18s var(--ease)}
.btn-ghost{background:var(--card);color:var(--ink);border-color:var(--line)}
.btn-ghost:hover{border-color:var(--mapdim)}
.btn-call{background:var(--urgent-fill);color:#fff;border-color:var(--urgent-fill)}
.btn-call:hover{background:var(--urgent-fill-h);border-color:var(--urgent-fill-h)}
.hero .fine{font-size:13px;color:var(--muted);margin:18px auto 0;max-width:40em;line-height:1.55}
#status{font-size:13.5px;color:var(--muted);margin:10px 0 0;min-height:19px;text-align:center}

/* 대시보드 프레임 — 창 모양. 주소 줄은 우리 경로를 적는다 */
.frame{max-width:var(--col);margin:34px auto 0;padding:0 24px}
.win{border:1px solid var(--line);border-radius:14px 14px 0 0;overflow:hidden;background:var(--card)}
.win .chrome{background:var(--soft);border-bottom:1px solid var(--line);display:flex;align-items:center;
             gap:7px;padding:13px 16px;position:relative}
.win .chrome i{width:11px;height:11px;border-radius:50%;display:block}
.win .chrome .path{position:absolute;left:0;right:0;text-align:center;font-size:13px;color:var(--muted);
                   pointer-events:none}
.win .body{padding:18px}
.win .topline{display:flex;align-items:center;gap:10px;margin:0 0 14px}
.win .crumb{font-size:13.5px;color:var(--muted)}
.win .crumb b{color:var(--ink);font-weight:620}
.win .stamp{margin-left:auto;font-size:12.5px;color:var(--muted);border:1px solid var(--line);
            border-radius:999px;padding:5px 11px;font-variant-numeric:tabular-nums}

/* 선택 — 앱토의 옵션 카드 줄 자리 */
.pickrow{border:1px solid var(--line);border-radius:11px;padding:13px 14px}
.lb{font-size:12.5px;color:var(--ink2);margin:0 0 9px;font-weight:600}
.lb span{font-weight:400;color:var(--muted)}
.safety{border:1px solid var(--line);border-radius:11px;margin:10px 0 0}
.safety>summary{font-size:14px;font-weight:620;color:var(--ink);padding:13px 14px;cursor:pointer;
                list-style:none;display:flex;align-items:center;gap:9px}
.safety>summary::-webkit-details-marker{display:none}
.safety>summary::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--urgent);flex:none}
.safety>summary::after{content:'';margin-left:auto;width:8px;height:8px;flex:none;
  border-right:1.6px solid var(--muted);border-bottom:1.6px solid var(--muted);
  transform:rotate(45deg) translate(-2px,-2px);transition:transform .2s var(--ease)}
.safety[open]>summary::after{transform:rotate(-135deg) translate(-3px,-3px)}
.safety .lb{padding:0 14px}
.safety .opts{padding:0 14px 14px}
.opts{display:flex;flex-wrap:wrap;gap:7px}
.opt{font:inherit;font-size:14px;padding:9px 13px;border-radius:999px;border:1px solid var(--line);
     background:var(--card);color:var(--ink);cursor:pointer;line-height:1.2;
     transition:border-color .16s var(--ease),background .16s var(--ease),color .16s var(--ease)}
.opt:hover{border-color:var(--mapdim)}
.opt[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:620}

/* 지표 줄 — 세로 머리카락선으로 나눈 4칸, 하나는 강조 */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);
       border-radius:11px;overflow:hidden;margin:14px 0 0}
.tiles>div{padding:13px 15px;border-left:1px solid var(--line)}
.tiles>div:first-child{border-left:0}
.tiles .k{font-size:12px;color:var(--muted)}
.tiles .v{font-size:25px;font-weight:720;letter-spacing:-.035em;margin:5px 0 0;
          font-variant-numeric:tabular-nums;line-height:1.1}
.tiles .t{font-size:11.5px;margin-top:6px;display:flex;align-items:center;gap:5px;color:var(--ink2)}
.tiles .t i{width:7px;height:7px;border-radius:50%;display:block;flex:none}
.tiles .on{background:var(--hl);box-shadow:inset 0 -2px 0 var(--accent)}
@media (max-width:720px){.tiles{grid-template-columns:repeat(2,1fr)}
  .tiles>div:nth-child(3){border-left:0}
  .tiles>div:nth-child(n+3){border-top:1px solid var(--line)}}

.plot{margin:16px 0 0;border-top:1px solid var(--line);padding-top:4px}
.plot>summary{font-size:13.5px;color:var(--ink2);padding:10px 2px;cursor:pointer;list-style:none;
              display:flex;align-items:center;gap:8px;font-weight:600}
.plot>summary::-webkit-details-marker{display:none}
.plot>summary::after{content:'';width:8px;height:8px;border-right:1.6px solid var(--muted);
  border-bottom:1.6px solid var(--muted);transform:rotate(45deg) translate(-2px,-2px);
  transition:transform .2s var(--ease)}
.plot[open]>summary::after{transform:rotate(-135deg) translate(-3px,-3px)}
.gh{font-size:15.5px;font-weight:700;letter-spacing:-.025em;margin:26px 0 4px;display:flex;
    align-items:baseline;gap:8px}
.gh:first-child{margin-top:4px}
.gh span{font-size:12.5px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums}
.gd{font-size:13px;color:var(--muted);margin:0 0 12px;line-height:1.55}
.plot canvas{display:block;width:100%;height:auto}
.maplabel{font-size:12.5px;color:var(--muted);margin:12px 2px 0;line-height:1.6}
.legend{display:flex;flex-wrap:wrap;gap:7px 16px;margin:10px 2px 0;font-size:11.5px;color:var(--muted)}
.legend i{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:-1px}

/* 결과 */
.results{max-width:var(--col);margin:0 auto;padding:0 24px}
.results .in{max-width:760px;margin:0 auto}
.verdict{border-radius:14px;padding:19px 20px;margin:26px 0 14px;border:1px solid}
.v1{background:var(--urgentbg);border-color:var(--urgentline)}
.v2{background:var(--warnbg);border-color:var(--warnline)}
.v3{background:var(--okbg);border-color:var(--line)}
.verdict .big{font-size:20px;font-weight:720;margin:0 0 8px;line-height:1.32;letter-spacing:-.025em}
.v1 .big{color:var(--urgent)} .v2 .big{color:var(--warn)} .v3 .big{color:var(--ok)}
.verdict p{margin:0;font-size:14.5px;color:var(--ink2);line-height:1.6}
.verdict .why{margin-top:10px;font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 17px;margin-bottom:10px;
      transition:border-color .18s var(--ease)}
.card:hover{border-color:var(--mapdim)}
/* 달빛은 응급실이 아니라는 걸 색으로도 구분한다 */
.card.moon{background:var(--soft)}
.card.moon .acts a.tel{background:var(--ink);border-color:var(--ink)}
.row1{display:flex;align-items:baseline;gap:10px}
.num{flex:none;width:22px;height:22px;border-radius:7px;background:var(--accent);color:#fff;font-size:12px;
     font-weight:700;display:flex;align-items:center;justify-content:center;font-variant-numeric:tabular-nums}
.name{font-size:17px;font-weight:680;letter-spacing:-.025em;line-height:1.33;flex:1}
.dist{font-size:13.5px;color:var(--accent);font-weight:680;white-space:nowrap;font-variant-numeric:tabular-nums}
.sub{font-size:12.5px;color:var(--muted);margin:5px 0 0 32px;font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:11px 0 0}
.chip{font-size:12px;padding:4px 10px;border-radius:999px;background:var(--accentbg);color:var(--accent);
      white-space:nowrap;font-variant-numeric:tabular-nums}
.chip.ok{background:var(--okbg);color:var(--ok)}
.chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.none{background:transparent;color:var(--muted);border:1px solid var(--line)}
.bar2{margin:13px 0 0;font-size:12.5px;color:var(--ink2);font-variant-numeric:tabular-nums}
.bar2 .track{height:6px;border-radius:99px;background:var(--line);overflow:hidden;margin-top:6px}
.bar2 .fill{height:100%;background:var(--accent);border-radius:99px}
.reason{font-size:13px;color:var(--muted);margin:11px 0 0;line-height:1.55}
.notice{border-radius:10px;padding:11px 13px;margin:11px 0 0;font-size:13.2px;line-height:1.55;
        background:var(--urgentbg);border:1px solid var(--urgentline);color:var(--ink)}
.notice .lab{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:650;
             color:var(--urgent);margin-bottom:5px}
.notice .lab svg{flex:none}
.notice p{margin:0 0 5px}.notice p:last-child{margin:0}
.notice.info{background:var(--accentbg);border-color:transparent}
.notice.info .lab{color:var(--accent)}
.acts{display:flex;gap:9px;margin-top:14px}
.acts a{flex:1;text-align:center;text-decoration:none;font-size:15px;font-weight:650;padding:12px;
        border-radius:999px;border:1px solid var(--line);color:var(--ink);
        transition:border-color .16s var(--ease),background .16s var(--ease)}
.acts a:hover{border-color:var(--mapdim)}
.acts a.tel{background:var(--accent);border-color:var(--accent);color:#fff}
.acts a.tel:hover{background:var(--accent-d);border-color:var(--accent-d)}
.ask{font-size:13.5px;color:var(--ink2);background:var(--soft);border-radius:12px;padding:14px 16px;
     margin:0 0 14px;line-height:1.65}
.ask b{color:var(--ink);font-weight:650}

/* 랜딩 */
.sec{max-width:var(--col);margin:0 auto;padding:72px 24px 0}
.sec .in{max-width:760px;margin:0 auto}
.sec .st{font-size:clamp(24px,3.4vw,34px);letter-spacing:-.038em;margin:0 0 12px;font-weight:780;
        text-align:center;text-wrap:balance}
.sec .desc{font-size:15.5px;color:var(--ink2);margin:0 auto 28px;line-height:1.65;max-width:38em;text-align:center}
.lede{font-size:16.5px;line-height:1.75;color:var(--ink2);margin:0}
.lede+.lede{margin-top:18px}
.lede .n{font-size:30px;font-weight:780;letter-spacing:-.04em;color:var(--accent);
         font-variant-numeric:tabular-nums;vertical-align:-2px;margin-right:2px}
.lede b{color:var(--ink)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media (max-width:760px){.steps{grid-template-columns:1fr}}
.step{border:1px solid var(--line);border-radius:12px;padding:16px 17px}
.step .k{width:25px;height:25px;border-radius:8px;background:var(--accentbg);color:var(--accent);
         font-size:12.5px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-bottom:11px}
.step b{display:block;font-size:14.5px;font-weight:660;margin-bottom:5px;letter-spacing:-.02em}
.step p{margin:0;font-size:13.5px;color:var(--ink2);line-height:1.6}
.faq details{border-bottom:1px solid var(--line)}
.faq details:first-child{border-top:1px solid var(--line)}
.faq summary{font-size:15.5px;font-weight:620;color:var(--ink);padding:17px 2px;list-style:none;
             cursor:pointer;display:flex;align-items:center;gap:10px;letter-spacing:-.02em}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:'';margin-left:auto;width:9px;height:9px;flex:none;
  border-right:1.6px solid var(--muted);border-bottom:1.6px solid var(--muted);
  transform:rotate(45deg) translate(-2px,-2px);transition:transform .2s var(--ease)}
.faq details[open] summary::after{transform:rotate(-135deg) translate(-3px,-3px)}
.faq p{margin:0 2px 18px;font-size:14.5px;color:var(--ink2);line-height:1.7}
.note{font-size:12.5px;color:var(--muted);line-height:1.7;margin-top:34px;background:var(--soft);
      border-radius:12px;padding:18px 20px}
.note strong{color:var(--ink2)} .note ul{padding-left:18px;margin:10px 0 0} .note li{margin:7px 0}
footer{margin-top:40px;border-top:1px solid var(--line);padding:26px 0 70px;font-size:12.5px;
       color:var(--muted);line-height:1.75}
footer b{color:var(--ink2)}

@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.reveal>*{animation:rise .45s var(--ease) both}
.reveal>*:nth-child(2){animation-delay:.05s}
.reveal>*:nth-child(3){animation-delay:.1s}
.reveal>*:nth-child(n+4){animation-delay:.15s}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
