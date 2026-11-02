import GoldenLinkCore
import KakaoMapsSDK
import SwiftUI
import UIKit
import CoreLocation

// 실제 지도 표시는 카카오맵 iOS SDK. 좌표·병원 선택·도로 경로는 기존 hub 데이터를 그대로 쓴다.
struct MapPin: Identifiable, Equatable {
    enum Kind: String, CaseIterable { case hospital, recommended, selected, ambulance, incident, base }
    let id: String
    let name: String
    let pos: GPS
    let kind: Kind
}


/// SDK의 PoiText 하나가 한 줄이다. 긴 이름은 폭에 맞춰 나누고 원문을 모두 보존한다.
private enum MapNodeLabel {
    static func texts(for pin: MapPin) -> [PoiText] {
        guard !pin.name.isEmpty else { return [] }
        guard pin.kind != .incident && pin.kind != .base else { return [PoiText(text: pin.name, styleIndex: 0)] }
        let font = UIFont.systemFont(ofSize: 12)
        let width: CGFloat = 160
        var lines: [String] = []
        for paragraph in pin.name.components(separatedBy: .newlines) {
            var rest = paragraph.trimmingCharacters(in: .whitespaces)
            while !rest.isEmpty {
                var end = rest.startIndex
                while end < rest.endIndex {
                    let next = rest.index(after: end)
                    let measured = (String(rest[..<next]) as NSString).size(withAttributes: [.font: font]).width
                    if measured > width && end > rest.startIndex { break }
                    end = next
                }
                // 가능하면 단어 사이에서 줄을 바꾸되, 공백 없는 긴 병원명도 잘라 표시한다.
                if end < rest.endIndex, let space = rest[..<end].lastIndex(of: " "),
                   rest.distance(from: rest.startIndex, to: space) >= rest.distance(from: rest.startIndex, to: end) / 2 {
                    end = space
                }
                lines.append(String(rest[..<end]).trimmingCharacters(in: .whitespaces))
                rest = String(rest[end...]).trimmingCharacters(in: .whitespaces)
            }
        }
        return lines.map { PoiText(text: $0, styleIndex: 0) }
    }
}

private extension GPS {
    var mapPoint: MapPoint { MapPoint(longitude: lng, latitude: lat) }
    var validMapPoint: Bool { lat.isFinite && lng.isFinite && (-90...90).contains(lat) && (-180...180).contains(lng) }
}

/// hub/geo.py의 규칙 기반 존 폭(5km). 활성 존은 매칭 결과를 그대로 따른다.
struct ResponseZone: Equatable {
    let bands: [Int]
    var activeBands: [Int] { Array(Set(bands.filter { $0 > 0 })).sorted() }
    var radiusKm: Double { Double(activeBands.last ?? 1) * 5 }
}

