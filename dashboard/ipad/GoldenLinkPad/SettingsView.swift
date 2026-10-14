import SwiftUI

/// 설정 — 이 아이패드가 실린 구급차, 서버 주소(hub / spider), 연결 확인. 바꾸면 소켓을 다시 붙이고 지도를 다시 연다.
struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @AppStorage("apid") private var apid = "auto"
    @State private var lanIP = "192.168.0.10"
    @State private var checkResult = ""
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("auto 또는 SEL0001", text: $apid)
                        .textInputAutocapitalization(.characters).autocorrectionDisabled()
                    HStack {
                        Button("auto (출동 구급대 자동)") { apid = "auto" }
                        Spacer()
                        Button("SEL0001") { apid = "SEL0001" }
                    }
                    Text("auto: 상황이 발생해 어떤 구급대든 출동하면 그 구급대 화면으로 자동 전환(웹 /ambulance?id=auto와 같음). 실제 차량에 고정하려면 구급차 ID(SEL0001~SEL0162)를 넣는다.")
                        .font(.footnote).foregroundStyle(.secondary)
                } header: { Text("이 아이패드의 구급차") }

                Section("hub 주소") {
                    TextField("https://app.rookie-goldenlink.xyz", text: $hubBase)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("WebSocket: \(Settings.wsURL?.absoluteString ?? "—")").font(.footnote).foregroundStyle(.secondary)
                }
                Section("spider(거미줄 지도) 주소") {
                    TextField("비우면 자동: \(Settings.autoSpiderBase(for: hubBase))", text: $spiderBase)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("공개 모드는 hub와 같은 도메인(/spider/를 터널이 spider로 보냄). 로컬 모드(…:5001)면 같은 IP의 2700번을 자동으로 쓴다.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("빠른 설정") {
                    Button("공개 도메인 (app.rookie-goldenlink.xyz)") { hubBase = Settings.defaultHub; spiderBase = "" }
                    HStack {
                        Text("로컬 LAN")
                        TextField("맥 IP", text: $lanIP).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.numbersAndPunctuation)
                        Button("적용") { hubBase = "http://\(lanIP.trimmingCharacters(in: .whitespaces)):5001"; spiderBase = "" }
                    }
                    Text("로컬 모드: 맥북에서 `./start-all.sh --local`, 아이패드와 같은 Wi-Fi. 맥 IP는 시스템 설정 > Wi-Fi > 세부사항.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("연결 확인") {
                    Button(checking ? "확인 중…" : "hub·spider·구급차 확인") { Task { await check() } }.disabled(checking)
                    if !checkResult.isEmpty { Text(checkResult).font(.footnote) }
                }
                Section {
                    Text("이 화면에서 하는 조작은 [이송 승인] 하나입니다(구급대원 판단) — 병원이 '후보 등록'한 병원에만 열린다. 출동·현장 종료는 웹 구급차 대시보드·시연 콘솔에서 한다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("설정")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("적용") {
                        model.reconnect()
                        NotificationCenter.default.post(name: .spiderReload, object: nil)
                        dismiss()
                    }
                }
                ToolbarItem(placement: .topBarLeading) { Button("닫기") { dismiss() } }
            }
        }
    }

    private func check() async {
        checking = true
        defer { checking = false }
        var lines: [String] = []
        let id = apid.trimmingCharacters(in: .whitespaces)
        if id.lowercased() == "auto" {
            if let u = Settings.identityURL(role: "hospital", id: "_") { lines.append("hub: " + (await status(u))) }
            lines.append("구급차: auto — 출동하는 구급대를 따라감")
        } else if let u = Settings.identityURL(role: "ambulance", id: id) {
            do {
                var req = URLRequest(url: u); req.timeoutInterval = 8
                let (d, r) = try await URLSession.shared.data(for: req)
                let obj = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any]
                lines.append("hub: \((r as? HTTPURLResponse)?.statusCode == 200 ? "✅ 응답" : "⚠️ 상태 \((r as? HTTPURLResponse)?.statusCode ?? 0)")")
                lines.append((obj?["known"] as? Bool) == true ? "구급차: ✅ \(obj?["name"] as? String ?? id)" : "구급차: ❌ hub가 모르는 ID(\(id))")
            } catch { lines.append("hub: ❌ \(error.localizedDescription)") }
        }
        if let u = Settings.spiderHealthURL { lines.append("spider: " + (await status(u))) }
        checkResult = lines.joined(separator: "\n")
    }

    private func status(_ u: URL) async -> String {
        do {
            var req = URLRequest(url: u); req.timeoutInterval = 8
            let (_, r) = try await URLSession.shared.data(for: req)
            return (r as? HTTPURLResponse)?.statusCode == 200 ? "✅ 응답" : "⚠️ 상태 \((r as? HTTPURLResponse)?.statusCode ?? 0)"
        } catch { return "❌ \(error.localizedDescription)" }
    }
}
