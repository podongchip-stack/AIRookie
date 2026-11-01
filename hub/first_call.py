"""통화 전 규칙 기반 추천. 승인/병상 예약이 아니며 임상 검증 전 시연 규칙."""
import spider_rule


def rank(rows, ktas, attempted, loads):
    eligible = [dict(h) for h in rows if ktas in h.get('supportedKtas', [])]
    for h in eligible:
        grade = spider_rule.LEVEL_G.get(h.get('emergencyLevel'), 1)
        # 기존 경증 센터 보존 상수(5분)를 사용. 먼 하급기관을 무조건 우선하지 않는다.
        center = max(0, grade - 2) * spider_rule.LAM if ktas >= 4 else 0
        load = loads.get(h['hospitalId'], {})
        pressure = load.get('costMin', 0) if isinstance(load, dict) else load * 5
        if isinstance(load, dict):
            for eta in load.get('transportEtas', []):
                # 도착 예상 차이가 15분을 넘으면 해당 이송의 6분 가산을 1.5분으로 낮춘다.
                if abs(eta - h.get('travelMin', h['distanceKm'] * 3)) > 15:
                    pressure -= 4.5
        # 중증은 분산 비용 상한을 낮춰 불필요한 우회를 제한한다.
        pressure = min(pressure, 2 if ktas <= 2 else 5 if ktas == 3 else 10)
        h['coordination'] = {'source': 'rule', 'costMin': pressure, 'counts': load.get('counts', {}) if isinstance(load, dict) else {}}
        h['firstCallScoreMin'] = h.get('travelMin', h['distanceKm'] * 3) + center + pressure
        h['firstCallReason'] = f"이동 {h.get('travelMin', h['distanceKm'] * 3):.1f}분 · 센터 보존 +{center:g}분 · 진행 부하 +{pressure:g}분"
        counts = h['coordination']['counts']
        details = []
        for key, label in [('recommendation', '다른 추천'), ('contact', '다른 연락'), ('awaiting', '판단 대기'), ('transport', '이송 확정')]:
            if counts.get(key): details.append(f"{label} {counts[key]}건")
        if details: h['firstCallReason'] += ' · ' + ', '.join(details)
        h['firstCallRecommended'] = False
    eligible.sort(key=lambda h: (h['firstCallScoreMin'], h.get('roadDistanceKm') or h['distanceKm'], h['hospitalId']))
    fresh = [h for h in eligible if h['hospitalId'] not in attempted]
    if fresh:
        fresh[0]['firstCallRecommended'] = True
    return fresh, [h for h in eligible if h['hospitalId'] in attempted]


class Coordinator:
    """추천 의향은 짧은 lease, 실제 이송은 기존 hub 사건/병상 유지 정보를 사용한다."""
    lease_seconds = 45

    def __init__(self):
        self.leases = {}

    def release(self, case_id):
        self.leases.pop(case_id, None)

    def pressure(self, case_id, active_ids, calls, results, now, transport_etas=None):
        self.leases = {c: v for c, v in self.leases.items() if c in active_ids and v['expires'] > now}
        contributions = {}
        # 동일 사건의 추천/통화/대기/확정은 중복 합산하지 않고 병원별 가장 확실한 상태만 쓴다.
        def add(cid, hid, weight, kind):
            if cid == case_id or cid not in active_ids or not hid:
                return
            old = contributions.get((cid, hid), (0, kind))
            if weight > old[0]: contributions[cid, hid] = (weight, kind)
        for cid, lease in self.leases.items():
            add(cid, lease['hospitalId'], 1, 'recommendation')
        for c in calls:
            if c.get('state') in ('ringing', 'calling'):
                add(c['caseId'], c.get('hospitalId'), 2, 'contact')
        for r in results:
            confirmed = next((h for h in r.hospitals if h.status == 'confirmed'), None)
            if confirmed:
                add(r.caseId, confirmed.hospitalId, 6, 'transport')
                continue
            pending = [h for h in r.hospitals if h.status in ('pending', 'approved')]
            # 한 사건의 동시 전달은 총 1분 상당으로 나눠 반영한다.
            for h in pending:
                add(r.caseId, h.hospitalId, 1 / len(pending), 'awaiting')
        loads = {}
        for (cid, hid), (weight, kind) in contributions.items():
            item = loads.setdefault(hid, {'costMin': 0, 'counts': {}})
            item['costMin'] += weight
            item['counts'][kind] = item['counts'].get(kind, 0) + 1
            if kind == 'transport' and transport_etas and (cid, hid) in transport_etas:
                item.setdefault('transportEtas', []).append(transport_etas[(cid, hid)])
        return loads

    def remember(self, case_id, hospital_id, now):
        if hospital_id:
            self.leases[case_id] = {'hospitalId': hospital_id, 'expires': now + self.lease_seconds}
        else:
            self.release(case_id)
