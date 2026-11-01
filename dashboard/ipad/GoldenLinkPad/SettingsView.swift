import SwiftUI

/// 설정 — 이 아이패드가 실린 구급차, 서버 주소(hub / spider), 연결 확인. 바꾸면 소켓을 다시 붙이고 지도를 다시 연다.
struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @State private var recordToken = RecordAccess.token(Settings.apid)
    @State private var kakaoKey = Settings.kakaoNativeAppKey
    @State private var lanIP = "192.168.0.10"
    @State private var checkResult = ""
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("접근 코드", value: Settings.accessCode)
                    Text(model.ambulanceName ?? Settings.apid).font(.headline)
                    Button("접근 코드 변경") {
                        dismiss()
                        model.changeAccessCode()
                    }
                    Text("입력한 구급대에 고정 연결됩니다. 다른 구급대로 바꾸려면 접근 코드를 다시 입력하세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                } header: { Text("이 아이패드의 구급차") }

                Section("hub 주소") {
                    TextField("https://app.rookie-goldenlink.xyz", text: $hubBase)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("WebSocket: \(Settings.wsURL?.absoluteString ?? "—")").font(.footnote).foregroundStyle(.secondary)
                }
                Section("카카오맵") {
                    SecureField("카카오맵 네이티브 앱 키", text: $kakaoKey)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit { Settings.kakaoNativeAppKey = kakaoKey }
                    Button("키 저장") { Settings.kakaoNativeAppKey = kakaoKey; model.show("카카오맵 키를 저장했습니다. 지도 화면을 다시 열면 적용됩니다.") }
                    Text("카카오 디벨로퍼스에 번들 ID(com.goldenlink.pad)를 iOS 플랫폼으로 등록한 키입니다. 비우면 Config/Kakao.local.xcconfig 값을 씁니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }

                Section("기록 동기화") {
                    SecureField("기록 동기화 키 (운영자 발급)", text: $recordToken)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit { RecordAccess.save(recordToken, apid: Settings.apid); model.syncRecords() }
                    Button("키 저장 후 동기화") { RecordAccess.save(recordToken, apid: Settings.apid); model.syncRecords() }
                    Text("구급차별로 보관됩니다. 있어야 [기록] 화면이 서버와 동기화됩니다.").font(.footnote).foregroundStyle(.secondary)
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
        let id = Settings.apid.trimmingCharacters(in: .whitespaces)
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


/// 아이패드 네이티브 앱의 구급대 접근 코드 입장 화면.
struct PadAccessCodeEntry: View {
    let onEnter: () -> Void
    @State private var code = ""
    @State private var hub = Settings.hubBase
    @State private var checking = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("골든링크").font(.system(size: 28, weight: .black)).foregroundStyle(AD.navy)
                Text("구급대 접근 코드").font(.title3.bold())
                Text("소속 구급대 코드를 입력하면 해당 구급대의 사건과 이송 정보를 확인합니다.")
                    .font(.subheadline).foregroundStyle(AD.sub)
                TextField("예: A-SEL0111", text: $code)
                    .textInputAutocapitalization(.characters).autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder).accessibilityLabel("접근 코드")
                    .onSubmit { Task { await enter() } }
                if let error { Text(error).font(.footnote).foregroundStyle(AD.red) }
                Button { Task { await enter() } } label: {
                    Text(checking ? "구급대 확인 중…" : "입장")
                        .font(.headline).frame(maxWidth: .infinity, minHeight: 48)
                        .foregroundStyle(.white).background(AD.blue, in: RoundedRectangle(cornerRadius: 12))
                }.disabled(checking || code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Text("시연: 역삼119안전센터 구급 1\n아이패드 A-SEL0111 · 아이폰 P-SEL0111")
                    .font(.footnote).foregroundStyle(AD.sub)
                DisclosureGroup("서버 연결 설정") {
                    TextField("hub 주소", text: $hub)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder).padding(.top, 8)
                }.font(.subheadline)
            }.padding(24).frame(maxWidth: 480).frame(maxWidth: .infinity).padding(.top, 64)
        }.background(AD.bg.ignoresSafeArea())
    }

    @MainActor private func enter() async {
        guard !checking else { return }
        guard let id = Settings.ambulanceID(from: code) else {
            error = "A-SEL0111 형식의 구급대 접근 코드를 입력하세요."
            return
        }
        guard let base = URL(string: hub.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(base.scheme?.lowercased() ?? ""), base.host != nil,
              var url = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            error = "서버 주소를 확인하세요."; return
        }
        url.path = "/identity"
        url.queryItems = [URLQueryItem(name: "role", value: "ambulance"), URLQueryItem(name: "id", value: id)]
        guard let endpoint = url.url else { return }
        checking = true; error = nil
        defer { checking = false }
        do {
            var request = URLRequest(url: endpoint); request.timeoutInterval = 10
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { error = "서버에서 구급대를 확인하지 못했습니다."; return }
            struct IdentityCheck: Decodable { let known: Bool; let id: String }
            let identity = try JSONDecoder().decode(IdentityCheck.self, from: data)
            guard identity.known, identity.id == id else { error = "등록되지 않은 구급대 코드입니다."; return }
            Settings.hubBase = hub.trimmingCharacters(in: .whitespacesAndNewlines)
            Settings.apid = id; Settings.accessCode = "A-" + id
            onEnter()
        } catch { self.error = "서버에 연결하지 못했습니다. 네트워크와 서버 주소를 확인한 뒤 다시 시도하세요." }
    }
}
