import Foundation
import OnnxRuntimeBindings

/// 1단계: 양자화 모델이 이 기기에서 올라가는지만 본다. 세션을 만들 때 MatMulNBits 커널이 없으면 여기서 실패한다.
enum LoadCheck {
    /// 모델 폴더: 앱 Documents/small_mf (Finder나 파일 앱으로 encoder.onnx, decoder.onnx, decoder.onnx.data 를 복사)
    static var modelDir: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("small_mf")
    }

    static func run(log: @escaping (String) -> Void) throws {
        let dir = modelDir
        let encoderPath = dir.appendingPathComponent("encoder.onnx").path
        let decoderPath = dir.appendingPathComponent("decoder.onnx").path
        for p in [encoderPath, decoderPath] where !FileManager.default.fileExists(atPath: p) {
            throw NSError(domain: "LabDH", code: 1, userInfo: [NSLocalizedDescriptionKey: "파일이 없습니다: \(p)"])
        }
        log(String(format: "시작  사용 %.0fMB / 남은 %.0fMB", footprintMB(), availableMB()))

        let env = try ORTEnv(loggingLevel: .warning)
        let options = try ORTSessionOptions()

        var t = Date()
        let encoder = try ORTSession(env: env, modelPath: encoderPath, sessionOptions: options)
        log(String(format: "인코더 로드 %.1f초  사용 %.0fMB / 남은 %.0fMB", Date().timeIntervalSince(t), footprintMB(), availableMB()))

        t = Date()
        let decoder = try ORTSession(env: env, modelPath: decoderPath, sessionOptions: options)
        log(String(format: "디코더 로드 %.1f초  사용 %.0fMB / 남은 %.0fMB", Date().timeIntervalSince(t), footprintMB(), availableMB()))

        // 임시 입력으로 한 번씩 돌려 본다(결과 값은 보지 않는다 — 실행이 되는지와 메모리만)
        t = Date()
        let tokens = 16
        let ids = [Int64](repeating: 2, count: tokens)
        let idsData = NSMutableData(bytes: ids, length: tokens * 8)
        let maskData = NSMutableData(bytes: [Int64](repeating: 1, count: tokens), length: tokens * 8)
        let shape: [NSNumber] = [1, NSNumber(value: tokens)]
        let encOut = try encoder.run(
            withInputs: [
                "input_ids": try ORTValue(tensorData: idsData, elementType: .int64, shape: shape),
                "attention_mask": try ORTValue(tensorData: maskData, elementType: .int64, shape: shape),
            ],
            outputNames: ["token_vectors"], runOptions: nil)
        guard let vectors = encOut["token_vectors"] else { throw NSError(domain: "LabDH", code: 2) }
        log(String(format: "인코더 실행(16토큰) %.2f초  사용 %.0fMB", Date().timeIntervalSince(t), footprintMB()))

        t = Date()
        let qData = NSMutableData(bytes: [Int64(0)], length: 8)
        let decOut = try decoder.run(
            withInputs: [
                "token_vectors": vectors,
                "question_ids": try ORTValue(tensorData: qData, elementType: .int64, shape: [1, 1]),
            ],
            outputNames: ["scores"], runOptions: nil)
        let shapeInfo = try decOut["scores"]?.tensorTypeAndShapeInfo().shape.map(\.intValue) ?? []
        log(String(format: "디코더 실행 %.2f초  scores 모양 %@  사용 %.0fMB", Date().timeIntervalSince(t), "\(shapeInfo)", footprintMB()))
    }
}
