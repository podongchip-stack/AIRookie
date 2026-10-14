// 거미줄 3D 화면 — 그리기와 조작만 한다. 계산(줄 길이·충돌·양보·재투척·경로)은 전부 서버의 파이썬 엔진(engine/)이
// 하고, 이 파일은 그 결과(세그먼트·이벤트)를 deck.gl + MapLibre로 그린다. 예전 map.html의 그리기 코드를 그대로 가져왔고,
// 엔진 호출만 fetch(api/solve 등)로 바꿨다. 주소는 전부 상대 경로라 /spider/ 접두어가 바뀌어도 된다.
const $ = id=>document.getElementById(id);
const css = n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgb = (hex,a=255)=>{const h=hex.replace('#','');return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16),a];};
const KTAS_Z = {1:4,2:3,3:2,4:1,5:1};
const COND_LABEL = {general:'일반',stemi:'심근경색',stroke:'뇌졸중',trauma:'중증외상'};
const full = h=>h.hasBeds && h.hvec!==null && h.hvec<=0;
const R=6371, toR=d=>d*Math.PI/180;
function straightKm(aLat,aLng,bLat,bLng){
  const dLat=toR(bLat-aLat),dLng=toR(bLng-aLng);
  const a=Math.sin(dLat/2)**2+Math.cos(toR(aLat))*Math.cos(toR(bLat))*Math.sin(dLng/2)**2;
  return 2*R*Math.asin(Math.sqrt(a));
}

// ---------- 서버 ----------
let H=[], LIVE=[], DEAD=[], HMAP=new Map(), META=null, ENGINE_INFO=null;
const hp = id=>HMAP.get(id);
async function api(path, body){
  const r = body===undefined ? await fetch(path) : await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){ let msg=r.status+' '+r.statusText; try{ msg=(await r.json()).error||msg; }catch(e){} throw new Error(msg); }
  return r.json();
}
function showBusy(text, err){ const b=$('busy'); b.textContent=text; b.classList.toggle('err',!!err); b.style.display='block'; }
function hideBusy(){ $('busy').style.display='none'; $('busy').classList.remove('err'); }
// 서버 결과를 화면 구조로 — 세그먼트의 hpid를 병원 객체로, cur의 번호를 hist의 세그먼트로 잇는다
function linkResult(j){
  const hist={}, cur={};
  for(const [pid,segs] of Object.entries(j.hist)) hist[pid]=segs.map(s=>({...s,h:hp(s.hpid)}));
  for(const [pid,i] of Object.entries(j.cur)) cur[pid]=hist[pid][i];
  return {cur,hist,forced:j.forced,events:j.events,tMax:j.tMax,dwell:j.dwell,settled:j.settled,ms:j.ms};
}
function readParams(){ return {tau:+$('tau').value,cap:+$('cap').value,dwell:+$('dwell').value,mu2:+$('mu2').value,mu3:+$('mu3').value,lam:+$('lam').value,start_hour:+$('sh').value,dyn:$('dyn').checked,wload:$('wload').checked}; }

// ---------- 환자·시나리오 ----------
let P=[], nextId=1, RES=null, timer=null, riseT0=performance.now();
// 'sim' = 환자 떨어뜨리기(가상, 이 화면이 환자를 만들고 서버 엔진이 푼다) / 'live' = hub의 실제 사건을 그대로 그린다(live.js)
let MODE='sim';
function addPatient(site,k,t0,lat,lng){
  if(lat===undefined){[lat,lng]=META.sites[site];}
  const id=nextId++;
  const n=P.filter(p=>p.site===site).length, ang=n*2.1, r=n?0.0012:0;
  P.push({id,site,k,t0,lat:lat+r*Math.sin(ang),lng:lng+r*Math.cos(ang)*1.25,z:KTAS_Z[k]});
}
function loadScenario(){ P=[]; nextId=1; const sc=META.scenarios.find(s=>s.id===$('scn').value); (sc?sc.patients:[]).forEach(([s,k,t])=>addPatient(s,k,t)); }
// 완전 랜덤 — 위치·KTAS·질환군은 서버가 뽑고(시드 없음), 번호·자리 비끼기는 여기서
async function randomPatients(n,add){
  const list = await api('api/random',{n,width:+$('rw').value,scope:$('rs').value,kdist:$('rk').value});
  if(!add){P=[];nextId=1;}
  list.forEach(r=>{ addPatient('무작위',r.k,r.t0,r.lat,r.lng); P[P.length-1].cond=r.cond; });
  $('scn').value='custom';
}
function cumul(coords){ const d=[0]; for(let i=1;i<coords.length;i++) d.push(d[i-1]+straightKm(coords[i-1][1],coords[i-1][0],coords[i][1],coords[i][0])); const T=d[d.length-1]||1; return d.map(x=>x/T); }
function posAt(seg,t){
  const f=Math.max(0,Math.min(1,(t-seg.tStart)/Math.max(1e-6,seg.tArr-seg.tStart)));
  const c=seg.coords, u=seg.cum; let i=1; while(i<u.length-1&&u[i]<f) i++;
  const a=c[i-1], b=c[i], w=(f-u[i-1])/Math.max(1e-9,u[i]-u[i-1]);
  return {lng:a[0]+(b[0]-a[0])*w, lat:a[1]+(b[1]-a[1])*w, z:seg.from.z+(seg.h.z-seg.from.z)*f, f, i};
}
function pathFrom(seg,f){ const p=posAt(seg,seg.tStart+f*(seg.tArr-seg.tStart)); return [[p.lng,p.lat],...seg.coords.slice(p.i)]; }

