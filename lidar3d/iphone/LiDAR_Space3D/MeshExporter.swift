import Foundation
import ARKit
import simd

/// 수집된 ARMeshAnchor 전부를 하나의 월드 좌표계 메시로 병합해서 내보낸다.
///
/// 이 프로젝트에서 메시 분류가 특별히 중요한 이유:
/// 기존 YOLO는 COCO 80클래스를 쓰는데 거기에 **door가 없다.** 응급현장에서 "출입구가 어디인가"는
/// 가장 먼저 필요한 정보인데 그걸 영영 알 수 없었다. ARMeshClassification에는 door / wall /
/// floor / ceiling / table / seat / window가 들어 있어 이 공백을 그대로 메운다.
///
/// 내보내는 것 (3종 세트인 이유가 있다):
///  1. scene_mesh.ply  — binary LE. 정점(좌표/법선/**분류색**) + 면(인덱스/분류).
///     정점에 분류색을 같이 굽기 때문에 Mac에서 Open3D나 MeshLab으로 **그냥 열기만 해도**
///     문이 빨갛게 보인다. 시연에 필요한 추가 도구가 0개다.
///  2. scene_mesh_faces_class.bin — 면당 UInt8 1바이트, PLY의 면 순서와 동일.
///     ⚠ 이게 필요한 이유: PLY 면에 붙인 커스텀 property를 **Open3D가 조용히 버린다.**
///     파일에는 있는데 파이썬에서 읽으면 없다. 그래서 정답 라벨은 이 사이드카가 들고 있고,
///     PLY의 face classification은 "파일 자체의 자기완결성"을 위한 중복이다.
///  3. metadata.json의 통계 (클래스별 면 개수, 바운딩 박스 — ARCaptureManager가 아니라 여기서 계산)
///
/// 실패 시 확인할 것:
/// - PLY는 생겼는데 0 vertex -> 스캔 시간이 너무 짧거나 .meshWithClassification 미지원 기기
/// - 색이 전부 회색  -> classificationActive == false (분류 미지원). 형상은 정상이다.
/// - 면이 뒤집혀 보임 -> ARKit은 반시계 감김(CCW). 뷰어의 backface culling 설정을 볼 것.
enum MeshExporter {

    /// 분류 라벨 -> 표시색. door를 가장 눈에 띄는 빨강으로 둔 것은 의도적이다.
    /// 이 표는 metadata.json과 웹 뷰어(server/viewer/index.html) 범례와 반드시 같아야 한다.
    static let classPalette: [(name: String, rgb: (UInt8, UInt8, UInt8))] = [
        ("none",    (130, 130, 130)),   // 미분류 — 회색
        ("wall",    (200, 200, 190)),   // 벽 — 아이보리
        ("floor",   ( 90, 140,  90)),   // 바닥 — 녹색
        ("ceiling", ( 90, 110, 180)),   // 천장 — 청색
        ("table",   (200, 150,  60)),   // 테이블 — 주황
        ("seat",    (180,  90, 180)),   // 좌석 — 보라
        ("window",  ( 90, 200, 220)),   // 창문 — 하늘색
        ("door",    (230,  40,  40)),   // 문 — 빨강 (가장 중요)
    ]

    struct Result {
        var vertexCount: Int
        var faceCount: Int
        var anchorCount: Int
        var classFaceCounts: [String: Int]   // 클래스명 -> 면 개수
        var boundsMin: SIMD3<Float>
        var boundsMax: SIMD3<Float>
        var plyURL: URL
        var classBinURL: URL?
        /// 분류 정보가 실제로 들어갔는가 (미지원 기기에서는 false)
        var hasClassification: Bool
    }

