package xyz.goldenlink.phone.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Map
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.kakao.vectormap.KakaoMap
import com.kakao.vectormap.KakaoMapReadyCallback
import com.kakao.vectormap.GestureType
import com.kakao.vectormap.KakaoMapSdk
import com.kakao.vectormap.LatLng
import com.kakao.vectormap.MapLifeCycleCallback
import com.kakao.vectormap.MapView
import com.kakao.vectormap.camera.CameraAnimation
import com.kakao.vectormap.camera.CameraPosition
import com.kakao.vectormap.camera.CameraUpdateFactory
import com.kakao.vectormap.label.Label
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelStyles
import com.kakao.vectormap.shape.DotPoints
import com.kakao.vectormap.shape.PolygonOptions
import com.kakao.vectormap.shape.PolygonStyle
import com.kakao.vectormap.shape.PolygonStyles
import com.kakao.vectormap.route.RouteLineOptions
import com.kakao.vectormap.route.RouteLineSegment
import com.kakao.vectormap.route.RouteLineStyle
import com.kakao.vectormap.route.RouteLineStyles
import kotlin.math.pow
import kotlinx.coroutines.delay
import xyz.goldenlink.core.GPS
import xyz.goldenlink.core.RoutePath
import xyz.goldenlink.phone.BuildConfig

// 통화 탭의 배경 지도(카카오맵 SDK) — 내 구급차·사건 현장·후보 병원을 핀으로 찍고, 출동 중엔 현장까지 선을 긋고,
// 통화가 끝나 정보가 전달되면 구급차에서 후보 병원들로 점이 날아가는 애니메이션을 그린다.
// 후보 메시지(scene_candidates)에는 병원 좌표가 없어 hub 병원 목록(map_overview)의 좌표를 hospitalId로 찾아 쓴다.

data class MapPin(val id: String, val name: String, val pos: GPS, val kind: Kind) {
    enum class Kind { HOSPITAL, RECOMMENDED, SELECTED, AMBULANCE, INCIDENT, BASE }
}

/** 지도에 올라가 있는 라벨과 지금 그 라벨이 가진 모양·글자·위치 — 바뀐 것만 고치려고 기억해 둔다 */
private class LiveLabel(val label: Label, var key: String, val text: String, var pos: GPS)

private var sdkReady = false
// 탭을 갔다 와도 지도 중심·배율을 유지한다(지도 화면은 탭을 떠나면 사라진다)
private var lastCamera: Pair<LatLng, Int>? = null
private var lastFitKey: Any? = null
private var lastZoneKey: Any? = null

private fun ll(g: GPS) = LatLng.from(g.lat, g.lng)

