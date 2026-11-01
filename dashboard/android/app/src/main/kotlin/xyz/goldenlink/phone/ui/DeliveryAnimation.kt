package xyz.goldenlink.phone.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.isActive
import xyz.goldenlink.core.GPS
import xyz.goldenlink.phone.PhoneModel
import kotlin.math.PI
import kotlin.math.hypot
import kotlin.math.sin

// 통화 요약이 후보 병원들에 전달되는 모습 — 구급차에서 병원마다 거미줄 같은 곡선이 거의 동시에 그려지고, 선을 따라 빛이 지나가며,
// 도착한 병원에 이름 칩과 ✓가 뜬다. 순차 전화가 아니라 존 안 병원에 동시에 전달한다는 서비스 방식을 그대로 보여 주는 연출이다.
// 병원이 많으면 앞의 8곳만 그리고 숫자는 전체를 센다.

/** 전달 연출에 그릴 병원 — 이름 칩에 쓴다 */
data class DeliveryTarget(val name: String, val gps: GPS)

object DeliveryTimeline {
    const val MAX_TARGETS = 8
    private const val DELAY = 650L     // 카메라가 구급차를 가운데로 옮기는 동안(이동 550ms + 여유)
    private const val STAGGER = 90L    // 병원마다 출발 간격 — 거의 동시로 보이게 짧게
    private const val FLIGHT = 800L    // 선이 구급차에서 병원까지 그려지는 시간
    private const val POP = 350L       // 도착한 병원의 이름 칩이 떠오르는 시간

    /** 선이 그려진 정도 0→1 */
    fun flight(i: Int, t: Long, reduce: Boolean): Float =
        if (reduce) 1f else ((t - DELAY - STAGGER * i).toFloat() / FLIGHT).coerceIn(0f, 1f)

    private fun arrivedAt(i: Int, reduce: Boolean) = if (reduce) 0L else DELAY + STAGGER * i + FLIGHT

    /** 도착 뒤 0→1, 도착 전에는 -1 — 이름 칩이 떠오르는 연출용 */
    fun pop(i: Int, t: Long, reduce: Boolean): Float =
        if (t < arrivedAt(i, reduce)) -1f else ((t - arrivedAt(i, reduce)).toFloat() / POP).coerceIn(0f, 1f)

    fun arrivedCount(n: Int, t: Long, reduce: Boolean): Int = (0 until n).count { t >= arrivedAt(it, reduce) }
}

/** 화면 프레임마다 바뀌는 지금 시각 — 연출이 떠 있는 동안에만 쓴다 */
@Composable
private fun nowEveryFrame(): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (isActive) withFrameMillis { now = System.currentTimeMillis() } }
    return now
}

private fun easeOutCubic(x: Float): Float { val d = 1f - x; return 1f - d * d * d }

/** 구급차→병원 곡선 위의 한 점(t: 0..1) — 병원마다 휘는 방향을 번갈아 줘서 선이 겹치지 않게 한다 */
private fun curvePoint(a: Offset, b: Offset, bendSign: Float, t: Float): Offset {
    val len = hypot(b.x - a.x, b.y - a.y).coerceAtLeast(1f)
    val nx = -(b.y - a.y) / len; val ny = (b.x - a.x) / len
    val c = Offset((a.x + b.x) / 2f + nx * len * 0.18f * bendSign, (a.y + b.y) / 2f + ny * len * 0.18f * bendSign)
    val u = 1f - t
    return Offset(u * u * a.x + 2f * u * t * c.x + t * t * b.x, u * u * a.y + 2f * u * t * c.y + t * t * b.y)
}

private fun DrawScope.curve(a: Offset, b: Offset, bendSign: Float, from: Float, to: Float, color: Color, width: Float) {
    if (to <= from) return
    val steps = 28
    val path = Path()
    for (k in 0..steps) {
        val p = curvePoint(a, b, bendSign, from + (to - from) * k / steps)
        if (k == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y)
    }
    drawPath(path, color, style = Stroke(width, cap = StrokeCap.Round))
}

