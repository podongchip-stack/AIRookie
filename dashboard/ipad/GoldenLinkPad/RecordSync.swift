import Foundation

// [기록] 동기화 — 아이폰 PhoneModel의 "영구 기록 동기화"와 같다(2026-11-02, 안드로이드·아이폰과 맞춤).
// 지난 사건과 그 사건의 병원 응답·인계확인서를 hub 보관소와 변경 순번으로 맞추고, 기기에도 날짜별로 남긴다(오프라인에서도 조회).
extension AppModel {
    func syncRecords() {
        guard let apid, let socket = ambulance, socket.isOpen else { return }
        let token = RecordAccess.token(apid)
        guard !token.isEmpty else { recordSyncStatus = "설정에 구급차별 기록 동기화 키를 입력해 주세요."; return }
        if let request = recordRequest, Date().timeIntervalSince(request.at) < 20 { return }
        let id: String
        let sent: Bool
        // 기존 설치에만 있던 기록은 20개씩 이관한다. 서버 기록이 있으면 서버 값을 유지한다.
        let legacy = records.legacyRecords()
        if !legacy.isEmpty {
            id = UUID().uuidString
            sent = socket.send(RecordImportRequest(requestId: id, token: token, records: legacy))
        } else if handoverConflict == nil, let pending = records.pending.first {
            id = pending.requestId
            sent = socket.send(RecordHandoverRequest(pending: pending, token: token))
        } else {
            id = UUID().uuidString
            let cursor = records.cursor
            sent = socket.send(RecordSyncRequest(requestId: id, token: token, cursor: cursor.cursor, epoch: cursor.epoch))
        }
        if sent { recordRequest = (id, Date()); recordSyncStatus = "기록 동기화 중…" }
        else { recordRequest = nil; recordSyncStatus = "연결되면 기록 동기화를 재시도합니다." }
    }

    private func applyArchived(_ record: CaseRecord) -> Bool {
        guard record.apid == apid else { return false }
        // 재전송된 쓰기 영수증/페이지가 더 최신인 로컬 서버 사본을 뒤로 돌리지 않는다.
        if let old = records.byCase(record.caseId), old.archiveEpoch == record.archiveEpoch,
           (old.archiveVersion ?? 0) > (record.archiveVersion ?? 0) { return true }
        guard records.upsert(record) else { return false }
        if !records.pending.contains(where: { $0.caseId == record.caseId }) && !caseEdits.ownsCase(record.caseId) {
            Handover.saveEdits(record.caseId, record.handoverEdits ?? [:])
        }
        recordsRev += 1
        return true
    }

    func handleRecordReply(_ type: String, _ data: Data) {
        guard let reply = try? JSONDecoder().decode(RecordSyncReply.self, from: data),
              let requestId = reply.requestId, recordRequest?.id == requestId else { return }
        recordRequest = nil
        if type == "record_error" {
            recordSyncStatus = reply.error == "unauthorized" ? "기록 동기화 키 또는 구급차 ID를 확인해 주세요." : "기록 동기화 실패 — 다음 연결 때 다시 시도합니다."
            return
        }
        guard reply.apid == apid else { return }
        if type == "record_handover_result", let record = reply.record {
            if reply.conflict == true {
                handoverConflict = record
                _ = applyArchived(record)
                recordSyncStatus = "다른 기기에서 인계확인서를 수정했습니다. 저장할 내용을 선택해 주세요."
                return
            }
            let remaining = records.pending.filter { $0.requestId != requestId }.map { pending in
                pending.caseId == record.caseId
                    ? PendingHandover(caseId: pending.caseId, revision: record.handoverRevision ?? 0, edits: pending.edits)
                    : pending
            }
            guard records.savePending(remaining), applyArchived(record) else {
                recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return
            }
        } else {
            for record in reply.records ?? [] {
                guard applyArchived(record) else { recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return }
            }
            if type == "record_sync_result" {
                guard let epoch = reply.epoch, let cursor = reply.cursor,
                      records.saveCursor(.init(epoch: epoch, cursor: cursor)) else {
                    recordSyncStatus = "기록 동기화 위치를 저장하지 못했습니다."; return
                }
            }
        }
        if reply.hasMore == true || type != "record_sync_result" { syncRecords() }
        else { recordSyncStatus = handoverConflict == nil ? "서버 기록과 동기화됨" : "인계확인서 수정 충돌 확인이 필요합니다." }
    }