@Composable
fun CallMap(
    pins: List<MapPin>, route: List<GPS>, onPin: (String) -> Unit, modifier: Modifier = Modifier,
    zoneKm: Double? = null, recenter: Int = 0,
    /** 출동·이송·복귀 중 경로 전체를 맞추는 때(사건·병원·경로가 바뀔 때만 달라지는 값). 아니면 null */
    routeKey: Any? = null,
    /** 응답 존을 맞추는 때(사건·반경). 아니면 null */
    zoneFitKey: Any? = null,
    /** 현장에서 고른 병원까지 구급차와 같이 맞추는 때. 아니면 null */
    sceneKey: Any? = null,
    /** 지도 아래를 덮은 패널 높이(px) */
    bottomOverlayPx: Int = 0,
    /** 전달 애니메이션처럼 이 점들이 모두 보이게 카메라를 한 번 맞춘다. 아니면 null */
    deliveryFit: List<GPS>? = null,
    /** 지도가 화면에 보이는가 — 다른 화면에 가려져 있으면 파동·깜빡임 같은 반복 그리기를 멈춘다(지도는 지우지 않고 그대로 둔다) */
    active: Boolean = true,
    /** 내비게이션 시점 — 구급차를 화면 아래쪽에 두고 진행 방향이 위가 되게 지도를 돌려 따라간다. 지도 조작은 잠근다 */
    navigate: Boolean = false,
    /** 내비게이션 한 번의 구간을 가르는 값(단계·사건). 값이 새로 바뀌면 로딩 후 바로 내비 시점으로, 같으면 지금 카메라에서 이어 간다 */
    navSession: Any? = null,
    /** 구급차의 처음 속도 추정(m/s) — hub ETA·배속으로 구한 값. 위치 변화로 속도를 재기 전에도 배율을 맞추려고 쓴다 */
    navSpeedHintMps: Double? = null,
    /** 내비 시점이 준비되는 동안 true — 멀리 있던 지도를 구급차 위치로 옮기는 장면을 가리려고 화면이 로딩을 띄운다 */
    onNavLoading: (Boolean) -> Unit = {},
    /** 지도 위에 얹는 그림 — 좌표를 화면 위치로 바꾸는 함수를 받는다(카메라가 움직이면 같이 따라간다) */
    overlay: (@Composable (project: (GPS) -> Offset?) -> Unit)? = null,
) {
    val key = BuildConfig.KAKAO_NATIVE_APP_KEY
    if (key.isBlank()) {
        // 키가 없으면 지도 자리에 안내만 — 병원 선택·전화는 위에 얹은 패널로 그대로 된다
        Column(modifier.background(AD.chip), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Filled.Map, null, tint = AD.gray)
            Text("지도 키가 설정되지 않았습니다", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = AD.ink3)
            Text("local.properties에 KAKAO_NATIVE_APP_KEY를 넣고 다시 빌드하세요", fontSize = 11.5.sp, color = AD.muted)
        }
        return
    }
    val context = LocalContext.current
    if (!sdkReady) { KakaoMapSdk.init(context, key); sdkReady = true }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val select by rememberUpdatedState(onPin)
    val navigating = rememberUpdatedState(navigate)
    var map by remember { mutableStateOf<KakaoMap?>(null) }
    val mapView = remember { MapView(context) }
    var mapHeightPx by remember { mutableIntStateOf(0) }

    DisposableEffect(mapView) {
        mapView.start(object : MapLifeCycleCallback() {
            override fun onMapDestroy() {}
            override fun onMapError(error: Exception?) {}
        }, object : KakaoMapReadyCallback() {
            override fun onMapReady(kakaoMap: KakaoMap) {
                kakaoMap.setOnCameraMoveEndListener { _, pos, _ -> if (!navigating.value) lastCamera = pos.position to pos.zoomLevel }
                kakaoMap.setOnLabelClickListener { _, _, label -> (label.tag as? String)?.let { select(it); true } ?: false }
                map = kakaoMap
            }
        })
        val observer = LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_RESUME) mapView.resume() else if (e == Lifecycle.Event.ON_PAUSE) mapView.pause()
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); mapView.finish() }
    }

    val dens = context.resources.displayMetrics.density
    val ambulance = pins.firstOrNull { it.kind == MapPin.Kind.AMBULANCE }
    val incident = pins.firstOrNull { it.kind == MapPin.Kind.INCIDENT }

    // 구급차 진행 방향 — 직전 위치에서 움직인 쪽(북쪽 0, 시계방향)을 15도 단위로 맞춘다. 멈춰 있으면 직전 방향을 유지한다
    var heading by remember { mutableIntStateOf(0) }
    val lastPos = remember { arrayOfNulls<GPS>(1) }
    LaunchedEffect(ambulance?.pos) {
        val now = ambulance?.pos ?: return@LaunchedEffect
        val before = lastPos[0]
        if (before != null) {
            val dLat = now.lat - before.lat
            val dLng = (now.lng - before.lng) * Math.cos(Math.toRadians(now.lat))
            if (Math.hypot(dLat, dLng) > 1e-6) {
                val deg = (Math.toDegrees(Math.atan2(dLng, dLat)) + 360.0) % 360.0
                heading = (Math.round(deg / 15.0).toInt() * 15) % 360
            }
        }
        lastPos[0] = now
    }
    // 내비게이션 시점에선 지도가 진행 방향으로 돌아 있어 마커는 늘 위를 본다(라벨은 화면 기준이라 지도를 따라 돌지 않는다)
    val markerHeading = if (navigate) 0 else heading
    // 경광등 깜빡임·사건 링 번짐 — 구급차나 사건이 보이는 동안만 0.45초마다 한 칸씩
    var frame by remember { mutableIntStateOf(0) }
    val animated = ambulance != null || incident != null
    LaunchedEffect(animated, active) { if (animated && active) while (true) { delay(450); frame = (frame + 1) % 4 } }
    // 같은 모양은 스타일을 다시 만들지 않고 재사용한다(0.45초마다 새로 만들면 지도에 스타일이 계속 쌓인다)
    val styles = remember { HashMap<String, LabelStyles>() }

    // 핀 — 종류별로 모양이 다르다. 전화 걸 병원(선택)과 내 구급차·사건 현장·센터만 찍는다(다른 병원은 지도에 그리지 않는다).
    // 라벨은 핀마다 한 번만 만들고 바뀐 것(위치·모양·글자)만 고친다 — 구급차가 1초마다 움직일 때마다 전부 지웠다 다시 만들면
    // 사건 표지판까지 같이 깜빡여서 경광등 주기와 겹쳐 불규칙해 보였다
    val live = remember(map) { HashMap<String, LiveLabel>() }
    LaunchedEffect(map, pins, frame, markerHeading) {
        val layer = map?.labelManager?.layer ?: return@LaunchedEffect
        val wanted = pins.filter { it.kind != MapPin.Kind.HOSPITAL && it.kind != MapPin.Kind.RECOMMENDED }.associateBy { it.id }
        for ((id, e) in live.toMap()) if (id !in wanted) { layer.remove(e.label); live.remove(id) }
        for (p in wanted.values) {
            val key = when (p.kind) {
                MapPin.Kind.AMBULANCE -> "amb-${frame % 2}-$markerHeading"
                MapPin.Kind.INCIDENT -> "inc-$frame"
                else -> p.kind.name
            }
            val labelStyles = styles.getOrPut("$key|${p.name}") {
                val icon = when (p.kind) {
                    MapPin.Kind.AMBULANCE -> ambulanceBitmap(dens, beaconOn = frame % 2 == 0, headingDeg = markerHeading.toFloat())
                    MapPin.Kind.INCIDENT -> incidentBitmap(dens, frame)
                    MapPin.Kind.BASE -> baseBitmap(dens)
                    else -> hospitalBitmap(dens, 0xFF1F4E9C.toInt())
                }
                // 이름은 지도 라벨 글자가 아니라 그림 안에 넣는다 — 아이콘 중심이 정확히 좌표(길 위)에 오게
                LabelStyles.from(LabelStyle.from(if (p.name.isBlank()) icon else withCaption(icon, p.name, dens)).setAnchorPoint(0.5f, 0.5f))
            }
            val cur = live[p.id]
            if (cur != null && cur.text != p.name) { layer.remove(cur.label); live.remove(p.id) }   // 글자가 바뀌면(예: 사건 현장 글자 떼기) 새로 만든다
            val have = live[p.id]
            if (have == null) {
                val opts = LabelOptions.from(ll(p.pos)).setStyles(labelStyles).setClickable(true).setTag(p.id)
                val label = layer.addLabel(opts)
                live[p.id] = LiveLabel(label, key, p.name, p.pos)
            } else {
                if (have.pos != p.pos) { if (!(navigate && p.kind == MapPin.Kind.AMBULANCE)) have.label.moveTo(ll(p.pos)); have.pos = p.pos }   // 내비 중 구급차 라벨은 아래 카메라 루프가 카메라와 같은 위치로 움직인다
                if (have.key != key) { have.label.changeStyles(labelStyles); have.key = key }
            }
        }
    }
    // 도로 경로(hub 카카오 길찾기, 지난 구간은 뺀 남은 구간) — 출동·이송·복귀 모두 같다
    LaunchedEffect(map, route) {
        val layer = map?.routeLineManager?.layer ?: return@LaunchedEffect
        layer.removeAll()
        if (route.size >= 2) {
            val style = RouteLineStyles.from(RouteLineStyle.from(10f * dens, 0xFF1F4E9C.toInt()))
            layer.addRouteLine(RouteLineOptions.from(RouteLineSegment.from(route.map(::ll), style)))
        }
    }
    // 활성 존 — 구급차 중심 보라색 영역과 바깥으로 퍼지는 펄스(관제 지도와 같은 색)
    LaunchedEffect(map, zoneKm, ambulance?.pos, active) {
        val m = map ?: return@LaunchedEffect
        if (!active) return@LaunchedEffect
        val layer = m.shapeManager?.layer ?: return@LaunchedEffect
        val center = ambulance?.pos ?: return@LaunchedEffect
        layer.removeAll()
        if (zoneKm == null) return@LaunchedEffect
        val purple = 0xFF7B4DFF.toInt()
        layer.addPolygon(PolygonOptions.from(DotPoints.fromCircle(ll(center), (zoneKm * 1000).toFloat()),
            PolygonStyles.from(PolygonStyle.from(0x147B4DFF, 3f * dens, purple))))
        // 은은한 파동 — 차분한 파랑 링 두 개가 7초 주기로 천천히 퍼지며, 나타날 때와 사라질 때 서서히 투명해진다
        var phase = 0f
        while (true) {
            val rings = (0 until 2).map { i -> ((phase + i / 2f) % 1f) }
            val pulse = rings.map { f ->
                val a = ((1f - f).pow(1.5f) * minOf(1f, f / 0.1f) * 56f).toInt()
                layer.addPolygon(PolygonOptions.from(DotPoints.fromCircle(ll(center), (zoneKm * 1000 * f).toFloat()),
                    PolygonStyles.from(PolygonStyle.from(0x00000000, 1.5f * dens, (a shl 24) or 0x2E6FD8))))
            }
            delay(120)
            pulse.forEach { layer.remove(it) }
            phase = (phase + 0.017f) % 1f
        }
    }
    // 여백 — 아래 패널이 가린 만큼 위로 비워, 맞춘 지도가 패널 뒤로 숨지 않게 한다(아이폰 margins와 같다)
    LaunchedEffect(map, bottomOverlayPx, mapHeightPx, navigate) {
        // 패널 높이가 부드럽게 바뀌는 동안 프레임마다 여백을 다시 잡으면 지도가 흔들린다 — 높이가 멈춘 뒤 한 번만
        delay(150)
        val m = map ?: return@LaunchedEffect
        if (navigate) {
            // 위(안내 배너)와 아래(상태 카드)를 뺀 보이는 영역 안에서 구급차가 위에서 70% 되는 곳에 오게 한다.
            // 지도 중심 = 패딩을 뺀 영역의 한가운데이므로, 위쪽 패딩을 그만큼 키운다
            val bottom = minOf(bottomOverlayPx, (mapHeightPx * 0.55).toInt())
            val banner = (mapHeightPx * 0.16).toInt()
            val vehicleY = banner + (0.7 * (mapHeightPx - bottom - banner)).toInt()
            m.setPadding(0, maxOf(0, 2 * vehicleY - mapHeightPx + bottom), 0, bottom)
            return@LaunchedEffect
        }
        val side = (44 * dens).toInt()
        m.setPadding(side, (60 * dens).toInt(), side, minOf(bottomOverlayPx + side, (mapHeightPx * 0.7).toInt()))
    }
    // 카메라 — 구성이 바뀔 때만 맞춘다. 다른 탭에 갔다 와도 사용자가 둔 배율을 유지한다.
    // 우선순위는 아이폰과 같다: 이동 경로 > 응답 존(단계 진입·확장 때 한 번) > 현장에서 고른 병원 > 전체
    // 병원 핀은 지도에 그리지 않으므로(위 핀 효과) 병원 목록이 바뀌는 것(상황 전파로 후보 → 응답 병원)은 카메라 조건이 아니다.
    // 조건에 넣으면 전파 순간 병원들이 들어오게 지도가 순간이동했다가 다시 구급차로 돌아온다
    val fitAfterNav = remember { booleanArrayOf(false) }
    val drawnPins = pins.filter { it.kind != MapPin.Kind.HOSPITAL && it.kind != MapPin.Kind.RECOMMENDED }
    var navExiting by remember { mutableStateOf(false) }
    LaunchedEffect(map, routeKey, zoneFitKey, sceneKey, deliveryFit != null, drawnPins.map { it.id }, bottomOverlayPx > 0, navigate, navExiting) {
        if (navigate || navExiting) return@LaunchedEffect
        // 전파 한 번에 시트·전달 연출·병원 목록이 거의 동시에 바뀐다 — 잠깐 모아서 마지막 상태로 한 번만 맞춘다
        delay(80)
        val m = map ?: return@LaunchedEffect
        if (zoneFitKey == null) lastZoneKey = null
        val id = listOf(routeKey, zoneFitKey, sceneKey, deliveryFit != null, drawnPins.map { it.id }, bottomOverlayPx > 0)
        val saved = lastCamera
        if (saved != null && id == lastFitKey) { m.moveCamera(CameraUpdateFactory.newCenterPosition(saved.first, saved.second)); return@LaunchedEffect }
        val drawn = drawnPins.map { it.pos }
        val zoneNew = zoneFitKey != null && zoneFitKey != lastZoneKey
        val points = when {
            // 전달 연출 — 구급차를 정중앙에 두고 모든 병원이 들어오게(병원 반대쪽 점을 대칭으로 더해 범위가 구급차 중심이 되게)
            deliveryFit != null -> { val c = deliveryFit[0]; deliveryFit + deliveryFit.drop(1).map { GPS(2 * c.lat - it.lat, 2 * c.lng - it.lng) } }
            routeKey != null -> route + drawn
            zoneNew && ambulance != null && zoneKm != null -> circlePoints(ambulance.pos, zoneKm) + drawn
            sceneKey != null && ambulance != null -> listOfNotNull(ambulance.pos, pins.firstOrNull { it.kind == MapPin.Kind.SELECTED }?.pos)
            else -> drawn + route
        }.map(::ll).distinct()
        // 처음 맞출 때만 바로, 그 뒤(내비 시점에서 나올 때·존이 넓어질 때 등)는 서서히 — 갑자기 줌 아웃되지 않게
        val glide = if (lastFitKey != null || fitAfterNav[0]) CameraAnimation.from(1300) else null
        fitAfterNav[0] = false
        when {
            // 전달 연출 앞에서는 순간이동처럼 다시 불러오지 않고, 구급차가 가운데 오도록 부드럽게 옮긴다
            points.size >= 2 && deliveryFit != null -> m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray()), CameraAnimation.from(550))
            points.size >= 2 -> if (glide != null) m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray()), glide) else m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray()))
            points.size == 1 -> if (glide != null) m.moveCamera(CameraUpdateFactory.newCenterPosition(points[0], 15), glide) else m.moveCamera(CameraUpdateFactory.newCenterPosition(points[0], 15))
        }
        if (zoneNew) lastZoneKey = zoneFitKey
        lastFitKey = id
    }
    // 내비게이션 시점 — 프레임마다 위치·회전·배율을 목표로 부드럽게 따라간다(구급차 위치는 1초마다 오고, 모퉁이에서 방위가 한 번에 바뀌므로
    // 받는 값을 그대로 쓰면 뚝뚝 끊긴다). 시뮬레이션 이동은 거리와 무관하게 몇 초 안에 끝나 속도가 크게 다르므로 배율은 속도에 맞춘다
    val nav = remember { NavCamera() }
    val latestPos = rememberUpdatedState(ambulance?.pos)
    val latestRoute = rememberUpdatedState(route)
    val latestSpeedHint = rememberUpdatedState(navSpeedHintMps)
    val lastNavSession = remember { arrayOfNulls<Any>(1) }
    val loadingCallback = rememberUpdatedState(onNavLoading)
    LaunchedEffect(map, navigate) {
        val m = map ?: return@LaunchedEffect
        m.setGestureEnable(GestureType.Pan, !navigate); m.setGestureEnable(GestureType.Zoom, !navigate)
        m.setGestureEnable(GestureType.Rotate, !navigate); m.setGestureEnable(GestureType.Tilt, !navigate)
        m.setGestureEnable(GestureType.RotateZoom, !navigate); m.setGestureEnable(GestureType.OneFingerZoom, !navigate)
        if (!navigate && nav.engaged) {
            // 내비 시점을 벗어날 때: 지도를 북쪽이 위가 되게 서서히 돌린 뒤, 경로 전체 맞추기가 서서히 이어진다
            navExiting = true
            nav.leave()
            latestPos.value?.let { live["ambulance"]?.label?.moveTo(ll(it), 600) }
            var last = 0L
            val startNs = withFrameNanos { it }
            while (true) {
                val ns = withFrameNanos { it }
                if (ns - last < 30_000_000L) continue
                last = ns
                val f = nav.settle(ns)
                m.moveCamera(CameraUpdateFactory.newCameraPosition(f.toCameraPosition()))
                if (ns - startNs > 900_000_000L) break
            }
            fitAfterNav[0] = true; lastFitKey = null
            navExiting = false
        }
    }
    LaunchedEffect(map, navigate, active, navSession) {
        val m = map ?: return@LaunchedEffect
        if (!navigate || !active) return@LaunchedEffect
        // 새 구간(출동·이송·복귀가 시작될 때)이거나 카메라가 구급차에서 멀리 있으면 날아가는 모습을 보이지 않는다 — 로딩을 띄운 채 그 뒤에서
        // 바로 내비 시점으로 맞추고, 준비되면 걷는다. 같은 구간 안에서 다시 들어올 때(탭을 다녀옴·전체 보기에서 돌아옴)는 지금 카메라에서 이어서 간다
        val cp = m.cameraPosition
        val first = latestPos.value
        val freshSession = lastNavSession[0] != navSession
        lastNavSession[0] = navSession
        val far = freshSession || cp == null || first == null || Math.hypot((first.lng - cp.position.longitude) * 111_320.0 * Math.cos(Math.toRadians(first.lat)),
            (first.lat - cp.position.latitude) * 110_540.0) > 800.0
        nav.begin(if (far) null else cp)
        if (far) loadingCallback.value(true)
        var revealAt = if (far) System.nanoTime() + 900_000_000L else 0L
        var last = 0L
        while (true) {
            val ns = withFrameNanos { it }
            if (ns - last < 30_000_000L) continue   // 약 30프레임/초
            last = ns
            val pos = latestPos.value ?: continue
            val f = nav.frame(pos, latestRoute.value, latestSpeedHint.value, ns)
            m.moveCamera(CameraUpdateFactory.newCameraPosition(f.toCameraPosition()))
            live["ambulance"]?.label?.moveTo(LatLng.from(f.lat, f.lng))
            // 첫 그림이 나간 뒤 지도 타일이 그려질 시간을 조금 주고 로딩을 걷는다
            if (revealAt != 0L && System.nanoTime() >= revealAt) { revealAt = 0L; loadingCallback.value(false) }
        }
    }
    // [내 위치] — 배율은 그대로 두고 내 구급차를 가운데로
    LaunchedEffect(recenter) {
        val m = map ?: return@LaunchedEffect
        if (recenter > 0 && ambulance != null) m.moveCamera(CameraUpdateFactory.newCenterPosition(ll(ambulance.pos)))
    }
    Box(modifier.onSizeChanged { mapHeightPx = it.height }) {
        // 다른 화면이 위를 덮을 때는 지도 뷰 자체를 숨긴다 — 네이티브 지도는 Compose 화면과 따로 그려져, 덮는 화면의 첫 프레임이 나오기 전까지 비친다
        AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize(),
            update = { it.visibility = if (active) android.view.View.VISIBLE else android.view.View.INVISIBLE })
        overlay?.invoke { g -> map?.toScreenPoint(ll(g))?.let { Offset(it.x.toFloat(), it.y.toFloat()) } }
    }
}

