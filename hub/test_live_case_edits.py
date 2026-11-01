"""기기별 다른 칸 병합, 같은 칸 충돌, 초기화, 중복 재전송 및 영구 복원."""
import tempfile
import unittest
from pathlib import Path
from record_archive import RecordArchive

class LiveEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'records.sqlite'
        self.archive = RecordArchive(self.path)
        self.archive.live_get('A', 'case')
    def tearDown(self): self.tmp.cleanup()
    def patch(self, rid, changes, base=None):
        return self.archive.live_patch('A', dict(caseId='case',requestId=rid,changes=changes,base=base or {}))
    def test_two_devices_merge_and_conflict(self):
        phone = self.patch('phone', {'h:patientName':'김환자'})
        pad = self.patch('pad', {'h:destination':'대학병원'})
        self.assertEqual(pad['fields'], {'h:patientName':'김환자','h:destination':'대학병원'})
        conflict = self.patch('stale', {'h:patientName':'다른이름'})
        self.assertEqual(conflict['conflicts'], ['h:patientName'])
        resolved = self.patch('resolved', {'h:patientName':'다른이름'}, pad['fields'])
        self.assertEqual(resolved['fields']['h:patientName'], '다른이름')
        self.assertEqual(phone['conflicts'], [])
    def test_reset_retry_and_reopen(self):
        initial = self.patch('1', {'h:notes':'확인','b:다리:좌':'{"added":true,"removed":false,"cares":["지혈"]}'})
        reset = self.patch('2', {'h:notes':None}, initial['fields'])
        self.assertNotIn('h:notes', reset['fields'])
        retry = self.patch('1', {'h:notes':'확인'})
        self.assertNotIn('h:notes', retry['fields'])
        restored = RecordArchive(self.path).live_get('A','case')
        self.assertEqual(restored['fields'],reset['fields'])
        self.assertEqual(restored['version'],reset['version'])
    def test_other_ambulance_and_archive_isolation(self):
        with self.assertRaises(ValueError): self.archive.live_get('B','case')
        self.patch('1', {'h:notes':'저장됨'})
        public = self.archive.page('A',0,None)['records'][0]
        self.assertEqual(public['handoverEdits']['notes'],'저장됨')
        denied = self.archive.handle(('ambulance','A'),dict(type='record_sync',requestId='x',cursor=0))
        self.assertEqual(denied['error'],'unauthorized')
    def test_oversized_and_bad_values(self):
        for changes in [{'x:bad':'v'},{'h:notes':1},{'h:notes':'a'*20001}]:
            with self.assertRaises(ValueError): self.patch('bad',changes)

if __name__ == '__main__': unittest.main()
