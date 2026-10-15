import SwiftUI

/// 목적지 카드(2026-10-16) — 구급차 화면 왼쪽, 이송이 확정되면(도착까지) 통화 요약 아래에 뜬다. "지금 가는 병원 상태가 괜찮은가".
/// 병원 이름·도착까지, 응급실 병상(정원 대비)·도착 시 유효 확률(AI, 초 단위 감쇠), 응급의학과 전문의·센터 등급, E-Gen 수용 제한 공지,
/// [배후역량](수술실·중환자실·장비 상세 — hub GET /hospital-backup, 웹 [배후역량] 버튼과 같은 데이터).
struct DestinationCard: View {
    @EnvironmentObject private var model: AppModel
    let h: HospitalMatch
    @State private var backup: HospitalBackup?
    @State private var showBackup = false

    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: model.now) } }
    private var emDoctors: Int? { backup?.specialties.first { $0.department == "응급의학과" }?.doctorCount }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline) {
                Text("목적지").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Pill(text: arrivalText, bg: AD.greenSoft, fg: AD.green, bold: true)
            }
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 15, weight: .heavy)).foregroundStyle(AD.navy).lineLimit(1)
                if let lv = h.emergencyLevel, lv.hasSuffix("센터") { Pill(text: lv.hasPrefix("권역") ? "권역센터" : "지역센터", bg: AD.blueSoft, fg: AD.blue) }
            }
            HStack(spacing: 8) {
                bedBox
                if let lv = live {
                    let t = Theme.validity(lv.rArrive)
                    StatBox(label: "AI 도착 시 유효", value: BedReliability.pct(lv.rArrive), bg: t.bg, fg: t.fg)
                } else {
                    StatBox(label: "AI 도착 시 유효", value: "—", bg: AD.chip, fg: AD.ink3)
                }
                StatBox(label: "응급의학 전문의", value: emDoctors.map { "\($0)명" } ?? "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
            }
            if let lv = live {
                VStack(alignment: .leading, spacing: 3) {
                    Text("AI · 병상 정보 지금 유효 \(BedReliability.pct(lv.authority)) → 도착 시 \(BedReliability.pct(lv.rArrive))\(lv.ageSec.map { " · 정보 \(Labels.age($0))" } ?? "")")
                        .font(.system(size: 11.5)).foregroundStyle(AD.sub).lineLimit(1)
                    ProbBar(value: lv.rArrive, height: 5)
                }
            }
            notices
            Button { showBackup = true } label: {
                HStack(spacing: 6) {
                    Image(systemName: "cross.case").font(.system(size: 13, weight: .semibold))
                    Text("배후역량 — 수술실·중환자실·장비").font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(AD.blue)
                .frame(maxWidth: .infinity, minHeight: 36)
                .background(AD.blueSoft).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
        }
        .card()
        .task(id: h.hospitalId) { backup = await HospitalBackup.fetch(h.hospitalId) }
        .sheet(isPresented: $showBackup) { BackupSheet(name: h.name, backup: backup, hospitalId: h.hospitalId) }
    }

    private var arrivalText: String {
        switch model.sim?.phase {
        case "at_hospital": return "병원 도착"
        case "transporting":
            if let s = model.sim?.etaSec { return s < 60 ? "곧 도착" : "도착까지 약 \(Int((s / 60).rounded()))분" }
            return "이송 중"
        default: return "이송 확정"
        }
    }

    @ViewBuilder private var bedBox: some View {
        let cap = h.erBedCapacity.map { "/\($0)" } ?? ""
        if h.bedCountUnknown == true {
            StatBox(label: "응급실 병상", value: "미상", bg: AD.chip, fg: AD.ink3)
        } else if (h.availableBedCount ?? 0) <= 0 {
            StatBox(label: "응급실 병상", value: h.erBedCapacity != nil ? "0\(cap)" : "없음", bg: AD.redSoft, fg: AD.red)
        } else {
            StatBox(label: h.erOccupancyPct.map { "응급실 \($0)%참" } ?? "응급실 병상",
                    value: h.erBedCapacity != nil ? "\(h.availableBedCount ?? 0)\(cap)" : "\(h.availableBedCount ?? 0)석", bg: AD.limeSoft, fg: AD.lime)
        }
    }

    /// E-Gen 수용 제한 공지 — 이 환자에 해당하는 것(matched)을 위에, 중증 차단은 빨강
    @ViewBuilder private var notices: some View {
        let msgs = (h.acceptanceMessages ?? []).sorted { ($0.matched == true ? 0 : 1) < ($1.matched == true ? 0 : 1) }
        if !msgs.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(msgs.prefix(2).enumerated()), id: \.offset) { _, m in
                    let severe = m.kind == "severe"
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 11)).foregroundStyle(severe ? AD.red : AD.orange)
                        Text("\(m.matched == true ? "이 환자 해당 · " : "")\(m.diseaseName ?? m.department ?? (severe ? "중증질환" : "응급실")) — \(m.message ?? "")")
                            .font(.system(size: 11.5, weight: m.matched == true ? .bold : .regular))
                            .foregroundStyle(severe ? AD.red : AD.ink3).lineLimit(2)
                    }
                }
                if msgs.count > 2 { Text("병원 공지 \(msgs.count - 2)건 더 — [배후역량]에서").font(.system(size: 11)).foregroundStyle(AD.muted) }
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(msgs.contains { $0.kind == "severe" } ? AD.redSoft : AD.orangeSoft)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }
}

