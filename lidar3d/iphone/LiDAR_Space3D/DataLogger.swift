import Foundation

/// CSV 파일에 스레드 안전하게 라인을 append하는 유틸리티.
/// Camera(비디오 큐)와 CoreMotion(모션 큐)이 동시에 쓰기 때문에 락이 필요하다.
final class CSVLogger {
    private let fileHandle: FileHandle
    private let lock = NSLock()
    let url: URL

    init?(fileURL: URL, header: String) {
        self.url = fileURL
        let fm = FileManager.default
        if !fm.fileExists(atPath: fileURL.path) {
            fm.createFile(atPath: fileURL.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: fileURL) else {
            return nil
        }
        self.fileHandle = handle
        write(header + "\n")
    }

    func write(_ line: String) {
        lock.lock()
        defer { lock.unlock() }
        guard let data = line.data(using: .utf8) else { return }
        fileHandle.seekToEndOfFile()
        fileHandle.write(data)
    }

    func close() {
        lock.lock()
        defer { lock.unlock() }
        try? fileHandle.close()
    }
}