// ---------- 지도 ----------
const BASE={
  sat:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:19,attribution:'Esri, Maxar, Earthstar Geographics'}},
    layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.55,'raster-saturation':-.35,'raster-contrast':.1}}]},
  street:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:19,attribution:'Esri, HERE, Garmin, © OpenStreetMap contributors'}},
    layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.45,'raster-saturation':-.6,'raster-contrast':.15}}]},
  esri:{version:8,sources:{b:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:16,attribution:'Esri, HERE, Garmin, © OpenStreetMap contributors'}},layers:[{id:'b',type:'raster',source:'b'}]},
  osm:{version:8,sources:{b:{type:'raster',tiles:['https://tile.openstreetmap.de/{z}/{x}/{y}.png'],tileSize:256,maxzoom:18,attribution:'© OpenStreetMap contributors (openstreetmap.de)'}},layers:[{id:'b',type:'raster',source:'b',paint:{'raster-brightness-max':.42,'raster-saturation':-.7,'raster-contrast':.15}}]}};
const {DeckGL, ColumnLayer, ScatterplotLayer, LineLayer, PathLayer, TripsLayer, TextLayer, SimpleMeshLayer} = deck;
// 병원 표시 방식: sphere(3D 구만) / node(공중 노드+줄기) / beams(빛기둥)
let HMODE='sphere';
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
  onClick:info=>{ if(!META||MODE==='live') return; if(info.layer&&info.object&&info.object.hpid) return; if(!info.coordinate) return;
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
  // 병원 노드: 높이에 뜬 점 + 바닥까지 가는 가는 선 + 바닥 그림자
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
  if(MODE==='live') return L.concat(liveLayers(t));
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
    li.innerHTML=`<span class="id">#${p.id}</span><span class="pill k" style="--c:var(--k${p.k})">K${p.k}</span><span title="${p.text||''}">${p.site}${p.cond&&p.cond!=='general'?' · '+COND_LABEL[p.cond]:''}${p.text?' · '+p.text:''}</span><span class="tm">${p.t0}분</span><button>빼기</button>`;
    li.querySelector('button').onclick=()=>{P=P.filter(q=>q.id!==p.id);$('scn').value='custom';recompute();}; ul.appendChild(li);});
}
let lastSideT=-1;
function tick(){ if(MODE==='live') return; const t=+$('time').value; if(t!==lastSideT){lastSideT=t; renderSide(t);} }
function stopPlay(){clearInterval(timer);timer=null;$('play').textContent='▶ 재생';}
// 계산은 서버로 — 환자 목록과 슬라이더 값을 보내고 결과를 받아 그린다. 늦게 온 응답이 새 요청 결과를 덮지 않게 번호를 센다.
let solveSeq=0;
async function recompute(keepT){
  if(MODE==='live'){ scheduleSuggest(); return; }   // 실시간 모드에선 슬라이더가 거미줄 제안 계산에만 쓰인다
  stopPlay(); renderList(); showBusy('경로 계산 중…');
  const seq=++solveSeq; const t0=performance.now();
  let j;
  try{ j=await api('api/solve',{patients:P,params:readParams()}); }
  catch(e){ showBusy('서버 계산 실패: '+e.message, true); return; }
  if(seq!==solveSeq) return;
  const ms=performance.now()-t0; hideBusy(); RES=linkResult(j);
  $('time').max=Math.ceil(RES.tMax); $('time').value=keepT!==undefined?Math.min(keepT,RES.tMax):0;
  renderTicks(); lastSideT=-1; tick();
  const g=ENGINE_INFO||{};
  $('etanote').textContent=g.roadNodes?`병원 ${H.length}곳(병상 데이터 ${LIVE.length}). 경로: 서버의 파이썬 엔진(OSM 전국 도로 ${g.roadNodes.toLocaleString()} 노드, scipy 다익스트라, 등급별 속도 ${(g.speedKmh||[]).join('/')} km/h). 마지막 계산 ${ms.toFixed(0)} ms(서버 ${RES.ms} ms), 탐색 ${RES.settled.toLocaleString()} 노드.`:'도로 그래프 없음 → 직선 추정.';
}
$('scn').addEventListener('change',()=>{loadScenario();recompute();});
$('add').onclick=()=>{addPatient($('site').value,+$('ktas').value,Math.max(0,+$('t0').value||0));P[P.length-1].cond=$('cond').value;$('scn').value='custom';recompute();};
$('vadd').onclick=async()=>{ let sum; try{ sum=JSON.parse($('vsum').value); }catch(e){ $('vmsg').textContent='JSON을 읽을 수 없음'; return; }
  let v; try{ v=await api('api/voice',{summary:sum}); }catch(e){ $('vmsg').textContent='서버 오류: '+e.message; return; }
  addPatient($('site').value,v.k,Math.max(0,+$('t0').value||0)); const p=P[P.length-1]; p.cond=v.cond; p.text=v.text;
  $('vmsg').textContent=`#${p.id} K${v.k} · ${COND_LABEL[v.cond]} · ${v.text}`; $('scn').value='custom'; recompute(); };
