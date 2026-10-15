"""보호자 사이트 스타일 — abto.app 디자인 언어를 따른다.

고정된 브리프: 흰 바탕 · 가운데 정렬 큰 헤드라인 · 알약 CTA 두 개 ·
**프레임에 담긴 대시보드**(앱토의 시그니처) · 큰 숫자 지표 타일 · 머리카락 테두리.

앱토의 가짜 브라우저 신호등(macOS 점 3개 + URL 바)은 **쓰지 않는다** — 우리 지도는
다른 앱의 스크린샷이 아니라 이 페이지에서 실제로 도는 것이라, 창틀을 씌우면
없는 사실을 암시하게 된다. 프레임 헤더는 실제 정보(곳 수·기준 시각)로 채운다.

손대기 전에 알아 둘 것
  · 색 테두리 왼쪽 굵은 띠(`border-left:3px`)를 경고 상자에 쓰지 않는다. 바탕 색조와
    1px 테두리, 그리고 그려진 아이콘으로 구분한다.
  · 이모지를 아이콘으로 쓰지 않는다. 아이콘은 같은 1.6 두께로 그린 SVG다.
  · 브라우저가 기본으로 주는 것(선택 영역·캐럿·포커스 링·스크롤바·숫자 정렬)도
    팔레트에서 가져온다.
  · 움직임은 한 번만 — 결과가 나타날 때 올라오며 떠오르는 것 하나. 나머지는 정적.
"""

CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{
  color-scheme:light;
  --bg:#fff; --soft:#f6f7f9; --card:#fff;
  --ink:#14171c; --ink2:#4b5563; --muted:#79839a;
  --line:#e7e9ee; --line2:#f0f2f6;
  --accent:#2a4bd0; --accent-d:#1d3ab0; --accentbg:#eef2fe;
  /* --urgent는 글자색, --urgent-fill은 채운 버튼 바탕. 다크에서 글자색을 그대로
     버튼 바탕에 쓰면 흰 글씨가 2.2:1까지 떨어진다 — 바탕은 두 모드 모두 진한 적색 */
  --urgent:#c42b1c; --urgent-fill:#c42b1c; --urgent-fill-h:#a82316;
  --urgentbg:#fdeeec; --urgentline:#f6d2cd;
  --warn:#8a5300; --warnbg:#fdf4e5; --warnline:#f0ddb8;
  --ok:#0a7a3c; --okbg:#eaf6ee;
  --mapbg:#fbfcfd; --mapring:#e6e9ef; --mapdim:#b9c3d4; --maptext:#6b7687;
  --sh-lift:0 2px 6px -2px rgba(20,23,28,.10);
  --ease:cubic-bezier(.16,1,.3,1);
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --bg:#0b0d11; --soft:#12151b; --card:#12151b;
  --ink:#f3f5f9; --ink2:#b7c0ce; --muted:#7f8a9d;
  --line:#222731; --line2:#1a1e26;
  --accent:#8ab4f8; --accent-d:#a9c7fb; --accentbg:#16233a;
  --urgent:#ff8f85; --urgent-fill:#c4301f; --urgent-fill-h:#da3a27;
  --urgentbg:#341917; --urgentline:#5a2b26;
  --warn:#efc271; --warnbg:#2e2211; --warnline:#4d3a1a;
  --ok:#6fd392; --okbg:#0f2718;
  --mapbg:#0e1116; --mapring:#222833; --mapdim:#3b4557; --maptext:#8a94a6;
  --sh-lift:0 2px 6px -2px rgba(0,0,0,.5);
}}

html{caret-color:var(--accent);scrollbar-color:var(--line) transparent}
html,body{margin:0;background:var(--bg)}
/* word-break:keep-all — 한글은 음절 단위로 끊으면 "고른 내용 / 과 위치는"처럼 읽힌다.
   어절 단위로 끊고, 긴 단어만 overflow-wrap으로 흘린다 */
body{font:400 16px/1.62 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
     -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
     word-break:keep-all;overflow-wrap:anywhere}
::selection{background:var(--accentbg);color:var(--accent-d)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:99px;border:3px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:var(--mapdim)}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 80px}
b,strong{font-weight:650}

/* 상단바 */
.bar{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%,transparent);
     backdrop-filter:saturate(1.6) blur(10px);border-bottom:1px solid var(--line2)}
.bar .in{max-width:760px;margin:0 auto;padding:11px 20px;display:flex;align-items:center;gap:10px}
.bar .logo{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:700;letter-spacing:-.025em}
.bar .logo svg{display:block}
.bar .sp{flex:1}
.bar .tel{font-size:13.5px;font-weight:650;color:#fff;background:var(--urgent-fill);text-decoration:none;
          border-radius:999px;padding:8px 15px;transition:background .18s var(--ease)}
