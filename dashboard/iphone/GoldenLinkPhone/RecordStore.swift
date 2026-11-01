import Foundation
import CryptoKit
import GoldenLinkCore

/// 서버/구급차별 로컬 복사본. 페이지 저장이 성공해야 커서를 전진시킨다.
final class RecordStore {
    private let root: URL
    private var dir: URL
    private(set) var apid: String?
    private var caseDates: [String: Set<String>] = [:]
    private var legacyIds: Set<String> = []
    struct Cursor: Codable { var epoch: String?; var cursor = 0 }

    init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        root = docs.appendingPathComponent("records", isDirectory: true)
        dir = root.appendingPathComponent("unselected", isDirectory: true)
    }

    func configure(apid: String?) {
        self.apid = apid
        let scope = (Settings.httpBase?.absoluteString ?? "") + "|" + (apid ?? "unselected")
        let digest = SHA256.hash(data: Data(scope.utf8)).map { String(format: "%02x", $0) }.joined()
        dir = root.appendingPathComponent(digest, isDirectory: true)
        caseDates = [:]; legacyIds = []
        for date in dates() {
            for record in load(date) {
                caseDates[record.caseId, default: []].insert(date)
                if record.archiveVersion == nil { legacyIds.insert(record.caseId) }
            }
        }
        // 기존 앱의 날짜별 파일은 첫 연결 서버로 이관할 복사본을 만든다. 원본은 삭제하지 않는다.
        guard let apid else { return }
        let oldDates = ((try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []).filter { $0.range(of: #"^\d{4}-\d{2}-\d{2}\.json$"#, options: .regularExpression) != nil }
        for name in oldDates {
            guard let data = try? Data(contentsOf: root.appendingPathComponent(name)), let list = try? JSONDecoder().decode([CaseRecord].self, from: data) else { continue }
            for record in list where record.apid == apid && byCase(record.caseId) == nil { _ = upsert(record) }
        }
    }

    func dates() -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        return names.filter { $0.range(of: #"^\d{4}-\d{2}-\d{2}\.json$"#, options: .regularExpression) != nil }.map { String($0.dropLast(5)) }.sorted()
    }
    func load(_ date: String) -> [CaseRecord] {
        guard date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else { return [] }
        return (read([CaseRecord].self, name: "\(date).json") ?? []).filter { $0.apid == apid }.sorted { $0.startedAt > $1.startedAt }
    }
    func all() -> [CaseRecord] { dates().flatMap { load($0) } }
    func byCase(_ caseId: String) -> CaseRecord? {
        // 연결 때 만든 사건→날짜 색인으로 조회한다. 매번 전체 기록을 읽지 않는다.
        (caseDates[caseId] ?? []).flatMap { load($0) }.filter { $0.caseId == caseId }.max { $0.updatedAt < $1.updatedAt }
    }
    func legacyRecords() -> [CaseRecord] { legacyIds.sorted().prefix(20).compactMap { byCase($0) } }
    @discardableResult
    func upsert(_ record: CaseRecord) -> Bool {
        guard record.apid == apid, record.date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else { return false }
        // 새 날짜 파일 저장 후에만 예전 날짜의 사본을 정리한다. 실패하면 커서를 유지하고 재시도한다.
        guard write(load(record.date).filter { $0.caseId != record.caseId } + [record], name: "\(record.date).json") else { return false }
        for date in caseDates[record.caseId] ?? [] where date != record.date {
            let list = load(date)
            if list.contains(where: { $0.caseId == record.caseId }),
               !write(list.filter { $0.caseId != record.caseId }, name: "\(date).json") { return false }
        }
        caseDates[record.caseId] = [record.date]
        if record.archiveVersion == nil { legacyIds.insert(record.caseId) } else { legacyIds.remove(record.caseId) }
        return true
    }
    var cursor: Cursor { read(Cursor.self, name: "cursor.json") ?? Cursor() }
    func saveCursor(_ value: Cursor) -> Bool { write(value, name: "cursor.json") }
    var pending: [PendingHandover] { read([PendingHandover].self, name: "outbox.json") ?? [] }
    func savePending(_ value: [PendingHandover]) -> Bool { write(value, name: "outbox.json") }

    private func read<T: Decodable>(_ type: T.Type, name: String) -> T? {
        guard let data = try? Data(contentsOf: dir.appendingPathComponent(name)) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    private func write<T: Encodable>(_ value: T, name: String) -> Bool {
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try JSONEncoder().encode(value).write(to: dir.appendingPathComponent(name), options: [.atomic, .completeFileProtection])
            return true
        } catch { return false }
    }
}
