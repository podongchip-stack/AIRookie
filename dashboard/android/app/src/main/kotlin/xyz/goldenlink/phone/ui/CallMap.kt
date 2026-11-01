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
import com.kakao.vectormap.KakaoMapSdk
import com.kakao.vectormap.LatLng
import com.kakao.vectormap.MapLifeCycleCallback
import com.kakao.vectormap.MapView
import com.kakao.vectormap.camera.CameraAnimation
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
    var map by remember { mutableStateOf<KakaoMap?>(null) }
    val mapView = remember { MapView(context) }
    var mapHeightPx by remember { mutableIntStateOf(0) }

    DisposableEffect(mapView) {
        mapView.start(object : MapLifeCycleCallback() {
            override fun onMapDestroy() {}
            override fun onMapError(error: Exception?) {}
        }, object : KakaoMapReadyCallback() {
            override fun onMapReady(kakaoMap: KakaoMap) {
                kakaoMap.setOnCameraMoveEndListener { _, pos, _ -> lastCamera = pos.position to pos.zoomLevel }
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
    LaunchedEffect(map, pins, frame, heading) {
        val layer = map?.labelManager?.layer ?: return@LaunchedEffect
        val wanted = pins.filter { it.kind != MapPin.Kind.HOSPITAL && it.kind != MapPin.Kind.RECOMMENDED }.associateBy { it.id }
        for ((id, e) in live.toMap()) if (id !in wanted) { layer.remove(e.label); live.remove(id) }
        for (p in wanted.values) {
            val key = when (p.kind) {
                MapPin.Kind.AMBULANCE -> "amb-${frame % 2}-$heading"
                MapPin.Kind.INCIDENT -> "inc-$frame"
                else -> p.kind.name
            }
            val labelStyles = styles.getOrPut("$key|${p.name}") {
                val icon = when (p.kind) {
                    MapPin.Kind.AMBULANCE -> ambulanceBitmap(dens, beaconOn = frame % 2 == 0, headingDeg = heading.toFloat())
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
                if (have.pos != p.pos) { have.label.moveTo(ll(p.pos)); have.pos = p.pos }
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
    LaunchedEffect(map, bottomOverlayPx, mapHeightPx) {
        val m = map ?: return@LaunchedEffect
        val side = (44 * dens).toInt()
        m.setPadding(side, (60 * dens).toInt(), side, minOf(bottomOverlayPx + side, (mapHeightPx * 0.7).toInt()))
    }
    // 카메라 — 구성이 바뀔 때만 맞춘다. 다른 탭에 갔다 와도 사용자가 둔 배율을 유지한다.
    // 우선순위는 아이폰과 같다: 이동 경로 > 응답 존(단계 진입·확장 때 한 번) > 현장에서 고른 병원 > 전체
    LaunchedEffect(map, routeKey, zoneFitKey, sceneKey, deliveryFit != null, pins.map { it.id }, if (routeKey != null) bottomOverlayPx > 0 else bottomOverlayPx) {
        val m = map ?: return@LaunchedEffect
        if (zoneFitKey == null) lastZoneKey = null
        val id = listOf(routeKey, zoneFitKey, sceneKey, deliveryFit != null, pins.map { it.id }, if (routeKey != null) bottomOverlayPx > 0 else bottomOverlayPx)
        val saved = lastCamera
        if (saved != null && id == lastFitKey) { m.moveCamera(CameraUpdateFactory.newCenterPosition(saved.first, saved.second)); return@LaunchedEffect }
        val drawn = pins.filter { it.kind != MapPin.Kind.HOSPITAL && it.kind != MapPin.Kind.RECOMMENDED }.map { it.pos }
        val zoneNew = zoneFitKey != null && zoneFitKey != lastZoneKey
        val points = when {
            // 전달 연출 — 구급차를 정중앙에 두고 모든 병원이 들어오게(병원 반대쪽 점을 대칭으로 더해 범위가 구급차 중심이 되게)
            deliveryFit != null -> { val c = deliveryFit[0]; deliveryFit + deliveryFit.drop(1).map { GPS(2 * c.lat - it.lat, 2 * c.lng - it.lng) } }
            routeKey != null -> route + drawn
            zoneNew && ambulance != null && zoneKm != null -> circlePoints(ambulance.pos, zoneKm) + drawn
            sceneKey != null && ambulance != null -> listOfNotNull(ambulance.pos, pins.firstOrNull { it.kind == MapPin.Kind.SELECTED }?.pos)
            else -> pins.map { it.pos } + route
        }.map(::ll).distinct()
        when {
            // 전달 연출 앞에서는 순간이동처럼 다시 불러오지 않고, 구급차가 가운데 오도록 부드럽게 옮긴다
            points.size >= 2 && deliveryFit != null -> m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray()), CameraAnimation.from(550))
            points.size >= 2 -> m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray()))
            points.size == 1 -> m.moveCamera(CameraUpdateFactory.newCenterPosition(points[0], 15))
        }
        if (zoneNew) lastZoneKey = zoneFitKey
        lastFitKey = id
    }
    // [내 위치] — 배율은 그대로 두고 내 구급차를 가운데로
    LaunchedEffect(recenter) {
        val m = map ?: return@LaunchedEffect
        if (recenter > 0 && ambulance != null) m.moveCamera(CameraUpdateFactory.newCenterPosition(ll(ambulance.pos)))
    }
    Box(modifier.onSizeChanged { mapHeightPx = it.height }) {
        AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize())
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
