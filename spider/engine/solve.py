"""시간 기반 해소 루프 — 환자들이 발생 순서대로 줄을 잡고, τ 창 충돌이 나면 덜 위급한 쪽이 이동 중 위치에서 다시 던진다.

map.html의 `solve()`를 그대로 옮겼다. 결과 구조도 같다(hist: 환자별 줄 세그먼트 이력, cur: 지금 유효한 세그먼트,
forced: 빈 벽이 없어 초과로 붙은 환자, events: 시간순 기록(HTML 문구), tMax, dwell, settled).
규칙(README "모델"):
  충돌 = 도착 시각이 τ 안에 겹치는 환자가 한도(cap)를 넘거나 병상(가용 − 우리 점유)이 없음
  양보 = KTAS 낮은 숫자가 남고, 같으면 먼저 닿는 쪽. 이미 도착한 환자는 안 밀림. 비킨 병원엔 다시 안 걸림
  초과 = 빈 벽이 없으면 가장 짧은 줄에 초과로 붙인다(제외하지 않는 원칙)
"""
from __future__ import annotations

from .model import KTAS_Z, Ctx, Params, candidates, cond_label, fx
from .roads import straight_km

MAX_ITER = 20000  # 무한 재투척 방지(JS guard와 같음)


def cumul(coords: list[list[float]]) -> list[float]:
    """경로 좌표의 누적 길이 비율(0~1)."""
    d = [0.0]
    for i in range(1, len(coords)):
        d.append(d[-1] + straight_km(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0]))
    total = d[-1] or 1.0
    return [x / total for x in d]


def pos_at(seg: dict, t: float) -> dict:
    """세그먼트 위 시각 t의 위치(경로 보간)와 높이(출발 z → 병원 z 선형)."""
    f = max(0.0, min(1.0, (t - seg["tStart"]) / max(1e-6, seg["tArr"] - seg["tStart"])))
    c, u = seg["coords"], seg["cum"]
    i = 1
    while i < len(u) - 1 and u[i] < f:
        i += 1
    a, b = c[i - 1], c[i]
    w = (f - u[i - 1]) / max(1e-9, u[i] - u[i - 1])
    return {"lng": a[0] + (b[0] - a[0]) * w, "lat": a[1] + (b[1] - a[1]) * w,
            "z": seg["from"]["z"] + (seg["h"]["z"] - seg["from"]["z"]) * f, "f": f, "i": i}


