"""리포트 공통 조각 — `poc/` 안의 생성기들이 같은 모양을 쓰도록 모아 둔 것.

CSS·툴팁 JS·좌표 거리 계산만 들어 있다. 데이터 해석은 각 생성기가 직접 한다.
"""

from __future__ import annotations

import html
import math


CSS = """
*{box-sizing:border-box}
.viz-root{
  color-scheme:light;
  --page:#f9f9f7; --surface:#fcfcfb;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --series:#2a78d6; --good:#0ca30c; --critical:#d03b3b; --warning:#fab219;
  --g-0:#104281; --g-1:#256abf; --g-2:#3987e5; --g-3:#86b6ef;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme=light])) .viz-root{
    color-scheme:dark;
    --page:#0d0d0d; --surface:#1a1a19;
    --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --series:#3987e5;
    --g-0:#cde2fb; --g-1:#86b6ef; --g-2:#3987e5; --g-3:#184f95;
  }
}
:root[data-theme=dark] .viz-root{
  color-scheme:dark;
  --page:#0d0d0d; --surface:#1a1a19;
  --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --series:#3987e5;
  --g-0:#cde2fb; --g-1:#86b6ef; --g-2:#3987e5; --g-3:#184f95;
}
/* --page는 .viz-root 스코프라 body에서는 안 보인다. 콘텐츠 아래 여백이 검게 남아서 따로 깐다 */
html,body{margin:0;background:#f9f9f7}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) html,
  :root:where(:not([data-theme=light])) body{background:#0d0d0d}}
:root[data-theme=dark] body{background:#0d0d0d}
.viz-root{
  font:400 15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;
  color:var(--ink);background:var(--page);
  max-width:1120px;margin:0 auto;padding:40px 24px 80px;
}
h1{font-size:28px;line-height:1.3;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:20px;margin:52px 0 6px;letter-spacing:-.01em}
h2 .n{color:var(--muted);font-weight:400;margin-right:8px}
h3{font-size:15px;margin:28px 0 8px;color:var(--ink2)}
p{margin:10px 0;color:var(--ink2);max-width:74ch}
.sub{color:var(--muted);font-size:13px;margin:0}
.lede{font-size:17px;color:var(--ink);max-width:68ch}
strong{color:var(--ink);font-weight:600}
.banner{
  border:1px solid var(--border);border-left:3px solid var(--warning);
  background:var(--surface);border-radius:6px;padding:12px 16px;margin:20px 0;
  font-size:13px;color:var(--ink2)
}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px 22px;margin:18px 0}
.find{border-left:3px solid var(--series)}
.find p{margin:0;color:var(--ink);font-size:16px}
.grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}
.sm{display:grid;grid-template-columns:repeat(auto-fill,minmax(282px,1fr));gap:14px}
.sm .panel{border:1px solid var(--border);border-radius:8px;padding:10px 12px 4px;background:var(--surface)}
.sm .panel h4{margin:0 0 2px;font-size:13.5px;font-weight:600}
.sm .panel .meta{margin:0 0 4px;font-size:11.5px;color:var(--muted)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
svg{display:block;max-width:100%;height:auto}
text.ax{font-size:10px;fill:var(--muted)}
text.lb{font-size:11.5px;fill:var(--ink2)}
text.mk{font-size:13px;fill:#fff;font-weight:600}
.dot,.cell{cursor:default}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
caption{text-align:left;color:var(--muted);font-size:12px;padding-bottom:8px}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--grid)}
th:first-child,td:first-child{text-align:left;font-variant-numeric:normal}
thead th{color:var(--muted);font-weight:500;font-size:12px;white-space:nowrap}
tbody tr:hover{background:color-mix(in srgb,var(--series) 6%,transparent)}
td.no{color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:12px 0 4px;font-size:12.5px;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;border:2px solid var(--surface);box-shadow:0 0 0 1px var(--border)}
.sw.hollow{background:transparent;border:1px dashed var(--axis);box-shadow:none}
#tip{
  position:fixed;z-index:30;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--ink);color:var(--page);font-size:12.5px;padding:6px 10px;
  border-radius:6px;max-width:300px;line-height:1.45
}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--grid);font-size:12.5px;color:var(--muted)}
footer li{margin:4px 0}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
@media print{.viz-root{max-width:none}h2{page-break-after:avoid}}
"""

JS = """
(function(){
  var tip=document.getElementById('tip');
  document.addEventListener('pointerover',function(e){
    var t=e.target.closest('[data-tip]'); if(!t)return;
    tip.textContent=t.getAttribute('data-tip'); tip.style.opacity='1';
  });
  document.addEventListener('pointermove',function(e){
    if(tip.style.opacity!=='1')return;
    var w=tip.offsetWidth,h=tip.offsetHeight;
    var x=e.clientX+14, y=e.clientY-h-10;
    if(x+w>innerWidth-8)x=e.clientX-w-14;
    if(y<8)y=e.clientY+16;
    tip.style.left=x+'px'; tip.style.top=y+'px';
  });
  document.addEventListener('pointerout',function(e){
    if(e.target.closest('[data-tip]')) tip.style.opacity='0';
  });
})();
"""


def esc(s) -> str:
    return html.escape(str(s))


def hav(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 좌표 사이 직선거리(km)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def page(title: str, body: str) -> str:
    """<title> + CSS + 본문 + 툴팁 JS를 한 장으로 감싼다."""
    return "\n".join(
        [
            f"<title>{html.escape(title)}</title>",
            f"<style>{CSS}</style>",
            '<div class="viz-root"><div id="tip"></div>',
            body,
            "</div>",
            f"<script>{JS}</script>",
        ]
    )
