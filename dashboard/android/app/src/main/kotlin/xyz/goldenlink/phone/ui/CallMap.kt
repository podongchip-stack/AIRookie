package xyz.goldenlink.phone.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
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
import com.kakao.vectormap.camera.CameraUpdateFactory
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelStyles
import com.kakao.vectormap.label.LabelTextBuilder
import com.kakao.vectormap.shape.DotPoints
import com.kakao.vectormap.shape.PolygonOptions
import com.kakao.vectormap.shape.PolygonStyle
import com.kakao.vectormap.shape.PolygonStyles
import com.kakao.vectormap.route.RouteLineOptions
import com.kakao.vectormap.route.RouteLineSegment
import com.kakao.vectormap.route.RouteLineStyle
import com.kakao.vectormap.route.RouteLineStyles
import kotlinx.coroutines.delay
import xyz.goldenlink.core.GPS
import xyz.goldenlink.phone.BuildConfig

// 통화 탭의 배경 지도(카카오맵 SDK) — 내 구급차·사건 현장·후보 병원을 핀으로 찍고, 출동 중엔 현장까지 선을 긋고,
// 통화가 끝나 정보가 전달되면 구급차에서 후보 병원들로 점이 날아가는 애니메이션을 그린다.
// 후보 메시지(scene_candidates)에는 병원 좌표가 없어 hub 병원 목록(map_overview)의 좌표를 hospitalId로 찾아 쓴다.

data class MapPin(val id: String, val name: String, val pos: GPS, val kind: Kind) {
    enum class Kind { HOSPITAL, RECOMMENDED, SELECTED, AMBULANCE, INCIDENT, BASE }
}

private var sdkReady = false
// 탭을 갔다 와도 지도 중심·배율을 유지한다(지도 화면은 탭을 떠나면 사라진다)
private var lastCamera: Pair<LatLng, Int>? = null
private var lastFitKey: Any? = null
private var lastZoneKey: Any? = null

private fun circle(sizePx: Int, fill: Int): Bitmap {
    val bmp = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
    val c = Canvas(bmp)
    val p = Paint(Paint.ANTI_ALIAS_FLAG)
    val r = sizePx / 2f
    p.color = android.graphics.Color.WHITE; c.drawCircle(r, r, r, p)
    p.color = fill; c.drawCircle(r, r, r * 0.78f, p)
    return bmp
}

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

    // 핀 — 종류에 따라 색·크기를 바꿔 다시 찍는다(구급차는 1초마다 움직여 같이 갱신된다)
    LaunchedEffect(map, pins) {
        val layer = map?.labelManager?.layer ?: return@LaunchedEffect
        layer.removeAll()
        // 전화 걸 병원(선택)과 내 구급차·사건 현장만 찍는다 — 다른 병원은 지도에 그리지 않는다
        for (p in pins) {
            if (p.kind == MapPin.Kind.HOSPITAL || p.kind == MapPin.Kind.RECOMMENDED) continue
            val (color, size) = when (p.kind) {
                MapPin.Kind.SELECTED -> 0xFF1F4E9C.toInt() to 30
                MapPin.Kind.RECOMMENDED -> 0xFF168A55.toInt() to 24
                MapPin.Kind.HOSPITAL -> 0xFF14213D.toInt() to 20
                MapPin.Kind.AMBULANCE -> 0xFFC75B00.toInt() to 28
                MapPin.Kind.INCIDENT -> 0xFFD93025.toInt() to 28
                MapPin.Kind.BASE -> 0xFF5A6676.toInt() to 24
            }
            val style = LabelStyle.from(circle((size * dens).toInt(), color)).setTextStyles((12 * dens).toInt(), 0xFF14213D.toInt(), 2, 0xFFFFFFFF.toInt())
            val opts = LabelOptions.from(ll(p.pos)).setStyles(LabelStyles.from(style)).setClickable(true).setTag(p.id)
            layer.addLabel(if (p.name.isBlank()) opts else opts.setTexts(LabelTextBuilder().setTexts(p.name)))
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
    LaunchedEffect(map, zoneKm, ambulance?.pos) {
        val m = map ?: return@LaunchedEffect
        val layer = m.shapeManager?.layer ?: return@LaunchedEffect
        val center = ambulance?.pos ?: return@LaunchedEffect
        layer.removeAll()
        if (zoneKm == null) return@LaunchedEffect
        val purple = 0xFF7B4DFF.toInt()
        layer.addPolygon(PolygonOptions.from(DotPoints.fromCircle(ll(center), (zoneKm * 1000).toFloat()),
            PolygonStyles.from(PolygonStyle.from(0x147B4DFF, 3f * dens, purple))))
        var phase = 0f
        while (true) {
            val rings = (0 until 3).map { i -> ((phase + i / 3f) % 1f) }
            val pulse = rings.map { f ->
                layer.addPolygon(PolygonOptions.from(DotPoints.fromCircle(ll(center), (zoneKm * 1000 * f).toFloat()),
                    PolygonStyles.from(PolygonStyle.from(0x00000000, 2f * dens, (((1f - f) * 160).toInt() shl 24) or 0x7B4DFF))))
            }
            delay(120)
            pulse.forEach { layer.remove(it) }
            phase = (phase + 0.03f) % 1f
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
    LaunchedEffect(map, routeKey, zoneFitKey, sceneKey, pins.map { it.id }, if (routeKey != null) bottomOverlayPx > 0 else bottomOverlayPx) {
        val m = map ?: return@LaunchedEffect
        if (zoneFitKey == null) lastZoneKey = null
        val id = listOf(routeKey, zoneFitKey, sceneKey, pins.map { it.id }, if (routeKey != null) bottomOverlayPx > 0 else bottomOverlayPx)
        val saved = lastCamera
        if (saved != null && id == lastFitKey) { m.moveCamera(CameraUpdateFactory.newCenterPosition(saved.first, saved.second)); return@LaunchedEffect }
        val drawn = pins.filter { it.kind != MapPin.Kind.HOSPITAL && it.kind != MapPin.Kind.RECOMMENDED }.map { it.pos }
        val zoneNew = zoneFitKey != null && zoneFitKey != lastZoneKey
        val points = when {
            routeKey != null -> route + drawn
            zoneNew && ambulance != null && zoneKm != null -> circlePoints(ambulance.pos, zoneKm) + drawn
            sceneKey != null && ambulance != null -> listOfNotNull(ambulance.pos, pins.firstOrNull { it.kind == MapPin.Kind.SELECTED }?.pos)
            else -> pins.map { it.pos } + route
        }.map(::ll).distinct()
        when {
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
    Box(modifier.onSizeChanged { mapHeightPx = it.height }) { AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize()) }
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
