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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import com.kakao.vectormap.label.LabelLayerOptions
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelStyles
import com.kakao.vectormap.label.LabelTextBuilder
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
    enum class Kind { HOSPITAL, RECOMMENDED, SELECTED, AMBULANCE, INCIDENT }
}

private var sdkReady = false

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
    pins: List<MapPin>, route: Boolean, burstKey: Int, onPin: (String) -> Unit, modifier: Modifier = Modifier,
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

    DisposableEffect(mapView) {
        mapView.start(object : MapLifeCycleCallback() {
            override fun onMapDestroy() {}
            override fun onMapError(error: Exception?) {}
        }, object : KakaoMapReadyCallback() {
            override fun onMapReady(kakaoMap: KakaoMap) {
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
            }
            val style = LabelStyle.from(circle((size * dens).toInt(), color)).setTextStyles((12 * dens).toInt(), 0xFF14213D.toInt(), 2, 0xFFFFFFFF.toInt())
            val opts = LabelOptions.from(ll(p.pos)).setStyles(LabelStyles.from(style)).setClickable(true).setTag(p.id)
            layer.addLabel(if (p.name.isBlank()) opts else opts.setTexts(LabelTextBuilder().setTexts(p.name)))
        }
    }
    // 출동 중 — 구급차에서 사건 현장까지 선(도로 경로는 hub가 아직 안 준다 — 직선)
    LaunchedEffect(map, route, ambulance?.pos, incident?.pos) {
        val layer = map?.routeLineManager?.layer ?: return@LaunchedEffect
        layer.removeAll()
        if (route && ambulance != null && incident != null) {
            val style = RouteLineStyles.from(RouteLineStyle.from(10f * dens, 0xFF1F4E9C.toInt()))
            layer.addRouteLine(RouteLineOptions.from(RouteLineSegment.from(listOf(ll(ambulance.pos), ll(incident.pos)), style)))
        }
    }
    // 카메라 — 핀 전체가 보이게 한 번 맞춘다(핀 구성이 바뀔 때만. 구급차가 움직이는 것으로는 다시 맞추지 않는다)
    LaunchedEffect(map, pins.map { it.id }) {
        val m = map ?: return@LaunchedEffect
        val points = pins.map { ll(it.pos) }
        when {
            points.size >= 2 -> m.moveCamera(CameraUpdateFactory.fitMapPoints(points.toTypedArray(), (56 * dens).toInt()))
            points.size == 1 -> m.moveCamera(CameraUpdateFactory.newCenterPosition(points[0], 15))
        }
    }
    // 전달 애니메이션 — 구급차에서 후보 병원마다 점이 날아간다(세 번 물결치듯)
    LaunchedEffect(map, burstKey) {
        val m = map ?: return@LaunchedEffect
        if (burstKey <= 0 || ambulance == null) return@LaunchedEffect
        val fx = m.labelManager?.getLayer("fx") ?: m.labelManager?.addLayer(LabelLayerOptions.from("fx")) ?: return@LaunchedEffect
        val dot = LabelStyles.from(LabelStyle.from(circle((14 * dens).toInt(), 0xFF1F4E9C.toInt())))
        val targets = pins.filter { it.kind == MapPin.Kind.HOSPITAL || it.kind == MapPin.Kind.RECOMMENDED || it.kind == MapPin.Kind.SELECTED }
        repeat(3) {
            for (t in targets) {
                val label = fx.addLabel(LabelOptions.from(ll(ambulance.pos)).setStyles(dot)) ?: continue
                label.moveTo(ll(t.pos), 1100)
            }
            delay(550)
        }
        delay(1200)
        fx.removeAll()
    }

    Box(modifier) { AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize()) }
}
