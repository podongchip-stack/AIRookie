import GoldenLinkCore
import SwiftUI

// [기록] 탭 — 날짜별 사건 목록과 병원 응답(이송 확정·수용 승인·거부·무응답), 병원별 응답 이력.
// hub 보관소와 변경 순번으로 동기화한 구급차별 로컬 복사본. 오프라인에서도 조회한다.

private func groupColors(_ g: ResponseGroup) -> (Color, Color) {
    switch g {
    case .confirmed: (AD.green, AD.greenSoft)
    case .approved: (AD.blue, AD.blueSoft)
    case .rejected: (AD.red, AD.redSoft)
    case .noReply: (AD.ink3, AD.chip)
    }
}

struct RecordsTab: View {
    @Environment(PhoneModel.self) private var m
    @State private var selected: String?
    @State private var openCase: String?
    @State private var picking = false
    @State private var responseLog: CaseRecord?

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Text(m.recordSyncStatus).font(.system(size: 11)).foregroundStyle(AD.sub)
                Spacer()
                Button { m.syncRecords() } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("기록 동기화")
            }
            if m.handoverConflict != nil {
                Card {
                    VStack(spacing: 8) {
                        Text("다른 기기의 인계확인서 수정과 겹칩니다. 내 수정은 기기에 보관되어 있습니다.").font(.system(size: 12))
                        HStack {
                            Button("서버 기록 사용") { m.resolveHandover(useMine: false) }
                            Spacer()
                            Button("내 수정으로 다시 저장") { m.resolveHandover(useMine: true) }
                        }.font(.system(size: 12, weight: .bold))
                    }
                }
            }
            content
        }
        .onAppear { m.syncRecords() }
    }

    @ViewBuilder private var content: some View {
        let _ = m.recordsRev  // 기록이 바뀌면 다시 읽는다
        let dates = m.records.dates()
        if dates.isEmpty {
            StatusPanel(icon: "clock.arrow.circlepath", tint: AD.gray, title: "아직 기록이 없습니다",
                        detail: "사건이 진행되면 병원 응답 이력이 날짜별로 여기에 쌓입니다.")
        } else {
            let date = selected.flatMap { dates.contains($0) ? $0 : nil } ?? (dates.contains(RecordDates.of(Date().timeIntervalSince1970 * 1000)) ? RecordDates.of(Date().timeIntervalSince1970 * 1000) : dates.last!)
            let idx = dates.firstIndex(of: date) ?? dates.count - 1
            let cases = m.records.load(date)
            VStack(spacing: 10) {
                HStack(spacing: 8) {
                    arrowButton(left: true, enabled: idx > 0) { selected = dates[idx - 1] }
                    Text(date).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy).frame(maxWidth: .infinity)
                        .padding(.vertical, 10).background(AD.blueSoft, in: Capsule())
                        .onTapGesture { picking = true }
                    arrowButton(left: false, enabled: idx < dates.count - 1) { selected = dates[idx + 1] }
                }
                Text("사건 \(cases.count)건").font(.system(size: 12)).foregroundStyle(AD.ink3).frame(maxWidth: .infinity, alignment: .leading)
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(cases) { c in
                            CaseCard(c: c, expanded: openCase == c.caseId, onToggle: { openCase = openCase == c.caseId ? nil : c.caseId },
                                     onMore: { responseLog = c })
                        }
                    }
                    .padding(.bottom, 8)
                }
            }
            .sheet(isPresented: $picking) { datePicker(dates: dates, selected: date) }
            .sheet(item: $responseLog) { c in
                CaseResponseLog(c: c)
            }
        }
    }

    private func arrowButton(left: Bool, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: left ? "chevron.left" : "chevron.right").foregroundStyle(enabled ? AD.navy : AD.control)
                .frame(width: 40, height: 40).background(AD.chip, in: Circle())
        }.buttonStyle(.plain).disabled(!enabled)
    }

    private func datePicker(dates: [String], selected current: String) -> some View {
        NavigationStack {
            List(dates.reversed(), id: \.self) { d in
                Button { selected = d; picking = false } label: {
                    HStack { Text(d); Spacer(); if d == current { Image(systemName: "checkmark").foregroundStyle(AD.blue) } }
                }
            }
            .navigationTitle("날짜 선택")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { picking = false } } }
        }
    }
}

