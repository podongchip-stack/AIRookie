import Foundation

/// hub WebSocket(순수 WebSocket, socket.io 아님). 연결 직후 identify(role=monitor), 끊기면 지수 백오프로 다시 붙고 identify를
/// 다시 보낸다 — hub가 진행 중 사건을 따라잡기로 돌려준다. 아이폰 앱의 HubSocket과 같은 규칙.
@MainActor
final class HubSocket {
    enum State { case connecting, live, reconnecting, closed }

    private let role: String
    private let id: String
    private let onMessage: (String, Data) -> Void
    private let onState: (State) -> Void
    private var task: URLSessionWebSocketTask?
    private var retryDelay: Double = 1
    private var closed = false

    init(role: String, id: String, onMessage: @escaping (String, Data) -> Void, onState: @escaping (State) -> Void) {
        self.role = role
        self.id = id
        self.onMessage = onMessage
        self.onState = onState
        connect()
    }

    func close() {
        closed = true
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        onState(.closed)
    }

    var isOpen: Bool { task?.state == .running }

    @discardableResult
    func send<T: Encodable>(_ message: T) -> Bool {
        guard let task, task.state == .running, let data = try? JSONEncoder().encode(message),
              let text = String(data: data, encoding: .utf8) else { return false }
        task.send(.string(text)) { _ in }
        return true
    }

    private func connect() {
        guard !closed else { return }
        guard let url = Settings.wsURL else { onState(.closed); return }
        onState(retryDelay > 1 ? .reconnecting : .connecting)
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        send(IdentifyMessage(role: role, id: id))  // 열리기 전에 보낸 것은 열린 뒤 순서대로 나간다
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
                    if let data, let env = try? JSONDecoder().decode(Envelope.self, from: data) {
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
        retryDelay = min(retryDelay * 2, 10)
        task = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, !self.closed, self.task == nil else { return }
            self.connect()
        }
    }
}