struct MapProjector: Equatable {
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


struct CallMapView: View {
    let pins: [MapPin]
    let routePath: [[Double]]
    let showCandidates: Bool
    let sceneFocusKey: String?
    let bottomOverlayHeight: CGFloat
    let topOverlayHeight: CGFloat
    let navigate: Bool
    let navAvailable: Bool
    let navSession: String
    let active: Bool
    let onToggleNavigation: () -> Void
    let onNavigationReady: () -> Void
    let responseZone: ResponseZone?
    let onPin: (String) -> Void
    @Environment(PhoneModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var centerRequest = 0
    @State private var projector: MapProjector?
    @State private var mapMessage: String? = "카카오맵을 불러오는 중…"

    var body: some View {
        KakaoCallMap(model: model, pins: pins, routePath: routePath, showCandidates: showCandidates,
                     sceneFocusKey: sceneFocusKey, bottomOverlayHeight: bottomOverlayHeight, topOverlayHeight: topOverlayHeight,
                     navigate: navigate, navSession: navSession, active: active, onNavigationReady: onNavigationReady,
                     responseZone: responseZone, centerRequest: centerRequest, reduceMotion: reduceMotion,
                     onPin: onPin, onMessage: { mapMessage = $0; if $0 != nil { onNavigationReady() } }, onProjector: { projector = $0 })
            .id(Settings.kakaoNativeAppKey)
            .overlay {
                if let mapMessage {
                    Text(mapMessage).font(.system(size: 13)).multilineTextAlignment(.center)
                        .padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(AD.bg.opacity(0.95)).accessibilityLabel(mapMessage)
                }
            }
            .overlay {
                if let show = model.deliveryShow, mapMessage == nil, let p = projector,
                   let from = pins.first(where: { $0.kind == .ambulance }) {
                    DeliveryOverlay(show: show, from: .init(latitude: from.pos.lat, longitude: from.pos.lng),
                                    targets: deliveryTargets, project: { p.point(lat: $0.latitude, lng: $0.longitude) },
                                    onSkip: { model.finishDelivery() })
                }
            }
            .overlay(alignment: .topTrailing) {
                Button { if navAvailable { onToggleNavigation() } else { centerRequest += 1 } } label: {
                    Label(navAvailable ? (navigate ? "경로 전체 보기" : "내비 시점") : "내 위치",
                          systemImage: navAvailable ? (navigate ? "map" : "location.north.fill") : "location.fill")
                        .labelStyle(.iconOnly)
                        .font(.system(size: 13, weight: .semibold)).padding(.horizontal, 16).frame(minHeight: 44)
                        .background(.white, in: Capsule()).shadow(radius: 3)
                }
                .padding(12).padding(.top, topOverlayHeight - (navigate ? 96 : 12))
                .disabled(mapMessage != nil || !pins.contains { $0.kind == .ambulance && $0.pos.validMapPoint })
                .accessibilityHint(navAvailable ? "경로 전체 보기와 진행 방향 시점을 전환합니다" : "현재 구급차 위치로 지도를 이동합니다")
            }
    }
    private var deliveryTargets: [DeliveryTarget] {
        (model.result?.hospitals ?? []).compactMap { h -> DeliveryTarget? in
            guard let gps = model.hospitalGps[h.hospitalId] else { return nil }
            return DeliveryTarget(id: h.hospitalId, name: h.name, coordinate: .init(latitude: gps.lat, longitude: gps.lng))
        }.prefix(DeliveryTimeline.maxTargets).map { $0 }
    }

}

private struct KakaoCallMap: UIViewRepresentable {
    let model: PhoneModel
    let pins: [MapPin]
    let routePath: [[Double]]
    let showCandidates: Bool
    let sceneFocusKey: String?
    let bottomOverlayHeight: CGFloat
    let topOverlayHeight: CGFloat
    let navigate: Bool
    let navSession: String
    let active: Bool
    let onNavigationReady: () -> Void
    let responseZone: ResponseZone?
    let centerRequest: Int
    let reduceMotion: Bool
    let onPin: (String) -> Void
    let onMessage: (String?) -> Void
    let onProjector: (MapProjector?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> KMViewContainer {
        let container = KMViewContainer()
        context.coordinator.start(container)
        return container
    }
    func updateUIView(_ uiView: KMViewContainer, context: Context) {
        context.coordinator.input = self
        context.coordinator.setVisible(active)
        uiView.isHidden = !active
        context.coordinator.scheduleRender()
    }
    static func dismantleUIView(_ uiView: KMViewContainer, coordinator: Coordinator) { coordinator.stop() }

    @MainActor final class Coordinator: NSObject, MapControllerDelegate, KakaoMapEventDelegate {
        var input: KakaoCallMap
        private var controller: KMController?
        private weak var container: KMViewContainer?
        private var map: KakaoMap?
        private var pinLayer: LabelLayer?
        private var ambulanceLayer: LabelLayer?
        private var zoneLayer: ShapeLayer?
        private var pulseShape: MapPolygonShape?
        private var routeLayer: ShapeLayer?
        private var roadLine: MapPolylineShape?
        private var pois: [String: Poi] = [:]
        private var priorPins: [String: MapPin] = [:]
        private var priorStyles: [String: String] = [:]
        private var priorRoute: [[Double]] = []
        private var soloAmbulanceFocus: String?
        private var animatedReturnPath: [[Double]]?
        private var firstCamera = true
        private var lastCenter = 0
        private var pulseTask: Task<Void, Never>?
        private var zoneSignature: String?
        private var foreground = true
        private var observers: [NSObjectProtocol] = []
        private var lastProjector: MapProjector?
        private var markerTask: Task<Void, Never>?
        private var navigationTask: Task<Void, Never>?
        private var navigationGeneration = UUID()
        private var navigationSession: String?
        private var navigationCamera = NavigationCamera()
        private var navReady = false
        private var wasNavigating = false
        private var markerFrame = 0
        private var heading = 0

        private var stopped = false
        private var renderScheduled = false
        private static var initializedKey = ""
        // 관제 지도 dashboard/src/lib/control-map.ts의 C.zone과 같은 보라색.
        private static var zoneColor: UIColor { UIColor(red: 123 / 255, green: 77 / 255, blue: 1, alpha: 1) }

        init(_ input: KakaoCallMap) { self.input = input }
        private func message(_ value: String?) {
            DispatchQueue.main.async { [weak self] in guard let self, !self.stopped else { return }; self.input.onMessage(value) }
        }
        func start(_ view: KMViewContainer) {
            container = view
            let key = Settings.kakaoNativeAppKey
            guard !key.isEmpty else { message("카카오맵 네이티브 앱 키가 없습니다. 앱 설정 또는 Config/Kakao.local.xcconfig에 키를 입력하세요."); return }
            if Self.initializedKey != key { SDKInitializer.InitSDK(appKey: key); Self.initializedKey = key }
            controller = KMController(viewContainer: view)
            controller?.delegate = self
            controller?.prepareEngine()
            controller?.activateEngine()
            observers = [
                NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.setAppActive(false) } },
                NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.setAppActive(true) } }
            ]
        }
        func stop() {
            stopped = true; navigationGeneration = UUID(); navigationTask?.cancel(); navigationTask = nil; markerTask?.cancel(); markerTask = nil; pulseTask?.cancel(); pulseTask = nil
            observers.forEach(NotificationCenter.default.removeObserver); observers = []
            if let map { input.model.kakaoCamera = CameraUpdate.make(mapView: map).cameraPosition }
            roadLine = nil
            map?.eventDelegate = nil
            controller?.pauseEngine(); controller?.resetEngine(); controller?.delegate = nil
            pois = [:]; priorPins = [:]; priorStyles = [:]; pinLayer = nil; ambulanceLayer = nil; pulseShape = nil; zoneLayer = nil; routeLayer = nil; map = nil; controller = nil
        }
        func setVisible(_ active: Bool) {
            if !active {
                navigationGeneration = UUID(); navigationTask?.cancel(); navigationTask = nil
                pulseTask?.cancel(); pulseTask = nil; zoneSignature = nil
            }
        }
        private func setAppActive(_ active: Bool) {
            guard !stopped else { return }
            foreground = active
            if active { controller?.activateEngine(); scheduleRender() }
            else { navigationGeneration = UUID(); navigationTask?.cancel(); navigationTask = nil; pulseTask?.cancel(); pulseTask = nil; zoneSignature = nil; animatedReturnPath = nil; controller?.pauseEngine() }
        }
        nonisolated func addViews() {
            DispatchQueue.main.async { [weak self] in self?.addMapView() }
        }
        private func addMapView() {
            guard !stopped else { return }
            let center = input.pins.first(where: { $0.kind == .ambulance && $0.pos.validMapPoint })?.pos.mapPoint ?? MapPoint(longitude: 126.978, latitude: 37.5665)
            controller?.addView(MapviewInfo(viewName: "call-map", viewInfoName: "map", defaultPosition: center, defaultLevel: 15))
        }
        nonisolated func addViewSucceeded(_ viewName: String, viewInfoName: String) {
            DispatchQueue.main.async { [weak self] in self?.configureMap(viewName) }
        }
        private func configureMap(_ viewName: String) {
            guard !stopped, let view = controller?.getView(viewName) as? KakaoMap else { return }
            map = view; view.eventDelegate = self
            // 하단 전화 카드에 공급자 로고가 가려지지 않게 빈 왼쪽 위에 둔다.
            view.setLogoPosition(origin: GuiAlignment(vAlign: .top, hAlign: .left), position: CGPoint(x: 12, y: 12))
            if let size = container?.bounds.size { view.viewRect = CGRect(origin: .zero, size: size) }
            let manager = view.getLabelManager()
            // SDK의 기본 지명·장소 POI는 0~4999 영역을 사용한다. 앱 핀은 그 위,
            // 구급차는 별도 최상단 레이어에 두어 병원·지도 글자에 가려지지 않게 한다.
            pinLayer = manager.addLabelLayer(option: LabelLayerOptions(layerID: "pins", competitionType: .none, competitionUnit: .poi, orderType: .rank, zOrder: 5000))
            ambulanceLayer = manager.addLabelLayer(option: LabelLayerOptions(layerID: "ambulance-foreground", competitionType: .none, competitionUnit: .poi, orderType: .rank, zOrder: 10000))
            for kind in MapPin.Kind.allCases {
                let color: UIColor
                switch kind {
                case .ambulance: color = UIColor(AD.orange)
                case .incident: color = UIColor(AD.red)
                case .recommended: color = UIColor(AD.green)
                case .selected: color = UIColor(AD.blue)
                default: color = UIColor(AD.navy)
                }
                // 줌 15에서 구급차 28pt, 병원 21pt. 구급차는 축소해도 최소 21pt로 식별한다.
                // 스타일은 한 번만 만들고
                // 지도 엔진이 줌 레벨에 맞는 크기를 선택한다(카메라 콜백에서 핀을 다시 만들지 않음).
                for variant in 0..<(kind == .ambulance ? 48 : 1) {
                    let styles = [0, 12, 13, 14, 15, 16, 17].map { level -> PerLevelPoiStyle in
                        let scale = max(kind == .ambulance ? 0.75 : 0.6, min(1.35, pow(1.18, Double(level - 15))))
                        let size = CGFloat(kind == .ambulance ? 22.4 * 0.68 : 21) * scale
                        let icon = PoiIconStyle(symbol: Self.marker(kind: kind, color: color, size: size, heading: Double(variant / 2) * 15, beacon: variant % 2 == 0))
                        let baseFontSize = max(9, min(12, (11 * scale).rounded()))
                        let nameScale = 1.0
                        let fontSize = UInt((baseFontSize * nameScale).rounded())
                        let text = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(fontSize: fontSize, fontColor: UIColor(AD.navy), strokeThickness: 2, strokeColor: .white))])
                        text.textLayouts = [.bottom]
                        return PerLevelPoiStyle(iconStyle: icon, textStyle: text, level: level)
                    }
                    manager.addPoiStyle(PoiStyle(styleID: kind == .ambulance ? "ambulance-\(variant)" : kind.rawValue, styles: styles))
                }
            }
            markerTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(450)) } catch { return }
                    guard let self, !self.stopped else { return }
                    if self.foreground {
                        self.markerFrame = (self.markerFrame + 1) % 2
                        self.scheduleRender()
                    }
                }
            }
            let shapes = view.getShapeManager()
            zoneLayer = shapes.addShapeLayer(layerID: "response-zone", zOrder: 1)
            let purple = Self.zoneColor
            // 고정 영역이 펄스가 끝난 뒤에도 지도에서 분명히 보이도록 채움과 경계를 유지한다.
            var zoneStyles = [PolygonStyle(styles: [PerLevelPolygonStyle(color: purple.withAlphaComponent(0.12), level: 0)])]
            for step in 0..<16 {
                let strength = CGFloat(step + 1) / 16
                zoneStyles.append(PolygonStyle(styles: [PerLevelPolygonStyle(color: purple.withAlphaComponent(strength * 0.018), strokeWidth: 2, strokeColor: purple.withAlphaComponent(strength * 0.5), level: 0)]))
            }
            shapes.addPolygonStyleSet(PolygonStyleSet(styleSetID: "zone", styles: zoneStyles))
            shapes.addPolylineStyleSet(PolylineStyleSet(styleSetID: "zone-outline", styles: [CGFloat(0.9), 0.72].map { alpha in
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: purple.withAlphaComponent(alpha), bodyWidth: 3, level: 0)])
            }, capType: .round))
            // hub의 도로 꼭짓점을 생략 없이 그려 짧은 도로·회전 구간도 표시한다.
            shapes.addPolylineStyleSet(PolylineStyleSet(styleSetID: "road-line", styles: [
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: UIColor(AD.blue), bodyWidth: 6,
                    strokeColor: .white, strokeWidth: 2, level: 0)]),
            ], capType: .round))
            routeLayer = shapes.addShapeLayer(layerID: "road-line", zOrder: 100)
            routeLayer?.visible = true
            message(nil); scheduleRender()
        }
        nonisolated func authenticationFailed(_ errorCode: Int, desc: String) {
            DispatchQueue.main.async { [weak self] in self?.showAuthenticationError(errorCode) }
        }
        private func showAuthenticationError(_ errorCode: Int) {
            let reason: String
            switch errorCode {
            case 401: reason = "네이티브 앱 키를 확인하세요."
            case 403: reason = "카카오 디벨로퍼스의 번들 ID와 카카오맵 사용 설정을 확인하세요."
            case 429: reason = "카카오맵 사용량 한도를 확인하세요."
            default: reason = "네트워크와 카카오맵 설정을 확인하세요."
            }
            message("카카오맵 인증 실패(\(errorCode)). \(reason)")
        }
        nonisolated func addViewFailed(_ viewName: String, viewInfoName: String) {
            DispatchQueue.main.async { [weak self] in self?.message("카카오맵을 불러오지 못했습니다. 네트워크 연결을 확인한 뒤 통화 탭을 다시 열어 주세요.") }
        }
        nonisolated func containerDidResized(_ size: CGSize) {
            DispatchQueue.main.async { [weak self] in
                self?.map?.viewRect = CGRect(origin: .zero, size: size)
                self?.scheduleRender()
            }
        }
        nonisolated func poiDidTapped(kakaoMap: KakaoMap, layerID: String, poiID: String, position: MapPoint) {
            guard layerID == "pins" else { return }
            DispatchQueue.main.async { [weak self] in self?.input.onPin(poiID) }
        }
        nonisolated func cameraDidStopped(kakaoMap: KakaoMap, by: MoveBy) {
            DispatchQueue.main.async { [weak self] in
                guard let self, let map = self.map else { return }
                self.input.model.kakaoCamera = CameraUpdate.make(mapView: map).cameraPosition
                self.publishProjector()
            }
        }

        private func publishProjector() {
            guard !stopped, let map, let size = container?.bounds.size, size.width > 0 else { return }
            let a = map.getPosition(.zero).wgsCoord
            let b = map.getPosition(CGPoint(x: size.width, y: size.height)).wgsCoord
            let next = MapProjector(a: (a.latitude, a.longitude), b: (b.latitude, b.longitude), size: size)
            guard next != lastProjector else { return }
            lastProjector = next
            input.onProjector(next)
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
            guard !stopped, input.active, let map, let pinLayer, let ambulanceLayer, let container, container.bounds.width > 0, container.bounds.height > 0 else { return }
            defer { publishProjector() }
            let visible = input.pins.filter { $0.pos.validMapPoint && (input.showCandidates || [.ambulance, .incident, .base, .selected].contains($0.kind)) }
            if input.sceneFocusKey == nil, input.model.sceneMapFocusKey != nil { input.model.sceneMapFocusKey = nil }
            let ids = Set(visible.map(\.id))
            for id in Array(pois.keys) where !ids.contains(id) {
                let layer = pois[id]?.layerID == "ambulance-foreground" ? ambulanceLayer : pinLayer
                layer.removePoi(poiID: id); pois[id] = nil; priorPins[id] = nil; priorStyles[id] = nil
            }
            if let pin = visible.first(where: { $0.kind == .ambulance }), let before = priorPins[pin.id] {
                let dy = pin.pos.lat - before.pos.lat
                let dx = (pin.pos.lng - before.pos.lng) * cos(pin.pos.lat * .pi / 180)
                if hypot(dx, dy) > 0.000001 {
                    heading = (Int(((atan2(dx, dy) * 180 / .pi + 360) / 15).rounded()) % 24)
                }
            }
            for pin in visible {
                let layer = pin.kind == .ambulance ? ambulanceLayer : pinLayer
                let style = pin.kind == .ambulance ? "ambulance-\((input.navigate ? 0 : heading) * 2 + markerFrame)" : pin.kind.rawValue
                if let poi = pois[pin.id] {
                    if priorPins[pin.id]?.pos != pin.pos {
                        if pin.kind != .ambulance || (!input.navigate && (!animateReturn || input.routePath.count < 2)) {
                            poi.moveAt(pin.pos.mapPoint, duration: pin.kind == .ambulance && animatedReturnPath != nil ? 200 : 0)
                        }
                    }
                    if priorPins[pin.id]?.name != pin.name || priorStyles[pin.id] != style {
                        poi.changeTextAndStyle(texts: MapNodeLabel.texts(for: pin), styleID: style)
                    }
                } else {
                    let options = PoiOptions(styleID: style, poiID: pin.id)
                    options.clickable = true; options.rank = pin.kind == .ambulance ? 30 : pin.kind == .selected ? 20 : 10
                    for text in MapNodeLabel.texts(for: pin) { options.addText(text) }
                    pois[pin.id] = layer.addPoi(option: options, at: pin.pos.mapPoint)
                    pois[pin.id]?.show()
                }
                priorPins[pin.id] = pin
                priorStyles[pin.id] = style
            }
            let routeChanged = input.routePath != priorRoute
            if routeChanged {
                let points = routePoints
                if points.count > 1 {
                    let lines = [MapPolyline(line: points, styleIndex: 0)]
                    if let roadLine {
                        roadLine.changeStyleAndData(styleID: "road-line", lines: lines)
                        roadLine.show()
                    } else {
                        let options = MapPolylineShapeOptions(shapeID: "road", styleID: "road-line", zOrder: 0)
                        options.polylines = lines
                        roadLine = routeLayer?.addMapPolylineShape(options)
                        roadLine?.show()
                    }
                    routeLayer?.visible = true
                } else {
                    routeLayer?.clearAllShapes()
                    roadLine = nil
                }
                priorRoute = input.routePath
            }
            let height = container.bounds.height
            let bottom = min(input.bottomOverlayHeight, height * 0.55)
            let vehicleY = input.topOverlayHeight + 0.7 * max(0, height - bottom - input.topOverlayHeight)
            let insets = input.navigate
                ? UIEdgeInsets(top: max(0, 2 * vehicleY - height + bottom), left: 0, bottom: bottom, right: 0)
                : UIEdgeInsets(top: max(60, input.topOverlayHeight), left: 44, bottom: min(input.bottomOverlayHeight + 44, height * 0.7), right: 44)
            if map.margins != insets { map.setMargins(insets) }
            updateNavigation()
            if input.navigate {
                input.model.needsInitialMapCenter = false
                input.model.routeFitRequest = nil
                input.model.kakaoFittedPath = input.routePath
                updateResponseZone()
                return
            }
            let ambulance = visible.first { $0.kind == .ambulance }
            // 센터·사고 현장·도로 경로는 병원 후보가 아니다. 병원이 없으면 구급차를 중심으로 따라간다.
            let ambulanceOnly = !visible.contains { [.hospital, .recommended, .selected].contains($0.kind) }
            if !ambulanceOnly { soloAmbulanceFocus = nil }
            if input.responseZone == nil, input.model.responseMapFocusKey != nil { input.model.responseMapFocusKey = nil }
            if input.model.needsInitialMapCenter, let ambulance {
                // 최초 GPS 수신까지 기다렸다가 한 번만 구급차를 중앙에 놓는다.
                map.moveCamera(CameraUpdate.make(target: ambulance.pos.mapPoint, zoomLevel: 15, mapView: map))
                input.model.needsInitialMapCenter = false
                lastCenter = input.centerRequest
                firstCamera = false
                input.model.routeFitRequest = nil
                input.model.kakaoFittedPath = input.routePath
                if let zone = input.responseZone {
                    input.model.responseMapFocusKey = "\(input.model.caseId ?? "")-\(zone.radiusKm)"
                }
                if let key = input.sceneFocusKey, let hospital = visible.first(where: { $0.kind == .selected }) {
                    input.model.sceneMapFocusKey = "\(key)-\(hospital.pos)-\(container.bounds.size)-\(input.bottomOverlayHeight)"
                }
            } else if input.centerRequest != lastCenter, let ambulance {
                map.moveCamera(CameraUpdate.make(target: ambulance.pos.mapPoint, mapView: map))
                lastCenter = input.centerRequest
            } else if ambulanceOnly, let ambulance {
                let key = "\(input.model.phase)-\(ambulance.pos)-\(container.bounds.size)-\(input.bottomOverlayHeight)"
                if soloAmbulanceFocus != key || firstCamera {
                    map.moveCamera(CameraUpdate.make(target: ambulance.pos.mapPoint, mapView: map))
                    soloAmbulanceFocus = key
                }
                firstCamera = false
                input.model.routeFitRequest = nil
                input.model.kakaoFittedPath = input.routePath
            } else if [.dispatching, .transporting, .returning].contains(input.model.phase),
                      input.model.routeFitRequest != nil || (routeChanged && input.routePath != input.model.kakaoFittedPath) {
                let points = routePoints + visible.filter { [.ambulance, .incident, .base, .selected].contains($0.kind) }.map { $0.pos.mapPoint }
                if !points.isEmpty {
                    fit(points); input.model.routeFitRequest = nil
                    input.model.kakaoFittedPath = input.routePath; firstCamera = false
                }
            } else if input.model.deliveryShow != nil, let ambulance {
                let key = "delivery-\(input.model.caseId ?? "")"
                if input.model.responseMapFocusKey != key {
                    let targets = Array((input.model.result?.hospitals ?? []).compactMap { input.model.hospitalGps[$0.hospitalId] }.prefix(8))
                    let mirrored = targets.filter(\.validMapPoint).map {
                        MapPoint(longitude: 2 * ambulance.pos.lng - $0.lng, latitude: 2 * ambulance.pos.lat - $0.lat)
                    }
                    fit([ambulance.pos.mapPoint] + targets.filter(\.validMapPoint).map(\.mapPoint) + mirrored)
                    input.model.responseMapFocusKey = key
                }
            } else if let zone = input.responseZone, let ambulance,
                      input.model.responseMapFocusKey != "\(input.model.caseId ?? "")-\(zone.radiusKm)" {
                // 응답 단계 진입·존 확장 때만 맞춘다. 이후 사용자의 확대·이동은 유지한다.
                fit(Self.circlePoints(center: ambulance.pos, radiusKm: zone.radiusKm) + visible.map { $0.pos.mapPoint })
                input.model.responseMapFocusKey = "\(input.model.caseId ?? "")-\(zone.radiusKm)"; firstCamera = false
            } else if let key = input.sceneFocusKey, let ambulance, let hospital = visible.first(where: { $0.kind == .selected }) {
                let signature = "\(key)-\(hospital.pos)-\(container.bounds.size)-\(input.bottomOverlayHeight)"
                if signature != input.model.sceneMapFocusKey {
                    fit([ambulance.pos.mapPoint, hospital.pos.mapPoint])
                    input.model.sceneMapFocusKey = signature; firstCamera = false
                } else if firstCamera {
                    if let saved = input.model.kakaoCamera { map.moveCamera(CameraUpdate.make(cameraPosition: saved)) }
                    else { fit([ambulance.pos.mapPoint, hospital.pos.mapPoint]) }
                    firstCamera = false
                }
            } else if firstCamera {
                if let saved = input.model.kakaoCamera { map.moveCamera(CameraUpdate.make(cameraPosition: saved)) }
                else { fit(visible.map { $0.pos.mapPoint }) }
                firstCamera = false
            }
            updateReturnMovement()
            updateResponseZone()
        }
        private func updateNavigation() {
            guard let map else { return }
            let enabled = input.navigate && input.active && foreground
            let gestures: [GestureType] = [.doubleTapZoomIn, .twoFingerTapZoomOut, .pan, .rotate, .zoom, .tilt, .longTapAndDrag, .rotateZoom, .oneFingerZoom]
            for gesture in gestures { map.setGestureEnable(type: gesture, enable: !enabled) }
            guard enabled else {
                navigationGeneration = UUID(); navigationTask?.cancel(); navigationTask = nil
                if wasNavigating {
                    wasNavigating = false
                    let camera = CameraUpdate.make(rotation: 0, tilt: 0, mapView: map)
                    if input.reduceMotion { map.moveCamera(camera) }
                    else { map.animateCamera(cameraUpdate: camera, options: CameraAnimationOptions(autoElevation: false, consecutive: false, durationInMillis: 650)) }
                    firstCamera = true
                    input.model.routeFitRequest = input.navSession
                    input.model.kakaoFittedPath = []
                }
                return
            }
            if navigationSession != input.navSession {
                navigationGeneration = UUID(); navigationTask?.cancel(); navigationTask = nil
                navigationSession = input.navSession
                navigationCamera = NavigationCamera(); navReady = false
            }
            wasNavigating = true
            guard navigationTask == nil else { return }
            let began = Date.timeIntervalSinceReferenceDate
            let generation = navigationGeneration
            navigationTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    guard let self, !self.stopped, self.foreground, self.input.active, self.input.navigate,
                          let map = self.map else { break }
                    if let pin = self.input.pins.first(where: { $0.kind == .ambulance }) {
                        let sim = self.input.model.mySim
                        let rest = RoadRoute.remaining(self.input.routePath, latitude: pin.pos.lat, longitude: pin.pos.lng)
                        var hint: Double?
                        if let eta = sim?.etaSec, let up = sim?.speedup, eta > 0, up > 0 { hint = RoadRoute.lengthM(rest) / (eta / up) }
                        let now = Date.timeIntervalSinceReferenceDate
                        if let frame = self.navigationCamera.frame(position: [pin.pos.lat, pin.pos.lng], route: self.input.routePath,
                                                                   speedHint: hint, time: now, moving: !self.input.model.paused && !self.input.model.transportHeld) {
                            let point = MapPoint(longitude: frame.longitude, latitude: frame.latitude)
                            let camera = CameraPosition(target: point, height: frame.height, rotation: frame.rotation * .pi / 180, tilt: 0)
                            map.moveCamera(CameraUpdate.make(cameraPosition: camera))
                            self.pois[pin.id]?.moveAt(point, duration: 0)
                            if !self.navReady && now - began >= 0.9 {
                                self.navReady = true; self.input.onNavigationReady()
                            }
                        }
                    }
                    do { try await Task.sleep(for: .milliseconds(33)) } catch { break }
                }
                if self?.navigationGeneration == generation { self?.navigationTask = nil }
            }
        }
        private var animateReturn: Bool {
            !input.navigate && input.active && input.model.phase == .returning && !input.reduceMotion && !input.model.paused && foreground
        }
        private func updateReturnMovement() {
            guard foreground, let pin = input.pins.first(where: { $0.kind == .ambulance && $0.pos.validMapPoint }),
                  let poi = pois[pin.id] else { return }
            guard animateReturn else {
                if animatedReturnPath != nil { poi.moveAt(pin.pos.mapPoint, duration: 200) }
                animatedReturnPath = nil
                return
            }
            guard animatedReturnPath != input.routePath else { return }
            let remaining = RoadRoute.remaining(input.routePath, latitude: pin.pos.lat, longitude: pin.pos.lng)
            guard remaining.count > 1 else { return }
            let sim = input.model.mySim
            let seconds: Double
            if let eta = sim?.etaSec, let speedup = sim?.speedup, eta.isFinite, speedup.isFinite, speedup > 0 {
                seconds = eta / speedup
            } else { seconds = 30 }
            // 서버의 도로 경로·ETA·배속으로 한 번 재생한다. 초당 위치 수신마다 애니메이션을 끊지 않는다.
            poi.moveOnPath(remaining.map { MapPoint(longitude: $0[1], latitude: $0[0]) },
                           duration: UInt(max(1, min(3600, seconds)) * 1000), cornerRadius: 0, jumpThreshold: 10000)
            animatedReturnPath = input.routePath
        }
        private var routePoints: [MapPoint] {
            input.routePath.compactMap { p -> MapPoint? in
                guard p.count == 2 else { return nil }
                guard p[0].isFinite, p[1].isFinite, (-90...90).contains(p[0]), (-180...180).contains(p[1]) else { return nil }
                return MapPoint(longitude: p[1], latitude: p[0])
            }
        }
        private func fit(_ points: [MapPoint]) {
            guard let map, !points.isEmpty else { return }
            if points.count == 1 { map.moveCamera(CameraUpdate.make(target: points[0], zoomLevel: 15, mapView: map)) }
            else {
                let update = CameraUpdate.make(area: AreaRect(points: points), levelLimit: 17)
                update.cameraPosition?.rotation = 0
                update.cameraPosition?.tilt = 0
                if !input.reduceMotion {
                    map.animateCamera(cameraUpdate: update, options: CameraAnimationOptions(autoElevation: false, consecutive: false, durationInMillis: input.model.deliveryShow != nil ? 550 : 1000))
                } else { map.moveCamera(update) }
            }
        }
        private func updateResponseZone() {
            guard foreground, let layer = zoneLayer else { return }
            guard let zone = input.responseZone,
                  let ambulance = input.pins.first(where: { $0.kind == .ambulance && $0.pos.validMapPoint }) else {
                guard zoneSignature != nil || pulseTask != nil else { return }
                pulseTask?.cancel(); pulseTask = nil; pulseShape = nil; zoneSignature = nil
                layer.clearAllShapes(); return
            }
            let key = "\(input.model.caseId ?? "")-\(ambulance.pos)-\(zone.activeBands)-\(input.reduceMotion)-\(input.model.paused)"
            guard zoneSignature != key else { return }
            pulseTask?.cancel(); pulseTask = nil; pulseShape = nil; layer.clearAllShapes()
            zoneSignature = key
            let boundary = MapPolygonShapeOptions(shapeID: "zone-boundary", styleID: "zone", zOrder: 0)
            boundary.polygons = [MapPolygon(exteriorRing: Self.circlePoints(center: ambulance.pos, radiusKm: zone.radiusKm), holes: nil, styleIndex: 0)]
            layer.addMapPolygonShape(boundary)?.show()
            // 관제 지도와 같은 옅은 보라 영역 + 점선 외곽. 확장 전 범위도 함께 남긴다.
            let firstRadius = Double(zone.activeBands.first ?? 1) * 5
            let expanded = firstRadius < zone.radiusKm
            let outline = MapPolylineShapeOptions(shapeID: "zone-outline", styleID: "zone-outline", zOrder: 2)
            outline.polylines = Self.dashedCircle(center: ambulance.pos, radiusKm: zone.radiusKm, styleIndex: expanded ? 1 : 0)
            if expanded { outline.polylines += Self.dashedCircle(center: ambulance.pos, radiusKm: firstRadius, styleIndex: 0) }
            layer.addMapPolylineShape(outline)?.show()
            guard !input.reduceMotion, !input.model.paused else { return }
            let pulse = MapPolygonShapeOptions(shapeID: "zone-pulse", styleID: "zone", zOrder: 1)
            pulse.polygons = pulsePolygons(center: ambulance.pos, radiusKm: zone.radiusKm, frame: 0)
            pulseShape = layer.addMapPolygonShape(pulse); pulseShape?.show()
            // 지도 좌표로 그려 확대·기울임·이동에도 실제 존 범위를 따른다. UI 상태를 프레임마다 갱신하지 않는다.
            pulseTask = Task { @MainActor [weak self] in
                var frame = 0
                while !Task.isCancelled {
                    guard let self, !self.stopped, self.foreground, self.zoneSignature == key else { return }
                    self.pulseShape?.changeStyleAndData(styleID: "zone", polygons: self.pulsePolygons(center: ambulance.pos, radiusKm: zone.radiusKm, frame: frame))
                    frame = (frame + 1) % 90
                    do { try await Task.sleep(for: .milliseconds(40)) } catch { return }
                }
            }
        }
        private func pulsePolygons(center: GPS, radiusKm: Double, frame: Int) -> [MapPolygon] {
            (0..<3).map { wave in
                let progress = Double((frame + wave * 30) % 90) / 90
                let radius = radiusKm * (0.025 + 0.975 * progress)
                let opacity = UInt(max(1, min(16, Int(pow(1 - progress, 1.4) * 16))))
                return MapPolygon(exteriorRing: Self.circlePoints(center: center, radiusKm: radius), holes: nil, styleIndex: opacity)
            }
        }
        /// 구면 거리로 만든 원: 존 표시와 펄스 모두 같은 지리 좌표를 사용한다.
        private static func circlePoints(center: GPS, radiusKm: Double) -> [MapPoint] {
            let lat = center.lat * .pi / 180, lng = center.lng * .pi / 180
            let angle = radiusKm / 6371
            return (0...180).map { index in
                let bearing = Double(index) * 2 * .pi / 180
                let targetLat = asin(sin(lat) * cos(angle) + cos(lat) * sin(angle) * cos(bearing))
                let targetLng = lng + atan2(sin(bearing) * sin(angle) * cos(lat), cos(angle) - sin(lat) * sin(targetLat))
                return MapPoint(longitude: targetLng * 180 / .pi, latitude: targetLat * 180 / .pi)
            }
        }

        private static func dashedCircle(center: GPS, radiusKm: Double, styleIndex: UInt) -> [MapPolyline] {
            let points = circlePoints(center: center, radiusKm: radiusKm)
            return stride(from: 0, to: 180, by: 3).map { index in
                MapPolyline(line: Array(points[index...index + 2]), styleIndex: styleIndex)
            }
        }
        /// 병원·구급차 모두 사각 박스+십자가. 구급차는 기존 주황색으로 구분한다.
        private static func marker(kind: MapPin.Kind, color: UIColor, size: CGFloat, heading: Double = 0, beacon: Bool = true) -> UIImage {
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
                case .hospital, .recommended, .selected:
                    box(CGRect(x: 0, y: 0, width: 28, height: 28), color: .white, radius: 6)
                    box(CGRect(x: 2, y: 2, width: 24, height: 24), color: color, radius: 4)
                    cross(x: 6, y: 6, length: 16, thickness: 5)
                case .ambulance:
                    context.cgContext.translateBy(x: 14, y: 14)
                    context.cgContext.rotate(by: heading * .pi / 180)
                    context.cgContext.translateBy(x: -14, y: -14)
                    box(CGRect(x: 6, y: 1, width: 16, height: 26), color: .white, radius: 4)
                    box(CGRect(x: 8, y: 4, width: 12, height: 6), color: UIColor(AD.navy), radius: 2)
                    box(CGRect(x: 6, y: 16, width: 2, height: 8), color: .systemRed)
                    box(CGRect(x: 20, y: 16, width: 2, height: 8), color: .systemRed)
                    box(CGRect(x: 8, y: 12, width: 6, height: 3), color: beacon ? .systemRed : .systemRed.withAlphaComponent(0.35), radius: 1)
                    box(CGRect(x: 14, y: 12, width: 6, height: 3), color: beacon ? .systemBlue.withAlphaComponent(0.35) : .systemBlue, radius: 1)
                    box(CGRect(x: 10, y: 20, width: 8, height: 2), color: .systemRed)
                    box(CGRect(x: 13, y: 17, width: 2, height: 8), color: .systemRed)
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
