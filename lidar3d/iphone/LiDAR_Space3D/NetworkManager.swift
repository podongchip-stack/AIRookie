import Foundation
import Combine

/// iPhone -> Mac 서버 통신 (요구사항 12~15번).
/// Server IP/Port는 코드에 하드코딩하지 않고 UI에서 입력받는다.
///
/// 요구사항 15번: "실시간 전송"과 "세션 종료 후 업로드"를 분리한다.
/// 이 파일은 B(세션 종료 후 업로드) 경로를 구현한다. 실시간 WebSocket(C)은
/// server/app.py의 /ws/session/{id} 스텁과 대응되며, 이 클래스와 독립적으로 동작하도록
/// 별도 클래스(향후 추가, TODO)로 분리할 수 있게 설계한다.
final class NetworkManager: ObservableObject {
    @Published var isConnected = false
    /// 서버 주소. 두 가지 형태를 모두 받는다.
    ///   - `192.168.0.5`        같은 Wi-Fi (아래 serverPort와 조합, http)
    ///   - `https://xxx.trycloudflare.com`  공개 터널 (포트 무시, 스킴 그대로)
    /// 시연장에서는 아이폰이 셀룰러, 맥이 행사장 Wi-Fi라 사설 IP로는 닿지 않는다.
    @Published var serverAddress: String = "" { didSet { saveSettings() } }
    @Published var serverPort: String = "8000" { didSet { saveSettings() } }
    /// 서버가 LIDAR_TOKEN으로 실행됐을 때 필요한 공유 토큰.
    /// 비어 있으면 헤더를 붙이지 않는다(같은 Wi-Fi 전용 모드와 호환).
    /// **절대 로그에 남기지 않는다.**
    @Published var authToken: String = "" { didSet { saveSettings() } }
    @Published var lastUploadStatus: String = ""
    /// 업로드가 진행 중인지. UPLOAD 버튼을 연타하면 같은 세션이 두 번 업로드되고
    /// 서버에서 /session/stop이 두 번 호출되어 파이프라인이 중복 실행되는 사고가 있었다.
    @Published var isUploading = false

    private var baseURL: URL? {
        var a = serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !a.isEmpty else { return nil }
        while a.hasSuffix("/") { a.removeLast() }
        let lower = a.lowercased()
        // 스킴이 있으면 전체 URL로 취급한다. 터널 주소는 443이라 포트를 붙이면 안 된다.
        if lower.hasPrefix("http://") || lower.hasPrefix("https://") {
            return URL(string: a)
        }
        guard let port = Int(serverPort) else { return nil }
        return URL(string: "http://\(a):\(port)")
    }

    /// 모든 요청은 여기를 거친다. 토큰 헤더를 한 곳에서만 붙이기 위해서다
    /// (호출부마다 붙이면 한 군데 빠뜨렸을 때 401이 나는데 원인을 찾기 어렵다).
    private func makeRequest(_ path: String) -> URLRequest? {
        guard let base = baseURL else { return nil }
        var r = URLRequest(url: base.appendingPathComponent(path))
        let t = authToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !t.isEmpty { r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        return r
    }

    // 시연장에서 긴 터널 주소와 토큰을 매번 손으로 치는 건 현실적이지 않다.
    private static let kAddr = "net.serverAddress"
    private static let kPort = "net.serverPort"
    private static let kToken = "net.authToken"
    private var loadingSettings = false

    private func saveSettings() {
        guard !loadingSettings else { return }
        let d = UserDefaults.standard
        d.set(serverAddress, forKey: Self.kAddr)
        d.set(serverPort, forKey: Self.kPort)
        d.set(authToken, forKey: Self.kToken)
    }

    init() {
        // 앱을 켤 때마다 긴 터널 주소와 토큰을 다시 치지 않도록 복원한다.
        loadSettings()
    }

    private func loadSettings() {
        loadingSettings = true
        let d = UserDefaults.standard
        serverAddress = d.string(forKey: Self.kAddr) ?? ""
        serverPort = d.string(forKey: Self.kPort) ?? "8000"
        authToken = d.string(forKey: Self.kToken) ?? ""
        loadingSettings = false
    }

    func checkHealth(completion: @escaping (Bool) -> Void) {
        guard var request = makeRequest("health") else {
            completion(false)
            return
        }
        request.timeoutInterval = 3
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200 && error == nil
            DispatchQueue.main.async {
                self?.isConnected = ok
                completion(ok)
            }
        }.resume()
    }

