"""서울 병원 역량 공간 — 도로 그래프 위 불빛 버전 (deck.gl + MapLibre, 로컬 파일로 연다).

seoul_roads.json(OSM 서울 도로 그래프)을 그대로 심어, 브라우저 안에서 최단경로(다익스트라)를 직접 돈다.
외부 경로 서버·외부 라이브러리 없음. 도로 그래프는 경로 계산에만 쓰고 화면엔 그리지 않는다.
"""
import json, pathlib, sys
here = pathlib.Path(__file__).parent
rows = json.load(open(here / 'hospitals_xyz.json', encoding='utf-8'))  # 전국 (build_xyz.py)
data = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else here / 'map.html'

html = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>병원 역량 공간 — 전국</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:dark;
  --bg:#0a1024; --panel:rgba(12,16,34,.86); --ink:#f2f1ec; --ink-2:#b9b8ae; --muted:#7c7b74; --line:#2b2d45;
  --g1:#7fb6ff; --g2:#4f9cff; --g3:#2a7ff0; --g4:#9ad0ff;
  --k1:#ff5c5c; --k2:#ff7a45; --k3:#ffb039; --k4:#ffd96b; --k5:#d8d08a;
  --yield:#7c7b74; --clash:#ff3b3b; --occ:#4fd1ff;
  --font:"IBM Plex Sans KR",system-ui,"Malgun Gothic",sans-serif; --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;}