def solve(patients: list[dict], prm: Params, roads, live: list[dict]) -> dict:
    """patients: {id, site, k, t0, lat, lng, z, cond?, text?} 목록. live: 병상 데이터가 있는 병원(node 붙은 것)."""
    cap, tau, dwell = prm.cap, prm.tau, prm.dwell
    by_id = {p["id"]: p for p in patients}
    cur: dict[int, dict] = {}
    hist: dict[int, list[dict]] = {}
    skip: dict[int, set] = {}
    forced: dict[int, bool] = {}
    events: list[dict] = []
    mm = lambda t: fx(t, 0)

    def assigned(hpid):
        return [s for s in cur.values() if s["h"]["hpid"] == hpid]

    def occupancy(hpid, t, me):
        return sum(1 for s in assigned(hpid) if s["pid"] != me and s["tArr"] <= t < s["tArr"] + dwell)

    def beds(h):
        return cap if h.get("hvec") is None else h["hvec"]

    def mk_seg(p, frm, t_now, c, t_arr):
        coords, km = roads.route_to(frm["lat"], frm["lng"], c["h"], live)
        return {"pid": p["id"], "h": c["h"], "from": dict(frm), "tStart": t_now, "tArr": t_arr, "tEnd": None,
                "len": c["len"], "road": c["road"], "coords": coords, "cum": cumul(coords), "distKm": km}

    queue = [{"p": p, "from": {"lat": p["lat"], "lng": p["lng"], "z": p["z"]}, "tNow": p["t0"], "first": True}
             for p in sorted(patients, key=lambda p: (p["t0"], p["id"]))]
    guard = settled = 0
    while queue and guard < MAX_ITER:
        guard += 1
        queue.sort(key=lambda q: (q["tNow"], q["p"]["id"]))
        item = queue.pop(0)
        p, frm, t_now, first = item["p"], item["from"], item["tNow"], item["first"]
        pid = p["id"]
        skip.setdefault(pid, set())
        hist.setdefault(pid, [])
        tb = roads.table_from(frm["lat"], frm["lng"], live)
        settled += tb["settled"]
        inflight_severe = sum(1 for sg in cur.values() if sg["tArr"] > t_now and by_id[sg["pid"]]["k"] <= 2)
        ctx = Ctx(cap, inflight_severe,
                  inflight=lambda hpid: sum(1 for sg in assigned(hpid) if sg["tArr"] > t_now),
                  win_count=lambda hpid: sum(1 for sg in assigned(hpid) if abs(sg["tArr"] - t_now) <= tau))
        all_cands = candidates(tb["row"], frm, p, t_now, ctx, prm, live)
        cands = [c for c in all_cands if c["h"]["hpid"] not in skip[pid]]
        if first:
            cond = p.get("cond")
            events.append({"t": t_now, "type": "s", "text":
                f"<b>#{pid}</b> (K{p['k']}{(' ' + cond_label(cond)) if cond and cond != 'general' else ''}) {p['site']} 발생"
                f" · 걸 수 있는 줄 {len(cands)}개 · μ {fx(cands[0]['mu'], 0) if cands else '-'}분/레벨"
                f"{(' (이송 중 중증 ' + str(inflight_severe) + ')') if inflight_severe else ''}"})
        placed = False
        avoided: list[str] = []

        def check(c):
            """후보 하나를 지금 잡을 수 있는지(병상·창·우선순위) 판정."""
            t_arr, h = t_now + c["road"], c["h"]
            if occupancy(h["hpid"], t_arr, pid) >= beds(h):
                return {"ok": False, "why": h["name"] + "(병상 참)"}
            win = [s for s in assigned(h["hpid"]) if s["pid"] != pid and abs(s["tArr"] - t_arr) <= tau]
            fixed = [s for s in win if s["tArr"] <= t_now]
            movable = [s for s in win if s["tArr"] > t_now]
            if len(fixed) >= cap:
                return {"ok": False, "why": f"{h['name']}(창 {len(fixed)}/{cap} 도착 완료)"}
            slots = cap - len(fixed)
            me = {"pid": pid, "k": p["k"], "tArr": t_arr}
            rank = sorted([{"pid": s["pid"], "k": by_id[s["pid"]]["k"], "tArr": s["tArr"]} for s in movable] + [me],
                          key=lambda r: (r["k"], r["tArr"], r["pid"]))
            if next(i for i, r in enumerate(rank) if r["pid"] == pid) >= slots:
                return {"ok": False, "why": h["name"] + "(창 꽉 참, 우선순위 밀림)"}
            return {"ok": True, "tArr": t_arr, "win": win, "rank": rank, "losers": rank[slots:]}

        pick = info = None
        for c in cands:
            f = check(c)
            if not f["ok"]:
                avoided.append(f["why"])
                continue
            pick, info = c, f
            break
        if pick:
            h, c, t_arr = pick["h"], pick, info["tArr"]
            if info["losers"]:
                events.append({"t": t_now, "type": "c", "hpid": h["hpid"], "text":
                    f"<b>{h['name']}</b> 충돌 · 창 안 {len(info['win']) + 1}명 (한도 {cap}): "
                    + " · ".join(f"#{r['pid']}(K{r['k']}, {mm(r['tArr'])}분 도착)" for r in info["rank"])})
            for l in info["losers"]:
                s, lp = cur[l["pid"]], by_id[l["pid"]]
                s["tEnd"] = t_now
                at = pos_at(s, t_now)
                skip[l["pid"]].add(h["hpid"])
                del cur[l["pid"]]
                why = f"더 위급한 #{pid}(K{p['k']})에게" if p["k"] < lp["k"] else f"같은 KTAS, #{pid}가 먼저 닿아서"
                events.append({"t": t_now, "type": "y", "text":
                    f"<b>#{l['pid']}</b> (K{lp['k']}) {h['name']} 줄을 놓음 · {why} · 이동 중 위치에서 다시 던짐"})
                queue.append({"p": lp, "from": {"lat": at["lat"], "lng": at["lng"], "z": at["z"]}, "tNow": t_now, "first": False})
            seg = mk_seg(p, frm, t_now, c, t_arr)
            cur[pid] = seg
            hist[pid].append(seg)
            placed = True
            seg["gap"] = c["gap"]
            need = KTAS_Z[p["k"]]
            events.append({"t": t_now, "type": "w" if first else "r", "text":
                f"<b>#{pid}</b> → {h['name']} {'줄 잡음' if first else '다시 잡음'} · 도로 {fx(c['road'], 1)}분 {fx(seg['distKm'], 1)}km"
                f" · 줄 길이 {fx(c['len'], 1)} (유효z {fx(c['gap'] + need, 2)} − 필요 {need} = {'+' if c['gap'] >= 0 else ''}{fx(c['gap'], 2)}; {c['parts']})"
                f" · {mm(t_arr)}분 도착 예정{(' · 예측 충돌로 피한 줄: ' + ', '.join(avoided)) if avoided else ''}"})
        if not placed:
            c = cands[0] if cands else (all_cands[0] if all_cands else None)
            if c:
                t_arr = t_now + c["road"]
                seg = mk_seg(p, frm, t_now, c, t_arr)
                cur[pid] = seg
                hist[pid].append(seg)
                forced[pid] = True
                events.append({"t": t_now, "type": "f", "text":
                    f"<b>#{pid}</b> (K{p['k']}) 빈 벽이 없어 {c['h']['name']}에 초과로 걸림 · {mm(t_arr)}분 도착"})
            else:
                events.append({"t": t_now, "type": "f", "text": f"<b>#{pid}</b> (K{p['k']}) 걸 수 있는 줄이 없음"})

    for s in cur.values():
        p = by_id[s["pid"]]
        events.append({"t": s["tArr"], "type": "a", "text": f"<b>#{p['id']}</b> {s['h']['name']} 도착 · {fx(s['tArr'] + dwell, 0)}분까지 병상 점유"})
        events.append({"t": s["tArr"] + dwell, "type": "o", "text": f"<b>#{p['id']}</b> {s['h']['name']} 병상 비움"})
    events.sort(key=lambda e: e["t"])
    t_max = max([10.0] + [s["tArr"] + dwell for s in cur.values()] + [p["t0"] + 5 for p in patients])
    return {"cur": cur, "hist": hist, "forced": forced, "events": events, "tMax": t_max, "dwell": dwell, "settled": settled}


def to_json(res: dict) -> dict:
    """화면·검증용 직렬화. 세그먼트의 병원 객체는 hpid로, cur는 hist 안의 번호로 바꾼다(화면이 다시 잇는다)."""
    hist_json = {}
    cur_json = {}
    for pid, segs in res["hist"].items():
        hist_json[str(pid)] = [
            {k: v for k, v in s.items() if k != "h"} | {"hpid": s["h"]["hpid"]} for s in segs
        ]
    for pid, seg in res["cur"].items():
        cur_json[str(pid)] = next(i for i, s in enumerate(res["hist"][pid]) if s is seg)
    return {"cur": cur_json, "hist": hist_json, "forced": {str(k): v for k, v in res["forced"].items()},
            "events": res["events"], "tMax": res["tMax"], "dwell": res["dwell"], "settled": res["settled"]}
