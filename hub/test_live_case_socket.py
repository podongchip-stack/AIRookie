"""두 네이티브 기기 실시간 수동 수정 분기: 소유권·동시 편집·종료 후 재전송·재접속."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['HUB_STATE_PATH'] = str(Path(tmp)/'hub.json')
        os.environ['HUB_RECORD_DB_PATH'] = str(Path(tmp)/'records.sqlite3')
        os.environ['HUB_DECISION_LOG_PATH'] = str(Path(tmp)/'decisions.jsonl')
        os.environ['HUB_SIM_DISPATCH'] = '0'
        import hub_engine
        with patch.object(hub_engine, 'SpecialtyMatcher', lambda: object()):
            import app
        from record_archive import RecordArchive
        app.record_archive = RecordArchive(Path(tmp)/'records.sqlite3')
        class Socket:
            def __init__(self): self.sent=[]
            def send(self, text): self.sent.append(json.loads(text))
        phone,pad,other,hospital,monitor = [Socket() for _ in range(5)]
        app._dashboard_sockets = {phone,pad,other,hospital,monitor}
        app._socket_identity = {phone:('ambulance','A'),pad:('ambulance','A'),other:('ambulance','B'),hospital:('hospital','H'),monitor:('monitor','M')}
        def apply(ws,kind,**kwargs):
            app._handle_live_case_edit(ws,dict(type=kind,caseId='case',**kwargs))
            return next(x for x in reversed(ws.sent) if x.get("type") in ("live_case_state", "live_case_error"))
        with patch.object(app.engine,'get_case_apid',return_value='A'),patch.object(app,'_case_paused',return_value=False):
            first=apply(phone,'live_case_get')
            ticket=first['ticket']
            assert apply(other,'live_case_get')['error']=='not_owner'
            assert apply(monitor,'live_case_get')['error']=='not_owner'
            assert apply(hospital,'live_case_get')['error']=='not_owner'
            one=apply(phone,'live_case_patch',requestId='phone',base={},changes={'h:patientName':'수정 이름'})
            assert one['fields']['h:patientName']=='수정 이름'
            assert any(x.get('fields',{}).get('h:patientName')=='수정 이름' for x in pad.sent)
            two=apply(pad,'live_case_patch',requestId='pad',base={},changes={'h:notes':'패드 수정'})
            assert two['fields']=={'h:patientName':'수정 이름','h:notes':'패드 수정'}
            conflict=apply(phone,'live_case_patch',requestId='conflict',base={},changes={'h:notes':'폰 수정'})
            assert conflict['conflicts']==['h:notes']
            reconnected=Socket();app._socket_identity[reconnected]=('ambulance','A')
            assert apply(reconnected,'live_case_get')['fields']==two['fields']
        before=len(pad.sent)
        with patch.object(app.engine,'get_case_apid',return_value=None),patch.object(app,'_case_paused',return_value=False):
            assert apply(pad,'live_case_get')['error']=='not_owner'
            late=apply(phone,'live_case_patch',requestId='offline',ticket=ticket,base=two['fields'],changes={'h:notes':'종료 직전 저장'})
            assert late['fields']['h:notes']=='종료 직전 저장'
            assert not any(x.get('type')=='live_case_state' for x in pad.sent[before:])
            assert apply(other,'live_case_get',ticket=ticket)['error']=='not_owner'
        assert not any(x.get('type')=='live_case_state' for ws in [other,hospital,monitor] for x in ws.sent)
        print('PASS: phone ↔ pad, merge/conflict, reconnect, archive isolation, scoped offline retry')

if __name__=='__main__': main()
