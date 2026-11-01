import KakaoMapsSDK
import SwiftUI
import UIKit

// 카카오맵 iOS SDK 지도 — 아이폰 앱(CallMapView)·안드로이드(CallMap)와 같은 지도·핀 모양이다(2026-11-02).
// 아이폰 코드는 PhoneModel에 카메라 상태를 맡기지만, 여기선 화면이 넘겨 주는 fitKey가 바뀔 때만 카메라를 맞춘다(사람이 옮긴 지도는 그대로 둔다).
// 좌표·병원·도로 경로는 hub 데이터 그대로다. 요약 전달 연출을 위해 지도 좌표 → 화면 점 변환(MapProjector)을 내보낸다.

struct MapPin: Identifiable, Equatable {
    enum Kind: String, CaseIterable { case hospital, recommended, selected, approved, rejected, ambulance, incident, base }
    let id: String
    let name: String
    let pos: GpsPoint
    let kind: Kind
}

private extension GpsPoint {
    var mapPoint: MapPoint { MapPoint(longitude: lng, latitude: lat) }
    var valid: Bool { lat.isFinite && lng.isFinite && (-90...90).contains(lat) && (-180...180).contains(lng) }
}

/// 지도 좌표 → 화면 점. SDK에는 화면 → 지도 변환(getPosition)만 있어서, 화면 두 모서리를 지도 좌표로 바꿔 둔 뒤 거꾸로 푼다
/// (경도는 선형, 위도는 메르카토르). 기울이거나 돌리지 않은 지도 기준이고 도시 규모에서 오차는 1px 안팎이다.
struct MapProjector {
    let size: CGSize
    let lng0: Double, lng1: Double
    let mercY0: Double, mercY1: Double

    private static func merc(_ lat: Double) -> Double { log(tan(.pi / 4 + lat * .pi / 360)) }

    init?(a: (lat: Double, lng: Double), b: (lat: Double, lng: Double), size: CGSize) {
        guard size.width > 0, size.height > 0, a.lng != b.lng, a.lat != b.lat else { return nil }
        self.size = size; lng0 = a.lng; lng1 = b.lng; mercY0 = Self.merc(a.lat); mercY1 = Self.merc(b.lat)
    }

    func point(lat: Double, lng: Double) -> CGPoint {
        CGPoint(x: (lng - lng0) / (lng1 - lng0) * size.width,
                y: (Self.merc(lat) - mercY0) / (mercY1 - mercY0) * size.height)
    }
}

/// 구면 거리로 만든 원(존 표시용)
func mapCircle(center: GpsPoint, radiusKm: Double) -> [GpsPoint] {
    let lat = center.lat * .pi / 180, lng = center.lng * .pi / 180
    let angle = radiusKm / 6371
    return (0...180).map { index in
        let bearing = Double(index) * 2 * .pi / 180
        let tLat = asin(sin(lat) * cos(angle) + cos(lat) * sin(angle) * cos(bearing))
        let tLng = lng + atan2(sin(bearing) * sin(angle) * cos(lat), cos(angle) - sin(lat) * sin(tLat))
        return GpsPoint(lat: tLat * 180 / .pi, lng: tLng * 180 / .pi)
    }
}