    /// session 폴더 전체를 업로드: /session/start -> 파일별 /session/upload -> /session/stop
    func uploadSession(sessionId: String, files: [URL], completion: @escaping (Result<Void, Error>) -> Void) {
        // 주소가 비었거나 형식이 틀리면 여기서 바로 막는다 (업로드 시작 전에).
        guard baseURL != nil else {
            completion(.failure(NetworkError.invalidServerAddress))
            return
        }
        guard !isUploading else {
            completion(.failure(NetworkError.uploadAlreadyInProgress))
            return
        }
        isUploading = true
        skippedFiles = []
        uploadProgress = ""

        // 어느 경로로 끝나든 isUploading을 반드시 내려준다.
        let finish: (Result<Void, Error>) -> Void = { [weak self] result in
            DispatchQueue.main.async {
                self?.isUploading = false
                self?.uploadProgress = ""
                completion(result)
            }
        }

        startRemoteSession(sessionId: sessionId) { [weak self] result in
            switch result {
            case .failure(let error):
                finish(.failure(error))
            case .success:
                self?.uploadFiles(sessionId: sessionId, files: files, index: 0) { result in
                    switch result {
                    case .failure(let error):
                        finish(.failure(error))
                    case .success:
                        self?.stopRemoteSession(sessionId: sessionId, completion: finish)
                    }
                }
            }
        }
    }