html,body{height:100%;margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:14px}
#map{position:absolute;inset:0}
.panel{position:absolute;background:var(--panel);backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:4px;padding:12px 14px;box-sizing:border-box}
#left{top:12px;left:12px;width:330px;max-height:calc(100% - 24px);overflow-y:auto}
#right{top:12px;right:12px;width:380px;max-height:calc(100% - 120px);overflow-y:auto}
#clock{left:50%;bottom:14px;transform:translateX(-50%);width:min(720px,calc(100% - 24px));display:grid;grid-template-columns:auto 1fr auto auto;gap:10px;align-items:center}
#busy{position:absolute;left:50%;top:14px;transform:translateX(-50%);padding:6px 12px;font-size:.8rem;color:var(--ink);background:rgba(255,122,69,.18);border:1px solid var(--k2);border-radius:3px;display:none}
@media(max-width:900px){#right{display:none}#left{width:min(330px,calc(100% - 24px))}}
h1{font-size:1rem;font-weight:600;margin:0 0 2px}
.lead{color:var(--ink-2);font-size:.8rem;margin:0 0 10px;line-height:1.45}
.ctl{display:grid;gap:8px}
label{display:flex;flex-direction:column;gap:3px;font-size:.78rem;color:var(--ink-2)}
label.row{flex-direction:row;align-items:center;gap:6px}
select,input{font:inherit;font-size:.85rem;padding:5px 7px;border:1px solid var(--line);background:#0c1020;color:var(--ink);border-radius:3px}
input[type=range]{padding:0}
input[type=checkbox]{margin:0}
button{font:inherit;font-size:.8rem;padding:5px 10px;border:1px solid var(--line);background:#0c1020;color:var(--ink);border-radius:3px;cursor:pointer;white-space:nowrap}
button.on{border-color:var(--ink);background:#1a2340}
button.pri{background:var(--ink);color:#0a1024;border-color:var(--ink)}
.addrow{display:grid;grid-template-columns:1.3fr .7fr .9fr auto;gap:5px;align-items:end}
.addrow input{width:100%;box-sizing:border-box}
.pill{display:inline-block;font-size:.68rem;padding:0 6px;border-radius:2px;border:1px solid var(--line);color:var(--ink-2);margin-left:4px;vertical-align:middle}
.pill.k{color:#0a1024;border:none;background:var(--c);font-family:var(--mono);font-weight:600}
.note{font-size:.72rem;color:var(--muted);margin:8px 0 0;line-height:1.4}
details{border-top:1px solid var(--line);padding-top:8px}
summary{font-size:.82rem;font-weight:600;cursor:pointer;color:var(--ink)}
#plist{list-style:none;padding:0;margin:0;display:grid;gap:3px;font-size:.8rem}
#plist li{display:flex;align-items:center;gap:6px}
#plist li button{padding:0 6px;font-size:.7rem}
#plist .id{font-family:var(--mono);color:var(--muted);width:2.2em}
#plist .tm{font-family:var(--mono);color:var(--muted);margin-left:auto}
h2{font-size:.85rem;font-weight:600;margin:0 0 6px}
.summary{font-size:.8rem;color:var(--ink-2);margin:0 0 8px}
#log{font-size:.78rem;line-height:1.5;display:grid;gap:2px}
#log .ev{padding-left:8px;border-left:2px solid var(--line);display:grid;grid-template-columns:3.4em 1fr;gap:6px}
#log .ev .tm{font-family:var(--mono);color:var(--muted);font-size:.74rem}
#log .ev.y,#log .ev.c{border-left-color:var(--clash)}
#log .ev.f{border-left-color:var(--k1)}
#log .ev.a{border-left-color:var(--occ)}
#log .ev.now{background:rgba(255,59,59,.12)}
#log .ev.future{opacity:.3}
#log b{font-weight:600}
#clock .t{font-family:var(--mono);font-size:1.3rem;min-width:4.2em;font-variant-numeric:tabular-nums}
#clock .t small{font-size:.7rem;color:var(--muted);font-family:var(--font);margin-left:3px}
#clock input[type=range]{width:100%}
.ticks{position:relative;height:12px;font-size:.62rem;color:var(--muted)}
.ticks span{position:absolute;transform:translateX(-50%);font-family:var(--mono)}
.ticks span.ev{color:var(--clash);font-weight:600}
.leg{display:flex;flex-wrap:wrap;gap:8px 12px;font-size:.72rem;color:var(--ink-2);margin:8px 0 0}
.leg span::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:0;background:var(--c);box-shadow:0 0 6px var(--c)}
.maplibregl-ctrl-attrib{font-size:10px}
</style></head><body>
<div id="map"></div>
<div id="busy">경로 계산 중…</div>

<div id="left" class="panel">
  <h1>병원 역량 공간 — 전국</h1>
  <div style="display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin:6px 0 4px"><span class="note" style="margin:0">병원 표시</span><button data-hmode="sphere">3D 구만 (순수 모델)</button><button data-hmode="node">공중 노드</button><button data-hmode="beams">빛기둥</button></div>
  <p class="lead">병원은 역량 z 높이에 뜬 노드. 환자는 발생 시각에 켜져서 자기 높이 이상의 병원 중 도로 시간이 가장 짧은 줄을 잡고, <b>이 브라우저가 도로 그래프(OSM)로 직접 계산한 최단경로</b>를 따라 흘러간다. 도로 그래프는 전국 3차로 이상 + 병원 주변 4 km 골목(OSM). 지도를 클릭하면 환자가 떨어진다.</p>
  <div class="ctl">
    <details open><summary>환자 떨어뜨리기 (분배 모델)</summary>
      <div class="ctl" style="margin-top:8px">
        <label>시나리오
          <select id="scn">
            <option value="gangnam">강남역 다중 추돌 — 6명, 경증부터 들어오고 중증이 뒤에</option>
            <option value="stagger">시청 KTAS 2 × 5명 — 4분 간격 (τ 창 효과)</option>
            <option value="same2">도심 KTAS 2 × 6명 — 서울역·시청·종로, 먼 쪽이 먼저 출발</option>
            <option value="turnover">강북삼성 앞 반복 — 20분 간격 4명 (회전 효과)</option>
            <option value="hongdae">홍대 화재 5명 + 10분 뒤 시청 2명</option>
            <option value="custom">직접 구성</option>
          </select></label>
        <div class="addrow">
          <label>위치<select id="site">
            <option>강남역</option><option>시청</option><option>종로3가</option><option>서울역</option><option>노원역</option>
            <option>구로디지털단지</option><option>잠실</option><option>홍대입구</option><option>건대입구</option><option>연신내</option></select></label>
          <label>KTAS<select id="ktas"><option value="1">1</option><option value="2" selected>2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option></select></label>
          <label>질환군<select id="cond"><option value="general">일반</option><option value="stemi">심근경색</option><option value="stroke">뇌졸중</option><option value="trauma">중증외상</option></select></label>
          <label>발생(분)<input id="t0" type="number" min="0" max="180" step="1" value="0"></label>
          <button id="add" class="pri">추가</button>
        </div>
        <details><summary>통화 요약(voice v2 JSON)으로 환자 추가</summary>
          <div style="display:grid;gap:6px;margin-top:6px">
            <textarea id="vsum" rows="5" style="font:inherit;font-size:.72rem;font-family:var(--mono);background:#0c1020;color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:6px" placeholder='{"ktas_level": 2, "chief_complaint": {"major": "I 심혈관계", "minor": "흉통(심장성)"}, "suspected_diagnosis": [{"text": "경색 의심"}], "incidents": [{"type": "질병", "primary": true}], "disease_category": "심장질환"}'></textarea>
            <div style="display:flex;gap:6px;align-items:center"><button id="vadd" class="pri">요약으로 추가</button><span id="vmsg" class="note" style="margin:0"></span></div>
            <p class="note" style="margin:0">위치·발생(분)은 위 칸을 쓴다. KTAS는 요약의 ktas_level, 질환군은 예상 병명 키워드 규칙(뇌졸중 → 심근경색 → 외상 기전+KTAS 1·2 → 일반). 규칙은 <code>voice_to_patient.py</code>와 같다. 무작위 환자의 질환군은 여전히 주사위다.</p>
          </div>
        </details>
        <div style="border:1px solid var(--line);border-radius:3px;padding:8px;display:grid;gap:6px">
          <div style="font-size:.78rem;color:var(--ink);font-weight:600">완전 랜덤 생성</div>
          <label>환자 수 <span id="rnv" class="pill">12</span><input id="rn" type="range" min="2" max="60" step="1" value="12"></label>
          <label>발생 시간 폭 (분, 0~이 안에서 무작위) <span id="rwv" class="pill">20</span><input id="rw" type="range" min="0" max="90" step="5" value="20"></label>
          <label>범위<select id="rs"><option value="seoul">서울 도로 위</option><option value="korea">전국 (병원 주변 10 km)</option></select></label>
          <label>KTAS 분포<select id="rk"><option value="real">실제 비슷하게 (1:5% 2:15% 3:40% 4:30% 5:10%)</option><option value="severe">중증 위주 (1:30% 2:40% 3:30%)</option><option value="uniform">균등</option></select></label>
          <div style="display:flex;gap:6px"><button id="rgen" class="pri">랜덤 생성</button><button id="radd">랜덤 추가</button></div>
          <p class="note" style="margin:0">서울은 서울 안 도로 노드 중 무작위. 전국은 병원 주변 10 km 안 무작위.</p>
        </div>
        <ul id="plist"></ul>
        <div style="display:flex;gap:6px"><button id="clear">전부 비우기</button><button id="rise">기둥 다시 올리기</button></div>
        <label class="row"><input id="air" type="checkbox" checked> 공중에도 거미줄 (환자 높이 → 병원 꼭대기)</label>
        <label>τ · 도착 시각이 이 안에 겹치면 같은 창 (분) <span id="tauv" class="pill">10</span><input id="tau" type="range" min="2" max="30" step="1" value="10"></label>
        <label>동시 수용 한도 · 한 창 안에 받는 환자 수 <span id="capv" class="pill">2</span><input id="cap" type="range" min="1" max="6" step="1" value="2"></label>
        <label>회전 · 도착 후 병상을 비우기까지 (분) <span id="dwellv" class="pill">30</span><input id="dwell" type="range" min="5" max="90" step="5" value="30"></label>
        <label>μ · 중증이 한 단계 위로 가려고 더 갈 분 (KTAS 1·2) <span id="mu2v" class="pill">30</span><input id="mu2" type="range" min="0" max="60" step="5" value="30"></label>
        <label>μ · KTAS 3 <span id="mu3v" class="pill">5</span><input id="mu3" type="range" min="0" max="60" step="5" value="5"></label>
        <label>λ · 경증(KTAS 4·5)이 센터로 갈 때 물리는 분 <span id="lamv" class="pill">5</span><input id="lam" type="range" min="0" max="15" step="1" value="5"></label>
        <label>시작 시각 (시, 야간 22~06은 얇은 병원 역량이 내려감) <span id="shv" class="pill">14</span><input id="sh" type="range" min="0" max="23" step="1" value="14"></label>
        <label class="row"><input id="dyn" type="checkbox" checked> 유효 역량 사용 (전문의 두께·야간) + 부하 항</label>
        <label class="row"><input id="wload" type="checkbox" checked> 부하 항 — 줄 길이에 분으로 (이송 중 건수 10×n/(n+가용) + 포화 최대 5분; 허브 공유 장부 전제, 각자 낡은 뷰면 끌 것)</label>
        <label>높이 배율 <span id="hv" class="pill">500</span><input id="hs" type="range" min="100" max="1500" step="50" value="500"></label>
        <label>높이 대비 (지수, 클수록 상급 병원이 더 솟음) <span id="zexpv" class="pill">2.0</span><input id="zexp" type="range" min="1" max="3" step="0.1" value="2.0"></label>
      </div>
    </details>
    <details><summary>보기</summary>
      <div class="ctl" style="margin-top:8px">
        <label>시점
          <div style="display:flex;gap:5px;flex-wrap:wrap"><button data-cam="korea">전국</button><button data-cam="seoul">서울</button><button data-cam="top">위에서</button><button data-cam="tilt">비스듬히</button><button data-cam="side">옆에서</button><button data-cam="low">낮게 옆에서</button><button id="spin">회전</button></div>
          <p class="note" style="margin:4px 0 0">언제든 마우스로 잡으면 회전·연출이 멈춘다. 왼쪽 드래그 이동 · 오른쪽 드래그(또는 Ctrl+드래그) 돌리기·기울이기 · 휠 확대 · 방향키/Shift+방향키</p></label>
        <label>바탕지도<select id="base"><option value="esri">어두운 회색 (Esri, 한글 지명)</option><option value="sat">위성 영상 어둡게 (Esri)</option><option value="street">길거리 지도 어둡게 (Esri)</option><option value="osm">OpenStreetMap 어둡게</option></select></label>
        <label class="row"><input id="camauto" type="checkbox" checked> 카메라 연출 (재생 때 위에서 → 옆으로)</label>
      </div>
    </details>
  </div>
  <div class="leg">
    <span style="--c:var(--g4)">권역센터</span><span style="--c:var(--g3)">지역센터</span><span style="--c:var(--g2)">지역기관</span>
    <span style="--c:var(--k1)">K1</span><span style="--c:var(--k2)">K2</span><span style="--c:var(--k3)">K3</span><span style="--c:var(--k4)">K4·5</span>
    <span style="--c:var(--occ)">점유 중</span><span style="--c:var(--clash)">충돌</span>
  </div>
  <p class="note" id="etanote"></p>
</div>

<div id="right" class="panel">
  <h2>시간순 기록</h2>
  <p class="summary" id="sum"></p>
  <div id="log"></div>
</div>

<div id="clock" class="panel">
  <div class="t"><span id="tv">0</span><small>분</small></div>
  <div><input id="time" type="range" min="0" max="60" step="0.25" value="0"><div class="ticks" id="ticks"></div></div>
  <button id="play" class="pri">▶ 재생</button>
  <button id="end">끝으로</button>
</div>

<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>
<script src="roads_data.js"></script>
<script>
const H = __DATA__;
const ROADS_RAW = window.ROADS_RAW||null;  // build_roads_kr.py → roads_data.js (전국 도로 그래프)
const $ = id=>document.getElementById(id);
const css = n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgb = (hex,a=255)=>{const h=hex.replace('#','');return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16),a];};
const KTAS_Z = {1:4,2:3,3:2,4:1,5:1};
const full = h=>h.hasBeds && h.hvec!==null && h.hvec<=0;
const hp = id=>H.find(h=>h.hpid===id);
const LIVE=H.filter(h=>h.hasBeds), DEAD=H.filter(h=>!h.hasBeds);
const R=6371, toR=d=>d*Math.PI/180;
function straightKm(aLat,aLng,bLat,bLng){
  const dLat=toR(bLat-aLat),dLng=toR(bLng-aLng);
  const a=Math.sin(dLat/2)**2+Math.cos(toR(aLat))*Math.cos(toR(bLat))*Math.sin(dLng/2)**2;
  return 2*R*Math.asin(Math.sqrt(a));
}
const straightMin=(aLat,aLng,bLat,bLng)=>straightKm(aLat,aLng,bLat,bLng)*1.35/25*60;

// ---------- 도로 그래프 ----------
// 등급별 자유흐름 속도(km/h). 구급차 보정 없음(초안).
const SPEED=[80,55,45,35,25];
const G=(()=>{ if(!ROADS_RAW) return null; const r=ROADS_RAW; const [x0,x1,y0,y1]=r.bbox;
  const u8=b=>Uint8Array.from(atob(b),c=>c.charCodeAt(0));
  const u16=b=>{const a=u8(b);return new Uint16Array(a.buffer,a.byteOffset,a.byteLength>>1);};
  const u32=b=>{const a=u8(b);return new Uint32Array(a.buffer,a.byteOffset,a.byteLength>>2);};
  const i32=b=>{const a=u8(b);return new Int32Array(a.buffer,a.byteOffset,a.byteLength>>2);};
  let n,lat,lng;
  if(r.scale){ const q=i32(r.npos); n=q.length>>1; lat=new Float64Array(n); lng=new Float64Array(n); for(let i=0;i<n;i++){lng[i]=q[2*i]/r.scale; lat[i]=q[2*i+1]/r.scale;} }
  else { const q=u16(r.npos); n=q.length>>1; lat=new Float64Array(n); lng=new Float64Array(n); for(let i=0;i<n;i++){lng[i]=x0+(x1-x0)*q[2*i]/65535; lat[i]=y0+(y1-y0)*q[2*i+1]/65535;} }
  const wn=u32(r.wn), starts=u32(r.starts), wcls=u8(r.wcls);
  // 인접 리스트 (CSR)
  const deg=new Uint32Array(n);
  for(let w=0;w<wcls.length;w++) for(let i=starts[w];i+1<starts[w+1];i++){deg[wn[i]]++; deg[wn[i+1]]++;}
  const off=new Uint32Array(n+1); for(let i=0;i<n;i++) off[i+1]=off[i]+deg[i];
  const adj=new Uint32Array(off[n]), wt=new Float32Array(off[n]), fill=new Uint32Array(n);
  for(let w=0;w<wcls.length;w++){ const sp=SPEED[wcls[w]];
    for(let i=starts[w];i+1<starts[w+1];i++){ const a=wn[i], b=wn[i+1]; const m=straightKm(lat[a],lng[a],lat[b],lng[b])/sp*60;
      adj[off[a]+fill[a]]=b; wt[off[a]+fill[a]++]=m; adj[off[b]+fill[b]]=a; wt[off[b]+fill[b]++]=m; } }
  // 공간 격자 (최근접 노드)
  const GX=Math.max(50,Math.round((x1-x0)*88.8)), GY=Math.max(50,Math.round((y1-y0)*111)), cell=new Int32Array(GX*GY).fill(-1), nxt=new Int32Array(n).fill(-1);  // 약 1 km 격자
  const cx=v=>Math.min(GX-1,Math.max(0,((v-x0)/(x1-x0)*GX)|0)), cy=v=>Math.min(GY-1,Math.max(0,((v-y0)/(y1-y0)*GY)|0));
  for(let i=0;i<n;i++){ if(deg[i]===0) continue; const c=cy(lat[i])*GX+cx(lng[i]); nxt[i]=cell[c]; cell[c]=i; }
  function nearest(la,lo){ let best=-1,bd=1e9; for(let rad=0;rad<6&&best<0;rad++){ const X=cx(lo),Y=cy(la);
    for(let yy=Y-rad;yy<=Y+rad;yy++) for(let xx=X-rad;xx<=X+rad;xx++){ if(xx<0||yy<0||xx>=GX||yy>=GY) continue; if(Math.max(Math.abs(xx-X),Math.abs(yy-Y))!==rad) continue;
      for(let i=cell[yy*GX+xx];i>=0;i=nxt[i]){ const d=(lat[i]-la)**2+((lng[i]-lo)*0.79)**2; if(d<bd){bd=d;best=i;} } } }
    return best; }
  return {n,lat,lng,off,adj,wt,nearest};
})();

// 이진 힙 (키: 분)
class Heap{ constructor(cap){this.k=new Float64Array(cap);this.v=new Int32Array(cap);this.n=0;}
  push(v,k){let i=this.n++; while(i>0){const p=(i-1)>>1; if(this.k[p]<=k) break; this.k[i]=this.k[p]; this.v[i]=this.v[p]; i=p;} this.k[i]=k; this.v[i]=v;}
  pop(){const v=this.v[0],k=this.k[0]; const lk=this.k[--this.n], lv=this.v[this.n]; let i=0; for(;;){let c=2*i+1; if(c>=this.n) break; if(c+1<this.n&&this.k[c+1]<this.k[c]) c++; if(this.k[c]>=lk) break; this.k[i]=this.k[c]; this.v[i]=this.v[c]; i=c;} this.k[i]=lk; this.v[i]=lv; return {v,k};}
  get size(){return this.n;} }
// 한 점에서 전체(또는 목표 집합)까지. 목표가 다 정착되면 멈춘다.
// 작업 배열(거리·방문·힙)은 한 번만 만들어 돌려쓴다 — 환자 수십 명을 연달아 돌려도 메모리가 늘지 않게.
// dist는 Float64 — Float32로 두면 힙 키(Float64)와 반올림이 달라 길이 0 간선에서 prev가 고리를 만든다(실제로 겪음)
const WORK=G?{dist:new Float64Array(G.n),done:new Uint8Array(G.n),isT:new Uint8Array(G.n),heap:new Heap(1<<21)}:null;
const MAX_ROUTE_MIN=120; // 이 시간 너머 병원은 탐색하지 않는다(전국 그래프 100만 노드를 매번 다 돌지 않게)
function dijkstra(src,targets){
  const n=G.n, {dist,done,isT,heap}=WORK; dist.fill(Infinity); done.fill(0); isT.fill(0); heap.n=0;
  const prev=new Int32Array(n).fill(-1);
  let left=0; if(targets){for(const t of targets){ if(!isT[t]){isT[t]=1;left++;} }}
  dist[src]=0; heap.push(src,0); let settled=0;
  while(heap.size){ const {v,k}=heap.pop(); if(done[v]) continue; if(k>MAX_ROUTE_MIN) break; done[v]=1; settled++;
    if(isT[v]&&--left===0) break;
    for(let e=G.off[v];e<G.off[v+1];e++){ const u=G.adj[e]; if(done[u]) continue; const nd=k+G.wt[e]; if(nd<dist[u]){dist[u]=nd; prev[u]=v; if(heap.n<heap.k.length) heap.push(u,nd);} } }
  return {dist,prev,settled};
}
const nodeLL=i=>[G.lng[i],G.lat[i]];

// ---------- 경로 서비스 ----------
const runCache={};
function tableFrom(from){ // 출발점 → 모든 병원 (분) + prev 트리
  const key=from.lat.toFixed(5)+','+from.lng.toFixed(5); if(runCache[key]) return runCache[key];
  let out;
  const s0=inG(from.lat,from.lng)?G.nearest(from.lat,from.lng):-1;
  if(G&&s0>=0){ const s=s0; const targets=LIVE.filter(h=>h.node>=0).map(h=>h.node); const r=dijkstra(s,targets);
    const row={}; LIVE.forEach(h=>{ const d=h.node>=0?r.dist[h.node]:Infinity; row[h.hpid]=isFinite(d)?d+straightMin(from.lat,from.lng,G.lat[s],G.lng[s])+straightMin(h.lat,h.lng,G.lat[h.node],G.lng[h.node]):null; });
    out={row,src:s,prev:r.prev,settled:r.settled}; }
  else { const row={}; LIVE.forEach(h=>row[h.hpid]=null); out={row,src:-1,prev:null,settled:0}; }
  const ks=Object.keys(runCache); if(ks.length>150) delete runCache[ks[0]];
  runCache[key]=out; return out;
}
function routeTo(from,h){
  const t=tableFrom(from);
  if(t.prev&&h.node>=0&&isFinite(t.row[h.hpid])){ const c=[]; for(let v=h.node,g=0;v>=0&&g<G.n;v=t.prev[v],g++) c.push(nodeLL(v)); c.reverse(); c.unshift([from.lng,from.lat]); c.push([h.lng,h.lat]);
    let km=0; for(let i=1;i<c.length;i++) km+=straightKm(c[i-1][1],c[i-1][0],c[i][1],c[i][0]); return {coords:c,distKm:km}; }
  return {coords:[[from.lng,from.lat],[h.lng,h.lat]],distKm:straightKm(from.lat,from.lng,h.lat,h.lng)};
}
const inG=(la,lo)=>!!G&&la>=ROADS_RAW.bbox[2]&&la<=ROADS_RAW.bbox[3]&&lo>=ROADS_RAW.bbox[0]&&lo<=ROADS_RAW.bbox[1];
if(G) LIVE.forEach(h=>h.node=inG(h.lat,h.lng)?G.nearest(h.lat,h.lng):-1);

// ---------- 환자·시나리오 ----------
const SITES = {강남역:[37.4981,127.0276],시청:[37.5665,126.9780],종로3가:[37.5704,126.9918],서울역:[37.5547,126.9707],
  노원역:[37.6542,127.0568],구로디지털단지:[37.5034,126.8820],잠실:[37.5145,127.1059],홍대입구:[37.5509,126.9100],건대입구:[37.5386,127.0824],연신내:[37.6176,126.9227]};
const SCN = {
  gangnam:[['강남역',4,0],['강남역',3,0],['강남역',3,1],['강남역',2,2],['강남역',2,2],['강남역',1,3]],
  stagger:[['시청',2,0],['시청',2,4],['시청',2,8],['시청',2,12],['시청',2,16]],
  same2:[['서울역',2,0],['서울역',2,0],['시청',2,1],['시청',2,1],['종로3가',2,3],['종로3가',2,3]],
  turnover:[['시청',2,0],['시청',2,20],['시청',2,40],['시청',2,60]],
  hongdae:[['홍대입구',4,0],['홍대입구',3,0],['홍대입구',3,1],['홍대입구',2,1],['홍대입구',1,2],['시청',2,10],['시청',3,10]],
  custom:[]};
let P=[], nextId=1, RES=null, timer=null, riseT0=performance.now();
function addPatient(site,k,t0,lat,lng){
  if(lat===undefined){[lat,lng]=SITES[site];}
  const id=nextId++;
  const n=P.filter(p=>p.site===site).length, ang=n*2.1, r=n?0.0012:0;
  P.push({id,site,k,t0,lat:lat+r*Math.sin(ang),lng:lng+r*Math.cos(ang)*1.25,z:KTAS_Z[k]});
}
function loadScenario(){ P=[]; nextId=1; SCN[$('scn').value].forEach(([s,k,t])=>addPatient(s,k,t)); }
// 완전 랜덤: 도로 노드 중 무작위 위치, KTAS 분포, 발생 시각
const KDIST={real:[.05,.15,.40,.30,.10],severe:[.30,.40,.30,0,0],uniform:[.2,.2,.2,.2,.2]};
function randomPatients(n,add){
  if(!add){P=[];nextId=1;}
  const W=+$('rw').value, dist=KDIST[$('rk').value];
  for(let i=0;i<n;i++){
    let k=1, r=Math.random(), acc=0; for(let j=0;j<5;j++){acc+=dist[j]; if(r<acc){k=j+1;break;}}
    let lat,lng;
    if($('rs').value==='korea'){ const h=LIVE[(Math.random()*LIVE.length)|0]; const r=Math.sqrt(Math.random())*0.09, a=Math.random()*Math.PI*2; lat=h.lat+r*Math.sin(a); lng=h.lng+r*Math.cos(a)*1.25; }
    else if(G){ let v,g=0; do{ v=(Math.random()*G.n)|0; }while((G.off[v+1]===G.off[v]||G.lat[v]<37.43||G.lat[v]>37.70||G.lng[v]<126.77||G.lng[v]>127.19)&&g++<100000); lat=G.lat[v]; lng=G.lng[v]; }
    else { lat=37.45+Math.random()*0.22; lng=126.80+Math.random()*0.36; }
    addPatient('무작위',k,Math.round(Math.random()*W),lat,lng);
    const r2=Math.random(); P[P.length-1].cond=k<=2?(r2<.2?'stemi':r2<.4?'stroke':r2<.5?'trauma':'general'):k===3?(r2<.1?'stemi':r2<.2?'stroke':r2<.3?'trauma':'general'):'general';
  }
  $('scn').value='custom';
}
function cumul(coords){ const d=[0]; for(let i=1;i<coords.length;i++) d.push(d[i-1]+straightKm(coords[i-1][1],coords[i-1][0],coords[i][1],coords[i][0])); const T=d[d.length-1]||1; return d.map(x=>x/T); }
// voice v2 통화 요약 → {k, cond, text}. voice_to_patient.py와 같은 규칙(규칙 기반). 한쪽을 고치면 다른 쪽도.
const V_STROKE=/뇌졸중|뇌\s*경색|뇌출혈|편마비|구음\s*장애|거미막하|지주막하|두개내\s*출혈|경막[하외]\s*(출혈|혈종)/, V_STEMI=/심근\s*경색|급성\s*관상|STEMI|흉통\(심장성\)|경색/;
function voiceToPatient(sum){
  if(sum&&typeof sum.summary==='object'&&sum.summary) sum=sum.summary;
  sum=sum||{};
  const k=[1,2,3,4,5].includes(+sum.ktas_level)?+sum.ktas_level:3;
  const incs=sum.incidents||[], pri=incs.find(i=>i.primary)||incs[0];
  const parts=[];
  if(pri&&pri.type&&pri.type!=='질병') parts.push(pri.detail?`${pri.type}(${pri.detail})`:pri.type);
  else if(sum.disease_category&&sum.disease_category!=='기타 질병') parts.push(sum.disease_category);
  const minor=(sum.chief_complaint||{}).minor; if(minor) parts.push(minor);
  (sum.suspected_diagnosis||[]).forEach(d=>d.text&&parts.push(d.text));
  (sum.injuries||[]).slice(0,3).forEach(i=>parts.push([i.side,i.region,i.type].filter(Boolean).join(' ')));
  const seen=[]; parts.map(x=>String(x).split(/\s+/).join(' ').trim()).forEach(x=>{if(x&&!seen.includes(x))seen.push(x);});
  const text=seen.join(' · ')||(sum.chief_complaint||{}).major||'미상';
  const trauma=!!(pri&&pri.type&&pri.type!=='질병');
  const cond=V_STROKE.test(text)?'stroke':V_STEMI.test(text)?'stemi':(trauma&&k<=2)?'trauma':'general';
  return {k,cond,text};
}
// 질환군 딱딱한 벽: 이 장비·등급이 없으면 줄 자체가 안 걸린다 (초안, 전문의 검토 전)
const COND={general:{label:'일반',wall:h=>true},stemi:{label:'심근경색',wall:h=>h.angio==='Y'},stroke:{label:'뇌졸중',wall:h=>h.ct==='Y'&&h.g>=2},trauma:{label:'중증외상',wall:h=>h.g>=3}};
// 병원 유효 역량: 등급 + 전문의 두께 + 야간 감점 (초안 값). 설명용 분해를 같이 돌려준다.
// 부하(포화·이송 중)는 z에 넣지 않는다 — z는 μ에 곱해지는데 μ가 경증에서 음수라 붐비는 병원이 경증에게 더 짧아졌다(2026-10-12 재생에서 확인).
// 부하는 load(분)로 따로 돌려주고 줄 길이에 더한다: 허브와 같은 식 — 이송 중 페널티 10×이송 중/(이송 중+가용), 포화 페널티 최대 5분.
function zEff(h,tNow,ctx){
  if(!$('dyn').checked) return {z:h.g,parts:'',load:0,loadParts:''};
  const em=h.em??0; const thick=em<=1?-0.4:em<=3?-0.2:em>=8?0.2:0;
  const hour=((+$('sh').value)+tNow/60)%24, night=hour>=22||hour<6; const nt=night?(h.g<=2&&em<=2?-0.6:em<=3?-0.25:-0.1):0;
  const occ=h.er_cap&&h.hvec!==null?Math.max(0,Math.min(1,1-h.hvec/h.er_cap)):0.5;
  const infl=$('wload').checked?ctx.inflight(h.hpid):0, free=Math.max(0,h.hvec??ctx.capN);
  const lp=10*infl/Math.max(1,infl+free), op=$('wload').checked?5*occ:0;
  return {z:h.g+thick+nt,parts:`등급${h.g} 전문의${em}명 ${thick>=0?'+':''}${thick.toFixed(1)}${night?' 야간'+nt.toFixed(1):''}`,
          load:lp+op,loadParts:`${op?' 포화+'+op.toFixed(1)+'분':''}${infl?' 이송중'+infl+'건+'+lp.toFixed(1)+'분':''}`};
}
function candidates(row,from,p,tNow,ctx){
  const need=KTAS_Z[p.k], lam=+$('lam').value;
  // μ: 위급할수록 한 단계 위로 더 멀리 간다. 이송 중 중증(K1·2)이 많을수록 μ를 깎아 센터를 아낀다.
  const mu0=p.k<=2?+$('mu2').value:p.k===3?+$('mu3').value:-lam;
  const mu=p.k<=3?mu0*Math.max(0,1-ctx.inflightSevere/10):mu0;
  const wall=COND[p.cond||'general'].wall;
  return LIVE.filter(h=>!full(h)&&wall(h)).map(h=>{
    const road=row[h.hpid]??straightMin(from.lat,from.lng,h.lat,h.lng), ze=zEff(h,tNow,ctx);
    const gap=ze.z-need; if(gap<-0.75) return null;   // 유효 역량이 필요 역량보다 0.75 넘게 모자라면 줄이 안 걸린다 (얇은 지역기관의 야간 등)
    // 위로 가는 이득은 μ(한 단계까지 전액, 그 위 1/4), 모자람의 비용은 ν(위급할수록 큼)
    const nu=p.k<=2?30:p.k===3?15:5;
    const len=(gap>=0?road-mu*(Math.min(gap,1)+0.25*Math.max(0,gap-1)):road+nu*(-gap))+ze.load;
    return {h,road,gap,mu,len,parts:ze.parts+ze.loadParts};
  }).filter(Boolean).sort((a,b)=>a.len-b.len);
}
function posAt(seg,t){
  const f=Math.max(0,Math.min(1,(t-seg.tStart)/Math.max(1e-6,seg.tArr-seg.tStart)));
  const c=seg.coords, u=seg.cum; let i=1; while(i<u.length-1&&u[i]<f) i++;
  const a=c[i-1], b=c[i], w=(f-u[i-1])/Math.max(1e-9,u[i]-u[i-1]);
  return {lng:a[0]+(b[0]-a[0])*w, lat:a[1]+(b[1]-a[1])*w, z:seg.from.z+(seg.h.z-seg.from.z)*f, f, i};
}
function pathFrom(seg,f){ const p=posAt(seg,seg.tStart+f*(seg.tArr-seg.tStart)); return [[p.lng,p.lat],...seg.coords.slice(p.i)]; }

// ---------- 시간 기반 해소 (동기 — 경로가 로컬이라 빠르다) ----------
function solve(){
  const lam=+$('lam').value, capN=+$('cap').value, tau=+$('tau').value, dwell=+$('dwell').value;
  const cur={}, hist={}, skip={}, forced={}, events=[];
  const mm=t=>t.toFixed(0);
  const assigned=hpid=>Object.values(cur).filter(s=>s.h.hpid===hpid);
  const occupancy=(hpid,t,me)=>assigned(hpid).filter(s=>s.pid!==me&&s.tArr<=t&&t<s.tArr+dwell).length;
  const beds=h=>h.hvec===null?capN:h.hvec;
  const queue=P.slice().sort((a,b)=>a.t0-b.t0||a.id-b.id).map(p=>({p,from:{lat:p.lat,lng:p.lng,z:p.z},tNow:p.t0,first:true}));
  let guard=0, settled=0;
  const mkSeg=(p,from,tNow,c,tArr)=>{ const rt=routeTo(from,c.h); return {pid:p.id,h:c.h,from:{...from},tStart:tNow,tArr,tEnd:null,len:c.len,road:c.road,coords:rt.coords,cum:cumul(rt.coords),distKm:rt.distKm}; };
  while(queue.length&&guard++<20000){
    queue.sort((a,b)=>a.tNow-b.tNow||a.p.id-b.p.id);
    const {p,from,tNow,first}=queue.shift();
    skip[p.id]??=new Set(); hist[p.id]??=[];
    const tb=tableFrom(from); settled+=tb.settled;
    const ctx={capN,inflightSevere:Object.values(cur).filter(sg=>sg.tArr>tNow&&P.find(q=>q.id===sg.pid).k<=2).length,winCount:hpid=>assigned(hpid).filter(sg=>Math.abs(sg.tArr-tNow)<=tau).length,inflight:hpid=>assigned(hpid).filter(sg=>sg.tArr>tNow).length};
    const cands=candidates(tb.row,from,p,tNow,ctx).filter(c=>!skip[p.id].has(c.h.hpid));
    if(first) events.push({t:tNow,type:'s',text:`<b>#${p.id}</b> (K${p.k}${p.cond&&p.cond!=='general'?' '+COND[p.cond].label:''}) ${p.site} 발생 · 걸 수 있는 줄 ${cands.length}개 · μ ${cands[0]?cands[0].mu.toFixed(0):'-'}분/레벨${ctx.inflightSevere?' (이송 중 중증 '+ctx.inflightSevere+')':''}`});
    let placed=false; const avoided=[];
    // 한 후보가 지금 잡을 수 있는지 (병상·창·우선순위) 판정
    const check=c=>{ const tArr=tNow+c.road, h=c.h;
      if(occupancy(h.hpid,tArr,p.id)>=beds(h)) return {ok:false,why:h.name+'(병상 참)'};
      const win=assigned(h.hpid).filter(s=>s.pid!==p.id&&Math.abs(s.tArr-tArr)<=tau);
      const fixed=win.filter(s=>s.tArr<=tNow), movable=win.filter(s=>s.tArr>tNow);
      if(fixed.length>=capN) return {ok:false,why:h.name+'(창 '+fixed.length+'/'+capN+' 도착 완료)'};
      const slots=capN-fixed.length, me={pid:p.id,k:p.k,tArr};
      const rank=[...movable.map(s=>({pid:s.pid,k:P.find(q=>q.id===s.pid).k,tArr:s.tArr})),me].sort((a,b)=>a.k-b.k||a.tArr-b.tArr||a.pid-b.pid);
      if(rank.findIndex(r=>r.pid===p.id)>=slots) return {ok:false,why:h.name+'(창 꽉 참, 우선순위 밀림)'};
      return {ok:true,tArr,win,rank,losers:rank.slice(slots)}; };
    let pick=null, info=null;
    for(const c of cands){ const f=check(c); if(!f.ok){avoided.push(f.why);continue;} pick=c; info=f; break; }
    if(pick){
      const h=pick.h, c=pick, tArr=info.tArr;
      if(info.losers.length) events.push({t:tNow,type:'c',text:`<b>${h.name}</b> 충돌 · 창 안 ${info.win.length+1}명 (한도 ${capN}): ${info.rank.map(r=>'#'+r.pid+'(K'+r.k+', '+mm(r.tArr)+'분 도착)').join(' · ')}`,hpid:h.hpid});
      for(const l of info.losers){
        const s=cur[l.pid], lp=P.find(q=>q.id===l.pid);
        s.tEnd=tNow; const at=posAt(s,tNow);
        skip[l.pid].add(h.hpid); delete cur[l.pid];
        const why=p.k<lp.k?`더 위급한 #${p.id}(K${p.k})에게`:`같은 KTAS, #${p.id}가 먼저 닿아서`;
        events.push({t:tNow,type:'y',text:`<b>#${l.pid}</b> (K${lp.k}) ${h.name} 줄을 놓음 · ${why} · 이동 중 위치에서 다시 던짐`});
        queue.push({p:lp,from:{lat:at.lat,lng:at.lng,z:at.z},tNow,first:false});
      }
      const seg=mkSeg(p,from,tNow,c,tArr); cur[p.id]=seg; hist[p.id].push(seg); placed=true; seg.gap=c.gap;
      events.push({t:tNow,type:first?'w':'r',text:`<b>#${p.id}</b> → ${h.name} ${first?'줄 잡음':'다시 잡음'} · 도로 ${c.road.toFixed(1)}분 ${seg.distKm.toFixed(1)}km · 줄 길이 ${c.len.toFixed(1)} (유효z ${(c.gap+KTAS_Z[p.k]).toFixed(2)} − 필요 ${KTAS_Z[p.k]} = ${c.gap>=0?'+':''}${c.gap.toFixed(2)}; ${c.parts}) · ${mm(tArr)}분 도착 예정${cands[0]&&cands[0].h!==c.h&&cands.indexOf(c)>0?'':''}${avoided.length?' · 예측 충돌로 피한 줄: '+avoided.join(', '):''}`});
    }
    if(!placed){
      const c=cands[0]??candidates(tb.row,from,p,tNow,ctx)[0];
      if(c){const tArr=tNow+c.road, seg=mkSeg(p,from,tNow,c,tArr); cur[p.id]=seg; hist[p.id].push(seg); forced[p.id]=true;
        events.push({t:tNow,type:'f',text:`<b>#${p.id}</b> (K${p.k}) 빈 벽이 없어 ${c.h.name}에 초과로 걸림 · ${mm(tArr)}분 도착`});}
      else events.push({t:tNow,type:'f',text:`<b>#${p.id}</b> (K${p.k}) 걸 수 있는 줄이 없음`});
    }
  }
  Object.values(cur).forEach(s=>{const p=P.find(q=>q.id===s.pid);
    events.push({t:s.tArr,type:'a',text:`<b>#${p.id}</b> ${s.h.name} 도착 · ${(s.tArr+dwell).toFixed(0)}분까지 병상 점유`});
    events.push({t:s.tArr+dwell,type:'o',text:`<b>#${p.id}</b> ${s.h.name} 병상 비움`});});
  events.sort((a,b)=>a.t-b.t);
  const tMax=Math.max(10,...Object.values(cur).map(s=>s.tArr+dwell),...P.map(p=>p.t0+5));
  return {cur,hist,forced,events,tMax,dwell,settled};
}

// ---------- 지도 ----------
const BASE={
  sat:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:19,attribution:'Esri, Maxar, Earthstar Geographics'}},
    layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.55,'raster-saturation':-.35,'raster-contrast':.1}}]},
  street:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:19,attribution:'Esri, HERE, Garmin, © OpenStreetMap contributors'}},
    layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.45,'raster-saturation':-.6,'raster-contrast':.15}}]},
  esri:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:16,attribution:'Esri, HERE, Garmin, © OpenStreetMap contributors'}},layers:[{id:'b',type:'raster',source:'b'}]},
  osm:{version:8,sources:{b:{type:'raster',tiles:['https://tile.openstreetmap.de/{z}/{x}/{y}.png'],tileSize:256,maxzoom:18,attribution:'© OpenStreetMap contributors (openstreetmap.de)'}},layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.42,'raster-saturation':-.7,'raster-contrast':.15}}]}};