// ── 배후역량(hub GET /hospital-backup) — 보유(심평원)·정원(E-Gen)·지금 가용·유효 확률, 장비 보유·운영, 전문의, 공지 ──
struct HospitalBackup: Codable {
    struct BedRow: Codable { var key: String; var label: String; var hiraCapacity: Int?; var egenCapacity: Int?; var available: Int?; var authority: Double?; var note: String? }
    struct EquipRow: Codable { var key: String; var label: String; var hiraCount: Int?; var egenOperating: String?; var note: String? }
    struct Doctor: Codable { var department: String; var doctorCount: Int }
    struct Notice: Codable { var kind: String?; var message: String?; var department: String?; var diseaseName: String? }
    var beds: [BedRow] = []
    var equipment: [EquipRow] = []
    var specialties: [Doctor] = []
    var nursingGrade: String?
    var acceptanceMessages: [Notice] = []
    var inFlightCount: Int?

    static func fetch(_ hospitalId: String) async -> HospitalBackup? {
        guard let url = Settings.backupURL(hospitalId) else { return nil }
        var req = URLRequest(url: url); req.timeoutInterval = 15
        guard let (data, resp) = try? await URLSession.shared.data(for: req), (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONDecoder().decode(HospitalBackup.self, from: data)
    }
}

struct BackupSheet: View {
    @Environment(\.dismiss) private var dismiss
    let name: String
    @State var backup: HospitalBackup?
    let hospitalId: String

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("보유는 최대치입니다. 지금 쓸 수 있는지는 E-Gen 가용과 병원 수용 승인으로 판단합니다. 장비의 지금 남은 대수는 공개 정보가 없습니다.")
                        .font(.system(size: 12)).foregroundStyle(AD.sub)
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
                    if let b = backup {
                        section("병상") {
                            row(["", "보유(심평원)", "정원(E-Gen)", "지금 가용", "AI 유효"], header: true)
                            ForEach(b.beds, id: \.key) { r in
                                row([r.label, num(r.hiraCapacity), num(r.egenCapacity), num(r.available), r.authority.map(BedReliability.pct) ?? "—"])
                            }
                        }
                        section("장비") {
                            row(["", "보유 대수", "운영(E-Gen)"], header: true)
                            ForEach(b.equipment, id: \.key) { r in
                                row([r.label, num(r.hiraCount), r.egenOperating.map { $0 == "Y" ? "운영" : "중단" } ?? "—"])
                            }
                        }
                        if !b.specialties.isEmpty {
                            section("전문의(심평원)\(b.nursingGrade.map { " · 간호등급 \($0)" } ?? "")") {
                                let docs = b.specialties.sorted { ($0.department == "응급의학과" ? 1 : 0, $0.doctorCount) > ($1.department == "응급의학과" ? 1 : 0, $1.doctorCount) }
                                Text(docs.prefix(12).map { "\($0.department) \($0.doctorCount)" }.joined(separator: " · "))
                                    .font(.system(size: 13)).foregroundStyle(AD.ink)
                            }
                        }
                        if !b.acceptanceMessages.isEmpty {
                            section("병원 공지(E-Gen 수용 제한)") {
                                ForEach(Array(b.acceptanceMessages.enumerated()), id: \.offset) { _, m in
                                    Text("• \(m.diseaseName ?? m.department ?? "") \(m.message ?? "")").font(.system(size: 12.5))
                                        .foregroundStyle(m.kind == "severe" ? AD.red : AD.ink3)
                                }
                            }
                        }
                    } else {
                        ProgressView("배후역량을 불러오는 중…").frame(maxWidth: .infinity).padding(.top, 30)
                    }
                }
                .padding(18)
            }
            .navigationTitle("\(name) · 배후역량")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
            .task { if backup == nil { backup = await HospitalBackup.fetch(hospitalId) } }
        }
    }

    private func num(_ v: Int?) -> String { v.map(String.init) ?? "—" }
    private func section<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy)
            content()
        }
    }
    private func row(_ cells: [String], header: Bool = false) -> some View {
        HStack(spacing: 6) {
            ForEach(Array(cells.enumerated()), id: \.offset) { i, c in
                Text(c).font(.system(size: header ? 11 : 12.5, weight: i == 0 || header ? .semibold : .regular))
                    .foregroundStyle(header ? AD.muted : i == 0 ? AD.navy : AD.ink)
                    .frame(maxWidth: .infinity, alignment: i == 0 ? .leading : .trailing)
            }
        }
        .padding(.vertical, 3)
    }
}
