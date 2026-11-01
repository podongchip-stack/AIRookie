"""구급차별 영구 사건 보관소. SQLite 변경 순번으로 동기화하며 환자 원문/음성은 보관하지 않는다.

운영자가 `python hub/record_archive.py grant SEL0001`로 발급한 기기 키만 해당 구급차 기록을 읽고 쓴다.
키는 DB에 SHA-256 지문만 보관한다. 기존 실시간 identify는 인증 수단으로 사용하지 않는다.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
DEFAULT_PATH = Path(os.environ.get('HUB_RECORD_DB_PATH') or Path(os.environ.get('HUB_STATE_PATH', str(Path(__file__).parent / 'data/state/hub_state.json'))).with_name('case_records.sqlite3'))


def now_ms(): return time.time() * 1000

def encode(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def stamp(ms): return datetime.fromtimestamp(ms / 1000, KST).strftime('%Y-%m-%d %H:%M')


def automatic(record, patient, hospitals):
    """인계확인서 자동값. 서버가 관측한 단계 시각을 사용하며 수동 수정은 별도로 덮어씌운다(규칙 기반)."""
    v = dict(record.get('_auto', {}))
    v.update(transportKind='현장 이송', selector='구급대(이송자)', selectMethod='이송정보체계', doctorComm='전화', vehicleKind='특수구급차', vehicleNo=record['apid'])
    if record.get('ambulanceName'): v['agency'] = record['ambulanceName']
    if patient:
        v.update(patientName='확인불가', patientBirth='확인불가', patientAddress='확인불가')
        p = patient.get('patient') or ''
        v['patientSex'] = '여' if '여' in p else ('남' if '남' in p else '확인불가')
        if p: v['patientBirth'] = f'확인불가({p})'
        if patient.get('ktasLevel') is not None: v['severity'] = '응급' if patient['ktasLevel'] <= 3 else '비응급'
        elif patient.get('severityTag'): v['severity'] = '비응급' if patient['severityTag'] == 'low' else '응급'
        v['suspected'] = patient.get('expectedDiagnosis') or patient.get('chiefComplaint') or ''
        text = ' '.join([v['suspected']] + (patient.get('injuryStatus') or []))
        v['category'] = '질병외' if any(w in text for w in ('사고','추락','낙상','골절','외상','화상','절단','압궤','중독','익수','폭행','열상','자상','충돌')) else '질병'
        consciousness = patient.get('consciousness') or ''
        for a in 'AVPU':
            if consciousness == a or f'({a})' in consciousness: v['avpu'] = a; break
        vitals = patient.get('vitals') or []
        def vital_line(item):
            def n(k):
                x = item.get(k)
                return f'{x:g}' if isinstance(x, (int,float)) else '?'
            parts = []
            if item.get('sbp') is not None: parts.append(f'BP {n("sbp")}/{n("dbp")}')
            for k,label,unit in [('hr','HR',''),('rr','RR',''),('spo2','SpO₂','%'),('bt','BT','℃'),('glucose','혈당','')]:
                if item.get(k) is not None: parts.append(f'{label} {n(k)}{unit}')
            return ' · '.join(parts)
        if vitals:
            v['vitals'] = vital_line(vitals[-1])
            if len(vitals)>1: v['vitals2'] = v['vitals']; v['avpu2'] = v.get('avpu','')
        care = {}
        treatments = list(patient.get('treatment') or [])
        for note in patient.get('extraNotes') or []:
            if note['text'].startswith('[처치] '): treatments.extend(note['text'][5:].split(' · '))
        for t in dict.fromkeys(treatments):
            if any(w in t for w in ('CPR','AED','지혈','순환보조','ECG','심전도','모니터','정맥로','수액','IV')): key='careCirculation'
            elif any(w in t for w in ('기도','삽관')): key='careAirway'
            elif any(w in t for w in ('산소','BVM','인공호흡')): key='careBreathing'
            elif any(w in t for w in ('투여','약')): key='careDrug'
            elif any(w in t for w in ('부목','고정','경추','척추')): key='careFix'
            else: key='careEtc'
            care.setdefault(key, []).append(t)
        for key in ('careAirway','careBreathing','careCirculation','careDrug','careFix','careEtc'): v[key] = ', '.join(care.get(key,[]))
        notes = []
        if patient.get('injuryStatus'): notes.append('증상: ' + ', '.join(patient['injuryStatus']))
        if patient.get('onset'): notes.append('발생: ' + patient['onset'])
        extra = [n['text'] for n in patient.get('extraNotes') or [] if not n['text'].startswith(('[처치]','[인계확인서]'))]
        if extra: notes.append('추가: ' + ' / '.join(extra))
        v['notes'] = '\n'.join(notes)
    dest = next((h for h in hospitals if h.get('status')=='confirmed'), None)
    if dest:
        v['destination'] = dest['name']
        if dest.get('distanceKm') is not None: v['distanceKm'] = f'{dest["distanceKm"]:.1f}'
    return v


class ImportedHospital(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    hospitalId: str = Field(min_length=1, max_length=200)
    name: str = Field(max_length=500)
    status: str = 'pending'
    rejectReason: str | None = None
    distanceKm: float | None = None
    etaMin: float | None = None


class ImportedRecord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    caseId: str = Field(min_length=1, max_length=200)
    apid: str = Field(min_length=1, max_length=200)
    ambulanceName: str | None = None
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    startedAt: float
    symptom: str | None = None
    expectedDiagnosis: str | None = None
    ktasLevel: int | None = Field(default=None, ge=1, le=5)
    hospitals: list[ImportedHospital] = Field(default_factory=list, max_length=1000)
    closed: bool = False
    handover: dict[str, str] = Field(default_factory=dict, max_length=100)


class RecordArchive:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY, epoch TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS records (case_id TEXT PRIMARY KEY, apid TEXT NOT NULL, body TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS records_apid ON records(apid);
              CREATE TABLE IF NOT EXISTS changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, apid TEXT NOT NULL, case_id TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS changes_apid_seq ON changes(apid,seq);
              CREATE TABLE IF NOT EXISTS grants (digest TEXT PRIMARY KEY, apid TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, apid TEXT NOT NULL, body TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO meta VALUES (1,?)',(str(uuid.uuid4()),))
        try: self.path.chmod(0o600)
        except OSError: pass

    @contextmanager
    def db(self):
        # 단일 잠금 + 트랜잭션: 기록·변경 순번·이벤트를 함께 커밋한다.
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                db.execute("BEGIN IMMEDIATE")
                with db: yield db
            finally: db.close()

    def grant(self, apid):
        token = secrets.token_urlsafe(32)
        with self.db() as db: db.execute('INSERT INTO grants VALUES (?,?)',(hashlib.sha256(token.encode()).hexdigest(),apid))
        return token

    def authorized(self, apid, token):
        if not isinstance(token,str) or len(token)>256: return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db: row = db.execute('SELECT apid FROM grants WHERE digest=?',(digest,)).fetchone()
        return row is not None and hmac.compare_digest(row[0],apid)

    def _get(self, db, case_id):
        row = db.execute('SELECT body FROM records WHERE case_id=?',(case_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _new(self, case_id, apid):
        at=now_ms()
        return dict(caseId=case_id, apid=apid, ambulanceName=None, date=datetime.fromtimestamp(at/1000,KST).strftime('%Y-%m-%d'), startedAt=at, updatedAt=at,
                    symptom=None, expectedDiagnosis=None, ktasLevel=None, hospitals=[], handover={}, closed=False, events=[], handoverEdits={}, handoverRevision=0, _auto={})

    def _save(self, db, record):
        record['handover'] = {**record.get('_auto',{}), **record.get('handoverEdits',{})}
        previous = self._get(db, record['caseId'])
        if previous and previous['apid'] != record['apid']: raise ValueError('owner_mismatch')
        clean = lambda r: {k:v for k,v in r.items() if k not in ('archiveVersion','updatedAt')}
        if previous and clean(previous)==clean(record): return
        seq=db.execute('INSERT INTO changes(apid,case_id) VALUES (?,?)',(record['apid'],record['caseId'])).lastrowid
        record.update(archiveVersion=seq, updatedAt=now_ms(), archiveEpoch=db.execute('SELECT epoch FROM meta WHERE id=1').fetchone()[0])
        db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)',(record['caseId'],record['apid'],encode(record)))
        return {'apid':record['apid'], 'cursor':seq}

    def observe(self, payload):
        cid,apid=payload.get('caseId'),payload.get('apid')
        if not cid or not apid: return
        with self.db() as db:
            r=self._get(db,cid) or self._new(cid,apid)
            if payload.get('ambulanceName'): r['ambulanceName']=payload['ambulanceName']
            p=payload.get('patientInfo') or {}
            hospitals=[dict(hospitalId=h['hospitalId'],name=h['name'],status=h.get('status','pending'),rejectReason=h.get('rejectReason'),distanceKm=h.get('roadDistanceKm') if h.get('roadDistanceKm') is not None else h.get('distanceKm'),etaMin=h.get('etaMin')) for h in payload.get('hospitals') or []]
            # Previously contacted hospitals remain in the historical record even after zone/ranking changes.
            old={h['hospitalId']:h for h in r['hospitals']}
            old.update({h['hospitalId']:h for h in hospitals})
            r.update(hospitals=list(old.values()),symptom=p.get('chiefComplaint') or p.get('expectedDiagnosis'),expectedDiagnosis=p.get('expectedDiagnosis'),ktasLevel=p.get('ktasLevel'))
            r['_auto']=automatic(r,p,hospitals)
            return self._save(db,r)

    def phase(self, state, name=None):
        cid,apid=state.get('caseId'),state.get('apid')
        if not cid or not apid: return
        with self.db() as db:
            r=self._get(db,cid) or self._new(cid,apid)
            if name: r['ambulanceName']=name
            phase=state.get('phase')
            field={'dispatching':'dispatchedAt','on_scene':'sceneArrivedAt','transporting':'transportStartedAt','at_hospital':'transportEndedAt'}.get(phase)
            r['_auto'].setdefault('requestedAt',stamp(r['startedAt']))
            if field: r['_auto'].setdefault(field,stamp(now_ms()))
            incident=state.get('incident')
            if incident: r['_auto']['originAddress']=f'위도 {incident["lat"]:.5f}, 경도 {incident["lng"]:.5f}'
            r['_auto']=automatic(r,None,r['hospitals'])
            return self._save(db,r)

    def action(self, action, apid):
        if not apid: return
        with self.db() as db:
            r=self._get(db,action['caseId']) or self._new(action['caseId'],apid)
            r['events'].append(dict(id=str(uuid.uuid4()),hospitalId=action['hospital_id'], action=action['action'], actor=action['actor'], timestamp=action['timestamp'], reason=action.get('reason')))
            return self._save(db,r)

    def close(self,cid):
        with self.db() as db:
            r=self._get(db,cid)
            if r: r['closed']=True; return self._save(db,r)

    @staticmethod
    def public(r): return {k:v for k,v in r.items() if not k.startswith('_')}

    def page(self,apid,cursor,epoch,limit=100):
        if type(cursor) is not int or cursor<0: raise ValueError('invalid_cursor')
        with self.db() as db:
            epoch_now=db.execute('SELECT epoch FROM meta WHERE id=1').fetchone()[0]
            head=db.execute('SELECT COALESCE(MAX(seq),0) FROM changes').fetchone()[0]
            if epoch != epoch_now or cursor>head: cursor=0
            rows=db.execute('SELECT MAX(seq) AS latest,case_id FROM changes WHERE apid=? AND seq>? GROUP BY case_id ORDER BY latest LIMIT ?',(apid,cursor,limit+1)).fetchall()
            more=len(rows)>limit; rows=rows[:limit]
            next_cursor=rows[-1][0] if more else head
            records=[self.public(self._get(db,cid)) for cid in dict.fromkeys(row[1] for row in rows)]
            return dict(epoch=epoch_now,cursor=next_cursor,hasMore=more,records=records)

    def import_legacy(self,apid,records):
        if not isinstance(records,list) or len(records)>20: raise ValueError('invalid_import')
        with self.db() as db:
            for raw in records:
                raw = ImportedRecord.model_validate(raw).model_dump()
                datetime.strptime(raw['date'], '%Y-%m-%d')
                if not isinstance(raw,dict) or raw.get('apid')!=apid or not isinstance(raw.get('caseId'),str): raise ValueError('invalid_import')
                if self._get(db,raw['caseId']): continue
                # Validate the complete batch in the same transaction; imported snapshots are not action history.
                r=self._new(raw['caseId'],apid)
                for key in ('ambulanceName','date','startedAt','symptom','expectedDiagnosis','ktasLevel','hospitals','closed'):
                    if key in raw: r[key]=raw[key]
                if not isinstance(r['date'],str) or len(r['date'])!=10 or not isinstance(r['startedAt'],(int,float)) or not isinstance(r['hospitals'],list): raise ValueError('invalid_import')
                edits=raw.get('handover') or {}
                if not isinstance(edits,dict) or any(not isinstance(k,str) or not isinstance(v,str) or len(v)>20000 for k,v in edits.items()): raise ValueError('invalid_import')
                r['_auto']=edits; r['legacyImport']=True
                self._save(db,r)

    def save_edits(self,apid,payload):
        cid=payload.get('caseId'); edits=payload.get('edits'); rid=payload.get('requestId')
        if not isinstance(cid,str) or not isinstance(rid,str) or not rid or len(rid)>200 or type(payload.get('revision')) is not int or not isinstance(edits,dict) or len(edits)>100 or any(not isinstance(k,str) or not isinstance(v,str) or len(v)>20000 for k,v in edits.items()): raise ValueError('invalid_edits')
        with self.db() as db:
            receipt=db.execute('SELECT apid,body FROM receipts WHERE id=?',(rid,)).fetchone()
            if receipt:
                if receipt[0]!=apid: raise ValueError('forbidden')
                return json.loads(receipt[1])
            r=self._get(db,cid)
            if not r or r['apid']!=apid: raise ValueError('not_found')
            if payload.get('revision')!=r['handoverRevision']: return dict(conflict=True,record=self.public(r))
            r['handoverEdits']=edits; r['handoverRevision']+=1
            self._save(db,r)
            result=dict(conflict=False,record=self.public(r))
            db.execute('INSERT INTO receipts VALUES (?,?,?)',(rid,apid,encode(result)))
            return result

    @staticmethod
    def live_state(record):
        fields = {'h:'+k: v for k,v in record.get('handoverEdits', {}).items()}
        fields.update(record.get('_bodyEdits', {}))
        return dict(type='live_case_state', source='rule', caseId=record['caseId'], apid=record['apid'],
                    version=record.get('archiveVersion', 0), epoch=record.get('archiveEpoch', ''), fields=fields,
                    ticket=record.get('_liveTicket'), handoverRevision=record.get('handoverRevision', 0))

    def authorized_live(self, apid, cid, ticket):
        if not isinstance(ticket, str) or not ticket: return False
        with self.db() as db:
            r = self._get(db, cid)
            return bool(r and r['apid'] == apid and hmac.compare_digest(r.get('_liveTicket', ''), ticket))

    def live_get(self, apid, cid):
        # 소켓 계층이 현재 사건 소유권을 검증한 뒤에만 호출한다. 과거 기록 API와 권한은 별개다.
        with self.db() as db:
            r = self._get(db, cid)
            if r is None:
                r = self._new(cid, apid)
                self._save(db, r)
            if r['apid'] != apid: raise ValueError('not_owner')
            if not r.get('_liveTicket'):
                r['_liveTicket'] = secrets.token_urlsafe(32)
                self._save(db, r)
            return self.live_state(r)

    def live_patch(self, apid, payload):
        cid, rid = payload.get('caseId'), payload.get('requestId')
        changes, base = payload.get('changes'), payload.get('base')
        valid = lambda d: isinstance(d, dict) and len(d) <= 200 and all(
            isinstance(k, str) and len(k) <= 200 and k.startswith(('h:', 'b:')) and
            (v is None or isinstance(v, str) and len(v) <= 20000) for k,v in d.items())
        if not isinstance(cid, str) or not isinstance(rid, str) or not 1 <= len(rid) <= 200 or not valid(changes) or not valid(base):
            raise ValueError('invalid_patch')
        with self.db() as db:
            r = self._get(db, cid)
            if not r or r['apid'] != apid: raise ValueError('not_owner')
            receipt = db.execute('SELECT apid,body FROM receipts WHERE id=?', ('live:'+rid,)).fetchone()
            if receipt:
                if receipt[0] != apid: raise ValueError('not_owner')
                if json.loads(receipt[1]).get('caseId') != cid: raise ValueError('request_id_reused')
                return {**self.live_state(r), 'requestId': rid, 'conflicts': []}
            current = self.live_state(r)['fields']
            conflicts = [k for k,v in changes.items() if current.get(k) != base.get(k) and current.get(k) != v]
            if conflicts:
                return {**self.live_state(r), 'requestId': rid, 'conflicts': conflicts}
            handover = dict(r.get('handoverEdits', {}))
            body = dict(r.get('_bodyEdits', {}))
            for k,v in changes.items():
                target, key = (handover, k[2:]) if k.startswith('h:') else (body, k)
                if v is None: target.pop(key, None)
                else: target[key] = v
            if handover != r.get('handoverEdits', {}): r['handoverRevision'] += 1
            r['handoverEdits'] = handover
            r['_bodyEdits'] = body
            self._save(db, r)
            db.execute('INSERT INTO receipts VALUES (?,?,?)', ('live:'+rid, apid, encode({'caseId':cid})))
            return {**self.live_state(r), 'requestId': rid, 'conflicts': []}

    def handle(self,identity,payload):
        role,apid=identity
        request_id=payload.get('requestId')
        if role!='ambulance' or not apid or not self.authorized(apid,payload.get('token')):
            return dict(type='record_error',requestId=request_id,error='unauthorized')
        if len(encode(payload))>1000000: return dict(type='record_error',requestId=request_id,error='too_large')
        try:
            kind=payload['type']
            if kind=='record_sync': result=self.page(apid,payload.get('cursor',0),payload.get('epoch'))
            elif kind=='record_import':
                self.import_legacy(apid,payload.get('records'))
                with self.db() as db:
                    result={'records':[self.public(self._get(db,r['caseId'])) for r in payload['records']]}
            elif kind=='record_handover': result=self.save_edits(apid,payload)
            else: raise ValueError('unsupported')
            return dict(type=kind+'_result',requestId=request_id,apid=apid,**result)
        except (ValueError,TypeError,KeyError): return dict(type='record_error',requestId=request_id,error='invalid_request')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='구급차 기록 동기화 키 발급·폐기')
    parser.add_argument('command',choices=['grant','revoke']); parser.add_argument('apid')
    args=parser.parse_args(); store=RecordArchive()
    if args.command=='grant': print(store.grant(args.apid))
    else:
        with store.db() as db: db.execute('DELETE FROM grants WHERE apid=?',(args.apid,))
        print('revoked')