const {DeckGL, ColumnLayer, ScatterplotLayer, LineLayer, PathLayer, TripsLayer, TextLayer, SimpleMeshLayer} = deck;
// 병원 표시 방식: sphere(3D 구만) / node(공중 노드+줄기, 기본) / beams(빛기둥)
let HMODE='node';   // 기본은 공중 노드(2026-10-15 요청) — 버튼으로 3D 구·빛기둥으로 바꿀 수 있다
// 단위 구 메시 (SimpleMeshLayer용) — 외부 의존 없이 직접 만든다
const SPHERE=(()=>{const la=18,lo=36,pos=[],nor=[],idx=[];
  for(let i=0;i<=la;i++){const th=Math.PI*i/la,st=Math.sin(th),ct=Math.cos(th);
    for(let j=0;j<=lo;j++){const ph=2*Math.PI*j/lo,x=st*Math.cos(ph),y=st*Math.sin(ph),z=ct; pos.push(x,y,z); nor.push(x,y,z);}}
  for(let i=0;i<la;i++)for(let j=0;j<lo;j++){const a=i*(lo+1)+j,b=a+lo+1; idx.push(a,b,a+1,b,b+1,a+1);}
  return {positions:{value:new Float32Array(pos),size:3},normals:{value:new Float32Array(nor),size:3},indices:{value:new Uint32Array(idx)}};})();