.bar .tel:hover{background:var(--urgent-fill-h)}

/* 히어로 — 가운데 정렬, 큰 헤드라인 */
.hero{max-width:760px;margin:0 auto;padding:62px 20px 30px;text-align:center}
.hero h1{font-size:clamp(31px,7.4vw,48px);line-height:1.18;letter-spacing:-.038em;
         font-weight:800;margin:0 0 14px;text-wrap:balance}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero .lead{font-size:16.5px;color:var(--ink2);margin:0 auto 26px;line-height:1.6;max-width:30em;text-wrap:pretty}
.ctas{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.btn{font:inherit;font-size:16px;font-weight:650;padding:14px 26px;border-radius:999px;
     cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:8px;
     transition:transform .18s var(--ease),background .18s var(--ease),box-shadow .18s var(--ease)}
.btn:active{transform:translateY(1px)}
.btn-call{background:var(--urgent-fill);color:#fff;border:1.5px solid var(--urgent-fill)}
.btn-call:hover{background:var(--urgent-fill-h);border-color:var(--urgent-fill-h)}
.btn-ghost{background:var(--card);color:var(--ink);border:1.5px solid var(--line)}
.btn-ghost:hover{border-color:var(--mapdim)}
.hero .fine{font-size:13px;color:var(--muted);margin:16px auto 0;line-height:1.55;max-width:34em}
#status{font-size:13.5px;color:var(--muted);margin:12px 0 0;min-height:19px;text-align:center}

/* 프레임에 담긴 대시보드 — 앱토의 시그니처 자리 */
.frame{background:var(--soft);border:1px solid var(--line);border-radius:22px;padding:10px;
       margin:30px 0 0}
.frame .head{display:flex;align-items:center;gap:9px;padding:8px 12px 12px}
.frame .head b{font-size:14.5px;font-weight:680;letter-spacing:-.015em}
.frame .head span{font-size:12.5px;color:var(--muted);margin-left:auto;font-variant-numeric:tabular-nums}
.frame .inner{background:var(--mapbg);border:1px solid var(--line);border-radius:14px;padding:14px}
.frame canvas{display:block;width:100%;height:auto}
.maplabel{font-size:12.5px;color:var(--muted);margin:12px 2px 0;line-height:1.6}
.legend{display:flex;flex-wrap:wrap;gap:7px 15px;margin:10px 2px 0;font-size:11.5px;color:var(--muted)}
.legend i{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:-1px}

/* 지표 타일 — 앱토가 차트 위에 두는 줄 */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);
       border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:12px 0 0}
.tiles div{background:var(--card);padding:12px 13px}
.tiles .v{font-size:21px;font-weight:720;letter-spacing:-.03em;font-variant-numeric:tabular-nums;line-height:1.15}
.tiles .k{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.35}
.tiles .warn .v{color:var(--warn)} .tiles .bad .v{color:var(--urgent)} .tiles .good .v{color:var(--ok)}
@media (max-width:520px){.tiles{grid-template-columns:repeat(2,1fr)}}

h2{font-size:13.5px;margin:40px 0 11px;color:var(--muted);font-weight:650;letter-spacing:.012em}
.opts{display:flex;flex-wrap:wrap;gap:8px}
.opt{font:inherit;font-size:15px;padding:12px 16px;border-radius:999px;border:1.5px solid var(--line);
     background:var(--card);color:var(--ink);cursor:pointer;line-height:1.2;
     transition:border-color .16s var(--ease),background .16s var(--ease),color .16s var(--ease)}
.opt:hover{border-color:var(--mapdim)}
.opt[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:650}

/* 판정 */
.verdict{border-radius:16px;padding:19px 20px;margin:26px 0 14px;border:1px solid}
.v1{background:var(--urgentbg);border-color:var(--urgentline)}
.v2{background:var(--warnbg);border-color:var(--warnline)}
.v3{background:var(--okbg);border-color:var(--line)}
.verdict .big{font-size:20px;font-weight:720;margin:0 0 8px;line-height:1.32;letter-spacing:-.022em}
.v1 .big{color:var(--urgent)} .v2 .big{color:var(--warn)} .v3 .big{color:var(--ok)}
.verdict p{margin:0;font-size:14.5px;color:var(--ink2);line-height:1.6}
.verdict .why{margin-top:10px;font-size:13px;color:var(--muted)}
.verdict .btn{margin-top:15px;width:100%;justify-content:center}

/* 병원 카드 */
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 17px;margin-bottom:11px;
      transition:box-shadow .2s var(--ease),border-color .2s var(--ease)}
