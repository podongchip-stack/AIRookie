import Foundation
import SwiftUI

/// 현재 사건의 수동 수정만 공유한다. 통화 원문·서버 자동값은 별도 match_result로 받는다.
@MainActor final class CaseEditSync: ObservableObject {
    struct Request: Codable {
        var type = "live_case_patch"
        var requestId = UUID().uuidString
        let caseId: String
        var base: [String: String]
        var changes: [String: String?]
        var ticket: String?
    }
    struct Get: Encodable { let type = "live_case_get"; let caseId: String; var ticket: String? }
    struct State: Decodable {
        let caseId: String
        let apid: String?
        let fields: [String: String]?
        let version: Int?
        let epoch: String?
        let requestId: String?
        let conflicts: [String]?
        let error: String?
        let ticket: String?
        let handoverRevision: Int?
    }
    @Published private(set) var fields: [String: String] = [:]
    @Published private(set) var status = "기기 간 수정 동기화 대기"
    @Published private(set) var conflicts: [String] = []
    @Published private(set) var pendingCount = 0
    var onUpdate: (() -> Void)?
    private var serverFields: [String: String] = [:]
    private var queue: [Request] = []
    private var active: String?
    private var unit: String?
    private var key = ""
    private var ready = false
    private var version = -1
    private var epoch = ""
    private var sent: String?
    private var lastAttempt = Date.distantPast
    private var sender: ((Data) -> Bool)?
    private var legacy: [String: String] = [:]
    private var conflictState: State?

    var handover: [String: String] { Dictionary(uniqueKeysWithValues: fields.filter { $0.key.hasPrefix("h:") }.map { (String($0.key.dropFirst(2)), $0.value) }) }
    func hasPending(_ caseId: String) -> Bool { queue.contains { $0.caseId == caseId } }
    func ownsCase(_ caseId: String) -> Bool { active == caseId }

    func activate(caseId: String?, apid: String?, server: String, initialHandover: [String: String] = [:], send: @escaping (Data) -> Bool) {
        sender = send
        let scope = "goldenlink.live-edits." + server + "." + (apid ?? "")
        if key != scope {
            key = scope
            queue = UserDefaults.standard.data(forKey: key).flatMap { try? JSONDecoder().decode([Request].self, from: $0) } ?? []
        }
        guard active != caseId || unit != apid else { return }
        active = caseId; unit = apid; ready = false; version = -1; epoch = ""; sent = nil
        legacy = initialHandover
        serverFields = caseId.flatMap { UserDefaults.standard.dictionary(forKey: key + ".cache." + $0) as? [String: String] } ?? [:]
        fields = serverFields; conflicts = []; project()
        refresh(); flush()
    }
    func refresh() {
        guard let active, let data = try? JSONEncoder().encode(Get(caseId: active, ticket: UserDefaults.standard.string(forKey: key + ".ticket." + active))) else { return }
        lastAttempt = Date()
        if sender?(data) != true { status = "연결되면 수정을 동기화합니다." }
    }
    func reconnect() { ready = false; sent = nil; refresh(); flush() }
    func tick() {
        guard Date().timeIntervalSince(lastAttempt) > 10 else { return }
        sent = nil
        if conflicts.isEmpty { flush() }
        refresh()
    }
    @discardableResult func submit(caseId: String, changes: [String: String?], base: [String: String]) -> Bool {
        guard caseId == active, !changes.isEmpty else { return changes.isEmpty }
        // 같은 칸을 되돌리는 nil도 JSON에 명시적으로 남겨, 자동값으로 초기화할 수 있다.
        queue.append(Request(caseId: caseId, base: base, changes: changes, ticket: UserDefaults.standard.string(forKey: key + ".ticket." + caseId)))
        persist(); project(); flush()
        return true
    }
    func accept(_ data: Data) {
        guard let state = try? JSONDecoder().decode(State.self, from: data),
              state.apid == nil || state.apid == unit else { return }
        guard state.caseId == active || queue.contains(where: { $0.requestId == state.requestId }) else { return }
        if let error = state.error {
            sent = nil
            handleError(error, state)
            return
        }
        guard let values = state.fields else { return }
        if let ticket = state.ticket { UserDefaults.standard.set(ticket, forKey: key + ".ticket." + state.caseId) }
        // 종료 직전에 저장한 대기열의 영수증은 현재 사건 화면에 섞지 않는다.
        if state.caseId != active {
            if let id = state.requestId, let i = queue.firstIndex(where: { $0.requestId == id }) {
                sent = nil
                if let keys = state.conflicts, !keys.isEmpty {
                    conflicts = keys; conflictState = state
                    status = "이전 사건 수정이 다른 기기와 겹칩니다. 저장할 값을 선택하세요."
                } else { queue.remove(at: i); persist(); project(); flush() }
            }
            return
        }
        if state.epoch != epoch || (state.version ?? -1) >= version {
            serverFields = values; version = state.version ?? 0; epoch = state.epoch ?? ""
            UserDefaults.standard.set(values, forKey: key + ".cache." + state.caseId)
        }
        ready = true
        let migrationKey = key + ".migrated." + state.caseId
        if !UserDefaults.standard.bool(forKey: migrationKey) {
            // 기존 기기의 수동 수정은 최초 한 번만 이관한다. 새 서버값이 있으면 그것이 우선이다.
            let queuedKeys = Set(queue.filter { $0.caseId == state.caseId }.flatMap { $0.changes.keys })
            let imported = legacy.filter { (state.handoverRevision ?? 0) == 0 && serverFields["h:" + $0.key] == nil && !queuedKeys.contains("h:" + $0.key) }
            if !imported.isEmpty {
                let changes = Dictionary(uniqueKeysWithValues: imported.map { ("h:" + $0.key, Optional($0.value)) })
                queue.append(Request(caseId: state.caseId, base: serverFields, changes: changes)); persist()
            }
            UserDefaults.standard.set(true, forKey: migrationKey)
        }
        if let id = state.requestId, let index = queue.firstIndex(where: { $0.requestId == id }) {
            sent = nil
            if let keys = state.conflicts, !keys.isEmpty {
                conflicts = keys; conflictState = state; status = "다른 기기에서 같은 칸을 수정했습니다. 저장할 값을 선택하세요."
            } else {
                let completed = queue.remove(at: index)
                // 같은 기기에서 연속 저장한 다음 수정의 기준만 전진한다.
                for i in queue.indices where queue[i].caseId == state.caseId {
                    for (k, v) in completed.changes where queue[i].base[k] == completed.base[k] {
                        queue[i].base[k] = v
                    }
                }
                conflicts = []; persist()
            }
        }
        project()
        if conflicts.isEmpty { flush() }
    }
    /// hub가 거절한 이유별로 다르게 다룬다 — 영영 안 들어갈 수정은 대기열에서 치워야 "동기화 실패" 안내가 계속 남지 않는다
    private func handleError(_ error: String, _ state: State) {
        switch error {
        case "paused":
            status = "일시정지 해제 후 수정이 동기화됩니다."
        case "not_owner":
            // 이 구급대 사건이 아니거나 끝난 사건(보관 증표도 없음) — 다시 보내도 같은 답이라 그 사건의 대기 수정을 지운다.
            // 지금 보는 사건이면 hub가 아직 사건을 모르는 것일 수 있어(재시작 직후 등) 지우지 않고 다시 시도한다
            if state.caseId != active {
                queue.removeAll { $0.caseId == state.caseId }; persist(); project()
                status = "끝난 사건의 수정은 동기화할 수 없어 지웠습니다."
            } else {
                status = "hub가 이 사건을 알지 못합니다 · 재연결하면 다시 시도합니다."
            }
        case "invalid_patch":
            // 형식이 맞지 않거나 너무 큰 수정 — 다시 보내도 같다
            queue.removeAll { $0.requestId == state.requestId }; persist(); project()
            status = "수정 내용이 형식에 맞지 않아 보내지 못했습니다(그 수정은 지웠습니다)."
        case "storage_unavailable":
            status = "hub 저장소 오류 · 잠시 뒤 다시 시도합니다."
        default:
            status = "수정 동기화 실패(" + error + ") · 재연결 시 재시도합니다."
        }
    }

