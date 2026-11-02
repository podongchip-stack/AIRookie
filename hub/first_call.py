"""통화 전 규칙 기반 추천. 승인/병상 예약이 아니며 임상 검증 전 시연 규칙.

2026-11-03: Pre-KTAS 선택을 없앴다 — 대원이 병원을 고르는 것 자체가 임상 판단이고, 첫 통화는 요약을 존 전체에 동시 전달하는 시작 신호라
틀려도 뒤에서 바로잡힌다. 그래서 중증도로 후보를 거르거나(적합 병원 필터) 센터 보존을 얹지 않고, 병원 사실(이동·병상·전문의·도착 유효 확률)과
다른 구급차의 점유(진행 부하)만으로 순위를 만든다.
"""
import scoring

# 통화 전 추천에 더하는 병원 자원 항(분) — 이동시간과 같은 '분' 통화로 섞는다(2026-11-03). 값은 전문의 검토 전 초안이고
# 거절 로그가 쌓이면 다시 맞춘다. 필드가 없거나 병상이 미상이면 그 항은 0이다(미상을 이유로 불리하게 두지 않는다).
BED_MARGIN_MIN_PER_BED = 0.5   # 병상이 많을수록 여유 — 병상 1개당 0.5분 앞당김
BED_MARGIN_MAX_BEDS = 6        # 6개부터는 더 앞당기지 않는다(최대 −3분)
BEDS_FULL_PENALTY_MIN = 20.0   # 확인된 만실은 후보에서 빼지 않고(뺑뺑이 방지) 뒤로 민다
R_ARRIVE_PENALTY_MAX_MIN = 6.0  # 도착 때 병상 숫자가 맞을 확률(rArrive)이 낮을수록 최대 +6분
PRESSURE_CAP_MIN = 5.0         # 다른 구급차 점유(진행 부하) 가산의 상한


def resource_terms(h):
    """병상 수·응급의학과 전문의 수·도착 유효 확률을 이동시간에서 가감할 분으로 바꾼다.

    돌려주는 값은 (가감 분 — 음수는 앞당김, 설명 문구 목록). 순위 계산(rank)과 설명 문구가 같은 숫자를 쓰도록 한 곳에서 만든다."""
    minutes, reasons = 0.0, []
    doctors = next((s.get('doctorCount') for s in h.get('specialties', []) if s.get('department') == '응급의학과'), None)
    if doctors:
        bonus, _ = scoring.expertise_bonus_min(doctors, None, None)
        if bonus:
            minutes -= bonus
            reasons.append(f"전문의 {doctors}명 −{bonus:g}분")
    beds = h.get('availableBedCount')
    if beds is not None and not h.get('bedCountUnknown'):
        if beds <= 0:
            minutes += BEDS_FULL_PENALTY_MIN
            reasons.append(f"병상 없음 +{BEDS_FULL_PENALTY_MIN:g}분")
        else:
            bonus = round(BED_MARGIN_MIN_PER_BED * min(beds, BED_MARGIN_MAX_BEDS), 1)
            minutes -= bonus
            reasons.append(f"병상 {beds}개 −{bonus:g}분")
            reliability = h.get('bedReliability')
            r_arrive = reliability.get('rArrive') if isinstance(reliability, dict) else None
            if r_arrive is not None:
                penalty = round(R_ARRIVE_PENALTY_MAX_MIN * (1 - max(0.0, min(1.0, r_arrive))), 1)
                if penalty:
                    minutes += penalty
                    reasons.append(f"도착 유효 {round(r_arrive * 100)}% +{penalty:g}분")
    return minutes, reasons


def rank(rows, attempted, loads):
    eligible = [dict(h) for h in rows]
    for h in eligible:
        load = loads.get(h['hospitalId'], {})
        pressure = load.get('costMin', 0) if isinstance(load, dict) else load * 5
        if isinstance(load, dict):
            for eta in load.get('transportEtas', []):
                # 도착 예상 차이가 15분을 넘으면 해당 이송의 6분 가산을 1.5분으로 낮춘다.
                if abs(eta - h.get('travelMin', h['distanceKm'] * 3)) > 15:
                    pressure -= 4.5
        # 점유 가산 상한 — 중증도를 모르는 통화 전이라 중간값(예전 KTAS 3 상한)으로 둬 불필요한 우회를 제한한다.
        pressure = min(pressure, PRESSURE_CAP_MIN)
        h['coordination'] = {'source': 'rule', 'costMin': pressure, 'counts': load.get('counts', {}) if isinstance(load, dict) else {}}
        resource_min, resource_reasons = resource_terms(h)
        h['firstCallScoreMin'] = h.get('travelMin', h['distanceKm'] * 3) + pressure + resource_min
        h['firstCallReason'] = f"이동 {h.get('travelMin', h['distanceKm'] * 3):.1f}분 · 진행 부하 +{pressure:g}분"
        if resource_reasons: h['firstCallReason'] += ' · ' + ', '.join(resource_reasons)
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
    """추천 의향은 통화를 걸기 전까지 유지하는 lease, 실제 이송은 기존 hub 사건/병상 유지 정보를 사용한다.

    2026-11-03: 예전엔 45초면 풀려서, 두 구급차를 몇 분 간격으로 띄우면 첫 구급차의 추천이 이미 사라져 같은 병원이 또 나왔다.
    이제 lease는 그 사건에 매칭 결과가 생길 때(통화 뒤 요약이 병원들에 전달될 때)·무응답·사건 종료 때 풀리고, 통화를 걸면
    통화 중 점유(contact)가 같은 병원을 더 세게 센다. lease_seconds는 사건이 방치된 경우의 안전 상한이다."""
    lease_seconds = 900

    def __init__(self):
        self.leases = {}

    def release(self, case_id):
        self.leases.pop(case_id, None)

    def pressure(self, case_id, active_ids, calls, results, now, transport_etas=None):
        # 매칭 결과가 생긴 사건은 추천 단계가 끝났다 — 병원들에 전달된 점유(수용 판단 대기·이송 확정)로 대신 센다
        matched = {r.caseId for r in results}
        self.leases = {c: v for c, v in self.leases.items() if c in active_ids and c not in matched and v['expires'] > now}
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
