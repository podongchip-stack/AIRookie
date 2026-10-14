import SwiftUI

/// 설정 — 서버 주소(hub / spider)와 연결 확인. 바꾸면 소켓을 다시 붙이고 WebView를 다시 연다.
struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @State private var lanIP = "192.168.0.10"
    @State private var checkResult = ""
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                Section("hub 주소") {
                    TextField("https://app.rookie-goldenlink.xyz", text: $hubBase)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("WebSocket: \(Settings.wsURL?.absoluteString ?? "—")").font(.footnote).foregroundStyle(.secondary)
                    Text("라이브 보드: \(Settings.liveBoardURL?.absoluteString ?? "—")").font(.footnote).foregroundStyle(.secondary)
                }
                Section("spider(거미줄 3D) 주소") {
                    TextField("비우면 자동: \(Settings.autoSpiderBase(for: hubBase))", text: $spiderBase)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("여는 주소: \(Settings.spiderURL?.absoluteString ?? "—")").font(.footnote).foregroundStyle(.secondary)
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
                    Button(checking ? "확인 중…" : "hub·spider 연결 확인") { Task { await check() } }.disabled(checking)
                    if !checkResult.isEmpty { Text(checkResult).font(.footnote) }
                }
                Section {
                    Text("이 앱은 보기 전용입니다 — hub에 identify 외에 아무것도 보내지 않습니다. 승인·이송 승인은 구급차·병원 대시보드에서 합니다.")
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
        if let u = Settings.identityURL {
            do {
                var req = URLRequest(url: u); req.timeoutInterval = 8
                let (_, r) = try await URLSession.shared.data(for: req)
                lines.append("hub: \((r as? HTTPURLResponse)?.statusCode == 200 ? "✅ 응답" : "⚠️ 상태 \((r as? HTTPURLResponse)?.statusCode ?? 0)")")
            } catch { lines.append("hub: ❌ \(error.localizedDescription)") }
        } else { lines.append("hub: ❌ 주소 형식 오류") }
        if let u = Settings.spiderHealthURL {
            do {
                var req = URLRequest(url: u); req.timeoutInterval = 8
                let (d, r) = try await URLSession.shared.data(for: req)
                let ok = (r as? HTTPURLResponse)?.statusCode == 200
                let nodes = (try? JSONSerialization.jsonObject(with: d) as? [String: Any])?["engine"].flatMap { ($0 as? [String: Any])?["roadNodes"] as? Int }
                lines.append("spider: \(ok ? "✅ 응답 (도로 노드 \(nodes ?? 0))" : "⚠️ 상태 \((r as? HTTPURLResponse)?.statusCode ?? 0)")")
            } catch { lines.append("spider: ❌ \(error.localizedDescription)") }
        } else { lines.append("spider: ❌ 주소 형식 오류") }
        checkResult = lines.joined(separator: "\n")
    }
}