    func resolve(useMine: Bool) {
        guard let state = conflictState, let i = queue.firstIndex(where: { $0.requestId == state.requestId }), !conflicts.isEmpty else { return }
        if useMine { queue[i].base = state.fields ?? [:]; queue[i].requestId = UUID().uuidString }
        else { queue.remove(at: i) }
        sent = nil; conflicts = []; conflictState = nil; persist(); project(); flush()
    }
    private func project() {
        pendingCount = queue.count
        var projected = ready ? serverFields : Dictionary(uniqueKeysWithValues: legacy.map { ("h:" + $0.key, $0.value) }).merging(serverFields) { _, server in server }
        for request in queue where request.caseId == active {
            for (k,v) in request.changes { projected[k] = v }
        }
        fields = projected
        if conflicts.isEmpty { status = !queue.isEmpty ? "수정 \(queue.count)건 저장됨 · 다른 기기에 전달 대기" : ready ? "아이폰·아이패드 수정 동기화됨" : "기기 간 수정 동기화 대기" }
        if ready || hasPending(active ?? "") { onUpdate?() }
    }
    private func persist() {
        if let data = try? JSONEncoder().encode(queue) { UserDefaults.standard.set(data, forKey: key) }
    }
    private func flush() {
        guard conflicts.isEmpty, sent == nil,
              let i = queue.firstIndex(where: { ($0.caseId == active && ready) || $0.ticket != nil }) else { return }
        if queue[i].ticket == nil { queue[i].ticket = UserDefaults.standard.string(forKey: key + ".ticket." + queue[i].caseId); persist() }
        let request = queue[i]
        guard let data = try? JSONEncoder().encode(request) else { return }
        lastAttempt = Date()
        if sender?(data) == true { sent = request.requestId }
        else { status = "수정 저장됨 · 연결되면 다시 전송합니다." }
    }
}

struct CaseEditStatusView: View {
    @ObservedObject var sync: CaseEditSync
    var onlyPending = false
    var body: some View {
        if !onlyPending || sync.pendingCount > 0 || !sync.conflicts.isEmpty {
        VStack(alignment: .leading, spacing: 8) {
            Text(sync.status).font(.system(size: 12)).foregroundStyle(sync.conflicts.isEmpty ? Color.secondary : Color.orange)
            if !sync.conflicts.isEmpty {
                HStack {
                    Button("서버 값 사용") { sync.resolve(useMine: false) }
                    Button("내 수정으로 다시 저장") { sync.resolve(useMine: true) }
                }.font(.system(size: 13, weight: .semibold))
            }
        }
        }
    }
}

struct SharedBodyValue: Codable { let added: Bool; let removed: Bool; let cares: [String] }
