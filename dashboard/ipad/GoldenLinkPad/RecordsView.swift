import SwiftUI

// [기록] 화면 — 날짜별 사건 목록(왼쪽)과 선택한 사건의 병원 응답 이력(오른쪽). 아이폰·안드로이드 [기록] 탭과 같은 데이터이고
// 태블릿 폭에 맞춰 두 칸으로 나눴다(2026-11-02). hub 보관소와 변경 순번으로 동기화한 구급차별 로컬 복사본이라 오프라인에서도 조회한다.

private func groupColors(_ g: ResponseGroup) -> (fg: Color, bg: Color) {
    switch g {
    case .confirmed: (AD.green, AD.greenSoft)
    case .approved: (AD.blue, AD.blueSoft)
    case .rejected: (AD.red, AD.redSoft)
    case .noReply: (AD.ink3, AD.chip)
    }
}

struct RecordsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var selectedDate: String?
    @State private var selectedCase: String?

    var body: some View {
        let _ = model.recordsRev   // 기록이 바뀌면 다시 읽는다
        let dates = model.records.dates()
        VStack(spacing: 10) {
            statusBar
            if dates.isEmpty {
                empty
            } else {
                let today = RecordDates.of(Date().timeIntervalSince1970 * 1000)
                let date = selectedDate.flatMap { dates.contains($0) ? $0 : nil } ?? (dates.contains(today) ? today : dates.last!)
                let idx = dates.firstIndex(of: date) ?? dates.count - 1
                let cases = model.records.load(date)
                let current = cases.first { $0.caseId == selectedCase } ?? cases.first
                HStack(alignment: .top, spacing: 14) {
                    VStack(spacing: 10) {
                        dateBar(dates: dates, date: date, idx: idx)
                        Text("사건 \(cases.count)건").font(.system(size: 12)).foregroundStyle(AD.ink3).frame(maxWidth: .infinity, alignment: .leading)
                        ScrollView {
                            LazyVStack(spacing: 8) {
                                ForEach(cases) { c in
                                    CaseRow(c: c, on: c.caseId == current?.caseId).onTapGesture { selectedCase = c.caseId }
                                }
                            }
                        }
                    }
                    .padding(14).frame(width: 380).frame(maxHeight: .infinity, alignment: .top).card(0)
                    CaseDetail(c: current).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
        }
        .onAppear { model.syncRecords() }
    }

    private var statusBar: some View {
        VStack(spacing: 8) {
            HStack {
                Text(model.recordSyncStatus).font(.system(size: 12)).foregroundStyle(AD.sub)
                Spacer()
                Button { model.syncRecords() } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("기록 동기화")
            }
            if model.handoverConflict != nil {
                VStack(spacing: 8) {
                    Text("다른 기기의 인계확인서 수정과 겹칩니다. 내 수정은 기기에 보관되어 있습니다.").font(.system(size: 13))
                    HStack {
                        Button("서버 기록 사용") { model.resolveHandover(useMine: false) }
                        Spacer()
                        Button("내 수정으로 다시 저장") { model.resolveHandover(useMine: true) }
                    }.font(.system(size: 13, weight: .bold))
                }.card()
            }
        }
    }

    private var empty: some View {
        VStack(spacing: 12) {
            Image(systemName: "clock.arrow.circlepath").font(.system(size: 48, weight: .semibold)).foregroundStyle(AD.gray)
            Text("아직 기록이 없습니다").font(.system(size: 24, weight: .black)).foregroundStyle(AD.navy)
            Text("사건이 진행되면 병원 응답 이력이 날짜별로 여기에 쌓입니다.").font(.system(size: 14)).foregroundStyle(AD.sub)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity).card(32)
    }

    private func dateBar(dates: [String], date: String, idx: Int) -> some View {
        HStack(spacing: 8) {
            arrow(left: true, enabled: idx > 0) { selectedDate = dates[idx - 1]; selectedCase = nil }
            Menu {
                ForEach(dates.reversed(), id: \.self) { d in Button(d) { selectedDate = d; selectedCase = nil } }
            } label: {
                Text(date).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy).frame(maxWidth: .infinity)
                    .padding(.vertical, 10).background(AD.blueSoft, in: Capsule())
            }
            arrow(left: false, enabled: idx < dates.count - 1) { selectedDate = dates[idx + 1]; selectedCase = nil }
        }
    }

    private func arrow(left: Bool, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: left ? "chevron.left" : "chevron.right").foregroundStyle(enabled ? AD.navy : AD.control)
                .frame(width: 40, height: 40).background(AD.chip, in: Circle())
        }.buttonStyle(.plain).disabled(!enabled)
    }
}