struct KakaoMapView: UIViewRepresentable {
    let pins: [MapPin]
    let routePath: [[Double]]
    /// 활성 존(구급차 중심 반경 km) — 없으면 안 그린다
    let zoneRadiusKm: Double?
    /// 이 값이 바뀔 때만 카메라를 fitPoints에 맞춘다
    let fitKey: String
    let fitPoints: [GpsPoint]
    let onPin: (String) -> Void
    let onProjector: (MapProjector?) -> Void
    let onMessage: (String?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> KMViewContainer {
        let container = KMViewContainer()
        context.coordinator.start(container)
        return container
    }
    func updateUIView(_ uiView: KMViewContainer, context: Context) {
        context.coordinator.input = self
        context.coordinator.scheduleRender()
    }
    static func dismantleUIView(_ uiView: KMViewContainer, coordinator: Coordinator) { coordinator.stop() }

    @MainActor final class Coordinator: NSObject, MapControllerDelegate, KakaoMapEventDelegate {
        var input: KakaoMapView
        private var controller: KMController?
        private weak var container: KMViewContainer?
        private var map: KakaoMap?
        private var pinLayer: LabelLayer?
        private var ambulanceLayer: LabelLayer?
        private var zoneLayer: ShapeLayer?
        private var routeLayer: RouteLayer?
        private var pois: [String: Poi] = [:]
        private var priorPins: [String: MapPin] = [:]
        private var priorStyles: [String: String] = [:]
        private var priorRoute: [[Double]] = []
        private var zoneSignature: String?
        private var lastFitKey: String?
        private var stopped = false
        private var renderScheduled = false
        private var foreground = true
        private var observers: [NSObjectProtocol] = []
        private static var initializedKey = ""
        // 관제 지도 dashboard/src/lib/control-map.ts의 C.zone과 같은 보라색
        private static var zoneColor: UIColor { UIColor(red: 123 / 255, green: 77 / 255, blue: 1, alpha: 1) }

        init(_ input: KakaoMapView) { self.input = input }
        private func message(_ value: String?) {
            DispatchQueue.main.async { [weak self] in guard let self, !self.stopped else { return }; self.input.onMessage(value) }
        }
        func start(_ view: KMViewContainer) {
            container = view
            let key = Settings.kakaoNativeAppKey
            guard !key.isEmpty else { message("카카오맵 네이티브 앱 키가 없습니다. 설정 > 카카오맵에 키를 넣거나 Config/Kakao.local.xcconfig에 입력하세요."); return }
            if Self.initializedKey != key { SDKInitializer.InitSDK(appKey: key); Self.initializedKey = key }
            controller = KMController(viewContainer: view)
            controller?.delegate = self
            controller?.prepareEngine()
            controller?.activateEngine()
            observers = [
                NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.setAppActive(false) } },
                NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.setAppActive(true) } },
            ]
        }
        func stop() {
            stopped = true
            observers.forEach(NotificationCenter.default.removeObserver); observers = []
            map?.eventDelegate = nil
            controller?.pauseEngine(); controller?.resetEngine(); controller?.delegate = nil
            pois = [:]; priorPins = [:]; priorStyles = [:]; pinLayer = nil; ambulanceLayer = nil; zoneLayer = nil; routeLayer = nil; map = nil; controller = nil
        }
        private func setAppActive(_ active: Bool) {
            guard !stopped else { return }
            foreground = active
            if active { controller?.activateEngine(); scheduleRender() } else { controller?.pauseEngine() }
        }
        nonisolated func addViews() { DispatchQueue.main.async { [weak self] in self?.addMapView() } }
        private func addMapView() {
            guard !stopped else { return }
            let center = input.pins.first(where: { $0.kind == .ambulance && $0.pos.valid })?.pos.mapPoint ?? MapPoint(longitude: 126.978, latitude: 37.5665)
            controller?.addView(MapviewInfo(viewName: "ipad-map", viewInfoName: "map", defaultPosition: center, defaultLevel: 15))
        }
        nonisolated func addViewSucceeded(_ viewName: String, viewInfoName: String) {
            DispatchQueue.main.async { [weak self] in self?.configureMap(viewName) }
        }
        private func configureMap(_ viewName: String) {
            guard !stopped, let view = controller?.getView(viewName) as? KakaoMap else { return }
            map = view; view.eventDelegate = self
            view.setLogoPosition(origin: GuiAlignment(vAlign: .bottom, hAlign: .left), position: CGPoint(x: 12, y: 12))
            if let size = container?.bounds.size { view.viewRect = CGRect(origin: .zero, size: size) }
            let manager = view.getLabelManager()
            // SDK 기본 지명·장소 POI는 0~4999 영역을 쓴다. 앱 핀은 그 위, 구급차는 별도 최상단 레이어에 둔다
            pinLayer = manager.addLabelLayer(option: LabelLayerOptions(layerID: "pins", competitionType: .none, competitionUnit: .poi, orderType: .rank, zOrder: 5000))
            ambulanceLayer = manager.addLabelLayer(option: LabelLayerOptions(layerID: "ambulance-foreground", competitionType: .none, competitionUnit: .poi, orderType: .rank, zOrder: 10000))
            for kind in MapPin.Kind.allCases {
                let color: UIColor
                switch kind {
                case .ambulance: color = UIColor(AD.orange)
                case .incident: color = UIColor(AD.red)
                case .recommended, .approved: color = UIColor(AD.green)
                case .selected: color = UIColor(AD.blue)
                case .rejected: color = UIColor(AD.red)
                default: color = UIColor(AD.navy)
                }
                // 줌 15에서 구급차 28pt, 병원 21pt. 스타일은 한 번만 만들고 지도 엔진이 줌 레벨에 맞는 크기를 고른다
                let styles = [0, 12, 13, 14, 15, 16, 17].map { level -> PerLevelPoiStyle in
                    let scale = max(kind == .ambulance ? 0.75 : 0.6, min(1.35, pow(1.18, Double(level - 15))))
                    let size = CGFloat(kind == .ambulance ? 22.4 : 21) * scale * 1.15   // 아이패드는 화면이 커서 조금 키운다
                    let icon = PoiIconStyle(symbol: Self.marker(kind: kind, color: color, size: size))
                    let fontSize = UInt(max(9, min(13, (12 * scale).rounded())))
                    let text = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(fontSize: fontSize, fontColor: UIColor(AD.navy), strokeThickness: 2, strokeColor: .white))])
                    text.textLayouts = [.bottom]
                    return PerLevelPoiStyle(iconStyle: icon, textStyle: text, level: level)
                }
                manager.addPoiStyle(PoiStyle(styleID: kind.rawValue, styles: styles))
            }
            let shapes = view.getShapeManager()
            zoneLayer = shapes.addShapeLayer(layerID: "response-zone", zOrder: 1)
            let purple = Self.zoneColor
            shapes.addPolygonStyleSet(PolygonStyleSet(styleSetID: "zone", styles: [
                PolygonStyle(styles: [PerLevelPolygonStyle(color: purple.withAlphaComponent(0.10), strokeWidth: 2, strokeColor: purple.withAlphaComponent(0.55), level: 0)]),
            ]))
            let routes = view.getRouteManager()
            routes.addRouteStyleSet(RouteStyleSet(styleID: "road", styles: [RouteStyle(styles: [PerLevelRouteStyle(width: 6, color: UIColor(AD.blue), strokeWidth: 1, strokeColor: .white, level: 0)])]))
            routeLayer = routes.addRouteLayer(layerID: "route", zOrder: 10)
            message(nil); scheduleRender()
        }
        nonisolated func authenticationFailed(_ errorCode: Int, desc: String) {
            DispatchQueue.main.async { [weak self] in self?.showAuthenticationError(errorCode) }
        }
        private func showAuthenticationError(_ errorCode: Int) {
            let reason: String
            switch errorCode {
            case 401: reason = "네이티브 앱 키를 확인하세요."
            case 403: reason = "카카오 디벨로퍼스의 번들 ID(com.goldenlink.pad)와 카카오맵 사용 설정을 확인하세요."
            case 429: reason = "카카오맵 사용량 한도를 확인하세요."
            default: reason = "네트워크와 카카오맵 설정을 확인하세요."
            }
            message("카카오맵 인증 실패(\(errorCode)). \(reason)")
        }
        nonisolated func addViewFailed(_ viewName: String, viewInfoName: String) {
            DispatchQueue.main.async { [weak self] in self?.message("카카오맵을 불러오지 못했습니다. 네트워크 연결을 확인한 뒤 [지도]를 다시 열어 주세요.") }
        }
        nonisolated func containerDidResized(_ size: CGSize) {
            DispatchQueue.main.async { [weak self] in
                self?.map?.viewRect = CGRect(origin: .zero, size: size)
                self?.scheduleRender(); self?.publishProjector()
            }
        }
        nonisolated func poiDidTapped(kakaoMap: KakaoMap, layerID: String, poiID: String, position: MapPoint) {
            guard layerID == "pins" else { return }
            DispatchQueue.main.async { [weak self] in self?.input.onPin(poiID) }
        }
        nonisolated func cameraDidStopped(kakaoMap: KakaoMap, by: MoveBy) {
            DispatchQueue.main.async { [weak self] in self?.publishProjector() }
        }

        /// 화면 좌상단·우하단을 지도 좌표로 바꿔 화면 점 변환기를 만들어 내보낸다
        private func publishProjector() {
            guard !stopped, let map, let size = container?.bounds.size, size.width > 0 else { return }
            let a = map.getPosition(.zero).wgsCoord, b = map.getPosition(CGPoint(x: size.width, y: size.height)).wgsCoord
            input.onProjector(MapProjector(a: (a.latitude, a.longitude), b: (b.latitude, b.longitude), size: size))
        }

        func scheduleRender() {
            guard !renderScheduled, !stopped else { return }
            renderScheduled = true
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.renderScheduled = false
                self.render()
            }
        }
        private func render() {
            guard !stopped, let map, let pinLayer, let ambulanceLayer, let container, container.bounds.width > 0, container.bounds.height > 0 else { return }
            let visible = input.pins.filter { $0.pos.valid }
            let ids = Set(visible.map(\.id))
            for id in Array(pois.keys) where !ids.contains(id) {
                let layer = pois[id]?.layerID == "ambulance-foreground" ? ambulanceLayer : pinLayer
                layer.removePoi(poiID: id); pois[id] = nil; priorPins[id] = nil; priorStyles[id] = nil
            }
            for pin in visible {
                let layer = pin.kind == .ambulance ? ambulanceLayer : pinLayer
                let style = pin.kind.rawValue
                if let poi = pois[pin.id] {
                    if priorPins[pin.id]?.pos != pin.pos { poi.moveAt(pin.pos.mapPoint, duration: pin.kind == .ambulance ? 200 : 0) }
                    if priorPins[pin.id]?.name != pin.name || priorStyles[pin.id] != style {
                        poi.changeTextAndStyle(texts: pin.name.isEmpty ? [] : [PoiText(text: pin.name, styleIndex: 0)], styleID: style)
                    }
                } else {
                    let options = PoiOptions(styleID: style, poiID: pin.id)
                    options.clickable = true; options.rank = pin.kind == .ambulance ? 30 : pin.kind == .selected ? 20 : 10
                    if !pin.name.isEmpty { options.addText(PoiText(text: pin.name, styleIndex: 0)) }
                    pois[pin.id] = layer.addPoi(option: options, at: pin.pos.mapPoint)
                    pois[pin.id]?.show()
                }
                priorPins[pin.id] = pin
                priorStyles[pin.id] = style
            }
            if input.routePath != priorRoute {
                routeLayer?.clearAllRoutes()
                let points = input.routePath.compactMap { p -> MapPoint? in
                    guard p.count == 2, p[0].isFinite, p[1].isFinite, (-90...90).contains(p[0]), (-180...180).contains(p[1]) else { return nil }
                    return MapPoint(longitude: p[1], latitude: p[0])
                }
                if points.count > 1 {
                    let options = RouteOptions(routeID: "road", styleID: "road", zOrder: 0)
                    options.segments = [RouteSegment(points: points, styleIndex: 0)]
                    routeLayer?.addRoute(option: options)?.show()
                }
                priorRoute = input.routePath
            }
            let insets = UIEdgeInsets(top: 60, left: 60, bottom: 60, right: 60)
            if map.margins != insets { map.setMargins(insets) }
            updateZone()
            if lastFitKey != input.fitKey {
                lastFitKey = input.fitKey
                fit(input.fitPoints.filter(\.valid).map(\.mapPoint))
            }
            publishProjector()
        }
        private func fit(_ points: [MapPoint]) {
            guard let map, !points.isEmpty else { return }
            if points.count == 1 { map.moveCamera(CameraUpdate.make(target: points[0], zoomLevel: 15, mapView: map)) }
            else { map.moveCamera(CameraUpdate.make(area: AreaRect(points: points), levelLimit: 17)) }
            // 카메라가 옮겨진 뒤 변환기를 다시 만든다(연출 위치가 어긋나지 않게)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.publishProjector() }
        }
        private func updateZone() {
            guard foreground, let layer = zoneLayer else { return }
            guard let km = input.zoneRadiusKm, let amb = input.pins.first(where: { $0.kind == .ambulance && $0.pos.valid }) else {
                guard zoneSignature != nil else { return }
                zoneSignature = nil; layer.clearAllShapes(); return
            }
            let key = "\(amb.pos)-\(km)"
            guard zoneSignature != key else { return }
            zoneSignature = key
            layer.clearAllShapes()
            let options = MapPolygonShapeOptions(shapeID: "zone-boundary", styleID: "zone", zOrder: 0)
            options.polygons = [MapPolygon(exteriorRing: mapCircle(center: amb.pos, radiusKm: km).map(\.mapPoint), holes: nil, styleIndex: 0)]
            layer.addMapPolygonShape(options)?.show()
        }

        /// 병원·구급차는 사각 박스+십자가(구급차는 주황), 사건 현장은 마름모 느낌표, 센터는 건물
        private static func marker(kind: MapPin.Kind, color: UIColor, size: CGFloat) -> UIImage {
            UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { context in
                context.cgContext.scaleBy(x: size / 28, y: size / 28)
                func box(_ rect: CGRect, color: UIColor, radius: CGFloat = 0) {
                    color.setFill()
                    UIBezierPath(roundedRect: rect, cornerRadius: radius).fill()
                }
                func cross(x: CGFloat, y: CGFloat, length: CGFloat, thickness: CGFloat) {
                    box(CGRect(x: x + (length - thickness) / 2, y: y, width: thickness, height: length), color: .white)
                    box(CGRect(x: x, y: y + (length - thickness) / 2, width: length, height: thickness), color: .white)
                }
                switch kind {
                case .hospital, .recommended, .selected, .ambulance, .approved, .rejected:
                    box(CGRect(x: 0, y: 0, width: 28, height: 28), color: .white, radius: 6)
                    box(CGRect(x: 2, y: 2, width: 24, height: 24), color: color, radius: 4)
                    cross(x: 6, y: 6, length: 16, thickness: 5)
                case .base:
                    box(CGRect(x: 1, y: 1, width: 26, height: 26), color: .white, radius: 4)
                    box(CGRect(x: 3, y: 3, width: 22, height: 22), color: color, radius: 3)
                    box(CGRect(x: 7, y: 14, width: 14, height: 11), color: .white, radius: 1)
                    cross(x: 10, y: 5, length: 8, thickness: 2)
                case .incident:
                    let diamond = UIBezierPath()
                    diamond.move(to: CGPoint(x: 14, y: 1))
                    diamond.addLine(to: CGPoint(x: 27, y: 14))
                    diamond.addLine(to: CGPoint(x: 14, y: 27))
                    diamond.addLine(to: CGPoint(x: 1, y: 14)); diamond.close()
                    color.setFill(); diamond.fill()
                    UIColor.white.setStroke(); diamond.lineWidth = 2; diamond.stroke()
                    box(CGRect(x: 12, y: 6, width: 4, height: 11), color: .white, radius: 1)
                    box(CGRect(x: 12, y: 19, width: 4, height: 4), color: .white, radius: 1)
                }
            }
        }
    }
}