/** 구면 거리로 만든 원 위의 점들 — 존 전체가 화면에 들어오게 맞출 때 쓴다 */
private fun circlePoints(center: GPS, radiusKm: Double): List<GPS> {
    val lat = Math.toRadians(center.lat)
    val lng = Math.toRadians(center.lng)
    val angle = radiusKm / 6371.0
    return (0 until 36).map { i ->
        val bearing = Math.toRadians(i * 10.0)
        val tLat = Math.asin(Math.sin(lat) * Math.cos(angle) + Math.cos(lat) * Math.sin(angle) * Math.cos(bearing))
        val tLng = lng + Math.atan2(Math.sin(bearing) * Math.sin(angle) * Math.cos(lat), Math.cos(angle) - Math.sin(lat) * Math.sin(tLat))
        GPS(Math.toDegrees(tLat), Math.toDegrees(tLng))
    }
}

/**
 * 내비게이션 카메라의 시간에 따른 상태. 구급차 위치는 1초마다 오므로, 그 위치로 다가가기만 하면 1초 주기로 가다 서다 한다.
 * 그래서 마지막 위치에서 경로를 따라 같은 속도로 계속 가는 것으로 보고(추정 주행), 새 위치가 오면 어긋난 만큼만 서서히 보정한다.
 * 회전도 그 경로 지점의 방향을 따라 서서히 돈다.
 */
