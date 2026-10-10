"""남한 OSM pbf(data/south-korea-latest.osm.pbf)에서 도로 그래프를 뽑아 roads_data.js로 만든다.
전국: 3차로(tertiary) 이상 전부. 골목(residential·unclassified·living_street): 병원 반경 4 km 안만.
노드는 교차점·끝점은 반드시, 그 사이 모양점은 15 m 허용 오차로 단순화해 줄인다.
출력은 <script src="roads_data.js">로 읽히는 JS (file://에서도 열리도록 fetch 대신 스크립트).

실행: conda activate rookie_info; python build_roads_kr.py
"""
import json, base64, math, pathlib, time, sys
import numpy as np
import osmium
here = pathlib.Path(__file__).parent
PBF = here / 'data' / 'south-korea-latest.osm.pbf'  # https://download.geofabrik.de/asia/south-korea-latest.osm.pbf (약 290 MB, 커밋 안 함)
BBOX = (124.5, 131.0, 33.0, 38.7)  # lng0, lng1, lat0, lat1
MAJOR = {'motorway':0,'trunk':0,'motorway_link':0,'trunk_link':0,'primary':1,'primary_link':1,
         'secondary':2,'secondary_link':2,'tertiary':3,'tertiary_link':3}
MINOR = {'residential':4,'unclassified':4,'living_street':4}
MINOR_RADIUS_KM = 4.0
SIMPLIFY_M = 15.0

hosp = json.load(open(here / 'hospitals_xyz.json', encoding='utf-8'))
hl = np.array([[h['lat'], h['lng']] for h in hosp])
# 병원 근처 판정용 격자 (0.05° ≈ 5 km)
cellset = set()
for la, lo in hl:
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cellset.add((int(la / 0.05) + dy, int(lo / 0.05) + dx))
def near_hospital(lat, lng):
    if (int(lat / 0.05), int(lng / 0.05)) not in cellset: return False
    d = np.hypot((hl[:, 0] - lat) * 111.0, (hl[:, 1] - lng) * 88.8)
    return bool(d.min() <= MINOR_RADIUS_KM)

class Pass1(osmium.SimpleHandler):
    """선택할 길을 고르고 노드 사용 횟수를 센다."""
    def __init__(self):
        super().__init__(); self.use = {}; self.ways = 0
    def way(self, w):
        hw = w.tags.get('highway')
        if hw in MAJOR: c = MAJOR[hw]
        elif hw in MINOR:
            c = MINOR[hw]
            try:
                n0 = w.nodes[len(w.nodes) // 2]; lat, lng = n0.lat, n0.lon
            except Exception:
                return
            if not near_hospital(lat, lng): return
        else: return
        self.ways += 1
        for n in w.nodes:
            self.use[n.ref] = self.use.get(n.ref, 0) + 1

def dp_keep(pts, keep, tol_m):
    """Douglas-Peucker: keep[i]=True인 점은 반드시 유지, 나머지는 허용 오차로 단순화."""
    n = len(pts)
    if n <= 2: return [True] * n
    out = keep[:]
    out[0] = out[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        # 구간 안의 고정점이 있으면 거기서 쪼갠다
        mid = next((i for i in range(a + 1, b) if out[i]), None)
        if mid is not None:
            stack.append((a, mid)); stack.append((mid, b)); continue
        if b - a < 2: continue
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        best, bi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L2 == 0: d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best: best, bi = d2, i
        if best > tol_m * tol_m:
            out[bi] = True; stack.append((a, bi)); stack.append((bi, b))
    return out

class Pass2(osmium.SimpleHandler):
    def __init__(self, use):
        super().__init__(); self.use = use
        self.idx = {}; self.npos = []; self.ncls = []; self.ndeg = []
        self.wn = []; self.starts = [0]; self.wcls = []
    def way(self, w):
        hw = w.tags.get('highway')
        if hw in MAJOR: c = MAJOR[hw]
        elif hw in MINOR:
            c = MINOR[hw]
            try:
                n0 = w.nodes[len(w.nodes) // 2];
                if not near_hospital(n0.lat, n0.lon): return
            except Exception: return
        else: return
        try:
            refs = [n.ref for n in w.nodes]; pts = [(n.lon * 88800.0, n.lat * 111000.0) for n in w.nodes]  # m 단위 평면
            ll = [(n.lat, n.lon) for n in w.nodes]
        except Exception:
            return
        keep = [self.use.get(r, 0) > 1 for r in refs]
        keep = dp_keep(pts, keep, SIMPLIFY_M)
        for i, r in enumerate(refs):
            if not keep[i]: continue
            k = self.idx.get(r)
            if k is None:
                k = len(self.npos); self.idx[r] = k; self.npos.append(ll[i]); self.ncls.append(c); self.ndeg.append(0)
            self.ncls[k] = min(self.ncls[k], c); self.ndeg[k] += 1
            self.wn.append(k)
        self.starts.append(len(self.wn)); self.wcls.append(c)

t0 = time.time()
p1 = Pass1(); p1.apply_file(str(PBF), locations=True)
print('pass1 ways', p1.ways, 'nodes', len(p1.use), f'{time.time()-t0:.0f}s')
p2 = Pass2(p1.use); p2.apply_file(str(PBF), locations=True)
print('pass2 ways', len(p2.wcls), 'nodes', len(p2.npos), 'verts', len(p2.wn), f'{time.time()-t0:.0f}s')
npos = np.array(p2.npos, dtype=np.float64)
q = np.empty((len(npos), 2), dtype=np.int32)
q[:, 0] = np.round(npos[:, 1] * 1e6); q[:, 1] = np.round(npos[:, 0] * 1e6)  # lng, lat (1e-6°)
b64 = lambda a: base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()
out = {'bbox': BBOX, 'scale': 1e6, 'ways': len(p2.wcls), 'nodes': len(npos),
       'npos': b64(q.ravel()), 'ncls': b64(np.array(p2.ncls, dtype=np.uint8)), 'ndeg': b64(np.array([min(255, d) for d in p2.ndeg], dtype=np.uint8)),
       'wn': b64(np.array(p2.wn, dtype=np.uint32)), 'starts': b64(np.array(p2.starts, dtype=np.uint32)), 'wcls': b64(np.array(p2.wcls, dtype=np.uint8))}
js = 'window.ROADS_RAW=' + json.dumps(out) + ';\n'
(here / 'roads_data.js').write_text(js, encoding='utf-8')
print('wrote roads_data.js', round(len(js) / 1e6, 1), 'MB', f'{time.time()-t0:.0f}s')