    /// 앵커들을 병합해 PLY + 사이드카를 쓴다. 정점 수십만 개가 나올 수 있으므로
    /// **반드시 백그라운드에서 호출할 것** (SessionManager가 그렇게 부른다).
    static func export(anchors: [ARMeshAnchor],
                       plyURL: URL,
                       classBinURL: URL) throws -> Result {

        var positions: [SIMD3<Float>] = []
        var normals: [SIMD3<Float>] = []
        var colors: [(UInt8, UInt8, UInt8)] = []
        /// 정점별로 "지금 칠해진 색이 어느 클래스에서 왔는지"를 기억한다.
        /// 이게 없으면 나중에 처리된 면이 무조건 이겨서, 문 주변 정점이 뒤이어 오는 벽 면에
        /// 덮여 사라진다 (합성 메시로 실제 재현함 — 정작 보여주려던 문이 안 보인다).
        var vertexClass: [UInt8] = []
        var faces: [(UInt32, UInt32, UInt32)] = []
        var faceClasses: [UInt8] = []

        var boundsMin = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var boundsMax = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        var anyClassification = false

        for anchor in anchors {
            let geometry = anchor.geometry
            let vSource = geometry.vertices
            let nSource = geometry.normals
            let faceElement = geometry.faces

            // ARKit은 삼각형/UInt32 인덱스를 주지만, 다른 값이 오면 조용히 깨진 파일을 쓰느니
            // 이 앵커를 건너뛴다.
            guard faceElement.primitiveType == .triangle,
                  faceElement.indexCountPerPrimitive == 3,
                  faceElement.bytesPerIndex == MemoryLayout<UInt32>.size else { continue }

            let transform = anchor.transform
            // 법선은 위치와 달리 평행이동을 받으면 안 된다. 강체 변환이므로 회전 3x3만 쓴다.
            let rotation = simd_float3x3(
                SIMD3(transform.columns.0.x, transform.columns.0.y, transform.columns.0.z),
                SIMD3(transform.columns.1.x, transform.columns.1.y, transform.columns.1.z),
                SIMD3(transform.columns.2.x, transform.columns.2.y, transform.columns.2.z)
            )

            // 면별 분류를 먼저 읽어둬야 정점 색을 칠할 수 있다.
            var localFaceClasses = [UInt8](repeating: 0, count: faceElement.count)
            if let cSource = geometry.classification {
                anyClassification = true
                let cBase = cSource.buffer.contents().advanced(by: cSource.offset)
                let count = min(cSource.count, faceElement.count)
                for i in 0..<count {
                    let raw = cBase.loadUnaligned(fromByteOffset: cSource.stride * i, as: UInt8.self)
                    localFaceClasses[i] = raw < UInt8(classPalette.count) ? raw : 0
                }
            }

            // 정점 -> 월드 좌표로 변환.
            // ⚠ ARMeshGeometry의 좌표는 **앵커 로컬** 좌표계다. anchor.transform을 곱하지 않으면
            //   모든 앵커가 원점에 겹쳐 쌓인 쓰레기 메시가 나온다.
            let vertexBase = positions.count
            let vBase = vSource.buffer.contents().advanced(by: vSource.offset)
            let nBase = nSource.buffer.contents().advanced(by: nSource.offset)
            let vertexCount = vSource.count

            for i in 0..<vertexCount {
                let vOff = vSource.stride * i
                // loadUnaligned: Metal 버퍼의 stride가 4바이트 정렬을 보장하지 않는다.
                let lx = vBase.loadUnaligned(fromByteOffset: vOff,     as: Float.self)
                let ly = vBase.loadUnaligned(fromByteOffset: vOff + 4, as: Float.self)
                let lz = vBase.loadUnaligned(fromByteOffset: vOff + 8, as: Float.self)
                let world4 = transform * SIMD4<Float>(lx, ly, lz, 1)
                let world = SIMD3(world4.x, world4.y, world4.z)
                positions.append(world)
                if world.x.isFinite, world.y.isFinite, world.z.isFinite {
                    boundsMin = simd_min(boundsMin, world)
                    boundsMax = simd_max(boundsMax, world)
                }

                let nOff = nSource.stride * i
                let nx = nBase.loadUnaligned(fromByteOffset: nOff,     as: Float.self)
                let ny = nBase.loadUnaligned(fromByteOffset: nOff + 4, as: Float.self)
                let nz = nBase.loadUnaligned(fromByteOffset: nOff + 8, as: Float.self)
                let wn = rotation * SIMD3(nx, ny, nz)
                let len = simd_length(wn)
                normals.append(len > 1e-6 ? wn / len : SIMD3(0, 1, 0))
                colors.append(classPalette[0].rgb)   // 면을 훑으면서 덮어쓴다
                vertexClass.append(0)
            }

            // 면 인덱스 + 면->정점 색 전파.
            let fBase = faceElement.buffer.contents()
            for f in 0..<faceElement.count {
                let idx = fBase.advanced(by: f * 3 * MemoryLayout<UInt32>.size)
                let i0 = idx.loadUnaligned(fromByteOffset: 0, as: UInt32.self)
                let i1 = idx.loadUnaligned(fromByteOffset: 4, as: UInt32.self)
                let i2 = idx.loadUnaligned(fromByteOffset: 8, as: UInt32.self)
                guard Int(i0) < vertexCount, Int(i1) < vertexCount, Int(i2) < vertexCount else { continue }

                let cls = localFaceClasses[f]
                faces.append((UInt32(vertexBase) + i0, UInt32(vertexBase) + i1, UInt32(vertexBase) + i2))
                faceClasses.append(cls)

                // ⚠ 분류는 **면 단위**인데 색은 **정점 단위**다. 경계 정점은 인접한 여러 클래스
                //   중 하나를 골라야 하는데, **우선순위가 높은 쪽이 이기게** 한다.
                //
                //   "나중 면이 이긴다"로 두면 안 되는 이유: 벽 면이 압도적으로 많아서 문/창문
                //   주변 정점이 거의 항상 벽 색으로 덮인다. 즉 시연에서 정작 보여주려는 것이
                //   사라진다 (합성 메시로 재현 확인함).
                //
                //   운 좋게도 ARMeshClassification의 raw value 순서가 그대로 관심도 순이다:
                //   none(0) < wall(1) < floor(2) < ceiling(3) < table(4) < seat(5) < window(6) < door(7)
                //   그래서 단순히 "더 큰 값이 이긴다"로 충분하다.
                //
                //   어디까지나 눈으로 보기 위한 근사이고, 기계가 읽어야 하는 정답 라벨은
                //   면 단위로 정확한 scene_mesh_faces_class.bin 쪽이다.
                if cls != 0 {
                    let rgb = classPalette[Int(cls)].rgb
                    for vi in [vertexBase + Int(i0), vertexBase + Int(i1), vertexBase + Int(i2)]
                    where cls > vertexClass[vi] {
                        vertexClass[vi] = cls
                        colors[vi] = rgb
                    }
                }
            }
        }

        guard !positions.isEmpty, !faces.isEmpty else {
            throw ExportError.emptyMesh
        }

        try writePLY(positions: positions, normals: normals, colors: colors,
                     faces: faces, faceClasses: faceClasses, to: plyURL)

        var classBinWritten: URL?
        if let data = faceClasses.withUnsafeBytes({ Data($0) }) as Data?,
           (try? data.write(to: classBinURL)) != nil {
            classBinWritten = classBinURL
        }

        var counts: [String: Int] = [:]
        for cls in faceClasses {
            let name = classPalette[Int(cls)].name
            counts[name, default: 0] += 1
        }

        return Result(
            vertexCount: positions.count,
            faceCount: faces.count,
            anchorCount: anchors.count,
            classFaceCounts: counts,
            boundsMin: boundsMin,
            boundsMax: boundsMax,
            plyURL: plyURL,
            classBinURL: classBinWritten,
            hasClassification: anyClassification
        )
    }