$('rn').addEventListener('input',()=>{$('rnv').textContent=$('rn').value;});
$('rw').addEventListener('input',()=>{$('rwv').textContent=$('rw').value;});
$('rgen').onclick=async()=>{ try{ await randomPatients(+$('rn').value,false); }catch(e){ showBusy('서버 오류: '+e.message,true); return; } recompute(); };
$('radd').onclick=async()=>{ try{ await randomPatients(+$('rn').value,true); }catch(e){ showBusy('서버 오류: '+e.message,true); return; } recompute(); };
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
document.querySelector('[data-hmode="sphere"]').classList.add('on');
$('time').addEventListener('input',()=>{stopPlay();tick();});
$('end').onclick=()=>{stopPlay();$('time').value=$('time').max;tick();};
$('play').onclick=()=>{ if(timer){stopPlay();return;} const s=$('time'); if(+s.value>=+s.max) s.value=0; $('play').textContent='❚❚ 멈춤'; if(+s.value===0) choreograph();
  timer=setInterval(()=>{if(+s.value>=+s.max){stopPlay();return;} s.value=Math.min(+s.max,+s.value+0.25); tick();},100); };

// ---------- 모드 전환 ----------
// 실시간 모드: 가상 환자·시계를 감추고 hub에 붙는다(live.js). 가상 모드로 돌아오면 hub 연결을 끊고 마지막 시나리오를 다시 그린다.
// 아이패드 앱은 /spider/?mode=live 로 열어 바로 실시간으로 시작한다.
function setMode(m){
  if(m===MODE) return;
  MODE=m; stopPlay();
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===m));
  $('simctl').style.display=m==='live'?'none':'';
  $('livepanel').style.display=m==='live'?'':'none';
  $('clock').style.display=m==='live'?'none':'';
  $('right').style.display='';
  if(m==='live'){ RES=null; hideBusy(); hubConnect(); renderLivePanel(); renderLiveSide(); $('etanote').textContent='실시간: 병원·사건·구급차 위치는 hub(관제 지도와 같은 소켓)에서, 거미줄 제안만 이 서버의 파이썬 엔진에서.'; }
  else { hubDisconnect(); lastSideT=-1; recompute(); }
  const u=new URL(location.href); if(m==='live') u.searchParams.set('mode','live'); else u.searchParams.delete('mode'); history.replaceState(null,'',u);
}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('suggest').addEventListener('change',()=>{ if(!$('suggest').checked){ HUB.suggest={}; renderLivePanel(); } else scheduleSuggest(); });

// ---------- 시작: 서버에서 병원·시나리오를 받은 뒤 첫 시나리오를 돌린다 ----------
(async function init(){
  showBusy('서버에서 병원 목록 받는 중…');
  try{
    [META, H] = await Promise.all([api('api/meta'), api('api/hospitals')]);
  }catch(e){ showBusy('서버에 연결할 수 없습니다: '+e.message, true); return; }
  ENGINE_INFO=META.engine; HMAP=new Map(H.map(h=>[h.hpid,h])); LIVE=H.filter(h=>h.hasBeds); DEAD=H.filter(h=>!h.hasBeds);
  $('scn').innerHTML=META.scenarios.map(s=>`<option value="${s.id}">${s.label}</option>`).join('');
  $('site').innerHTML=Object.keys(META.sites).map(s=>`<option>${s}</option>`).join('');
  riseT0=performance.now();
  loadScenario();
  if(new URLSearchParams(location.search).get('mode')==='live') setMode('live'); else recompute();
})();
