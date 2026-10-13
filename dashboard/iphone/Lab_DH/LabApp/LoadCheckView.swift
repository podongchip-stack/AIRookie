import SwiftUI

struct LoadCheckView: View {
    @State private var lines: [String] = []
    @State private var running = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                Section("모델 폴더") {
                    Text(LoadCheck.modelDir.path).font(.caption).textSelection(.enabled)
                    Text("encoder.onnx · decoder.onnx · decoder.onnx.data 를 이 폴더에 복사").font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button(running ? "확인 중…" : "모델 로드 확인") { start() }.disabled(running)
                }
                if !lines.isEmpty {
                    Section("결과") { ForEach(lines, id: \.self) { Text($0).font(.system(.footnote, design: .monospaced)) } }
                }
                if let error {
                    Section("실패") { Text(error).font(.footnote).foregroundStyle(.red) }
                }
            }
            .navigationTitle("LabDH · 1단계")
        }
    }

    private func start() {
        lines = []; error = nil; running = true
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try LoadCheck.run { line in DispatchQueue.main.async { lines.append(line) } }
                DispatchQueue.main.async { lines.append("✅ 로드·실행 성공"); running = false }
            } catch {
                DispatchQueue.main.async { self.error = "\(error)"; running = false }
            }
        }
    }
}