/// 사건 하나 — 접힌 상태엔 시각·증상·응답 집계, 펼치면 응답 그룹별 병원
private struct CaseCard: View {
    let c: CaseRecord
    let expanded: Bool
    let onToggle: () -> Void
    let onMore: () -> Void

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(RecordDates.timeOf(c.startedAt))  \(c.symptom ?? c.expectedDiagnosis ?? "증상 미상")")
                            .font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy).lineLimit(2)
                        Text([c.ambulanceName, "병원 \(c.hospitals.count)곳"].compactMap { $0 }.joined(separator: " · "))
                            .font(.system(size: 12)).foregroundStyle(AD.ink3)
                    }
                    Spacer()
                    if let k = c.ktasLevel { Pill(text: "KTAS \(k)", fg: ktasColor(k), bg: ktasSoft(k), bold: true) }
                }
                .contentShape(Rectangle())
                .onTapGesture(perform: onToggle)
                HStack(spacing: 6) {
                    ForEach(ResponseGroup.allCases, id: \.label) { g in
                        let n = c.count(g)
                        if n > 0 { let (fg, bg) = groupColors(g); Pill(text: "\(g.label) \(n)", fg: fg, bg: bg, bold: true) }
                    }
                }
                if expanded {
                    ForEach(ResponseGroup.allCases, id: \.label) { g in
                        let list = c.hospitals.filter { $0.group == g }
                        if !list.isEmpty {
                            let (fg, bg) = groupColors(g)
                            Text("\(g.label) \(list.count)곳").font(.system(size: 12, weight: .bold)).foregroundStyle(fg)
                            ForEach(g == .noReply ? Array(list.prefix(3)) : list) { h in
                                HStack(spacing: 8) {
                                    Text(h.name).font(.system(size: 14, weight: .semibold)).foregroundStyle(AD.ink).lineLimit(1)
                                    Spacer()
                                    if g == .rejected { Text(DisplayLabels.reject(h.rejectReason)).font(.system(size: 12)).foregroundStyle(fg) }
                                }
                                .padding(.horizontal, 12).padding(.vertical, 10)
                                .background(bg, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                        }
                    }
                    Button(action: onMore) {
                        HStack {
                            Text("더보기 · 전체 병원 응답 이력")
                            Spacer()
                            Image(systemName: "chevron.right")
                        }
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(AD.blue)
                        .padding(.vertical, 12)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

/// 현재 응답 상태별 전체 병원과, 상태가 바뀌기 전의 승인·거절까지 함께 보존한 이력.
private struct CaseResponseLog: View {
    @Environment(\.dismiss) private var dismiss
    let c: CaseRecord

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("\(c.date) \(RecordDates.timeOf(c.startedAt)) · \(c.symptom ?? c.expectedDiagnosis ?? "증상 미상")")
                        .font(.system(size: 14, weight: .semibold))
                    if c.legacyImport == true {
                        Text("기존 기기에서 이관한 기록으로, 이관 전 응답 변경 이력은 포함되지 않을 수 있습니다.")
                            .font(.system(size: 12)).foregroundStyle(AD.sub)
                    }
                }
                ForEach(ResponseGroup.allCases, id: \.label) { group in
                    let hospitals = c.hospitals.filter { $0.group == group }
                    if !hospitals.isEmpty {
                        Section("\(group.label) \(hospitals.count)곳") {
                            ForEach(hospitals) { hospital in
                                VStack(alignment: .leading, spacing: 8) {
                                    let (fg, _) = groupColors(group)
                                    Text(hospital.name).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                                    Text(group.label).font(.system(size: 12, weight: .semibold)).foregroundStyle(fg)
                                    if group == .rejected {
                                        Text("사유: \(DisplayLabels.reject(hospital.rejectReason))").font(.system(size: 12))
                                    }
                                    let events = (c.events ?? []).filter { $0.hospitalId == hospital.hospitalId }
                                    if events.isEmpty {
                                        Text(group == .noReply ? "기록된 병원 응답이 없습니다." : "상세 응답 이력이 없습니다.")
                                            .font(.system(size: 12)).foregroundStyle(AD.sub)
                                    } else {
                                        ForEach(events) { event in
                                            RecordEventRow(event: event)
                                        }
                                    }
                                }
                                .padding(.vertical, 6)
                            }
                        }
                    }
                }
                let otherEvents = (c.events ?? []).filter { event in !c.hospitals.contains { $0.hospitalId == event.hospitalId } }
                if !otherEvents.isEmpty {
                    Section("기타 병원 응답 이력") {
                        ForEach(otherEvents) { event in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(event.hospitalId).font(.system(size: 14, weight: .semibold))
                                RecordEventRow(event: event)
                            }
                        }
                    }
                }
            }
            .navigationTitle("전체 병원 응답 이력")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
        }
        .presentationDragIndicator(.visible)
    }
}

private struct RecordEventRow: View {
    let event: HospitalRecordEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(event.label + " · " + event.actor).font(.system(size: 13, weight: .semibold))
            Text(event.timestamp).font(.system(size: 11)).foregroundStyle(AD.sub)
            if let reason = event.reason { Text(DisplayLabels.reject(reason)).font(.system(size: 12)) }
        }
    }
}
