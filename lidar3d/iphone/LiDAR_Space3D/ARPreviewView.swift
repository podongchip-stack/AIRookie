import SwiftUI
import ARKit
import SceneKit

/// 카메라 프리뷰 + 라이브 메시 오버레이.
///
/// 기존 ContentView는 매 프레임 CGImage를 만들어 SwiftUI Image로 그렸다(CameraManager의
/// onPreviewImage). 풀해상도 CIContext 렌더를 초당 30번 도는 셈이라 발열과 프레임드랍의 주범이었다.
/// ARSCNView는 카메라 배경을 GPU에서 직접 그리므로 그 비용이 통째로 사라진다.
///
/// ⚠ SDK 확인 결과 정정: `.showSceneUnderstanding`은 **ARSCNView에 없다.**
///    ARSCNView의 ARSCNDebugOptions에는 showWorldOrigin / showFeaturePoints 둘뿐이고,
///    showSceneUnderstanding은 RealityKit의 ARView.DebugOptions 소속이다.
///    게다가 RealityKit 쪽 옵션은 메시를 단색으로만 그려서 **문이 어디인지 보이지 않는다.**
///    그래서 여기서는 ARMeshAnchor를 직접 SCNGeometry로 바꿔 **분류별 색 와이어프레임**으로 그린다.
///    이 프로젝트에서 가장 설득력 있는 화면 — 문이 빨갛게 실시간으로 뜨는 것 — 이 여기서 나온다.
///
/// 실패 시 확인할 것:
/// - 화면이 검음        -> 카메라 권한, 그리고 session.run이 실제로 불렸는지
/// - 메시가 안 보임      -> showMeshOverlay 토글, .meshWithClassification 지원 여부, 스캔 시간
/// - 메시가 전부 회색    -> 분류 미지원 기기(형상은 정상). metadata의 classification_supported 확인
/// - 프레임이 뚝뚝 끊김   -> 앵커가 수백 개면 갱신 비용이 커진다. updateThrottle을 키울 것
struct ARPreviewView: UIViewRepresentable {
    let session: ARSession
    var showMeshOverlay: Bool

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        // 우리가 만든 세션을 넘겨준다. ARSCNView가 자기 세션을 새로 만들게 두면
        // ARCaptureManager가 붙잡고 있는 세션과 카메라를 두고 싸운다.
        view.session = session
        view.automaticallyUpdatesLighting = true
        view.rendersContinuously = true
        // 디버그 점(featurePoints)은 켜지 않는다. 메시 오버레이와 겹쳐 화면만 지저분해진다.
        view.delegate = context.coordinator
        context.coordinator.view = view
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {
        context.coordinator.showMeshOverlay = showMeshOverlay
        if !showMeshOverlay { context.coordinator.clearAllMeshNodes() }
    }