    private func startRemoteSession(sessionId: String, completion: @escaping (Result<Void, Error>) -> Void) {
        guard var request = makeRequest("session/start") else {
            // completion을 부르지 않고 빠져나가면 isUploading이 영영 true로 남는다.
            completion(.failure(NetworkError.invalidServerAddress))
            return
        }
        request.httpMethod = "POST"
        let body = "session_id=\(sessionId)"
        request.httpBody = body.data(using: .utf8)
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error = error { completion(.failure(error)); return }
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                completion(.failure(NetworkError.serverError)); return
            }
            completion(.success(()))
        }.resume()
    }

    /// 실패해도 세션 전체를 포기하지 않는 파일들.
    ///
    /// 왜 필요한가 (실측으로 드러난 문제):
    ///   depth.zip은 수백 MB라 가장 실패하기 쉬운데, 업로드 순서상 metadata.json 바로 앞이다.
    ///   예전에는 하나라도 실패하면 즉시 중단해서, **뎁스 실패가 metadata.json까지 날려버렸다.**
    ///   metadata.json이 없으면 서버도 뷰어도 그 세션을 해석할 수 없어 **세션 전체가 쓸모없어진다.**
    ///   뎁스는 "있으면 좋은" 부가 데이터이므로, 실패하면 건너뛰고 나머지를 끝까지 올린다.
    private static let optionalFilenames: Set<String> = ["depth.zip"]

    /// 선택적 파일 중 실패한 것들. UI에 무엇이 빠졌는지 알려주기 위해 기록한다.
    @Published var skippedFiles: [String] = []
    /// 업로드 진행 상황 (몇 번째 / 총 몇 개 / 지금 어떤 파일).
    /// 업로드가 중간에 멈췄을 때 **어디서 멈췄는지**를 화면에서 바로 알 수 있어야 한다.
    @Published var uploadProgress: String = ""

    private func uploadFiles(sessionId: String, files: [URL], index: Int,
                              completion: @escaping (Result<Void, Error>) -> Void) {
        guard index < files.count else { completion(.success(())); return }
        let fileURL = files[index]
        let name = fileURL.lastPathComponent
        let mb = Double((try? FileManager.default.attributesOfItem(
            atPath: fileURL.path)[.size] as? Int64) ?? 0) / 1e6
        // 조각 진행률이 이 문구를 덮어쓰면 "몇 번째 파일인지"가 사라진다.
        // 접두사를 따로 보관해 두 정보가 같이 보이게 한다.
        let label = String(format: "%d/%d %@ (%.0fMB)", index + 1, files.count, name, mb)
        currentFileLabel = label
        DispatchQueue.main.async {
            self.uploadProgress = label + " 전송 중…"
        }
        uploadOneFile(sessionId: sessionId, fileURL: fileURL) { [weak self] result in
            switch result {
            case .failure(let error):
                if Self.optionalFilenames.contains(name) {
                    // 건너뛰고 계속. 조용히 넘어가지 않고 무엇이 빠졌는지 남긴다.
                    DispatchQueue.main.async {
                        self?.skippedFiles.append(name)
                        self?.lastUploadStatus = "\(name) 업로드 실패 — 건너뜀 (\(error.localizedDescription))"
                    }
                    self?.uploadFiles(sessionId: sessionId, files: files,
                                      index: index + 1, completion: completion)
                } else {
                    completion(.failure(error))
                }
            case .success:
                self?.uploadFiles(sessionId: sessionId, files: files, index: index + 1, completion: completion)
            }
        }
    }

    /// 파일 하나를 multipart로 업로드한다.
    ///
    /// ⚠️ 메모리 주의 — 예전 구현이 여기서 실패했다:
    ///   `Data(contentsOf:)`로 파일 전체를 메모리에 올린 뒤 `body.append(fileData)`로 또 복사하면
    ///   **파일 크기의 2배**를 순간적으로 쓴다. video.mov(57MB)까지는 버텼지만 depth.zip이
    ///   수백 MB가 되자 iOS가 앱을 죽여 업로드가 통째로 중단됐다 (실측으로 확인).
    ///
    ///   그래서 multipart 본문을 **임시 파일로 디스크에 조립**하고
    ///   `uploadTask(with:fromFile:)`로 스트리밍한다. 메모리 사용량이 파일 크기와 무관해진다.
    ///   임시 파일은 완료 콜백에서 반드시 지운다(안 지우면 폰 용량을 두 배로 먹는다).
    /// 이보다 큰 파일은 조각내서 보낸다.
    ///
    /// Cloudflare 무료 플랜은 **요청 본문 100MB**가 상한이라, video.mov(132MB까지 나온다)를
    /// 통째로 보내면 Cloudflare 단계에서 잘려 서버에 요청이 도달조차 하지 않는다.
    /// 앱에는 "The request timed out"으로만 보여서 원인을 알기 어렵다.
    /// 여유를 크게 두어 50MB를 기준으로 삼는다 (multipart 헤더 오버헤드까지 감안).
    /// 지금 보내는 파일의 "3/10 video.mov (132MB)" 부분. 조각 진행률과 함께 보여준다.
    private var currentFileLabel = ""
    private let chunkThreshold: Int64 = 50 * 1024 * 1024
    private let chunkSize: Int = 20 * 1024 * 1024

    private func uploadOneFile(sessionId: String, fileURL: URL,
                                completion: @escaping (Result<Void, Error>) -> Void) {
        let size = (try? FileManager.default.attributesOfItem(
            atPath: fileURL.path)[.size] as? Int64) ?? 0
        if size > chunkThreshold {
            uploadInChunks(sessionId: sessionId, fileURL: fileURL, totalSize: size,
                           completion: completion)
            return
        }
        uploadWholeFile(sessionId: sessionId, fileURL: fileURL, completion: completion)
    }

    // MARK: 분할 전송
    //
    // **전송만** 조각낸다. 서버가 원래 파일로 다시 합치므로 세션 폴더 구조도,
    // video.mov의 frame_index와 arkit_pose.csv의 대응도 전혀 바뀌지 않는다.

    private func uploadInChunks(sessionId: String, fileURL: URL, totalSize: Int64,
                                completion: @escaping (Result<Void, Error>) -> Void) {
        let name = fileURL.lastPathComponent
        let count = Int((totalSize + Int64(chunkSize) - 1) / Int64(chunkSize))

        func sendChunk(_ index: Int) {
            if index >= count {
                finishChunked(sessionId: sessionId, name: name, count: count,
                              totalSize: totalSize, completion: completion)
                return
            }
            let prefix = self.currentFileLabel
            DispatchQueue.main.async {
                self.uploadProgress = "\(prefix) 조각 \(index + 1)/\(count) 전송 중…"
            }
            uploadChunk(sessionId: sessionId, fileURL: fileURL, name: name,
                        index: index, count: count) { [weak self] result in
                switch result {
                case .failure(let e): completion(.failure(e))
                case .success:        self?.queueNextChunk { sendChunk(index + 1) }
                }
            }
        }
        sendChunk(0)
    }

    /// 재귀 호출이 콜백 스택에 계속 쌓이지 않도록 다음 조각은 큐로 넘긴다.
    private func queueNextChunk(_ work: @escaping () -> Void) {
        DispatchQueue.global(qos: .utility).async(execute: work)
    }

    private func uploadChunk(sessionId: String, fileURL: URL, name: String,
                             index: Int, count: Int,
                             completion: @escaping (Result<Void, Error>) -> Void) {
        let boundary = "Boundary-\(UUID().uuidString)"
        guard var request = makeRequest("session/upload/chunk") else {
            completion(.failure(NetworkError.invalidServerAddress)); return
        }
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300

        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-\(UUID().uuidString)")
        let cleanup = { try? FileManager.default.removeItem(at: tempURL) }

        func field(_ key: String, _ value: String) -> String {
            "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)\r\n"
        }
        var header = field("session_id", sessionId)
        header += field("filename", name)
        header += field("chunk_index", String(index))
        header += field("chunk_count", String(count))
        header += "--\(boundary)\r\n"
        header += "Content-Disposition: form-data; name=\"file\"; filename=\"\(name).part\"\r\n"
        header += "Content-Type: application/octet-stream\r\n\r\n"
        let footer = "\r\n--\(boundary)--\r\n"

        do {
            try Data(header.utf8).write(to: tempURL)
            let out = try FileHandle(forWritingTo: tempURL)
            defer { try? out.close() }
            try out.seekToEnd()

            let reader = try FileHandle(forReadingFrom: fileURL)
            defer { try? reader.close() }
            try reader.seek(toOffset: UInt64(index) * UInt64(chunkSize))
            // 조각 하나를 다시 작게 나눠 읽는다 (20MB를 한 번에 메모리에 올리지 않는다).
            var remaining = chunkSize
            while remaining > 0 {
                let want = min(remaining, 4 * 1024 * 1024)
                guard let buf = try reader.read(upToCount: want), !buf.isEmpty else { break }
                try out.write(contentsOf: buf)
                remaining -= buf.count
            }
            try out.write(contentsOf: Data(footer.utf8))
        } catch {
            cleanup()
            let detail = "\(name) 조각 \(index + 1)/\(count) 준비 실패: \(error.localizedDescription)"
            DispatchQueue.main.async { self.lastUploadStatus = detail }
            completion(.failure(NetworkError.uploadPrepareFailed(detail)))
            return
        }

        URLSession.shared.uploadTask(with: request, fromFile: tempURL) { _, response, error in
            cleanup()
            if let error = error { completion(.failure(error)); return }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard status == 200 else {
                DispatchQueue.main.async {
                    self.lastUploadStatus = "\(name) 조각 \(index + 1)/\(count): HTTP \(status)"
                }
                completion(.failure(NetworkError.serverError)); return
            }
            completion(.success(()))
        }.resume()
    }

    /// 조각을 다 보냈다고 서버에 알려 원래 파일로 합치게 한다.
    /// 서버가 크기를 대조하므로, 하나라도 빠지면 여기서 실패로 걸러진다.
    private func finishChunked(sessionId: String, name: String, count: Int, totalSize: Int64,
                               completion: @escaping (Result<Void, Error>) -> Void) {
        guard var request = makeRequest("session/upload/complete") else {
            completion(.failure(NetworkError.invalidServerAddress)); return
        }
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300
        request.httpBody = "session_id=\(sessionId)&filename=\(name)&chunk_count=\(count)&total_size=\(totalSize)"
            .data(using: .utf8)
        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            if let error = error { completion(.failure(error)); return }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            DispatchQueue.main.async {
                self?.lastUploadStatus = "\(name): 조각 \(count)개 합침 (HTTP \(status))"
            }
            guard status == 200 else { completion(.failure(NetworkError.serverError)); return }
            completion(.success(()))
        }.resume()
    }

    private func uploadWholeFile(sessionId: String, fileURL: URL,
                                 completion: @escaping (Result<Void, Error>) -> Void) {
        let boundary = "Boundary-\(UUID().uuidString)"
        guard var request = makeRequest("session/upload") else {
            // completion을 부르지 않고 빠져나가면 isUploading이 영영 true로 남는다.
            completion(.failure(NetworkError.invalidServerAddress))
            return
        }
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        // 큰 파일은 Wi-Fi에서도 오래 걸린다. 기본 60초로는 depth.zip이 끊긴다.
        request.timeoutInterval = 600

        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("upload-\(UUID().uuidString)")
        let name = fileURL.lastPathComponent

        var header = ""
        header += "--\(boundary)\r\n"
        header += "Content-Disposition: form-data; name=\"session_id\"\r\n\r\n"
        header += "\(sessionId)\r\n"
        header += "--\(boundary)\r\n"
        header += "Content-Disposition: form-data; name=\"file\"; filename=\"\(name)\"\r\n"
        header += "Content-Type: application/octet-stream\r\n\r\n"
        let footer = "\r\n--\(boundary)--\r\n"

        let cleanup = { try? FileManager.default.removeItem(at: tempURL) }

        // 임시 본문은 원본 파일만큼의 여유 공간을 더 쓴다. 공간이 모자라면
        // **쓰다가 죽는 것보다 먼저 멈추는 게 낫다** (아래 write가 실패하면 앱이 통째로 죽는다).
        let fileSize = (try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? Int64) ?? 0
        let freeSpace = (try? FileManager.default.attributesOfFileSystem(
            forPath: NSHomeDirectory())[.systemFreeSize] as? Int64) ?? 0
        if fileSize > 0, freeSpace > 0, freeSpace < fileSize + 50_000_000 {
            let detail = String(format: "%@ 업로드 실패: 저장공간 부족 (파일 %.0fMB, 여유 %.0fMB)",
                                name, Double(fileSize) / 1e6, Double(freeSpace) / 1e6)
            DispatchQueue.main.async { self.lastUploadStatus = detail }
            completion(.failure(NetworkError.uploadPrepareFailed(detail)))
            return
        }

        do {
            // 헤더를 먼저 쓰고, 파일 본문은 청크 단위로 이어 붙인다 (메모리에 전부 올리지 않는다).
            //
            // ⚠️ write(contentsOf:)를 쓰는 이유 (중요):
            //   FileHandle.write(_:)는 실패 시 Swift 에러가 아니라 **ObjC 예외**를 던진다.
            //   Swift의 catch로 잡히지 않아 디스크가 차면 **앱이 그대로 죽는다** — 업로드가
            //   조용히 중간에 멈추고 사용자는 이유를 알 수 없다. 던지는 버전을 써야 잡을 수 있다.
            try Data(header.utf8).write(to: tempURL)
            let handle = try FileHandle(forWritingTo: tempURL)
            defer { try? handle.close() }
            try handle.seekToEnd()

            let reader = try FileHandle(forReadingFrom: fileURL)
            defer { try? reader.close() }
            while true {
                guard let chunk = try reader.read(upToCount: 4 * 1024 * 1024), !chunk.isEmpty else { break }
                try handle.write(contentsOf: chunk)
            }
            try handle.write(contentsOf: Data(footer.utf8))
        } catch {
            cleanup()
            // 원인을 뭉개지 않는다. "왜 실패했는지"를 모르면 고칠 수가 없다.
            // 특히 폰 저장공간 부족이 흔한 원인인데, 그건 코드 문제가 아니라 사용자가
            // 해결해야 하는 것이라 반드시 구분해서 알려야 한다.
            let free = (try? FileManager.default.attributesOfFileSystem(
                forPath: NSHomeDirectory())[.systemFreeSize] as? Int64) ?? nil
            let size = (try? FileManager.default.attributesOfItem(
                atPath: fileURL.path)[.size] as? Int64) ?? nil
            var detail = "\(name) 전송 준비 실패: \(error.localizedDescription)"
            if let free, let size {
                detail += String(format: " (파일 %.0fMB, 폰 여유 %.0fMB)",
                                 Double(size) / 1e6, Double(free) / 1e6)
            }
            DispatchQueue.main.async { self.lastUploadStatus = detail }
            completion(.failure(NetworkError.uploadPrepareFailed(detail)))
            return
        }

        let task = URLSession.shared.uploadTask(with: request, fromFile: tempURL) { [weak self] _, response, error in
            cleanup()
            if let error = error { completion(.failure(error)); return }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            DispatchQueue.main.async {
                self?.lastUploadStatus = "\(name): HTTP \(status)"
            }
            guard status == 200 else { completion(.failure(NetworkError.serverError)); return }
            completion(.success(()))
        }
        task.resume()
    }

    private func stopRemoteSession(sessionId: String, completion: @escaping (Result<Void, Error>) -> Void) {
        guard var request = makeRequest("session/stop") else {
            // completion을 부르지 않고 빠져나가면 isUploading이 영영 true로 남는다.
            completion(.failure(NetworkError.invalidServerAddress))
            return
        }
        request.httpMethod = "POST"
        let body = "session_id=\(sessionId)"
        request.httpBody = body.data(using: .utf8)
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error = error { completion(.failure(error)); return }
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                completion(.failure(NetworkError.serverError)); return
            }
            completion(.success(()))
        }.resume()
    }

    enum NetworkError: Error, LocalizedError {
        var errorDescription: String? {
            switch self {
            case .invalidServerAddress: return "서버 주소가 올바르지 않습니다"
            case .serverError:          return "서버가 요청을 거부했습니다"
            case .fileReadFailed(let f): return "파일을 읽지 못했습니다: \(f)"
            case .uploadPrepareFailed(let d): return d
            case .uploadAlreadyInProgress: return "이미 업로드 중입니다"
            }
        }

        case invalidServerAddress
        case serverError
        case fileReadFailed(String)
        case uploadPrepareFailed(String)
        case uploadAlreadyInProgress
    }
}
