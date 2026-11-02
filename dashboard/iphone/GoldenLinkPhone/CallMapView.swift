import GoldenLinkCore
import KakaoMapsSDK
import SwiftUI
import UIKit

// 실제 지도 표시는 카카오맵 iOS SDK. 좌표·병원 선택·도로 경로는 기존 hub 데이터를 그대로 쓴다.
struct MapPin: Identifiable, Equatable {
    enum Kind: String, CaseIterable { case hospital, recommended, selected, ambulance, incident, base }
    let id: String
    let name: String
    let pos: GPS
    let kind: Kind
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

struct CallMapView: View {
    let pins: [MapPin]
    let routePath: [[Double]]
    let showCandidates: Bool
    let delivery: DeliveryInput?
    let topOverlayHeight: CGFloat
    let sceneFocusKey: String?
    let bottomOverlayHeight: CGFloat
    let responseZone: ResponseZone?
    let onPin: (String) -> Void
    @Environment(PhoneModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var centerRequest = 0
    @State private var mapMessage: String? = "카카오맵을 불러오는 중…"

    var body: some View {
        KakaoCallMap(model: model, pins: pins, routePath: routePath, showCandidates: showCandidates,
                     delivery: delivery, topOverlayHeight: topOverlayHeight, sceneFocusKey: sceneFocusKey, bottomOverlayHeight: bottomOverlayHeight,
                     responseZone: responseZone, centerRequest: centerRequest, reduceMotion: reduceMotion,
                     onPin: onPin, onMessage: { mapMessage = $0 })
            .id(Settings.kakaoNativeAppKey)
            .overlay {
                if let mapMessage {
                    Text(mapMessage).font(.system(size: 13)).multilineTextAlignment(.center)
                        .padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(AD.bg.opacity(0.95)).accessibilityLabel(mapMessage)
                }
            }
            .overlay(alignment: .topTrailing) {
                Button { centerRequest += 1 } label: {
                    Label("내 위치", systemImage: "location.fill")
                        .font(.system(size: 13, weight: .semibold)).padding(12)
                        .background(.white, in: Capsule()).shadow(radius: 3)
                }.padding(.trailing, 12).padding(.top, max(12, topOverlayHeight + 8)).disabled(!pins.contains { $0.kind == .ambulance })
            }
    }
}

private struct KakaoCallMap: UIViewRepresentable {
    let model: PhoneModel
    let pins: [MapPin]
    let routePath: [[Double]]
    let showCandidates: Bool
    let delivery: DeliveryInput?
    let topOverlayHeight: CGFloat
    let sceneFocusKey: String?
    let bottomOverlayHeight: CGFloat
    let responseZone: ResponseZone?
    let centerRequest: Int
    let reduceMotion: Bool
    let onPin: (String) -> Void
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
        var input: KakaoCallMap
        private var controller: KMController?
        private weak var container: KMViewContainer?
        private var map: KakaoMap?
        private var pinLayer: LabelLayer?
        private var ambulanceLayer: LabelLayer?
        private var zoneLayer: ShapeLayer?
        private var pulseShape: MapPolygonShape?
        private var routeLayer: RouteLayer?
        private var pois: [String: Poi] = [:]
        private var priorPins: [String: MapPin] = [:]
        private var priorStyles: [String: String] = [:]
        private var priorRoute: [[Double]] = []
        private var animatedReturnPath: [[Double]]?
        private var firstCamera = true
        private var lastCenter = 0
        private var pulseTask: Task<Void, Never>?
        private var zoneSignature: String?
        // 구급차 진행 방향(15도 단위)과 경광등 깜빡임 — 그림에 방향을 구워 넣은 스타일을 바꿔 끼운다(안드로이드와 같은 방식)
        private var lastAmbulancePos: GPS?
        private var headingIndex = 0
        private var beaconPhase = 0
        private var beaconTask: Task<Void, Never>?
        private var lastLogoTop: CGFloat = -1
        // 요약 전달 연출 — 지도 안 도형(곡선)과 도착한 병원의 이름표
        private var deliveryLayer: ShapeLayer?
        private var deliveryTask: Task<Void, Never>?
        private var deliveryKey: String?
        private var deliveryPoiIDs: [String] = []
        private var foreground = true
        private var observers: [NSObjectProtocol] = []
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
            stopped = true; pulseTask?.cancel(); pulseTask = nil
            beaconTask?.cancel(); beaconTask = nil
            deliveryTask?.cancel(); deliveryTask = nil
            observers.forEach(NotificationCenter.default.removeObserver); observers = []
            if let map { input.model.kakaoCamera = CameraUpdate.make(mapView: map).cameraPosition }
            map?.eventDelegate = nil
            controller?.pauseEngine(); controller?.resetEngine(); controller?.delegate = nil
            pois = [:]; priorPins = [:]; priorStyles = [:]; pinLayer = nil; ambulanceLayer = nil; pulseShape = nil; zoneLayer = nil; deliveryLayer = nil; map = nil; controller = nil
        }
        private func setAppActive(_ active: Bool) {
            guard !stopped else { return }
            foreground = active
            if active { controller?.activateEngine(); scheduleRender() }
            else { pulseTask?.cancel(); pulseTask = nil; zoneSignature = nil; animatedReturnPath = nil; stopDelivery(); controller?.pauseEngine() }
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
                case .recommended: color = UIColor(AD.green)
                case .selected: color = UIColor(AD.blue)
                case .incident: color = UIColor(AD.red)
                default: color = UIColor(red: 0x1F / 255, green: 0x4E / 255, blue: 0x9C / 255, alpha: 1)
                }
                // 지도 아이콘은 안드로이드와 같은 그림을 26pt로 고정한다(줌에 따라 크기가 변하지 않는다) — 기기를 나란히 놓아도 같게 보이도록
                let icon = PoiIconStyle(symbol: Self.marker(kind: kind, color: color, size: Self.mapIconSize))
                let text = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(fontSize: 11, fontColor: UIColor(AD.navy), strokeThickness: 2, strokeColor: .white))])
                text.textLayouts = [.bottom]
                manager.addPoiStyle(PoiStyle(styleID: kind.rawValue, styles: [PerLevelPoiStyle(iconStyle: icon, textStyle: text, level: 0)]))
            }
            // 구급차: 진행 방향 24칸(15도) × 경광등 2칸 — 방향을 그림에 구워 넣는다
            for beacon in 0..<2 {
                for index in 0..<24 {
                    let image = Self.marker(kind: .ambulance, color: UIColor(AD.orange), size: Self.mapIconSize, heading: Double(index) * 15, beaconOn: beacon == 0)
                    let text = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(fontSize: 11, fontColor: UIColor(AD.navy), strokeThickness: 2, strokeColor: .white))])
                    text.textLayouts = [.bottom]
                    manager.addPoiStyle(PoiStyle(styleID: "ambulance-" + String(beacon) + "-" + String(index),
                                                 styles: [PerLevelPoiStyle(iconStyle: PoiIconStyle(symbol: image), textStyle: text, level: 0)]))
                }
            }
            // 전달 연출에서 도착한 병원 — 초록 점 + ✓ 이름표
            let doneText = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(fontSize: 12, fontColor: UIColor(AD.navy), strokeThickness: 2, strokeColor: .white))])
            doneText.textLayouts = [.bottom]
            manager.addPoiStyle(PoiStyle(styleID: "delivered", styles: [PerLevelPoiStyle(iconStyle: PoiIconStyle(symbol: Self.deliveredMarker()), textStyle: doneText, level: 0)]))
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
            // 전달 연출 곡선 — 옅은 파랑(0·1)과 앞서가는 빛(2 흰색 바탕, 3 파랑)
            deliveryLayer = shapes.addShapeLayer(layerID: "delivery", zOrder: 3)
            let blue = UIColor(AD.blue)
            shapes.addPolylineStyleSet(PolylineStyleSet(styleSetID: "delivery-line", styles: [
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: blue.withAlphaComponent(0.45), bodyWidth: 3, level: 0)]),
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: blue.withAlphaComponent(0.25), bodyWidth: 3, level: 0)]),
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: UIColor.white.withAlphaComponent(0.9), bodyWidth: 6, level: 0)]),
                PolylineStyle(styles: [PerLevelPolylineStyle(bodyColor: blue.withAlphaComponent(0.85), bodyWidth: 4, level: 0)])
            ], capType: .round))
            startBeacon()
            let routes = view.getRouteManager()
            routes.addRouteStyleSet(RouteStyleSet(styleID: "road", styles: [RouteStyle(styles: [PerLevelRouteStyle(width: 5, color: UIColor(AD.blue), strokeWidth: 1, strokeColor: .white, level: 0)])]))
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
            }
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
            let visible = input.pins.filter { $0.pos.validMapPoint && (input.showCandidates || [.ambulance, .incident, .base, .selected].contains($0.kind)) }
            if input.sceneFocusKey == nil, input.model.sceneMapFocusKey != nil { input.model.sceneMapFocusKey = nil }
            if let ambulancePin = visible.first(where: { $0.kind == .ambulance }) { updateHeading(ambulancePin.pos) }
            let ids = Set(visible.map(\.id))
            for id in Array(pois.keys) where !ids.contains(id) {
                let layer = pois[id]?.layerID == "ambulance-foreground" ? ambulanceLayer : pinLayer
                layer.removePoi(poiID: id); pois[id] = nil; priorPins[id] = nil; priorStyles[id] = nil
            }
            for pin in visible {
                let layer = pin.kind == .ambulance ? ambulanceLayer : pinLayer
                let style = pin.kind == .ambulance ? ambulanceStyle : pin.kind.rawValue
                if let poi = pois[pin.id] {
                    if priorPins[pin.id]?.pos != pin.pos {
                        if pin.kind != .ambulance || !animateReturn || input.routePath.count < 2 {
                            poi.moveAt(pin.pos.mapPoint, duration: pin.kind == .ambulance && animatedReturnPath != nil ? 200 : 0)
                        }
                    }
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
            let routeChanged = input.routePath != priorRoute
            if routeChanged {
                routeLayer?.clearAllRoutes()
                let points = routePoints
                if points.count > 1 {
                    let options = RouteOptions(routeID: "road", styleID: "road", zOrder: 0)
                    options.segments = [RouteSegment(points: points, styleIndex: 0)]
                    routeLayer?.addRoute(option: options)?.show()
                }
                priorRoute = input.routePath
            }
            // 위쪽은 지도를 덮는 헤더 아래부터 — 지도는 헤더 뒤까지 이어지므로 카메라 맞춤이 그 아래 영역을 쓴다. 공급자 로고도 헤더 아래로
            let topInset = max(60, input.topOverlayHeight + 12)
            if lastLogoTop != input.topOverlayHeight {
                map.setLogoPosition(origin: GuiAlignment(vAlign: .top, hAlign: .left), position: CGPoint(x: 12, y: input.topOverlayHeight + 8))
                lastLogoTop = input.topOverlayHeight
            }
            let insets = UIEdgeInsets(top: topInset, left: 44, bottom: min(input.bottomOverlayHeight + 44, container.bounds.height * 0.7), right: 44)
            if map.margins != insets { map.setMargins(insets) }
            let ambulance = visible.first { $0.kind == .ambulance }
            if input.responseZone == nil, input.model.responseMapFocusKey != nil { input.model.responseMapFocusKey = nil }
            if input.centerRequest != lastCenter, let ambulance {
                map.moveCamera(CameraUpdate.make(target: ambulance.pos.mapPoint, mapView: map))
                lastCenter = input.centerRequest
            } else if [.dispatching, .transporting, .returning].contains(input.model.phase),
                      input.model.routeFitRequest != nil || (routeChanged && input.routePath != input.model.kakaoFittedPath) {
                let points = routePoints + visible.filter { [.ambulance, .incident, .base, .selected].contains($0.kind) }.map { $0.pos.mapPoint }
                if !points.isEmpty {
                    fit(points); input.model.routeFitRequest = nil
                    input.model.kakaoFittedPath = input.routePath; firstCamera = false
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
            updateDelivery()
        }

        // MARK: 구급차 방향·경광등

        private var ambulanceStyle: String { "ambulance-" + String(beaconPhase) + "-" + String(headingIndex) }

        /// 구급차 진행 방향 — 직전 위치에서 움직인 쪽(북쪽 0, 시계방향)을 15도 단위로 맞춘다. 멈춰 있으면 직전 방향을 유지한다
        private func updateHeading(_ now: GPS) {
            if let before = lastAmbulancePos, before != now {
                let dLat = now.lat - before.lat
                let dLng = (now.lng - before.lng) * cos(now.lat * .pi / 180)
                if hypot(dLat, dLng) > 1e-6 {
                    let degrees = (atan2(dLng, dLat) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
                    headingIndex = Int((degrees / 15).rounded()) % 24
                }
            }
            lastAmbulancePos = now
        }

        /// 경광등 깜빡임 — 0.45초마다 한 칸(안드로이드와 같다). 지도 전체를 다시 그리지 않고 구급차 스타일만 바꾼다
        private func startBeacon() {
            beaconTask?.cancel()
            beaconTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(450)) } catch { return }
                    guard let self, !self.stopped, self.foreground, !self.input.reduceMotion else { continue }
                    self.beaconPhase = 1 - self.beaconPhase
                    self.refreshAmbulanceStyle()
                }
            }
        }

        private func refreshAmbulanceStyle() {
            guard let pin = priorPins.values.first(where: { $0.kind == .ambulance }), let poi = pois[pin.id] else { return }
            let style = ambulanceStyle
            guard priorStyles[pin.id] != style else { return }
            poi.changeTextAndStyle(texts: pin.name.isEmpty ? [] : [PoiText(text: pin.name, styleIndex: 0)], styleID: style)
            priorStyles[pin.id] = style
        }

        // MARK: 요약 전달 연출

        private func updateDelivery() {
            guard foreground, deliveryLayer != nil, pinLayer != nil else { return }
            guard let plan = input.delivery else {
                if deliveryKey != nil { stopDelivery() }
                return
            }
            guard deliveryKey != plan.caseId else { return }
            stopDelivery()
            deliveryKey = plan.caseId
            // 구급차를 정중앙에 두고 모든 병원이 들어오게 — 병원 반대쪽 점을 대칭으로 더해 범위가 구급차 중심이 되게
            let center = plan.from
            let mirrored = plan.targets.map { MapPoint(longitude: 2 * center.lng - $0.gps.lng, latitude: 2 * center.lat - $0.gps.lat) }
            fit([center.mapPoint] + plan.targets.map { $0.gps.mapPoint } + mirrored)
            let started = Date()
            input.model.deliveryShow?.readyAt = started
            deliveryTask = Task { @MainActor [weak self] in
                var shown = Set<Int>()
                while !Task.isCancelled {
                    guard let self, !self.stopped else { return }
                    let elapsed = Int(Date().timeIntervalSince(started) * 1000)
                    self.drawDelivery(plan, elapsed: elapsed, shown: &shown)
                    if elapsed >= plan.durationMs { self.input.model.finishDelivery(); return }
                    do { try await Task.sleep(for: .milliseconds(33)) } catch { return }
                }
            }
        }

        private func stopDelivery() {
            deliveryTask?.cancel(); deliveryTask = nil
            deliveryLayer?.clearAllShapes()
            for id in deliveryPoiIDs { pinLayer?.removePoi(poiID: id) }
            deliveryPoiIDs = []; deliveryKey = nil
        }

        private func drawDelivery(_ plan: DeliveryInput, elapsed: Int, shown: inout Set<Int>) {
            guard let layer = deliveryLayer, let pinLayer else { return }
            var lines: [MapPolyline] = []
            for (index, target) in plan.targets.enumerated() {
                let flight = DeliveryTimeline.flight(index, t: elapsed, reduce: plan.reduceMotion)
                let pop = DeliveryTimeline.pop(index, t: elapsed, reduce: plan.reduceMotion)
                let sign: Double = index % 2 == 0 ? 1 : -1
                let eased = 1 - pow(1 - flight, 3)
                // 선 — 구급차에서 병원으로 그려진다. 그려지는 동안 끝에 빛이 지나가고, 다 그려진 뒤엔 은은하게 남는다(도착 뒤 더 옅게)
                if eased > 0 { lines.append(MapPolyline(line: Self.curve(plan.from, target.gps, sign, 0, eased), styleIndex: pop >= 0.5 ? 1 : 0)) }
                if flight > 0 && flight < 1 {
                    let head = Self.curve(plan.from, target.gps, sign, max(0, eased - 0.22), eased)
                    lines.append(MapPolyline(line: head, styleIndex: 2))
                    lines.append(MapPolyline(line: head, styleIndex: 3))
                }
                // 병원 — 도착하면 초록 점과 ✓ 이름표가 뜬다
                if pop >= 0, !shown.contains(index) {
                    let options = PoiOptions(styleID: "delivered", poiID: "delivered-" + String(index))
                    options.rank = 40
                    options.addText(PoiText(text: "✓ " + target.name, styleIndex: 0))
                    pinLayer.addPoi(option: options, at: target.gps.mapPoint)?.show()
                    deliveryPoiIDs.append("delivered-" + String(index))
                    shown.insert(index)
                }
            }
            layer.clearAllShapes()
            guard !lines.isEmpty else { return }
            let shape = MapPolylineShapeOptions(shapeID: "delivery", styleID: "delivery-line", zOrder: 1)
            shape.polylines = lines
            layer.addMapPolylineShape(shape)?.show()
        }

        /// 구급차→병원 곡선 위의 점들(from~to: 0..1) — 병원마다 휘는 방향을 번갈아 줘서 선이 겹치지 않게 한다
        private static func curve(_ a: GPS, _ b: GPS, _ sign: Double, _ from: Double, _ to: Double) -> [MapPoint] {
            let cosLat = max(0.2, cos(a.lat * .pi / 180))
            let ax = a.lng * cosLat, ay = a.lat, bx = b.lng * cosLat, bY = b.lat
            let length = max(1e-9, hypot(bx - ax, bY - ay))
            let nx = -(bY - ay) / length, ny = (bx - ax) / length
            let cx = (ax + bx) / 2 + nx * length * 0.18 * sign, cy = (ay + bY) / 2 + ny * length * 0.18 * sign
            let steps = 28
            return (0...steps).map { k in
                let t = from + (to - from) * Double(k) / Double(steps)
                let u = 1 - t
                let x = u * u * ax + 2 * u * t * cx + t * t * bx
                let y = u * u * ay + 2 * u * t * cy + t * t * bY
                return MapPoint(longitude: x / cosLat, latitude: y)
            }
        }

        /// 도착한 병원 점 — 초록 원 + 흰 테두리(안드로이드 전달 연출과 같다)
        private static func deliveredMarker() -> UIImage {
            UIGraphicsImageRenderer(size: CGSize(width: 18, height: 18)).image { _ in
                let rect = CGRect(x: 1.5, y: 1.5, width: 15, height: 15)
                UIColor(AD.green).setFill(); UIBezierPath(ovalIn: rect).fill()
                UIColor.white.setStroke()
                let ring = UIBezierPath(ovalIn: rect); ring.lineWidth = 1.5; ring.stroke()
            }
        }
        private var animateReturn: Bool {
            input.model.phase == .returning && !input.reduceMotion && !input.model.paused && foreground
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
            else { map.moveCamera(CameraUpdate.make(area: AreaRect(points: points), levelLimit: 17)) }
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
        /// 지도 아이콘 크기(pt) — 안드로이드 CallMap.kt의 MAP_ICON_DP와 같은 값. 그림의 긴 변이 이 크기다.
        private static let mapIconSize: CGFloat = 26

        /// 안드로이드 MapIcons.kt와 같은 그림(위에서 본 구급차·파란 병원·현장 경고판·센터 집). 그림의 긴 변이 `size`pt다.
        /// 구급차는 진행 방향(`heading`, 북쪽 0·시계방향)으로 돌려 그리고, 지붕 경광등은 `beaconOn`에 따라 빨강↔파랑이 번갈아 밝다 —
        /// 돌려도 잘리지 않게 구급차만 더 큰 정사각형에 그린다(안드로이드 72dp 상자와 같은 이유).
        private static func marker(kind: MapPin.Kind, color: UIColor, size: CGFloat, heading: Double = 0, beaconOn: Bool = true) -> UIImage {
            let side = kind == .ambulance ? size * 1.5 : size
            return UIGraphicsImageRenderer(size: CGSize(width: side, height: side)).image { renderer in
                let c = renderer.cgContext
                func rgb(_ hex: UInt32, _ alpha: CGFloat = 1) -> UIColor {
                    UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
                }
                func round(_ rect: CGRect, _ radius: CGFloat, fill: UIColor? = nil, stroke: UIColor? = nil, width: CGFloat = 1) {
                    let path = UIBezierPath(roundedRect: rect, cornerRadius: radius)
                    if let fill { fill.setFill(); path.fill() }
                    if let stroke { stroke.setStroke(); path.lineWidth = width; path.stroke() }
                }
                func polygon(_ points: [CGPoint], fill: UIColor, stroke: UIColor? = nil, width: CGFloat = 1) {
                    let path = UIBezierPath()
                    path.move(to: points[0]); points.dropFirst().forEach { path.addLine(to: $0) }; path.close()
                    path.lineJoinStyle = .round
                    fill.setFill(); path.fill()
                    if let stroke { stroke.setStroke(); path.lineWidth = width; path.stroke() }
                }
                // 그림의 긴 변(extent)이 size가 되게, 그림 중심(center)을 정사각형 한가운데로
                func fit(center: CGPoint, extent: CGFloat) {
                    c.translateBy(x: side / 2, y: side / 2)
                    if kind == .ambulance { c.rotate(by: CGFloat(heading) * .pi / 180) }
                    c.scaleBy(x: size / extent, y: size / extent)
                    c.translateBy(x: -center.x, y: -center.y)
                }
                let white = UIColor.white
                let red = rgb(0xD93025)
                switch kind {
                case .ambulance:
                    fit(center: CGPoint(x: 20, y: 32), extent: 54)   // 차량 영역 40x64 안에서 차체 9..31 x 5..59(사이드미러 포함 6.5..33.5)
                    round(CGRect(x: 9, y: 5, width: 22, height: 54), 7, fill: rgb(0xF8FAFD), stroke: rgb(0xB4BDCA), width: 1)
                    round(CGRect(x: 9.6, y: 33, width: 1.4, height: 22), 0, fill: red)
                    round(CGRect(x: 29, y: 33, width: 1.4, height: 22), 0, fill: red)
                    polygon([CGPoint(x: 12, y: 21), CGPoint(x: 13.5, y: 11), CGPoint(x: 26.5, y: 11), CGPoint(x: 28, y: 21)], fill: rgb(0x27364A))
                    round(CGRect(x: 6.5, y: 17, width: 2.5, height: 5), 1, fill: rgb(0x8F9AAA))
                    round(CGRect(x: 31, y: 17, width: 2.5, height: 5), 1, fill: rgb(0x8F9AAA))
                    // 지붕 경광등 바 — 밝은 쪽에는 번지는 빛
                    let glow = beaconOn ? rgb(0xFF3B30, 0.33) : rgb(0x3B8CFF, 0.33)
                    glow.setFill()
                    UIBezierPath(ovalIn: CGRect(x: (beaconOn ? 15 : 25) - 8, y: 27.5 - 8, width: 16, height: 16)).fill()
                    round(CGRect(x: 11, y: 25, width: 9, height: 5), 1.5, fill: beaconOn ? rgb(0xFF3B30) : rgb(0x7A2623))
                    round(CGRect(x: 20, y: 25, width: 9, height: 5), 1.5, fill: beaconOn ? rgb(0x2A4C80) : rgb(0x3B8CFF))
                    round(CGRect(x: 15.5, y: 43.6, width: 9, height: 3), 0, fill: red)
                    round(CGRect(x: 18.5, y: 40.6, width: 3, height: 9), 0, fill: red)
                    round(CGRect(x: 12, y: 54, width: 16, height: 0.8), 0, fill: rgb(0xC9D0DA))
                    round(CGRect(x: 11, y: 56, width: 3, height: 2), 0, fill: red)
                    round(CGRect(x: 26, y: 56, width: 3, height: 2), 0, fill: red)
                case .incident:
                    fit(center: CGPoint(x: 30, y: 28.5), extent: 34)   // 경고판 삼각형 13..47 x 13..44
                    polygon([CGPoint(x: 30, y: 13), CGPoint(x: 47, y: 44), CGPoint(x: 13, y: 44)], fill: color, stroke: white, width: 2)
                    round(CGRect(x: 28.4, y: 24, width: 3.2, height: 11), 1.6, fill: white)
                    white.setFill(); UIBezierPath(ovalIn: CGRect(x: 28.1, y: 37.6, width: 3.8, height: 3.8)).fill()
                case .base:
                    fit(center: CGPoint(x: 15, y: 15), extent: 24)   // 집 3..27
                    polygon([CGPoint(x: 15, y: 4), CGPoint(x: 27, y: 14), CGPoint(x: 23, y: 14), CGPoint(x: 23, y: 26),
                             CGPoint(x: 7, y: 26), CGPoint(x: 7, y: 14), CGPoint(x: 3, y: 14)], fill: rgb(0x5A6676), stroke: white, width: 1.5)
                    round(CGRect(x: 12, y: 18, width: 6, height: 8), 0, fill: white)
                case .hospital, .recommended, .selected:
                    fit(center: CGPoint(x: 16, y: 16), extent: 26)   // 사각형 3..29
                    let box = CGRect(x: 3, y: 3, width: 26, height: 26)
                    round(box, 6, fill: color, stroke: white, width: 1.5)
                    round(CGRect(x: 8.5, y: 13.5, width: 15, height: 5), 0, fill: white)
                    round(CGRect(x: 13.5, y: 8.5, width: 5, height: 15), 0, fill: white)
                }
            }
        }


    }
}
