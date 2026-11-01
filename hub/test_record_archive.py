"""영구 기록·서로 다른 기기·커서·키 범위·재전송·충돌 검증. 외부 API를 쓰지 않는다."""
import tempfile
import unittest
from pathlib import Path
from record_archive import RecordArchive

class RecordArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'records.sqlite3'
        self.store=RecordArchive(self.path)
        self.token=self.store.grant('A')
    def tearDown(self): self.temp.cleanup()
    def observe(self,cid='old',apid='A',status='pending'):
        self.store.observe(dict(caseId=cid,apid=apid,patientInfo=dict(expectedDiagnosis='발목 손상',chiefComplaint='통증',ktasLevel=3,treatment=['부목 고정']),hospitals=[dict(hospitalId='H',name='병원',status=status,distanceKm=2)]))
    def request(self,**fields):
        return self.store.handle(('ambulance','A'),dict(type='record_sync',token=self.token,requestId='request',cursor=0,epoch=None,**fields))
    def test_initial_install_and_old_case_update(self):
        self.observe()
        first=self.request()
        self.assertEqual(len(first['records']),1)
        self.assertEqual(first['records'][0]['handover']['careFix'],'부목 고정')
        self.observe('new')
        self.observe(status='approved')
        second=self.store.page('A',first['cursor'],first['epoch'])
        self.assertEqual({r['caseId'] for r in second['records']},{'old','new'})
        self.assertEqual(next(r for r in second['records'] if r['caseId']=='old')['hospitals'][0]['status'],'approved')
    def test_duplicate_snapshot_does_not_advance(self):
        self.observe(); a=self.request(); self.observe(); b=self.store.page('A',a['cursor'],a['epoch'])
        self.assertEqual(b['records'],[]); self.assertEqual(a['cursor'],b['cursor'])
    def test_page_scope_and_restart(self):
        for i in range(5): self.observe(str(i))
        self.observe('other','B')
        first=self.store.page('A',0,None,limit=2)
        self.assertTrue(first['hasMore'])
        cursor=first['cursor']; records=list(first['records']); epoch=first['epoch']
        other=RecordArchive(self.path)
        while True:
            page=other.page('A',cursor,epoch,limit=2); records.extend(page['records']); cursor=page['cursor']
            if not page['hasMore']: break
        self.assertEqual({r['caseId'] for r in records},{str(i) for i in range(5)})
    def test_keys_scope_and_revocation(self):
        self.observe(); self.observe('secret','B')
        for identity,token in [(('hospital','A'),self.token),(('ambulance','B'),self.token),(('ambulance','A'),'wrong')]:
            self.assertEqual(self.store.handle(identity,dict(type='record_sync',requestId='x',token=token))['error'],'unauthorized')
        with self.store.db() as db: db.execute('DELETE FROM grants WHERE apid=?',('A',))
        self.assertEqual(self.request()['error'],'unauthorized')
    def test_event_history_survives_changed_status_and_close(self):
        self.observe()
        for action in ['hospital_approve','hospital_reject']:
            self.store.action(dict(caseId='old',hospital_id='H',action=action,actor='hospital',timestamp='2026-11-01T00:00:00Z',reason='BEDS_FULL' if action.endswith('reject') else None),'A')
        self.observe(status='rejected'); self.store.close('old')
        record=self.request()['records'][0]
        self.assertTrue(record['closed']); self.assertEqual(len(record['events']),2)
        self.assertEqual(record['events'][-1]['reason'],'BEDS_FULL')
        self.observe(status='rejected'); self.assertTrue(self.request()['records'][0]['closed'])
    def test_two_device_edits_conflict_and_retry_receipt(self):
        self.observe()
        command=dict(type='record_handover',requestId='save-1',token=self.token,caseId='old',revision=0,edits={'careFix':'부목 고정 확인'})
        first=self.store.handle(('ambulance','A'),command)
        second=self.store.handle(('ambulance','A'),command)
        self.assertEqual(first,second); self.assertFalse(first['conflict'])
        other=self.store.handle(('ambulance','A'),dict(command,requestId='save-2',edits={'notes':'다른 기기 수정'}))
        self.assertTrue(other['conflict']); self.assertEqual(other['record']['handoverRevision'],1)
        rebased=self.store.handle(('ambulance','A'),dict(command,requestId='save-3',revision=1,edits={'notes':'사용자가 선택한 수정'}))
        self.assertFalse(rebased['conflict'])
    def test_epoch_reset_bootstraps(self):
        self.observe(); first=self.request()
        reset=self.store.page('A',first['cursor'],'old-server-epoch')
        self.assertEqual(len(reset['records']),1)
    def test_legacy_import_is_marked_and_cannot_overwrite(self):
        self.observe(); current=self.request()['records'][0]
        legacy=dict(current,caseId='legacy',handover={'notes':'이전 기기 기록'})
        self.store.import_legacy('A',[legacy]); self.store.import_legacy('A',[dict(current,handover={'notes':'덮어쓰기'})])
        records={r['caseId']:r for r in self.request()['records']}
        self.assertTrue(records['legacy']['legacyImport']); self.assertEqual(records['legacy']['events'],[])
        self.assertNotIn('덮어쓰기',str(records['old']['handover']))
    def test_wrong_owner_in_import_rolls_back_batch(self):
        self.observe(); record=self.request()['records'][0]
        with self.assertRaises(ValueError): self.store.import_legacy('A',[dict(record,caseId='valid'),dict(record,caseId='forbidden',apid='B')])
        self.assertEqual([r['caseId'] for r in self.request()['records']],['old'])

if __name__=='__main__': unittest.main()