.card:hover{box-shadow:var(--sh-lift);border-color:var(--line)}
.row1{display:flex;align-items:baseline;gap:10px}
.num{flex:none;width:22px;height:22px;border-radius:8px;background:var(--accent);color:#fff;
     font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;
     font-variant-numeric:tabular-nums}
.name{font-size:17.5px;font-weight:680;letter-spacing:-.022em;line-height:1.33;flex:1}
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

/* 공지 — 왼쪽 색띠 대신 바탕 색조 + 1px 테두리 + 그려진 아이콘 */
.notice{border-radius:12px;padding:11px 13px;margin:11px 0 0;font-size:13.2px;line-height:1.55;
        background:var(--urgentbg);border:1px solid var(--urgentline);color:var(--ink)}
.notice .lab{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:650;
             color:var(--urgent);margin-bottom:5px}
.notice .lab svg{flex:none}
.notice p{margin:0 0 5px}.notice p:last-child{margin:0}
.notice.info{background:var(--accentbg);border-color:transparent}
.notice.info .lab{color:var(--accent)}

.acts{display:flex;gap:9px;margin-top:14px}
.acts a{flex:1;text-align:center;text-decoration:none;font-size:15px;font-weight:650;padding:12px;
        border-radius:999px;border:1.5px solid var(--line);color:var(--ink);
        transition:border-color .16s var(--ease),background .16s var(--ease)}
.acts a:hover{border-color:var(--mapdim)}
.acts a.tel{background:var(--accent);border-color:var(--accent);color:#fff}
.acts a.tel:hover{background:var(--accent-d);border-color:var(--accent-d)}
.ask{font-size:13.5px;color:var(--ink2);background:var(--soft);border-radius:14px;
     padding:14px 16px;margin:0 0 14px;line-height:1.65}
.ask b{color:var(--ink);font-weight:650}
.stale{font-size:12.5px;color:var(--muted);margin:14px 2px 0;line-height:1.55;font-variant-numeric:tabular-nums}

/* 랜딩 */
.sec{margin-top:66px}
.sec h3{font-size:clamp(22px,4.4vw,28px);letter-spacing:-.032em;margin:0 0 10px;font-weight:760;text-wrap:balance}
.sec .desc{font-size:15px;color:var(--ink2);margin:0 0 22px;line-height:1.65;max-width:34em;text-wrap:pretty}
.lede{font-size:16.5px;line-height:1.72;color:var(--ink2);margin:0}
.lede+.lede{margin-top:16px}
.lede .n{font-size:30px;font-weight:780;letter-spacing:-.035em;color:var(--accent);
         font-variant-numeric:tabular-nums;vertical-align:-2px;margin-right:2px}
.lede b{color:var(--ink)}
.steps{display:grid;gap:11px}
.step{display:flex;gap:13px;align-items:flex-start}
.step .k{flex:none;width:25px;height:25px;border-radius:9px;background:var(--accentbg);color:var(--accent);
         font-size:12.5px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:1px}
.step b{display:block;font-size:15px;font-weight:660;margin-bottom:4px;letter-spacing:-.015em}
.step p{margin:0;font-size:14px;color:var(--ink2);line-height:1.6}
.faq details{border-bottom:1px solid var(--line)}
.faq details:first-child{border-top:1px solid var(--line)}
.faq summary{font-size:15.5px;font-weight:620;color:var(--ink);padding:16px 2px;list-style:none;
             cursor:pointer;display:flex;align-items:center;gap:10px;letter-spacing:-.015em}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:'';margin-left:auto;width:9px;height:9px;flex:none;
  border-right:1.6px solid var(--muted);border-bottom:1.6px solid var(--muted);
  transform:rotate(45deg) translate(-2px,-2px);transition:transform .2s var(--ease)}
.faq details[open] summary::after{transform:rotate(-135deg) translate(-3px,-3px)}
.faq p{margin:0 2px 18px;font-size:14.5px;color:var(--ink2);line-height:1.7}
.note{font-size:12.5px;color:var(--muted);line-height:1.7;margin-top:34px}
.note strong{color:var(--ink2)} .note ul{padding-left:18px;margin:10px 0 0} .note li{margin:7px 0}
footer{margin-top:40px;border-top:1px solid var(--line);padding:24px 0 0;font-size:12.5px;
       color:var(--muted);line-height:1.75}
footer b{color:var(--ink2)}

/* 움직임 — 결과가 떠오르는 한 번만 */
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.reveal>*{animation:rise .5s var(--ease) both}
.reveal>*:nth-child(2){animation-delay:.05s}
.reveal>*:nth-child(3){animation-delay:.1s}
.reveal>*:nth-child(4){animation-delay:.15s}
.reveal>*:nth-child(n+5){animation-delay:.2s}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