let VIEW={longitude:127.7,latitude:36.3,zoom:6.6,pitch:50,bearing:-10}, spinning=false;
const CAMS={korea:{longitude:127.7,latitude:36.3,zoom:6.6,pitch:50,bearing:-10},seoul:{longitude:126.99,latitude:37.53,zoom:11,pitch:58,bearing:-18},top:{pitch:0,bearing:0,zoom:11},tilt:{pitch:58,bearing:-18,zoom:11},side:{pitch:75,bearing:-30,zoom:11.4},low:{pitch:78,bearing:20,zoom:12.2}};
function goCam(c){VIEW={...VIEW,...c,transitionDuration:900}; deckgl.setProps({initialViewState:VIEW});}
// 카메라 연출: 환자들 위에서 내려다보다가 3초 뒤 천천히 옆으로 기울어진다
let camT=null;
function choreograph(){
  if(!$('camauto').checked||!P.length) return;
  spinning=false; $('spin').textContent='회전'; clearTimeout(camT);
  const pts=P.map(p=>[p.lng,p.lat]).concat(Object.values(RES?.cur||{}).map(sg=>[sg.h.lng,sg.h.lat]));
  const lngs=pts.map(a=>a[0]), lats=pts.map(a=>a[1]);
  const cLng=(Math.min(...lngs)+Math.max(...lngs))/2, cLat=(Math.min(...lats)+Math.max(...lats))/2;
  const span=Math.max((Math.max(...lngs)-Math.min(...lngs))*0.79,Math.max(...lats)-Math.min(...lats));
  const zoom=Math.min(13,Math.max(10.5,Math.log2(0.6/Math.max(span,0.02))+9.2));
  goCam({longitude:cLng,latitude:cLat,zoom,pitch:0,bearing:0});
  camT=setTimeout(()=>{VIEW={...VIEW,pitch:72,bearing:-28,zoom:zoom+0.3,transitionDuration:3200}; deckgl.setProps({initialViewState:VIEW});},3000);
}
const deckgl = new DeckGL({
  container:'map', mapLib: maplibregl, mapStyle:BASE.esri,
  initialViewState:VIEW, controller:{maxPitch:80,inertia:true,dragRotate:true,touchRotate:true,keyboard:true},
  // 사용자가 잡으면 회전·연출을 즉시 멈추고 손에 맡긴다
  onViewStateChange:({viewState,interactionState})=>{VIEW=viewState; const u=interactionState||{}; if(u.isDragging||u.isPanning||u.isRotating||u.isZooming){ if(spinning){spinning=false;$('spin').textContent='회전';} clearTimeout(camT); }},
  getTooltip:({object})=>object&&object.hpid?{html:`<b>${object.name}</b><br>${object.grade}<br>z ${object.z} · 중증 가능 ${object.severeY}/28<br>응급실 ${object.hasBeds?(object.hvec===null?'미상':object.hvec)+' / '+(object.er_cap??'?'):'데이터 없음'}`,
    style:{background:'rgba(12,16,34,.95)',color:'#f2f1ec',fontSize:'12px',fontFamily:css('--font'),border:'1px solid #2b2d45',padding:'6px 8px'}}:null,
  onClick:info=>{ if(info.layer&&info.object&&info.object.hpid) return; if(!info.coordinate) return;
    const [lng,lat]=info.coordinate;
    const t=+$('time').value; addPatient('지도 클릭',+$('ktas').value,Math.round(t),lat,lng); $('scn').value='custom'; recompute(t); }
});
// 바탕지도(MapLibre)의 최대 기울기를 deck와 맞춘다. 기본 60°라 그 위로는 바탕만 멈춰 기둥이 어긋났다.
{ const m=deckgl.getMapboxMap(); if(m&&m.setMaxPitch) m.setMaxPitch(85); }
const shortName=n=>n.replace(/^(학교법인|의료법인|재단법인)[가-힣]*?(학원|재단)\s*/,'').replace(/^(의료법인|재단법인)\s*/,'').replace(/의과대학부속|의과대학/g,'').replace(/대학교/g,'대').replace(/서울특별시|한국보훈복지의료공단 |성심의료재단|성애의료재단|가톨릭대/g,'').replace(/\(.*\)$/,'').slice(0,10);
const HS=()=>+$('hs').value;
// 높이 변환: z(2~5)를 그대로 쓰면 기둥이 다 비슷해 보여서, 바닥(1.7)부터의 차이를 지수로 벌린다
const ZH=z=>Math.pow(Math.max(0.15,z-1.7),+$('zexp').value);
const gCol=g=>rgb(css('--g'+g)), kCol=k=>rgb(css('--k'+k));
let animTick=0;
const ADD={blend:true,blendFunc:[770,1,770,1],depthTest:false};
function layers(t){
  const hs=HS(), rise=Math.min(1,(performance.now()-riseT0)/1800), ease=1-Math.pow(1-rise,3);
  const pulse=0.5+0.5*Math.sin(performance.now()/350);
  const L=[], live=LIVE;
  // 병원 노드 (첫 3D 화면 방식): 높이에 뜬 점 + 바닥까지 가는 가는 선 + 바닥 그림자
  const top=h=>[h.lng,h.lat,ZH(h.z)*hs*ease];
  const hcol=h=>full(h)?[255,80,80]:gCol(h.g).slice(0,3);
  if(HMODE==='sphere'){
    // 순수 3D 모델: 병원 = 역량 높이에 뜬 구 (등급이 높을수록 크다). 기둥·줄기·빛 없음
    L.push(new SimpleMeshLayer({id:'h-sphere',data:live,mesh:SPHERE,material:{ambient:0.35,diffuse:0.7,shininess:40,specularColor:[255,255,255]},getPosition:top,getColor:h=>[...hcol(h),255],getScale:h=>{const r=h.g>=4?170:h.g===3?130:h.g===2?95:70;return [r,r,r];},pickable:true,updateTriggers:{getPosition:[ease]}}));
    L.push(new ScatterplotLayer({id:'h-shadow',data:live,radiusUnits:'meters',getRadius:50,radiusMinPixels:1.5,getPosition:h=>[h.lng,h.lat,0],getFillColor:h=>[...hcol(h),70],parameters:{depthTest:false}}));
    L.push(new ScatterplotLayer({id:'h-dead',data:DEAD,radiusUnits:'meters',getRadius:70,radiusMinPixels:3,getPosition:h=>[h.lng,h.lat,0],getFillColor:[0,0,0,0],stroked:true,getLineColor:[150,150,150,170],lineWidthMinPixels:1,pickable:true}));
    L.push(new TextLayer({id:'h-name',data:live.filter(h=>h.g>=4||(VIEW.zoom>=9.5&&h.g>=3)),getPosition:top,getText:h=>shortName(h.name),getSize:11,characterSet:'auto',getColor:[242,241,236,230],getPixelOffset:[0,-18],fontFamily:css('--font'),background:true,getBackgroundColor:[10,16,36,150],backgroundPadding:[3,1],parameters:{depthTest:false},updateTriggers:{getPosition:[ease]}}));
  } else {
  L.push(new LineLayer({id:'h-stem',data:live,getSourcePosition:h=>[h.lng,h.lat,0],getTargetPosition:top,getColor:h=>[...hcol(h),110],getWidth:1,widthUnits:'pixels',parameters:ADD,updateTriggers:{getTargetPosition:[ease]}}));
  L.push(new ScatterplotLayer({id:'h-shadow',data:live,radiusUnits:'meters',getRadius:60,radiusMinPixels:2,getPosition:h=>[h.lng,h.lat,0],getFillColor:h=>[...hcol(h),120],parameters:{depthTest:false}}));
  L.push(new ScatterplotLayer({id:'h-glow',data:live,radiusUnits:'meters',getRadius:300+pulse*40,radiusMinPixels:9,getPosition:top,getFillColor:h=>[...hcol(h),60],parameters:ADD,updateTriggers:{getRadius:[animTick],getPosition:[ease]}}));
  L.push(new ScatterplotLayer({id:'h-node',data:live,radiusUnits:'meters',getRadius:h=>h.g>=4?120:h.g===3?95:70,radiusMinPixels:h=>h.g>=4?6:h.g===3?4.5:3,getPosition:top,getFillColor:h=>[...hcol(h),255],stroked:true,getLineColor:[255,255,255,200],lineWidthMinPixels:1.2,pickable:true,parameters:{depthTest:false},updateTriggers:{getPosition:[ease]}}));
  L.push(new ScatterplotLayer({id:'h-dead',data:DEAD,radiusUnits:'meters',getRadius:70,radiusMinPixels:3,getPosition:h=>[h.lng,h.lat,0],getFillColor:[0,0,0,0],stroked:true,getLineColor:[150,150,150,170],lineWidthMinPixels:1,pickable:true}));
  L.push(new TextLayer({id:'h-name',data:live.filter(h=>h.g>=4||(VIEW.zoom>=9.5&&h.g>=3)),getPosition:top,getText:h=>shortName(h.name),getSize:11,characterSet:'auto',getColor:[242,241,236,230],getPixelOffset:[0,-16],fontFamily:css('--font'),background:true,getBackgroundColor:[10,16,36,150],backgroundPadding:[3,1],parameters:{depthTest:false},updateTriggers:{getPosition:[ease]}}));
  }
  if(HMODE==='beams'){
    const beam=(id,r,a,res)=>new ColumnLayer({id,data:live,diskResolution:res,radius:r,extruded:true,elevationScale:hs*ease,getPosition:h=>[h.lng,h.lat],getElevation:h=>ZH(h.z),getFillColor:h=>full(h)?[255,60,60,a]:[...gCol(h.g).slice(0,3),a],getLineColor:[0,0,0,0],material:false,pickable:id==='beam-core',parameters:ADD});
    L.push(beam('beam-halo',150,10,12)); L.push(beam('beam-mid',60,38,12)); L.push(beam('beam-core',18,230,10));
    L.push(new ScatterplotLayer({id:'top-halo',data:live,radiusUnits:'meters',getRadius:420+pulse*90,getPosition:top,getFillColor:h=>full(h)?[255,60,60,45]:[...gCol(h.g).slice(0,3),55],parameters:ADD,updateTriggers:{getRadius:[animTick],getPosition:[ease]}}));
  }
  if(!RES) return L;
  const dwell=RES.dwell, webs=[], gone=[], trails=[], lights=[], occ={}, ups=[], airWebs=[], airGone=[], airLights=[], stems=[];
  const air=$('air').checked;
  P.forEach(p=>{
    const segs=RES.hist[p.id]||[];
    segs.forEach(s=>{
      if(s.tStart>t) return;
      const ended=s.tEnd!==null&&s.tEnd<=t;
      if(ended){ const f=(s.tEnd-s.tStart)/Math.max(1e-6,s.tArr-s.tStart); const pf=pathFrom(s,f); gone.push({path:pf.map(c=>[c[0],c[1],0])}); if(air){const q=posAt(s,s.tEnd); airGone.push({a:[q.lng,q.lat,ZH(q.z)*hs],b:[s.h.lng,s.h.lat,ZH(s.h.z)*hs]});} return; }
      const ts=s.cum.map(u=>s.tStart+u*(s.tArr-s.tStart));
      trails.push({path:s.coords.map(c=>[c[0],c[1],0]),timestamps:ts,k:p.k});
      if(t<s.tArr){
        const a=posAt(s,t); const pf=pathFrom(s,a.f);
        webs.push({path:pf.map(c=>[c[0],c[1],0]),k:p.k,forced:!!RES.forced[p.id]});
        if(air){ airWebs.push({a:[a.lng,a.lat,ZH(a.z)*hs],b:[s.h.lng,s.h.lat,ZH(s.h.z)*hs],k:p.k,forced:!!RES.forced[p.id]}); airLights.push({pos:[a.lng,a.lat,ZH(a.z)*hs],k:p.k}); stems.push({a:[a.lng,a.lat,0],b:[a.lng,a.lat,ZH(a.z)*hs],k:p.k}); }
        ups.push({a:[s.h.lng,s.h.lat,0],b:[s.h.lng,s.h.lat,ZH(s.h.z)*hs],k:p.k});
        lights.push({pos:[a.lng,a.lat,0],k:p.k,label:'#'+p.id+' K'+p.k});
      } else if(t<s.tArr+dwell){(occ[s.h.hpid]??=[]).push(p.id);}
    });
    if(p.t0<=t&&!segs.some(s=>s.tStart<=t)){ lights.push({pos:[p.lng,p.lat,0],k:p.k,label:'#'+p.id+' K'+p.k}); if(air){airLights.push({pos:[p.lng,p.lat,ZH(p.z)*hs],k:p.k}); stems.push({a:[p.lng,p.lat,0],b:[p.lng,p.lat,ZH(p.z)*hs],k:p.k});} }
  });
  L.push(new PathLayer({id:'gone',data:gone,getPath:d=>d.path,getColor:[124,123,116,120],getWidth:1.5,widthUnits:'pixels',parameters:{depthTest:false}}));
  L.push(new PathLayer({id:'webs',data:webs,getPath:d=>d.path,getColor:d=>[...kCol(d.k).slice(0,3),d.forced?60:140],getWidth:d=>d.forced?1:2,widthUnits:'pixels',parameters:{depthTest:false}}));
  L.push(new TripsLayer({id:'trails',data:trails,getPath:d=>d.path,getTimestamps:d=>d.timestamps,getColor:d=>kCol(d.k).slice(0,3),widthMinPixels:4,trailLength:5,currentTime:t,opacity:.8,capRounded:true,jointRounded:true,fadeTrail:true,parameters:ADD}));
  L.push(new LineLayer({id:'air-gone',data:airGone,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:[150,150,150,110],getWidth:1.2,widthUnits:'pixels',parameters:{depthTest:false}}));
  L.push(new LineLayer({id:'air-glow',data:airWebs,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:d=>[...kCol(d.k).slice(0,3),70],getWidth:10,widthUnits:'pixels',parameters:ADD}));
  L.push(new LineLayer({id:'air',data:airWebs,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:d=>[...kCol(d.k).slice(0,3),d.forced?110:240],getWidth:d=>d.forced?1.5:3,widthUnits:'pixels',parameters:{depthTest:false}}));
  L.push(new LineLayer({id:'pstems',data:stems,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:d=>[...kCol(d.k).slice(0,3),130],getWidth:1.5,widthUnits:'pixels',parameters:ADD}));
  L.push(new ScatterplotLayer({id:'air-light-glow',data:airLights,radiusUnits:'meters',getRadius:200+pulse*50,getPosition:d=>d.pos,getFillColor:d=>[...kCol(d.k).slice(0,3),100],parameters:ADD,updateTriggers:{getRadius:[animTick]}}));
  L.push(new ScatterplotLayer({id:'air-light',data:airLights,radiusUnits:'meters',getRadius:55,radiusMinPixels:5,getPosition:d=>d.pos,getFillColor:[255,255,255,245],stroked:true,getLineColor:d=>kCol(d.k),lineWidthMinPixels:2,parameters:{depthTest:false}}));
  L.push(new LineLayer({id:'ups',data:ups,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:d=>[...kCol(d.k).slice(0,3),160],getWidth:2,widthUnits:'pixels',parameters:ADD}));
  const oh=Object.entries(occ).map(([id,ids])=>({h:hp(id),n:ids.length}));
  L.push(new ScatterplotLayer({id:'occ',data:oh,radiusUnits:'meters',getRadius:d=>200+d.n*90+pulse*60,getPosition:d=>[d.h.lng,d.h.lat,ZH(d.h.z)*hs],getFillColor:[79,209,255,0],stroked:true,getLineColor:[79,209,255,200],lineWidthMinPixels:2,parameters:{depthTest:false},updateTriggers:{getRadius:[animTick]}}));
  L.push(new TextLayer({id:'occ-txt',data:oh,getPosition:d=>[d.h.lng,d.h.lat,ZH(d.h.z)*hs],getText:d=>d.n+'명 점유',getSize:12,characterSet:'auto',getColor:[79,209,255,255],getPixelOffset:[0,-36],fontFamily:css('--font'),background:true,getBackgroundColor:[10,16,36,170],backgroundPadding:[4,2],parameters:{depthTest:false}}));
  const cl=RES.events.filter(e=>e.type==='c'&&e.t<=t&&t-e.t<3).map(e=>({h:hp(e.hpid),age:t-e.t}));
  L.push(new ScatterplotLayer({id:'clash',data:cl,radiusUnits:'meters',getRadius:d=>260+d.age*120+pulse*80,getPosition:d=>[d.h.lng,d.h.lat,ZH(d.h.z)*hs],getFillColor:[255,59,59,0],stroked:true,getLineColor:d=>[255,59,59,Math.round(230*(1-d.age/3))],lineWidthMinPixels:3,parameters:{depthTest:false},updateTriggers:{getRadius:[animTick],getLineColor:[t]}}));
  L.push(new ScatterplotLayer({id:'light-glow',data:lights,radiusUnits:'meters',getRadius:160+pulse*40,getPosition:d=>d.pos,getFillColor:d=>[...kCol(d.k).slice(0,3),90],parameters:ADD,updateTriggers:{getRadius:[animTick]}}));
  L.push(new ScatterplotLayer({id:'light',data:lights,radiusUnits:'meters',getRadius:45,radiusMinPixels:4,getPosition:d=>d.pos,getFillColor:d=>kCol(d.k),stroked:true,getLineColor:[255,255,255,230],lineWidthMinPixels:1.5,parameters:{depthTest:false}}));
  L.push(new TextLayer({id:'light-txt',data:lights,getPosition:d=>d.pos,getText:d=>d.label,getSize:12,characterSet:'auto',getColor:[242,241,236,255],getPixelOffset:[0,-16],fontFamily:css('--mono'),background:true,getBackgroundColor:[10,16,36,170],backgroundPadding:[4,2],parameters:{depthTest:false}}));
  return L;
}
function render(){ const t=+$('time').value; $('tv').textContent=t.toFixed(0);
  if(spinning){ VIEW={...VIEW,bearing:(VIEW.bearing+0.12)%360,transitionDuration:0}; deckgl.setProps({layers:layers(t),initialViewState:VIEW}); } else deckgl.setProps({layers:layers(t)}); }
