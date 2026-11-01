"""실제 dashboard_socket 분기와 새 기기 동기화/권한/변경 알림 통합 검사. 외부 모델/API는 사용하지 않는다."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['HUB_STATE_PATH']=str(Path(tmp)/'state.json')
        os.environ['HUB_RECORD_DB_PATH']=str(Path(tmp)/'records.sqlite3')
        os.environ['HUB_DECISION_LOG_PATH']=str(Path(tmp)/'decisions.jsonl')
        import hub_engine
        with patch.object(hub_engine,'SpecialtyMatcher',lambda:object()):
            import app
        from record_archive import RecordArchive
        app.record_archive=RecordArchive(Path(tmp)/'records.sqlite3')
        token=app.record_archive.grant('A')
        app.record_archive.observe(dict(caseId='finished',apid='A',patientInfo={'treatment':['부목 고정']},hospitals=[]))
        app.record_archive.close('finished')

        class Socket:
            def __init__(self,messages=()): self.messages=iter(messages); self.sent=[]
            def receive(self): return next(self.messages,None)
            def send(self,text): self.sent.append(json.loads(text))

        def connect(role,apid,key):
            ws=Socket([json.dumps(dict(type='identify',role=role,id=apid)),json.dumps(dict(type='record_sync',requestId='r',token=key,cursor=0))])
            app.app.view_functions["dashboard_socket"].__wrapped__(ws)
            return ws.sent

        good=connect('ambulance','A',token)
        record=next(p for p in good if p['type']=='record_sync_result')['records'][0]
        assert record['closed'] and record['caseId']=='finished'
        for role,apid in [('ambulance','B'),('hospital','A')]:
            messages=connect(role,apid,token)
            assert any(p.get('error')=='unauthorized' for p in messages)
            assert not any(p['type']=='record_sync_result' for p in messages)
        a,b=Socket(),Socket()
        app._dashboard_sockets.update([a,b])
        app._socket_identity.update({a:('ambulance','A'),b:('ambulance','B')})
        app._archive_call('phase',dict(caseId='next',apid='A',phase='dispatching',incident={'lat':37.5,'lng':127.0}),'A구급대')
        assert any(p['type']=='records_changed' for p in a.sent)
        assert not b.sent
        app._dashboard_sockets.clear(); app._socket_identity.clear()
        print('통과 — 새 기기 종료 사건 다운로드 / 타 구급차·병원 차단 / 소속 구급차에만 변경 알림')

if __name__=='__main__': main()
