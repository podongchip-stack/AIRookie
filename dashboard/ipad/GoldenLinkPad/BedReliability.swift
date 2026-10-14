import Foundation

/// 병상 정보 신뢰도(bedReliability)의 실시간 감쇠. dashboard/src/lib/bedReliability.ts · hub/bed_reliability.py와 같은 식:
///   S(age) = 1 − Φ((ln age − ln m) / σ)   (log-normal AFT 생존곡선), norm.sf(x) = erfc(x/√2)/2
/// 병원이 "현재 정보 확인"을 눌렀으면 조건부 생존 S(a)/S(u). 파라미터가 없으면 hub가 보낸 스칼라 그대로(정지값).
enum BedReliability {
    struct Live {
        var authority: Double    // 지금 이 숫자가 유효할 확률
        var rArrive: Double      // 도착 시점(horizon 뒤)에도 유효할 확률
        var live: Bool           // true면 초 단위로 흘러가는 값
        var ageSec: Double?      // 정보 나이(claim이 태어난 뒤 지난 초)
    }

    static func survival(predT: Double, age: Double, sigma: Double) -> Double {
        if age <= 0 { return 1 }
        let z = (log(max(age, 1e-9)) - log(max(predT, 1e-9))) / (max(sigma, 1e-9) * 2.0.squareRoot())
        return min(max(0.5 * erfc(z), 0), 1)
    }

    static func live(_ br: BedReliabilityMatch, now: Date) -> Live {
        guard let predT = br.predictedSurvivalSec, let bornAt = br.bornAt, let born = ISO.parse(bornAt) else {
            return Live(authority: br.authority, rArrive: br.rArrive, live: false, ageSec: nil)
        }
        let sigma = br.sigma ?? 1.0
        let age = max(now.timeIntervalSince(born), 0)
        let sU = br.confirmedAgeSec.map { max(survival(predT: predT, age: $0, sigma: sigma), 1e-12) } ?? 1.0
        return Live(
            authority: min(survival(predT: predT, age: age, sigma: sigma) / sU, 1),
            rArrive: min(survival(predT: predT, age: age + br.horizonSec, sigma: sigma) / sU, 1),
            live: true, ageSec: age)
    }

    static func pct(_ p: Double) -> String { "\(Int((p * 100).rounded()))%" }
}
