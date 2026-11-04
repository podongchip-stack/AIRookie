import Foundation
import GoldenLinkCore

/// hub WebSocket(순수 WebSocket, socket.io 아님). use-dashboard-socket.ts와 같은 규칙:
/// 연결 직후 identify, 끊기면 지수 백오프로 다시 붙고 identify를 다시 보낸다(hub가 진행 중 사건을 따라잡기로 돌려준다).
@MainActor
final class HubSocket {
    enum State { case connecting, live, reconnecting }

    private let role: String
    private let id: String
    private let callCapable: Bool
    private let onMessage: (String, Data) -> Void
    private let onState: (State) -> Void
    private var task: URLSessionWebSocketTask?
    private var retryDelay: Double = 1
    private var closed = false

    init(role: String, id: String, callCapable: Bool = false, onMessage: @escaping (String, Data) -> Void, onState: @escaping (State) -> Void) {
        self.role = role
        self.id = id
        self.callCapable = callCapable
        self.onMessage = onMessage
        self.onState = onState
        connect()
    }

    func close() {
        closed = true
        task?.cancel(with: .goingAway, reason: nil)
    }

    func sendJSON(_ data: Data) -> Bool {
        guard let task, task.state == .running, let text = String(data: data, encoding: .utf8) else { return false }
        task.send(.string(text)) { _ in }
        return true
    }

    var isOpen: Bool { task?.state == .running }

    func send<T: Encodable>(_ message: T) -> Bool {
        guard let task, task.state == .running, let data = try? JSONEncoder().encode(message),
              let text = String(data: data, encoding: .utf8) else { return false }
        task.send(.string(text)) { _ in }
        return true
    }

    /// 서버 STT 모드: 16kHz 모노 16비트 PCM 프레임(리틀엔디언) — pcm-capture.ts와 같은 형식
    func sendBinary(_ data: Data) {
        task?.send(.data(data)) { _ in }
    }

    private func connect() {
        guard !closed, let url = Settings.wsURL else { return }
        onState(retryDelay > 1 ? .reconnecting : .connecting)
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        _ = send(IdentifyMessage(role: role, id: id, callCapable: callCapable ? true : nil))
        receive(task)
    }

    private func receive(_ task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, task === self.task else { return }
                switch result {
                case let .success(message):
                    self.retryDelay = 1
                    self.onState(.live)
                    var data: Data?
                    switch message {
                    case let .string(s): data = s.data(using: .utf8)
                    case let .data(d): data = d
                    @unknown default: break
                    }
                    // type으로 갈래를 고르고, type이 없으면 예전 hub의 매칭 결과다
                    if let data, let env = try? JSONDecoder().decode(InboundEnvelope.self, from: data) {
                        self.onMessage(env.type ?? "match_result", data)
                    }
                    self.receive(task)
                case .failure:
                    self.scheduleReconnect()
                }
            }
        }
    }

    private func scheduleReconnect() {
        guard !closed else { return }
        onState(.reconnecting)
        let delay = retryDelay
        retryDelay = min(retryDelay * 2, 15)
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(delay))
            self.connect()
        }
    }
}

/// hub HTTP(온디바이스 모드에서 voice 대신 보낸다). 지금 voice와 같은 엔드포인트·JSON
enum HubHTTP {
    /// 통화 중 발화 하나 — 실패해도 무시(자막일 뿐)
    static func postUtterance(_ m: UtteranceMessage) {
        guard let url = Settings.httpBase?.appendingPathComponent("voice/utterance") else { return }
        var req = URLRequest(url: url, timeoutInterval: 3)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(m)
        URLSession.shared.dataTask(with: req).resume()
    }

    /// 통화 요약 — hub는 202로 바로 답하고 매칭 결과는 WebSocket match_result로 온다. 성공 여부를 돌려준다
    static func postSummary(_ payload: JSONValue) async -> String? {
        guard let url = Settings.httpBase?.appendingPathComponent("voice/summary") else { return "hub 주소 오류" }
        var req = URLRequest(url: url, timeoutInterval: 10)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(payload)
        do {
            let (_, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if (200..<300).contains(code) { return nil }
            return code == 404 ? "hub가 /voice/summary를 받지 않음(404) — 공개 도메인이면 로컬 모드로" : "hub 응답 \(code)"
        } catch {
            return "hub 전송 실패: \(error.localizedDescription)"
        }
    }
}