    // MARK: - PLY 쓰기 (binary_little_endian 1.0)

    /// arm64는 네이티브 little-endian이라 Float/UInt32 비트패턴을 그대로 흘려 쓰면 된다.
    /// 텍스트(ascii) PLY를 쓰지 않는 이유: 정점 50만 개면 파일이 3배로 커지고,
    /// 로컬 Wi-Fi 업로드 시간이 그대로 3배가 된다.
    private static func writePLY(positions: [SIMD3<Float>],
                                 normals: [SIMD3<Float>],
                                 colors: [(UInt8, UInt8, UInt8)],
                                 faces: [(UInt32, UInt32, UInt32)],
                                 faceClasses: [UInt8],
                                 to url: URL) throws {
        var header = ""
        header += "ply\n"
        header += "format binary_little_endian 1.0\n"
        header += "comment Generated by LiDAR_Space3D (ARKit sceneReconstruction)\n"
        header += "comment Coordinate system: ARKit world. Right-handed, Y-up (against gravity), meters.\n"
        header += "comment Origin = device pose at session start. NOT converted to COLMAP convention.\n"
        header += "comment Face 'classification' = ARMeshClassification: "
        header += classPalette.enumerated().map { "\($0.offset)=\($0.element.name)" }.joined(separator: " ")
        header += "\n"
        header += "comment Vertex colors are a visualization of face classification (see sidecar .bin for ground truth).\n"
        header += "element vertex \(positions.count)\n"
        header += "property float x\nproperty float y\nproperty float z\n"
        header += "property float nx\nproperty float ny\nproperty float nz\n"
        header += "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        header += "element face \(faces.count)\n"
        header += "property list uchar uint vertex_indices\n"
        header += "property uchar classification\n"
        header += "end_header\n"

        // 정점 27B + 면 14B. 미리 잡아두지 않으면 수십만 번 재할당이 일어나 저장이 몇 초씩 걸린다.
        var body = [UInt8]()
        body.reserveCapacity(positions.count * 27 + faces.count * 14)

        for i in 0..<positions.count {
            appendFloat(&body, positions[i].x)
            appendFloat(&body, positions[i].y)
            appendFloat(&body, positions[i].z)
            appendFloat(&body, normals[i].x)
            appendFloat(&body, normals[i].y)
            appendFloat(&body, normals[i].z)
            let c = colors[i]
            body.append(c.0); body.append(c.1); body.append(c.2)
        }
        for (i, face) in faces.enumerated() {
            body.append(3)                       // list 길이 (삼각형)
            appendUInt32(&body, face.0)
            appendUInt32(&body, face.1)
            appendUInt32(&body, face.2)
            body.append(i < faceClasses.count ? faceClasses[i] : 0)
        }

        var data = Data(header.utf8)
        data.append(contentsOf: body)
        try data.write(to: url)
    }

    private static func appendFloat(_ buffer: inout [UInt8], _ value: Float) {
        // NaN/Inf가 파일에 들어가면 Open3D가 메시 전체를 거부한다. 0으로 눌러 둔다.
        let safe = value.isFinite ? value : 0
        withUnsafeBytes(of: safe.bitPattern.littleEndian) { buffer.append(contentsOf: $0) }
    }

    private static func appendUInt32(_ buffer: inout [UInt8], _ value: UInt32) {
        withUnsafeBytes(of: value.littleEndian) { buffer.append(contentsOf: $0) }
    }

    enum ExportError: Error, LocalizedError {
        case emptyMesh
        var errorDescription: String? {
            switch self {
            case .emptyMesh:
                return "메시가 비어 있습니다. 스캔 시간이 너무 짧거나 LiDAR 미지원 기기입니다."
            }
        }
    }
}