(function loop(){ animTick++; render(); requestAnimationFrame(loop); })();

function renderSide(t){
  if(!RES) return;
  const E=RES.events, nC=E.filter(e=>e.type==='c').length, nY=E.filter(e=>e.type==='y').length, nF=Object.keys(RES.forced).length;
  const moving=P.filter(p=>{const s=RES.cur[p.id];return s&&p.t0<=t&&t<s.tArr;}).length;
  const occ=P.filter(p=>{const s=RES.cur[p.id];return s&&s.tArr<=t&&t<s.tArr+RES.dwell;}).length;
  $('sum').textContent=P.length?`환자 ${P.length}명 · 충돌 ${nC}건 · 줄 바꿈 ${nY}회${nF?' · 초과 '+nF+'명':''} · 지금 ${t.toFixed(0)}분: 이동 중 ${moving}명, 점유 ${occ}명`:'환자를 추가하거나 지도를 클릭하세요.';
  const L=$('log'); L.innerHTML=''; let lastPast=null;
  E.forEach(e=>{const v=document.createElement('div'); const past=e.t<=t;
    v.className='ev '+e.type+(past?'':' future'); v.innerHTML=`<span class="tm">${e.t.toFixed(0)}분</span><span>${e.text}</span>`; L.appendChild(v); if(past) lastPast=v;});
  if(lastPast){lastPast.classList.add('now'); lastPast.scrollIntoView({block:'nearest'});}
}
function renderTicks(){
  const k=$('ticks'); k.innerHTML=''; const max=+$('time').max;
  RES.events.filter(e=>e.type==='c'||e.type==='s').forEach(e=>{const s=document.createElement('span'); s.style.left=(e.t/max*100)+'%'; s.className=e.type==='c'?'ev':''; s.textContent=e.type==='c'?'✕':'·'; k.appendChild(s);});
}
function renderList(){
  const ul=$('plist'); ul.innerHTML='';
  P.slice().sort((a,b)=>a.t0-b.t0||a.id-b.id).forEach(p=>{const li=document.createElement('li');
    li.innerHTML=`<span class="id">#${p.id}</span><span class="pill k" style="--c:var(--k${p.k})">K${p.k}</span><span title="${p.text||''}">${p.site}${p.cond&&p.cond!=='general'?' · '+COND[p.cond].label:''}${p.text?' · '+p.text:''}</span><span class="tm">${p.t0}분</span><button>빼기</button>`;
    li.querySelector('button').onclick=()=>{P=P.filter(q=>q.id!==p.id);$('scn').value='custom';recompute();}; ul.appendChild(li);});
}
let lastSideT=-1;
function tick(){ const t=+$('time').value; if(t!==lastSideT){lastSideT=t; renderSide(t);} }
function stopPlay(){clearInterval(timer);timer=null;$('play').textContent='▶ 재생';}
function recompute(keepT){
  stopPlay(); renderList(); $('busy').style.display='block';
  setTimeout(()=>{ const t0=performance.now(); RES=solve(); const ms=performance.now()-t0; $('busy').style.display='none';
    $('time').max=Math.ceil(RES.tMax); $('time').value=keepT!==undefined?Math.min(keepT,RES.tMax):0;
    renderTicks(); lastSideT=-1; tick();
    $('etanote').textContent=G?`병원 ${H.length}곳(병상 데이터 ${LIVE.length}). 경로: 이 브라우저 안의 다익스트라 (OSM 전국 도로 ${G.n.toLocaleString()} 노드, 등급별 속도 80/55/45/35/25 km/h). 마지막 계산 ${ms.toFixed(0)} ms, 탐색 ${RES.settled.toLocaleString()} 노드.`:'도로 그래프 없음 → 직선 추정.'; },20);
}
$('scn').addEventListener('change',()=>{loadScenario();recompute();});
$('add').onclick=()=>{addPatient($('site').value,+$('ktas').value,Math.max(0,+$('t0').value||0));P[P.length-1].cond=$('cond').value;$('scn').value='custom';recompute();};
$('vadd').onclick=()=>{ let sum; try{ sum=JSON.parse($('vsum').value); }catch(e){ $('vmsg').textContent='JSON을 읽을 수 없음'; return; }
  const v=voiceToPatient(sum); addPatient($('site').value,v.k,Math.max(0,+$('t0').value||0)); const p=P[P.length-1]; p.cond=v.cond; p.text=v.text;
  $('vmsg').textContent=`#${p.id} K${v.k} · ${COND[v.cond].label} · ${v.text}`; $('scn').value='custom'; recompute(); };
