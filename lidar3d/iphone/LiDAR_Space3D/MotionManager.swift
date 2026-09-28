import Foundation
import CoreMotion

/// CoreMotion으로 Gyroscope / Accelerometer / DeviceMotion을 수집해서
/// imu.csv, device_motion.csv에 기록한다.
///
/// 중요 (프로젝트 요구사항 9번, 24번):
/// - timestamp는 CMGyroData/CMAccelerometerData/CMDeviceMotion가 제공하는
///   `.timestamp`(시스템 uptime 기준, CACurrentMediaTime()과 같은 clock)를 그대로 쓴다.
///   앱이 데이터를 "받은" wall-clock 시각을 쓰지 않는다.
/// - Accelerometer 원시값은 g 단위이므로 m/s^2로 변환해서 기록한다 (9.80665 곱함).
///   이 변환 여부는 metadata.json에 명시된다 (SessionManager 참고).
final class MotionManager {
    private let motionManager = CMMotionManager()
    private let motionQueue = OperationQueue()

    static let gravityConstant = 9.80665  // g -> m/s^2 변환 상수

    private(set) var gyroSampleCount = 0
    private(set) var accelSampleCount = 0
    private(set) var deviceMotionSampleCount = 0

    var isGyroAvailable: Bool { motionManager.isGyroAvailable }
    var isAccelerometerAvailable: Bool { motionManager.isAccelerometerAvailable }
    var isDeviceMotionAvailable: Bool { motionManager.isDeviceMotionAvailable }

    private var imuLogger: CSVLogger?
    private var deviceMotionLogger: CSVLogger?

    func start(imuLogger: CSVLogger, deviceMotionLogger: CSVLogger?, updateHz: Double = 100.0) {
        self.imuLogger = imuLogger
        self.deviceMotionLogger = deviceMotionLogger
        gyroSampleCount = 0
        accelSampleCount = 0
        deviceMotionSampleCount = 0

        let interval = 1.0 / updateHz

        if motionManager.isGyroAvailable {
            motionManager.gyroUpdateInterval = interval
            motionManager.startGyroUpdates(to: motionQueue) { [weak self] data, error in
                guard let self = self, let data = data else { return }
                // CMGyroData.rotationRate: rad/s (CoreMotion 기본 단위, 변환 불필요)
                let r = data.rotationRate
                self.imuLogger?.write(String(format: "%.6f,gyro,%.6f,%.6f,%.6f\n",
                                              data.timestamp, r.x, r.y, r.z))
                self.gyroSampleCount += 1
            }
        }

        if motionManager.isAccelerometerAvailable {
            motionManager.accelerometerUpdateInterval = interval
            motionManager.startAccelerometerUpdates(to: motionQueue) { [weak self] data, error in
                guard let self = self, let data = data else { return }
                // CMAccelerometerData.acceleration: g 단위 -> m/s^2로 변환해서 기록
                let a = data.acceleration
                let g = MotionManager.gravityConstant
                self.imuLogger?.write(String(format: "%.6f,accel,%.6f,%.6f,%.6f\n",
                                              data.timestamp, a.x * g, a.y * g, a.z * g))
                self.accelSampleCount += 1
            }
        }

        if let dmLogger = deviceMotionLogger, motionManager.isDeviceMotionAvailable {
            motionManager.deviceMotionUpdateInterval = interval
            motionManager.startDeviceMotionUpdates(
                using: .xArbitraryZVertical,
                to: motionQueue
            ) { [weak self] motion, error in
                guard let self = self, let motion = motion else { return }
                let q = motion.attitude.quaternion
                dmLogger.write(String(
                    format: "%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n",
                    motion.timestamp, q.x, q.y, q.z, q.w,
                    motion.attitude.roll, motion.attitude.pitch, motion.attitude.yaw
                ))
                self.deviceMotionSampleCount += 1
            }
        }
    }

    func stop() {
        motionManager.stopGyroUpdates()
        motionManager.stopAccelerometerUpdates()
        motionManager.stopDeviceMotionUpdates()
        imuLogger = nil
        deviceMotionLogger = nil
    }
}