/** 지도 위 연출 — 화면을 누르면 건너뛴다 */
@Composable
fun DeliveryOverlay(show: PhoneModel.DeliveryShow, from: GPS, targets: List<DeliveryTarget>, project: (GPS) -> Offset?, onSkip: () -> Unit) {
    val now = nowEveryFrame()
    // 구급차 위치를 화면에 찍을 수 있는(지도가 준비된) 첫 프레임부터 시간이 흐른다
    LaunchedEffect(now) { if (show.readyAt == 0L && project(from) != null) show.readyAt = now }
    val t = if (show.readyAt == 0L) 0L else now - show.readyAt
    LaunchedEffect(show.readyAt != 0L && t >= show.durationMs) { if (show.readyAt != 0L && t >= show.durationMs) onSkip() }
    val dens = LocalDensity.current.density
    val measurer = rememberTextMeasurer()
    val chipStyle = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.navy)
    // 이름 칩 글자는 한 번만 재 둔다(프레임마다 다시 재지 않는다)
    val labels = remember(targets) {
        targets.map { target ->
            measurer.measure(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = AD.green)) { append("✓ ") }
                    append(target.name)
                },
                style = chipStyle, overflow = TextOverflow.Ellipsis, maxLines = 1,
                constraints = Constraints(maxWidth = (140 * dens).toInt()),
            )
        }
    }
    Canvas(Modifier.fillMaxSize().clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { onSkip() }) {
        val a = project(from) ?: return@Canvas
        // 구급차 — 전달이 시작되는 곳에 은은한 빛
        val glow = if (show.reduceMotion) 0f else (1f - (t / 900f).coerceIn(0f, 1f))
        drawCircle(AD.blue.copy(alpha = 0.10f + 0.12f * glow), radius = (20f + 18f * (1f - glow)) * dens, center = a)

        targets.forEachIndexed { i, target ->
            val b = project(target.gps) ?: return@forEachIndexed
            val sign = if (i % 2 == 0) 1f else -1f
            val f = DeliveryTimeline.flight(i, t, show.reduceMotion)
            val pop = DeliveryTimeline.pop(i, t, show.reduceMotion)
            val arrived = pop >= 0f

            // 선 — 구급차에서 병원으로 그려진다. 그려지는 동안 끝에 빛이 지나가고, 다 그려진 뒤엔 은은하게 남는다
            val e = easeOutCubic(f)
            val settle = if (arrived) 0.45f - 0.2f * pop else 0.45f
            curve(a, b, sign, 0f, e, AD.blue.copy(alpha = settle), 2f * dens)
            if (f > 0f && f < 1f) curve(a, b, sign, (e - 0.22f).coerceAtLeast(0f), e, Color.White.copy(alpha = 0.9f), 3.5f * dens)
            if (f > 0f && f < 1f) curve(a, b, sign, (e - 0.22f).coerceAtLeast(0f), e, AD.blue.copy(alpha = 0.85f), 2.2f * dens)

            // 병원 자리 — 도착 전엔 속 빈 작은 점, 도착하면 초록으로 켜지고 파동이 한 번 번진다
            if (arrived) {
                drawCircle(AD.green.copy(alpha = 0.25f * (1f - pop)), radius = (7f + 14f * pop) * dens, center = b)
                drawCircle(AD.green, radius = 6f * dens, center = b)
                drawCircle(Color.White, radius = 6f * dens, center = b, style = Stroke(1.5f * dens))
            } else {
                drawCircle(Color.White.copy(alpha = 0.85f), radius = 4.5f * dens, center = b)
                drawCircle(AD.gray, radius = 4.5f * dens, center = b, style = Stroke(1.5f * dens))
            }

            // 이름 칩 — 도착하면 떠오른다. 이웃한 병원과 겹치지 않게 번갈아 위·아래에 둔다
            if (arrived) {
                val label = labels[i]
                val w = label.size.width + 16f * dens
                val h = label.size.height + 8f * dens
                val x = (b.x - w / 2f).coerceIn(4f * dens, (size.width - w - 4f * dens).coerceAtLeast(4f * dens))
                val y = if (i % 2 == 0) b.y - 12f * dens - h else b.y + 12f * dens
                val grow = easeOutCubic((pop * 1.6f).coerceAtMost(1f))
                scale(0.7f + 0.3f * grow, 0.7f + 0.3f * grow, pivot = Offset(x + w / 2f, y + h / 2f)) {
                    drawRoundRect(Color.White.copy(alpha = 0.96f * grow), Offset(x, y), Size(w, h), CornerRadius(h / 2f))
                    drawRoundRect(AD.green.copy(alpha = grow), Offset(x, y), Size(w, h), CornerRadius(h / 2f), style = Stroke(1.5f * dens))
                    drawText(label, topLeft = Offset(x + 8f * dens, y + 4f * dens), alpha = grow)
                }
            }
        }
    }
}

/** 연출 중 아래 카드 — 도착한 병원 수가 올라가고, 모두 도착하면 전체 수로 바뀐다 */
@Composable
fun DeliveryCard(show: PhoneModel.DeliveryShow, shownTargets: Int, total: Int) {
    val now = nowEveryFrame()
    val t = if (show.readyAt == 0L) 0L else now - show.readyAt
    val arrived = DeliveryTimeline.arrivedCount(shownTargets, t, show.reduceMotion)
    val done = arrived >= shownTargets
    val count = if (done) total else arrived
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(if (done) Icons.Filled.CheckCircle else Icons.AutoMirrored.Filled.Send, null, tint = if (done) AD.green else AD.blue, modifier = Modifier.size(26.dp))
            Text(if (done) "후보 병원 ${count}곳에 전달됐습니다" else "후보 병원 ${count}곳에 전달 중…", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
        }
        Text("화면을 누르면 건너뜁니다", fontSize = 11.sp, color = AD.muted)
    }
}