    static func dismantleUIView(_ uiView: ARSCNView, coordinator: Coordinator) {
        // 뷰가 사라져도 세션은 SessionManager 소유라 pause하지 않는다.
        // 여기서 session.pause()를 부르면 화면 전환만으로 녹화가 끊긴다.
        uiView.delegate = nil
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    // MARK: - Coordinator: ARMeshAnchor -> SCNNode

    final class Coordinator: NSObject, ARSCNViewDelegate {
        weak var view: ARSCNView?
        var showMeshOverlay = true

        /// 앵커별 마지막 갱신 시각. ARKit은 같은 앵커를 초당 여러 번 갱신하는데
        /// 그때마다 SCNGeometry를 새로 만들면 GPU 메모리가 요동친다.
        private var lastUpdate: [UUID: TimeInterval] = [:]
        private let updateThrottle: TimeInterval = 0.4

        func renderer(_ renderer: SCNSceneRenderer, didAdd node: SCNNode, for anchor: ARAnchor) {
            guard showMeshOverlay, let mesh = anchor as? ARMeshAnchor else { return }
            attachGeometry(mesh, to: node)
        }

        func renderer(_ renderer: SCNSceneRenderer, didUpdate node: SCNNode, for anchor: ARAnchor) {
            guard showMeshOverlay, let mesh = anchor as? ARMeshAnchor else { return }
            let now = CACurrentMediaTime()
            if let last = lastUpdate[mesh.identifier], now - last < updateThrottle { return }
            lastUpdate[mesh.identifier] = now
            node.childNodes.forEach { $0.removeFromParentNode() }
            attachGeometry(mesh, to: node)
        }

        func renderer(_ renderer: SCNSceneRenderer, didRemove node: SCNNode, for anchor: ARAnchor) {
            lastUpdate.removeValue(forKey: anchor.identifier)
        }

        func clearAllMeshNodes() {
            guard let view else { return }
            view.scene.rootNode.childNodes.forEach { node in
                node.childNodes.filter { $0.name == "meshOverlay" }.forEach { $0.removeFromParentNode() }
            }
            lastUpdate.removeAll()
        }

        /// ARMeshGeometry의 Metal 버퍼를 SCNGeometry로 감싼다.
        ///
        /// 여기가 이 파일의 핵심이자 가장 미묘한 부분이다: ARMeshGeometry의 버퍼는 **이미 GPU에
        /// 올라가 있으므로** SCNGeometrySource(buffer:)로 그대로 참조하면 CPU 복사가 0이다.
        /// 정점을 CPU로 내려받아 다시 올리는 방식(수만 정점 x 초당 여러 번)은 확실히 버벅인다.
        ///
        /// 좌표는 **앵커 로컬**이다. node는 ARSCNView가 anchor.transform으로 이미 배치해 주므로
        /// 여기서 월드 변환을 또 하면 안 된다 (MeshExporter는 파일로 내보내는 것이라 직접 곱한다 —
        /// 둘의 차이를 헷갈리면 메시가 원점에 겹쳐 쌓이거나 두 배로 밀린다).
        private func attachGeometry(_ mesh: ARMeshAnchor, to node: SCNNode) {
            let geometry = mesh.geometry
            let vertices = geometry.vertices
            let faces = geometry.faces
            guard faces.primitiveType == .triangle,
                  faces.bytesPerIndex == MemoryLayout<UInt32>.size else { return }

            let vertexSource = SCNGeometrySource(
                buffer: vertices.buffer,
                vertexFormat: vertices.format,
                semantic: .vertex,
                vertexCount: vertices.count,
                dataOffset: vertices.offset,
                dataStride: vertices.stride
            )
            let indexData = Data(bytes: faces.buffer.contents(),
                                 count: faces.count * 3 * MemoryLayout<UInt32>.size)
            let element = SCNGeometryElement(
                data: indexData,
                primitiveType: .triangles,
                primitiveCount: faces.count,
                bytesPerIndex: MemoryLayout<UInt32>.size
            )

            let scnGeometry = SCNGeometry(sources: [vertexSource], elements: [element])
            let material = SCNMaterial()
            material.diffuse.contents = Self.dominantColor(of: geometry)
            material.isDoubleSided = true
            material.lightingModel = .constant   // 조명 계산 없이 지정색 그대로 (선이 어두워지지 않게)
            // 면을 채우지 않고 선만 그린다. 채우면 현장이 가려져서 "무엇을 더 찍어야 하는지"를
            // 볼 수 없다 — 오버레이의 존재 이유가 사라진다.
            // (SCNGeometryElement.primitiveType은 읽기 전용이라 여기서 .line으로 못 바꾼다.
            //  선 렌더링은 머티리얼의 fillMode로 지정하는 것이 맞는 방법이다.)
            material.fillMode = .lines
            scnGeometry.materials = [material]

            let child = SCNNode(geometry: scnGeometry)
            child.name = "meshOverlay"
            // 오버레이가 카메라 영상과 z-fighting 하지 않도록 살짝 앞에 그린다.
            child.renderingOrder = 10
            node.addChildNode(child)
        }

        /// 앵커 하나의 대표 분류색. ARMeshAnchor 하나 안에서도 면마다 분류가 다를 수 있지만,
        /// SceneKit에서 면별 색을 칠하려면 정점 색 버퍼를 매번 새로 만들어야 해서
        /// 라이브 오버레이에는 너무 비싸다. **최빈 분류 하나로 앵커 전체를 칠한다.**
        /// 정확한 면별 라벨은 최종 scene_mesh.ply / scene_mesh_faces_class.bin이 들고 있다.
        ///
        /// 단, 'none'과 'wall'은 최빈이어도 door/window에 양보한다 — 대부분의 앵커는 벽이라
        /// 최빈값만 쓰면 문이 있는 앵커도 벽 색이 되어 **정작 보여주고 싶은 것이 사라진다.**
        private static func dominantColor(of geometry: ARMeshGeometry) -> UIColor {
            guard let classification = geometry.classification else {
                return UIColor(white: 0.85, alpha: 0.9)
            }
            var histogram = [Int](repeating: 0, count: MeshExporter.classPalette.count)
            let base = classification.buffer.contents().advanced(by: classification.offset)
            // 전수 조사할 필요가 없다. 최대 512점만 균등 샘플해도 최빈값은 안정적이다.
            let total = classification.count
            guard total > 0 else { return UIColor(white: 0.85, alpha: 0.9) }
            let step = max(1, total / 512)
            var index = 0
            while index < total {
                let raw = base.loadUnaligned(fromByteOffset: classification.stride * index, as: UInt8.self)
                if raw < UInt8(histogram.count) { histogram[Int(raw)] += 1 }
                index += step
            }
            // 우선 관심 클래스(문/창문/좌석/테이블)가 조금이라도 있으면 그 색을 쓴다.
            let priority = [7, 6, 5, 4]   // door, window, seat, table
            var chosen = 0
            if let hit = priority.first(where: { histogram[$0] > 0 }) {
                chosen = hit
            } else if let maxIndex = histogram.indices.max(by: { histogram[$0] < histogram[$1] }) {
                chosen = maxIndex
            }
            let rgb = MeshExporter.classPalette[chosen].rgb
            return UIColor(red: CGFloat(rgb.0) / 255.0,
                           green: CGFloat(rgb.1) / 255.0,
                           blue: CGFloat(rgb.2) / 255.0,
                           alpha: 0.9)
        }
    }
}