/// 사건 한 줄 — 시각·증상·응답 집계
private struct CaseRow: View {
    let c: CaseRecord
    let on: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(RecordDates.timeOf(c.startedAt))  \(c.symptom ?? c.expectedDiagnosis ?? "증상 미상")")
                        .font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy).lineLimit(2)
                    Text([c.ambulanceName, "병원 \(c.hospitals.count)곳"].compactMap { $0 }.joined(separator: " · "))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3)
                }
                Spacer()
                if let k = c.ktasLevel { Pill(text: "KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
            }
            HStack(spacing: 6) {
                ForEach(ResponseGroup.allCases, id: \.label) { g in
                    let n = c.count(g)
                    if n > 0 { let col = groupColors(g); Pill(text: "\(g.label) \(n)", bg: col.bg, fg: col.fg, bold: true) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(on ? AD.blueSoft : AD.chip, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
    }
}

/// 선택한 사건의 응답 그룹별 병원과 병원별 응답 이력
private struct CaseDetail: View {
    let c: CaseRecord?

    var body: some View {
        if let c {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("\(c.date) \(RecordDates.timeOf(c.startedAt)) · \(c.symptom ?? c.expectedDiagnosis ?? "증상 미상")")
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(AD.navy)
                    if c.legacyImport == true {
                        Text("기존 기기에서 이관한 기록으로, 이관 전 응답 변경 이력은 포함되지 않을 수 있습니다.")
                            .font(.system(size: 12)).foregroundStyle(AD.sub)
                    }
                    ForEach(ResponseGroup.allCases, id: \.label) { group in
                        let hospitals = c.hospitals.filter { $0.group == group }
                        if !hospitals.isEmpty {
                            let col = groupColors(group)
                            Text("\(group.label) \(hospitals.count)곳").font(.system(size: 13, weight: .bold)).foregroundStyle(col.fg)
                            ForEach(hospitals) { h in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text(h.name).font(.system(size: 15, weight: .semibold)).foregroundStyle(AD.ink).lineLimit(1)
                                        Spacer()
                                        if group == .rejected { Text(Labels.reject(h.rejectReason)).font(.system(size: 12)).foregroundStyle(col.fg) }
                                    }
                                    ForEach((c.events ?? []).filter { $0.hospitalId == h.hospitalId }) { RecordEventRow(event: $0) }
                                }
                                .padding(.horizontal, 12).padding(.vertical, 10)
                                .background(col.bg, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                        }
                    }
                    let others = (c.events ?? []).filter { e in !c.hospitals.contains { $0.hospitalId == e.hospitalId } }
                    if !others.isEmpty {
                        Text("기타 병원 응답 이력").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.ink3)
                        ForEach(others) { e in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(e.hospitalId).font(.system(size: 14, weight: .semibold))
                                RecordEventRow(event: e)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .card(0)
        } else {
            Text("왼쪽에서 사건을 고르세요").font(.system(size: 14)).foregroundStyle(AD.sub)
                .frame(maxWidth: .infinity, maxHeight: .infinity).card(32)
        }
    }
}

private struct RecordEventRow: View {
    let event: HospitalRecordEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(event.label + " · " + event.actor).font(.system(size: 13, weight: .semibold))
            Text(event.timestamp).font(.system(size: 11)).foregroundStyle(AD.sub)
            if let reason = event.reason { Text(Labels.reject(reason)).font(.system(size: 12)) }
        }
    }
}
