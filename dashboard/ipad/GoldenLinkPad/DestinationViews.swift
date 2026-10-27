import SwiftUI

/// 목적지 카드(2026-10-16) — 구급차 화면 왼쪽, 이송이 확정되면(도착까지) 통화 요약 아래에 뜬다. "지금 가는 병원 상태가 괜찮은가".
/// 병원 이름·도착까지, 응급실 병상(정원 대비)·도착 시 유효 확률(AI, 초 단위 감쇠), 응급의학과 전문의·센터 등급, E-Gen 수용 제한 공지,
/// [배후역량](수술실·중환자실·장비 상세 — hub GET /hospital-backup, 웹 [배후역량] 버튼과 같은 데이터).
struct DestinationCard: View {
    @EnvironmentObject private var model: AppModel
    let h: HospitalMatch
    @State private var backup: HospitalBackup?

    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: model.now) } }
    private var emDoctors: Int? { backup?.specialties.first { $0.department == "응급의학과" }?.doctorCount }

    /// true면 왼쪽 열의 남는 높이를 채운다(구급차 화면, 2026-10-16) — 내용은 위부터, 넘치면 카드 안에서 스크롤
    var fill = false

    var body: some View {
        // fill이면 남는 높이를 '도착 시 유효' 상자가 채운다 — 높이가 모자라면 압축 배치(숫자 한 줄·[배후역량]은 이름 옆),
        // 그래도 안 들어가면 그때만 카드 안 스크롤(2026-10-16)
        Group {
            if fill {
                ViewThatFits(in: .vertical) {
                    inner(expand: true)
                    inner(expand: false, compact: true)
                    ScrollView { inner(expand: false, compact: true) }.scrollIndicators(.hidden)
                }
            } else { inner(expand: false) }
        }
            .frame(maxWidth: .infinity, maxHeight: fill ? .infinity : nil, alignment: .topLeading)
            .card()
            .task(id: h.hospitalId) { backup = await HospitalBackup.fetch(h.hospitalId) }
    }

    private func inner(expand: Bool, compact: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("목적지").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Pill(text: arrivalText, bg: AD.greenSoft, fg: AD.green, bold: true)
            }
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 15, weight: .heavy)).foregroundStyle(AD.navy).lineLimit(1)
                if let lv = h.emergencyLevel, lv.hasSuffix("센터") { Pill(text: lv.hasPrefix("권역") ? "권역센터" : "지역센터", bg: AD.blueSoft, fg: AD.blue) }
            }
            // AI 확률은 가로 절반, 오른쪽 절반에 응급실 병상·응급의학 전문의를 두 줄로(2026-10-27) — 카드가 낮아진
            // 만큼 아래 배후역량표가 길어진다. [배후역량] 버튼은 그 표가 대신해 없앴다
            HStack(alignment: .top, spacing: 8) {
                Group { if compact { arrivalHeroCompact } else { arrivalHero(expand: expand) } }
                    .frame(maxWidth: .infinity)
                VStack(spacing: 8) {
                    bedBox
                    StatBox(label: "응급의학 전문의", value: emDoctors.map { "\($0)명" } ?? "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
                }
                .frame(maxWidth: .infinity)
            }
            notices
        }
    }

    /// 높이가 모자랄 때의 '도착 시 유효' — 숫자 왼쪽, 설명·막대 오른쪽 한 줄
    private var arrivalHeroCompact: some View {
        let t = live.map { Theme.validity($0.rArrive) } ?? (bg: AD.chip, fg: AD.ink3)
        return HStack(spacing: 12) {
            Text(live.map { BedReliability.pct($0.rArrive) } ?? "—").font(.system(size: 32, weight: .black, design: .rounded)).foregroundStyle(t.fg)
                .lineLimit(1).fixedSize()
            VStack(alignment: .leading, spacing: 3) {
                Text("AI · 도착 시 병상 정보 유효").font(.system(size: 11.5, weight: .bold)).foregroundStyle(t.fg)
                if let lv = live {
                    ProbBar(value: lv.rArrive, height: 6)
                    Text("지금 \(BedReliability.pct(lv.authority)) → 도착 시 \(BedReliability.pct(lv.rArrive))\(lv.ageSec.map { " · 정보 \(Labels.age($0))" } ?? "")")
                        .font(.system(size: 11)).foregroundStyle(AD.sub).lineLimit(1).minimumScaleFactor(0.8)
                } else {
                    Text("병상 신뢰도 정보 없음").font(.system(size: 11)).foregroundStyle(AD.sub)
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(t.bg)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    /// AI 도착 시 유효(병상 숫자가 도착 때까지 맞을 확률) — 목적지 카드의 주인공. expand면 남는 높이를 채우고 숫자는 가운데
    @ViewBuilder private func arrivalHero(expand: Bool) -> some View {
        let t = live.map { Theme.validity($0.rArrive) } ?? (bg: AD.chip, fg: AD.ink3)
        VStack(alignment: .leading, spacing: 4) {
            Text("AI · 도착 시 병상 정보 유효").font(.system(size: 13, weight: .bold)).foregroundStyle(t.fg)
            if let lv = live {
                Text(BedReliability.pct(lv.rArrive)).font(.system(size: 46, weight: .black, design: .rounded)).foregroundStyle(t.fg)
                    .lineLimit(1).minimumScaleFactor(0.6)
                ProbBar(value: lv.rArrive, height: 8)
                Text("지금 유효 \(BedReliability.pct(lv.authority)) → 도착 시 \(BedReliability.pct(lv.rArrive))\(lv.ageSec.map { " · 정보 \(Labels.age($0))" } ?? "")")
                    .font(.system(size: 12)).foregroundStyle(AD.sub).lineLimit(1).minimumScaleFactor(0.8)
            } else {
                Text("—").font(.system(size: 46, weight: .black, design: .rounded)).foregroundStyle(t.fg)
                Text("이 병원은 병상 신뢰도 정보가 없습니다").font(.system(size: 12)).foregroundStyle(AD.sub)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(maxWidth: .infinity, maxHeight: expand ? .infinity : nil, alignment: .leading)
        .background(t.bg)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
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
                if msgs.count > 2 { Text("병원 공지 \(msgs.count - 2)건 더 — 아래 배후역량표에서").font(.system(size: 11)).foregroundStyle(AD.muted) }
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

/// 배후역량 표(2026-10-27) — 시트와 구급차 화면 카드가 같이 쓴다. 안내 한 줄 + 병상·장비·전문의·공지 표.
struct BackupTables: View {
    let backup: HospitalBackup?
    /// 카드에서는 안내 문구를 접는다(자리가 좁다 — 시트에서만 보인다)
    var showNote = true

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if showNote {
                Text("보유는 최대치입니다. 지금 쓸 수 있는지는 E-Gen 가용과 병원 수용 승인으로 판단합니다. 장비의 지금 남은 대수는 공개 정보가 없습니다.")
                    .font(.system(size: 12)).foregroundStyle(AD.sub)
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
            }
            if let b = backup {
                BackupSection(title: "병상") {
                    BackupRow(cells: ["", "보유(심평원)", "정원(E-Gen)", "지금 가용", "AI 유효"], header: true)
                    ForEach(b.beds, id: \.key) { r in
                        BackupRow(cells: [r.label, num(r.hiraCapacity), num(r.egenCapacity), num(r.available),
                                          r.authority.map(BedReliability.pct) ?? "—"])
                    }
                }
                BackupSection(title: "장비") {
                    BackupRow(cells: ["", "보유 대수", "운영(E-Gen)"], header: true)
                    ForEach(b.equipment, id: \.key) { r in
                        BackupRow(cells: [r.label, num(r.hiraCount), r.egenOperating.map { $0 == "Y" ? "운영" : "중단" } ?? "—"])
                    }
                }
                if !b.specialties.isEmpty {
                    BackupSection(title: "전문의(심평원)\(b.nursingGrade.map { " · 간호등급 \($0)" } ?? "")") {
                        let docs = b.specialties.sorted { ($0.department == "응급의학과" ? 1 : 0, $0.doctorCount) > ($1.department == "응급의학과" ? 1 : 0, $1.doctorCount) }
                        Text(docs.prefix(12).map { "\($0.department) \($0.doctorCount)" }.joined(separator: " · "))
                            .font(.system(size: 13)).foregroundStyle(AD.ink)
                    }
                }
                if !b.acceptanceMessages.isEmpty {
                    BackupSection(title: "병원 공지(E-Gen 수용 제한)") {
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
    }

    private func num(_ v: Int?) -> String { v.map(String.init) ?? "—" }
}

struct BackupSection<C: View>: View {
    let title: String
    @ViewBuilder let content: () -> C
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy)
            content()
        }
    }
}

struct BackupRow: View {
    let cells: [String]
    var header = false
    var body: some View {
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

struct BackupSheet: View {
    @Environment(\.dismiss) private var dismiss
    let name: String
    @State var backup: HospitalBackup?
    let hospitalId: String

    var body: some View {
        NavigationStack {
            ScrollView {
                BackupTables(backup: backup)
                    .padding(18)
            }
            .navigationTitle("\(name) · 배후역량")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
            .task { if backup == nil { backup = await HospitalBackup.fetch(hospitalId) } }
        }
    }

}

// ── 배후역량표 카드(2026-10-27) — 구급차 화면 오른쪽. 병원 응답 단계엔 추천 병원들을 나란히, 이송이 확정되면 목적지 한 곳을 자세히 ──

/// 이송 확정 전 — 추천 병원들의 배후역량을 한 표로 비교(hub GET /hospital-backup, 병원마다 한 번).
/// 순위는 hub가 보낸 순서 그대로이고, 이 표는 "그 병원이 뒤를 받칠 수 있나"를 보여주는 열람용이다.
struct BackupCompareCard: View {
    let hospitals: [HospitalMatch]
    let recommendedId: String?
    @State private var backups: [String: HospitalBackup] = [:]
    @State private var detail: HospitalMatch?

    /// 병원 리스트 탭과 같은 후보 전부(2026-10-27 — 예전엔 앞 5곳만 보여 리스트와 개수가 달랐다). 넘치면 카드 안에서 스크롤
    private var shown: [HospitalMatch] { hospitals }
    private var signature: String { shown.map(\.hospitalId).joined(separator: ",") }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("추천 병원 배후역량").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                if !shown.isEmpty { Pill(text: "\(shown.count)곳", bg: AD.chip, fg: AD.ink3) }
            }
            if shown.isEmpty {
                Spacer(minLength: 0)
                Text("병원 후보가 오면 배후역량을 비교해 보여줍니다").font(.system(size: 13)).foregroundStyle(AD.muted)
                    .frame(maxWidth: .infinity)
                Spacer(minLength: 0)
            } else {
                BackupRow(cells: ["", "응급실", "수술실", "중환자실", "응급의학", "CT·조영"], header: true)
                Divider().overlay(AD.line)
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(shown) { h in
                            Button { detail = h } label: { row(h) }.buttonStyle(.plain)
                            Divider().overlay(AD.line)
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .card()
        .task(id: signature) {
            for h in shown where backups[h.hospitalId] == nil {
                if let b = await HospitalBackup.fetch(h.hospitalId) { backups[h.hospitalId] = b }
            }
        }
        .sheet(item: $detail) { h in BackupSheet(name: h.name, backup: backups[h.hospitalId], hospitalId: h.hospitalId) }
    }

    private func row(_ h: HospitalMatch) -> some View {
        let b = backups[h.hospitalId]
        let bed = { (key: String) -> HospitalBackup.BedRow? in b?.beds.first { $0.key == key } }
        let er = bed("ER_ADULT"), or = bed("OR"), icu = bed("ICU")
        let em = b?.specialties.first { $0.department == "응급의학과" }?.doctorCount
        let equip = { (key: String) -> Bool? in b?.equipment.first { $0.key == key }?.egenOperating.map { $0 == "Y" } }
        let ct = equip("CT"), angio = equip("ANGIO")
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 13.5, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                if h.hospitalId == recommendedId { Pill(text: "추천", bg: AD.greenSoft, fg: AD.green, bold: true) }
                if h.status == "approved" { Pill(text: "수용 승인", bg: AD.greenSoft, fg: AD.green) }
                Spacer(minLength: 0)
                if b == nil { ProgressView().controlSize(.mini) }
            }
            BackupRow(cells: ["", slash(er?.available, er?.egenCapacity), slash(or?.available, or?.egenCapacity ?? or?.hiraCapacity),
                              slash(icu?.available, icu?.egenCapacity ?? icu?.hiraCapacity), em.map { "\($0)명" } ?? "—",
                              onOff(ct) + "·" + onOff(angio)])
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }

    /// "가용/정원" — 가용을 모르면 정원만, 둘 다 모르면 —
    private func slash(_ available: Int?, _ capacity: Int?) -> String {
        switch (available, capacity) {
        case let (a?, c?): return "\(a)/\(c)"
        case let (a?, nil): return "\(a)"
        case let (nil, c?): return "—/\(c)"
        default: return "—"
        }
    }
    private func onOff(_ v: Bool?) -> String { v == nil ? "—" : (v! ? "O" : "X") }
}

/// 이송 확정 뒤 — 목적지 한 곳의 배후역량표(목적지 카드 아래).
struct BackupDetailCard: View {
    let h: HospitalMatch
    @State private var backup: HospitalBackup?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("배후역량").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Text(h.name).font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.sub).lineLimit(1)
                Spacer(minLength: 0)
            }
            ScrollView { BackupTables(backup: backup, showNote: false) }.scrollIndicators(.hidden)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .card()
        .task(id: h.hospitalId) { backup = await HospitalBackup.fetch(h.hospitalId) }
    }
}