$('rn').addEventListener('input',()=>{$('rnv').textContent=$('rn').value;});
$('rw').addEventListener('input',()=>{$('rwv').textContent=$('rw').value;});
$('rgen').onclick=()=>{randomPatients(+$('rn').value,false);recompute();};
$('radd').onclick=()=>{randomPatients(+$('rn').value,true);recompute();};
$('clear').onclick=()=>{P=[];nextId=1;$('scn').value='custom';recompute();};
$('rise').onclick=()=>{riseT0=performance.now();};
document.querySelectorAll('[data-cam]').forEach(b=>b.onclick=()=>{spinning=false;$('spin').textContent='회전';goCam(CAMS[b.dataset.cam]);});
$('spin').onclick=()=>{spinning=!spinning;$('spin').textContent=spinning?'회전 멈춤':'회전';};
[['tau','tauv'],['cap','capv'],['dwell','dwellv'],['lam','lamv'],['mu2','mu2v'],['mu3','mu3v'],['sh','shv']].forEach(([id,v])=>$(id).addEventListener('input',()=>{$(v).textContent=$(id).value;recompute(+$('time').value);}));
$('hs').addEventListener('input',()=>{$('hv').textContent=$('hs').value;});
$('zexp').addEventListener('input',()=>{$('zexpv').textContent=$('zexp').value;});
$('base').addEventListener('change',()=>{deckgl.setProps({mapStyle:BASE[$('base').value]});});
$('dyn').addEventListener('change',()=>recompute(+$('time').value));
$('wload').addEventListener('change',()=>recompute(+$('time').value));
document.querySelectorAll('[data-hmode]').forEach(b=>b.addEventListener('click',()=>{HMODE=b.dataset.hmode; document.querySelectorAll('[data-hmode]').forEach(x=>x.classList.toggle('on',x===b));}));
document.querySelector('[data-hmode="node"]').classList.add('on');
$('time').addEventListener('input',()=>{stopPlay();tick();});
$('end').onclick=()=>{stopPlay();$('time').value=$('time').max;tick();};
$('play').onclick=()=>{ if(timer){stopPlay();return;} const s=$('time'); if(+s.value>=+s.max) s.value=0; $('play').textContent='❚❚ 멈춤'; if(+s.value===0) choreograph();
  timer=setInterval(()=>{if(+s.value>=+s.max){stopPlay();return;} s.value=Math.min(+s.max,+s.value+0.25); tick();},100); };
loadScenario(); recompute();
</script>
</body></html>
'''
out.write_text(html.replace('__DATA__', data), encoding='utf-8')
print('wrote', out)
