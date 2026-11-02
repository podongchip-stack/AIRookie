"""모델·실제 GPS 없이 동시 사건의 분산/해제/중증 접근을 재현한다."""
import unittest
from types import SimpleNamespace as NS
from first_call import Coordinator, rank

ROWS = [dict(hospitalId=h, emergencyLevel="지역응급의료기관", supportedKtas=[3,4,5], travelMin=t, distanceKm=t/3) for h,t in [("A",5),("B",5.5)]]
class CoordinationTests(unittest.TestCase):
    def test_simultaneous_intent_distributes_and_expires(self):
        c=Coordinator(); active={"one","two"}
        first=rank(ROWS,[],c.pressure("one",active,[],[],0))[0][0]
        c.remember("one", first['hospitalId'],0)
        second=rank(ROWS,[],c.pressure("two",active,[],[],1))[0][0]
        self.assertEqual((first['hospitalId'],second['hospitalId']),("A","B"))
        # 통화를 걸기 전이면 추천 점유가 유지된다(예전엔 45초 만에 풀려 몇 분 간격으로 띄운 두 번째 구급차가 같은 병원을 추천받았다)
        self.assertEqual(rank(ROWS,[],c.pressure("two",active,[],[],46))[0][0]['hospitalId'],"B")
        self.assertEqual(rank(ROWS,[],c.pressure("two",active,[],[],600))[0][0]['hospitalId'],"B")
        # 방치된 사건의 점유는 안전 상한(lease_seconds)에 풀린다
        self.assertEqual(rank(ROWS,[],c.pressure("two",active,[],[],c.lease_seconds+2))[0][0]['hospitalId'],"A")

    def test_lease_ends_when_the_case_gets_a_match_result_or_closes(self):
        c=Coordinator(); c.remember("one","A",0)
        # 요약이 병원들에 전달되면(매칭 결과) 추천 단계가 끝난 것 — 추천 점유 대신 전달된 병원 점유만 센다
        sent=NS(caseId="one",hospitals=[NS(hospitalId="C",status="pending")])
        loads=c.pressure("two",{"one","two"},[],[sent],2)
        self.assertNotIn("A",loads); self.assertIn("C",loads); self.assertNotIn("one",c.leases)
        # 사건이 끝나면 풀린다
        c.remember("one","A",0)
        self.assertEqual(c.pressure("two",{"two"},[],[],3),{})
        self.assertNotIn("one",c.leases)

    def test_broadcast_not_four_patients_and_contact_not_double_counted(self):
        c=Coordinator(); c.remember("one","A",0)
        r=NS(caseId="one",hospitals=[NS(hospitalId=h,status="pending") for h in "ABCD"])
        loads=c.pressure("two",{"one","two"},[],[r],1)
        self.assertEqual(loads['B']['costMin'],.25)
        calls=[dict(caseId="one",hospitalId="A",state="calling")]
        self.assertEqual(c.pressure("two",{"one","two"},calls,[r],1)['A']['costMin'],2)

    def test_confirmed_stronger_and_closed_removed(self):
        c=Coordinator(); r=NS(caseId="one",hospitals=[NS(hospitalId="A",status="confirmed")])
        self.assertEqual(c.pressure("two",{"one","two"},[],[r],0)['A']['costMin'],6)
        self.assertEqual(c.pressure("two",{"two"},[],[r],0),{})

    def test_arrival_time_window_reduces_distant_transport_cost(self):
        c=Coordinator(); r=NS(caseId="one",hospitals=[NS(hospitalId="A",status="confirmed")])
        loads=c.pressure("two",{"one","two"},[],[r],0,{("one","A"):40})
        self.assertEqual(rank(ROWS,[],loads)[0][-1]['coordination']['costMin'],1.5)

    def test_pressure_capped_and_hospital_stays_listed(self):
        out=rank([ROWS[0]],[],{"A":{"costMin":100,"counts":{"transport":10}}})[0]
        self.assertEqual(out[0]['coordination']['costMin'],5)
        self.assertEqual(out[0]['hospitalId'],"A")

    def test_resource_terms_beds_doctors_and_arrival_probability(self):
        def row(hid, t, **extra):
            return dict(hospitalId=hid, emergencyLevel="지역응급의료기관", travelMin=t, distanceKm=t/3, **extra)
        order = lambda rows: [h['hospitalId'] for h in rank(rows, [], {})[0]]
        # 확인된 만실은 후보에서 빠지지 않지만 더 먼 병원 뒤로 간다
        self.assertEqual(order([row("full", 4, availableBedCount=0, bedCountUnknown=False), row("far", 9, availableBedCount=4, bedCountUnknown=False)]), ["far", "full"])
        # 병상 수를 모르면(미상) 그 항은 없다 — 이동시간만으로 정렬
        self.assertEqual(order([row("unknown", 4, availableBedCount=0, bedCountUnknown=True), row("far", 5, availableBedCount=1, bedCountUnknown=False)]), ["unknown", "far"])
        # 응급의학과 전문의가 두꺼우면 조금 더 멀어도 앞선다(최대 3분)
        thick = [dict(department="응급의학과", doctorCount=20)]
        thin = [dict(department="응급의학과", doctorCount=1)]
        self.assertEqual(order([row("thin", 5, specialties=thin), row("thick", 7, specialties=thick)]), ["thick", "thin"])
        self.assertEqual(order([row("thin", 5, specialties=thin), row("thick", 9, specialties=thick)]), ["thin", "thick"])
        # 도착 때 병상 숫자가 맞을 확률이 낮으면 같은 거리·병상에서 뒤로 간다
        low = dict(rArrive=0.2); high = dict(rArrive=0.95)
        self.assertEqual(order([row("low", 5, availableBedCount=3, bedCountUnknown=False, bedReliability=low),
                                row("high", 5.5, availableBedCount=3, bedCountUnknown=False, bedReliability=high)]), ["high", "low"])
        out = rank([row("x", 5, availableBedCount=3, bedCountUnknown=False, bedReliability=low, specialties=thick)], [], {})[0][0]
        self.assertIn("병상 3개", out['firstCallReason']); self.assertIn("전문의 20명", out['firstCallReason']); self.assertIn("도착 유효 20%", out['firstCallReason'])

if __name__=='__main__': unittest.main()