    /// 기기에서 저장한 수정은 먼저 파일에 보관하고, 연결이 돌아오면 같은 requestId로 재전송한다.
    func queueHandover(_ caseId: String, edits: [String: String], revision: Int? = nil) {
        let old = records.byCase(caseId)
        let pending = PendingHandover(caseId: caseId, revision: revision ?? old?.handoverRevision ?? 0, edits: edits)
        var outbox = records.pending
        if let index = outbox.firstIndex(where: { $0.caseId == caseId && $0.requestId != recordRequest?.id }) { outbox.remove(at: index) }
        outbox.append(pending)
        guard records.savePending(outbox) else { show("수정 대기열을 저장하지 못했습니다."); return }
        syncRecords()
    }

    func resolveHandover(useMine: Bool) {
        guard let conflict = handoverConflict else { return }
        let mine = records.pending.last { $0.caseId == conflict.caseId }
        var outbox = records.pending.filter { $0.caseId != conflict.caseId }
        if useMine, let mine {
            outbox.append(PendingHandover(caseId: conflict.caseId, revision: conflict.handoverRevision ?? 0, edits: mine.edits))
        }
        guard records.savePending(outbox) else { return }
        if !useMine { Handover.saveEdits(conflict.caseId, conflict.handoverEdits ?? [:]) }
        handoverConflict = nil
        syncRecords()
    }

    /// 이 사건의 지금 상태를 기록에 올린다(없으면 새로, 있으면 갱신). 병원 응답·환자 요약·인계확인서 최종 값을 한 덩이로 둔다
    func snapshotCase(_ id: String) {
        guard let r = result, r.caseId == id else { return }
        let p = r.patientInfo
        let now = Date()
        let old = records.byCase(id)
        // 서버 버전이 있는 복사본은 지연 도착한 실시간 메시지로 덮어쓰지 않는다. 기록 탭은 서버 변경 순번으로만 갱신한다.
        if old?.archiveVersion != nil { return }
        let requestedAt = phaseTimes["requestedAt"].map { $0.timeIntervalSince1970 * 1000 }
        let started = old?.startedAt ?? requestedAt ?? now.timeIntervalSince1970 * 1000
        let confirmedHospital = r.hospitals.first { $0.status == "confirmed" }
        let auto = Handover.auto(patient: p, confirmed: confirmedHospital, ambulanceName: ambulanceName, apid: apid,
                                 times: phaseTimes, incident: sim?.incident, incidentAddress: incidentAddress, bodyCare: bodyEdits.careLines)
        let values = (old?.handover ?? [:]).merging(auto) { _, new in new }.merging(Handover.loadEdits(id)) { _, new in new }
        var record = CaseRecord(
            caseId: id, apid: r.apid ?? apid, ambulanceName: old?.ambulanceName ?? ambulanceName,
            date: RecordDates.of(started), startedAt: started, updatedAt: now.timeIntervalSince1970 * 1000,
            symptom: p?.chiefComplaint ?? p?.expectedDiagnosis, expectedDiagnosis: p?.expectedDiagnosis, ktasLevel: p?.ktasLevel,
            hospitals: r.hospitals.map { RecordHospital(hospitalId: $0.hospitalId, name: $0.name, status: $0.status, rejectReason: $0.rejectReason,
                                                        distanceKm: $0.roadDistanceKm ?? $0.distanceKm, etaMin: $0.etaMin.map(Double.init)) },
            handover: values, closed: old?.closed == true
        )
        record.archiveVersion = old?.archiveVersion
        record.archiveEpoch = old?.archiveEpoch
        record.handoverRevision = old?.handoverRevision
        record.handoverEdits = old?.handoverEdits
        record.events = old?.events
        record.legacyImport = old?.legacyImport
        records.upsert(record)
        recordsRev += 1
    }

    /// 사건이 끝났음을 기록에 남긴다
    func closeRecord(_ id: String) {
        guard let old = records.byCase(id), old.archiveVersion == nil, !old.closed else { return }
        var closed = old; closed.closed = true; closed.updatedAt = Date().timeIntervalSince1970 * 1000
        records.upsert(closed)
        recordsRev += 1
    }
}