private class NavCamera {
    class Frame(val lat: Double, val lng: Double, val rotationDeg: Double, val heightM: Double) {
        // 높이는 연속 배율이다(from(...높이)으로 만들면 높이가 배율을 덮어쓴다). 높이 = 4646m x 2^(15-줌), 실측
        fun toCameraPosition(): CameraPosition = CameraPosition.from(CameraPosition.Builder().setPosition(LatLng.from(lat, lng))
            .setZoomLevel(15).setHeight(heightM).setTiltAngle(0.0).setRotationAngle(Math.toRadians(rotationDeg)))
    }

    var engaged = false; private set
    private var ready = false
    private var lat = 0.0; private var lng = 0.0; private var rot = 0.0; private var logH = Math.log(HEIGHT_Z15)
    private var speedMps = 0.0
    private var lastNs = 0L
    private var snap = false
    // 마지막으로 받은 위치와 그 시점의 남은 경로, 그리고 새 위치가 올 때 생긴 어긋남(서서히 0으로)
    private var fixLat = 0.0; private var fixLng = 0.0; private var fixAtNs = 0L
    private var path = RoutePath(emptyList())
    private var offLat = 0.0; private var offLng = 0.0

    /** 지금 카메라에서 이어서 시작한다 — 내비 시점으로 들어갈 때 튀지 않고 날아 들어가듯 */
    fun begin(cp: CameraPosition?) {
        engaged = true; lastNs = 0L; fixAtNs = 0L; speedMps = 0.0; path = RoutePath(emptyList()); offLat = 0.0; offLng = 0.0
        if (cp != null && cp.height > 0) {
            lat = cp.position.latitude; lng = cp.position.longitude
            rot = (Math.toDegrees(cp.rotationAngle) % 360.0 + 360.0) % 360.0; logH = Math.log(cp.height); ready = true; snap = false
        } else { ready = false; snap = true }   // 이어 갈 카메라가 없으면 첫 프레임에서 회전·배율을 목표로 바로 맞춘다
    }

