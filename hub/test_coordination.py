"""모델·실제 GPS 없이 동시 사건의 분산/해제/중증 접근을 재현한다."""
import unittest
from types import SimpleNamespace as NS
from first_call import Coordinator, rank

ROWS = [dict(hospitalId=h, emergencyLevel="지역응급의료기관", supportedKtas=[3,4,5], travelMin=t, distanceKm=t/3) for h,t in [("A",5),("B",5.5)]]
class CoordinationTests(unittest.TestCase):
    def test_simultaneous_intent_distributes_and_expires(self):
        c=Coordinator(); active={"one","two"}
        first=rank(ROWS,4,[],c.pressure("one",active,[],[],0))[0][0]
        c.remember("one", first['hospitalId'],0)
        second=rank(ROWS,4,[],c.pressure("two",active,[],[],1))[0][0]
        self.assertEqual((first['hospitalId'],second['hospitalId']),("A","B"))
        self.assertEqual(rank(ROWS,4,[],c.pressure("two",active,[],[],46))[0][0]['hospitalId'],"A")

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
        self.assertEqual(rank(ROWS,4,[],loads)[0][-1]['coordination']['costMin'],1.5)

    def test_severe_penalty_capped_and_only_eligible_remains(self):
        row=dict(ROWS[0],supportedKtas=[1,2,3,4,5])
        out=rank([row],1,[],{"A":{"costMin":100,"counts":{"transport":10}}})[0]
        self.assertEqual(out[0]['coordination']['costMin'],2)
        self.assertEqual(out[0]['hospitalId'],"A")

if __name__=='__main__': unittest.main()
