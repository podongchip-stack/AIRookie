import Foundation
@main struct CaseSyncCheck {
    @MainActor static func main() {
        let scope = "test-" + UUID().uuidString
        var sent: [[String: Any]] = []
        let sync = CaseEditSync()
        func state(_ fields: [String:String], version: Int, id: String? = nil, conflicts: [String] = [], caseId: String = "case") {
            var value: [String:Any] = ["type":"live_case_state","caseId":caseId,"apid":"A","version":version,"epoch":"epoch","fields":fields,"ticket":"ticket","conflicts":conflicts]
            if let id { value["requestId"] = id }
            sync.accept(try! JSONSerialization.data(withJSONObject:value))
        }
        func send(_ data: Data) -> Bool { sent.append(try! JSONSerialization.jsonObject(with:data) as! [String:Any]); return true }
        sync.activate(caseId:"case",apid:"A",server:scope,send:send)
        state([:],version:1)
        assert(sync.submit(caseId:"case",changes:["h:patientName":"이름"],base:[:]))
        let first = sent.last!["requestId"] as! String
        state(["h:destination":"병원"],version:2)
        assert(sync.handover == ["patientName":"이름","destination":"병원"])
        state(["h:patientName":"이름","h:destination":"병원"],version:3,id:first)
        assert(!sync.hasPending("case"))
        let before = sync.fields
        let reset: [String:String?] = ["h:patientName":nil]
        sync.submit(caseId:"case",changes:reset,base:before)
        assert((sent.last!["changes"] as! [String:Any])["h:patientName"] is NSNull)
        let resetID = sent.last!["requestId"] as! String
        state(["h:patientName":"다른 기기","h:destination":"병원"],version:4,id:resetID,conflicts:["h:patientName"])
        assert(!sync.conflicts.isEmpty)
        sync.resolve(useMine:false)
        assert(sync.handover["patientName"] == "다른 기기")
        sync.submit(caseId:"case",changes:["h:notes":"기록"],base:sync.fields)
        sync.activate(caseId:nil,apid:"A",server:scope,send:send)
        assert(sync.fields.isEmpty)
        sync.reconnect()
        assert(sent.last!["ticket"] as? String == "ticket")
        let oldID = sent.last!["requestId"] as! String
        state(["h:notes":"기록"],version:5,id:oldID)
        assert(!sync.hasPending("case"))
        assert(sync.fields.isEmpty)
        let offlineScope = scope + "-offline"
        let offline = CaseEditSync()
        offline.activate(caseId:"offline",apid:"A",server:offlineScope,send:{ _ in false })
        let initial: [String:Any] = ["caseId":"offline","apid":"A","fields":[:],"version":1,"epoch":"e","ticket":"offline-ticket","handoverRevision":0]
        offline.accept(try! JSONSerialization.data(withJSONObject:initial))
        offline.submit(caseId:"offline",changes:["h:notes":"오프라인 수정"],base:[:])
        let reopened = CaseEditSync()
        reopened.activate(caseId:"offline",apid:"A",server:offlineScope,send:send)
        assert(reopened.hasPending("offline"))
        assert(reopened.handover["notes"] == "오프라인 수정")
        assert(sent.last!["ticket"] as? String == "offline-ticket")
        assert(!reopened.submit(caseId:"wrong",changes:["h:notes":"혼입"],base:[:]))
        let legacy = CaseEditSync()
        legacy.activate(caseId:"legacy",apid:"A",server:scope + "-legacy",initialHandover:["notes":"기존 메모","agency":"기존 소속"],send:{ _ in false })
        legacy.submit(caseId:"legacy",changes:["h:notes":"오프라인 갱신"],base:[:])
        assert(legacy.handover["agency"] == "기존 소속")
        let legacyState: [String:Any] = ["caseId":"legacy","apid":"A","fields":[:],"version":1,"epoch":"e","ticket":"legacy-ticket","handoverRevision":0]
        legacy.accept(try! JSONSerialization.data(withJSONObject:legacyState))
        assert(legacy.handover == ["notes":"오프라인 갱신","agency":"기존 소속"])
        // hub 오류는 이유별로 다룬다 — 일시정지·저장소 오류·지금 보는 사건의 not_owner는 대기열을 두고, 형식 오류와 끝난 사건의 not_owner는 지운다
        let errors = CaseEditSync()
        errors.activate(caseId:"case",apid:"A",server:scope + "-errors",send:send)
        errors.accept(try! JSONSerialization.data(withJSONObject:["caseId":"case","apid":"A","fields":[:],"version":1,"epoch":"e","ticket":"t"] as [String:Any]))
        errors.submit(caseId:"case",changes:["h:notes":"기록"],base:[:])
        let errorID = sent.last!["requestId"] as! String
        func fail(_ code: String, _ caseId: String = "case") {
            errors.accept(try! JSONSerialization.data(withJSONObject:["caseId":caseId,"error":code,"requestId":errorID] as [String:Any]))
        }
        fail("paused"); assert(errors.hasPending("case"))
        fail("storage_unavailable"); assert(errors.hasPending("case"))
        fail("not_owner"); assert(errors.hasPending("case"))
        fail("invalid_patch"); assert(!errors.hasPending("case"))
        for key in UserDefaults.standard.dictionaryRepresentation().keys where key.contains(scope) { UserDefaults.standard.removeObject(forKey:key) }
        print("Client checks passed: merge, null reset, conflict, pending projection, closed-case retry, persisted offline replay, case isolation")
    }
}