    fun leave() { engaged = false; lastNs = 0L }

    private fun step(ns: Long): Double {
        val dt = if (lastNs == 0L) 0.033 else ((ns - lastNs) / 1e9).coerceIn(0.001, 0.2)
        lastNs = ns
        return dt
    }

    private fun approach(dt: Double, tau: Double) = 1.0 - Math.exp(-dt / tau)

    private fun shortest(from: Double, to: Double) = ((to - from + 540.0) % 360.0) - 180.0

    private fun meters(aLat: Double, aLng: Double, bLat: Double, bLng: Double) =
        Math.hypot((bLng - aLng) * 111_320.0 * Math.cos(Math.toRadians(bLat)), (bLat - aLat) * 110_540.0)

    fun frame(pos: GPS, route: List<GPS>, speedHintMps: Double?, ns: Long): Frame {
        val dt = step(ns)
        if (fixAtNs == 0L || pos.lat != fixLat || pos.lng != fixLng) {
            // 새 위치 — 속도는 직전 위치와의 거리로 재고(한 번 튀는 값에 흔들리지 않게 섞는다), 지금 보이는 위치와의 어긋남은 남겨 서서히 없앤다
            if (fixAtNs != 0L) {
                val sec = (ns - fixAtNs) / 1e9
                if (sec > 0.2) {
                    val v = meters(fixLat, fixLng, pos.lat, pos.lng) / sec
                    speedMps = if (speedMps == 0.0) v else 0.6 * speedMps + 0.4 * v
                }
            }
            if (ready) { offLat = lat - pos.lat; offLng = lng - pos.lng } else { offLat = 0.0; offLng = 0.0 }
            fixLat = pos.lat; fixLng = pos.lng; fixAtNs = ns
            path = RoutePath(route.map { listOf(it.lat, it.lng) })
            // 아직 속도를 못 쟀으면 hub 추정치로 시작한다
            if (speedMps == 0.0 && speedHintMps != null && speedHintMps > 0) speedMps = speedHintMps
        }
        // 위치 — 마지막 위치에서 경로를 따라 속도만큼 계속 간다. 새 위치가 한참 안 오면(멈춤) 1.5초 뒤부터는 서 있는다
        val sinceFix = ((ns - fixAtNs) / 1e9).coerceAtMost(1.5)
        val travelled = speedMps * sinceFix
        val dr = path.pointAt(travelled) ?: (pos.lat to pos.lng)
        val k = Math.exp(-dt / 0.6)
        offLat *= k; offLng *= k
        lat = dr.first + offLat; lng = dr.second + offLng
        ready = true
        // 회전 — 지금 지점의 경로 방향(조금 앞을 내다보며 모퉁이를 미리 돌기 시작한다)으로 서서히. 가까운 쪽으로 돌아서 북쪽을 지나도 튀지 않는다
        path.bearingAt(travelled, 60.0 + speedMps * 0.5)?.let {
            val want = (360.0 - it) % 360.0
            rot = if (snap) want else ((rot + shortest(rot, want) * approach(dt, 0.5)) % 360.0 + 360.0) % 360.0
        }
        // 배율 — 화면 높이가 구급차가 1초에 가는 거리의 약 7배, 느려도 주변이 보이게 최소 2.5km(줌 14). 로그 값으로 서서히 바꾼다
        val screenM = (speedMps * 7.0).coerceIn(2_500.0, 60_000.0)
        val target = Math.log(screenM * HEIGHT_PER_SCREEN_M).coerceIn(Math.log(HEIGHT_Z15), Math.log(HEIGHT_Z15 * 64.0))
        logH = if (snap) target else logH + (target - logH) * approach(dt, 1.2)
        snap = false
        return Frame(lat, lng, rot, Math.exp(logH))
    }

    /** 내비 시점을 벗어날 때 — 위치·배율은 그대로 두고 북쪽이 위가 되게만 돌린다 */
    fun settle(ns: Long): Frame {
        val dt = step(ns)
        rot = ((rot + shortest(rot, 0.0) * approach(dt, 0.25)) % 360.0 + 360.0) % 360.0
        return Frame(lat, lng, rot, Math.exp(logH))
    }

    private companion object {
        const val HEIGHT_Z15 = 4645.92          // 줌 15일 때 카메라 높이(m) — 실측
        const val HEIGHT_PER_SCREEN_M = 4645.92 / 1750.0   // 화면 높이(m) 대비 카메라 높이 — 줌 15의 화면 높이 약 1.75km
    }
}
