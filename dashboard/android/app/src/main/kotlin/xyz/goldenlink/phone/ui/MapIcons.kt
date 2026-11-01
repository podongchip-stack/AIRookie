package xyz.goldenlink.phone.ui

import android.graphics.Bitmap
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.text.TextPaint
import android.text.TextUtils

// 통화 지도 마커 — 모양만 봐도 무엇인지 알 수 있게 역할별로 코드로 그린다(이미지 파일 없음).
//   구급차: 위에서 내려다본 구급차(앞유리·지붕 경광등 바·십자·옆 빨간 줄). 진행 방향으로 돌려서 그리고, 경광등은 빨강↔파랑이 번갈아 깜빡인다
//   사건 현장: 빨간 경고판(!)과 바깥으로 번지는 링   병원: 파란 사각형 + 흰 십자   센터: 회색 집
// 외곽선은 얇게, 입체감은 은은한 그림자로만 — 만화처럼 보이지 않게. 좌표는 dp 기준 값을 `d`(화면 밀도)로 곱해 쓴다.

private const val WHITE = 0xFFFFFFFF.toInt()
private const val RED = 0xFFD93025.toInt()

private fun fill(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color; style = Paint.Style.FILL }
private fun line(color: Int, width: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    this.color = color; style = Paint.Style.STROKE; strokeWidth = width; strokeJoin = Paint.Join.ROUND; strokeCap = Paint.Cap.ROUND
}
/** 바닥에 깔리는 부드러운 그림자 — 번진 반투명 검정 */
private fun shadow(blur: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0x40000000; maskFilter = BlurMaskFilter(blur, BlurMaskFilter.Blur.NORMAL) }

private fun bitmap(wDp: Int, hDp: Int, d: Float, draw: Canvas.(u: (Float) -> Float) -> Unit): Bitmap {
    val bmp = Bitmap.createBitmap((wDp * d).toInt(), (hDp * d).toInt(), Bitmap.Config.ARGB_8888)
    Canvas(bmp).draw { v -> v * d }
    return bmp
}

/**
 * 위에서 본 구급차. 앞이 위쪽인 모양을 그린 뒤 headingDeg(북쪽 0, 시계방향)만큼 돌린다.
 * beaconOn이 켜지면 빨간 쪽, 꺼지면 파란 쪽이 밝다(번갈아 깜빡이는 경광등).
 */
fun ambulanceBitmap(d: Float, beaconOn: Boolean, headingDeg: Float): Bitmap = bitmap(72, 72, d) { u ->
    rotate(headingDeg, u(36f), u(36f))
    translate(u(16f), u(4f))   // 차량 그리기 영역(40x64)을 72x72 한가운데로
    val red = if (beaconOn) 0xFFFF3B30.toInt() else 0xFF7A2623.toInt()
    val blue = if (beaconOn) 0xFF2A4C80.toInt() else 0xFF3B8CFF.toInt()
    // 그림자와 차체
    drawRoundRect(RectF(u(8f), u(9f), u(34f), u(63f)), u(8f), u(8f), shadow(u(4f)))
    val body = RectF(u(9f), u(5f), u(31f), u(59f))
    drawRoundRect(body, u(7f), u(7f), fill(0xFFF8FAFD.toInt()))
    drawRoundRect(body, u(7f), u(7f), line(0xFFB4BDCA.toInt(), u(1f)))
    // 옆 빨간 줄
    drawRect(RectF(u(9.6f), u(33f), u(11f), u(55f)), fill(RED)); drawRect(RectF(u(29f), u(33f), u(30.4f), u(55f)), fill(RED))
    // 앞유리와 사이드미러
    drawPath(Path().apply {
        moveTo(u(12f), u(21f)); lineTo(u(13.5f), u(11f)); lineTo(u(26.5f), u(11f)); lineTo(u(28f), u(21f)); close()
    }, fill(0xFF27364A.toInt()))
    drawRoundRect(RectF(u(6.5f), u(17f), u(9f), u(22f)), u(1f), u(1f), fill(0xFF8F9AAA.toInt()))
    drawRoundRect(RectF(u(31f), u(17f), u(33.5f), u(22f)), u(1f), u(1f), fill(0xFF8F9AAA.toInt()))
    // 지붕 경광등 바 — 밝은 쪽에는 번지는 빛
    if (beaconOn) drawCircle(u(15f), u(27.5f), u(8f), fill(0x55FF3B30)) else drawCircle(u(25f), u(27.5f), u(8f), fill(0x553B8CFF))
    drawRoundRect(RectF(u(11f), u(25f), u(20f), u(30f)), u(1.5f), u(1.5f), fill(red))
    drawRoundRect(RectF(u(20f), u(25f), u(29f), u(30f)), u(1.5f), u(1.5f), fill(blue))
    // 지붕 십자와 뒷문 이음선, 미등
    drawRect(RectF(u(15.5f), u(43.6f), u(24.5f), u(46.6f)), fill(RED)); drawRect(RectF(u(18.5f), u(40.6f), u(21.5f), u(49.6f)), fill(RED))
    drawRect(RectF(u(12f), u(54f), u(28f), u(54.8f)), fill(0xFFC9D0DA.toInt()))
    drawRect(RectF(u(11f), u(56f), u(14f), u(58f)), fill(RED)); drawRect(RectF(u(26f), u(56f), u(29f), u(58f)), fill(RED))
}

/** 사건 현장 — 경고판과 바깥으로 번지는 링. phase 0..3이 한 바퀴(링이 커지며 옅어진다) */
fun incidentBitmap(d: Float, phase: Int): Bitmap = bitmap(60, 60, d) { u ->
    val p = (phase % 4) / 4f
    drawCircle(u(30f), u(32f), u(12f + 17f * p), line(((1f - p) * 140).toInt() shl 24 or (RED and 0xFFFFFF), u(2f)))
    val tri = Path().apply { moveTo(u(30f), u(13f)); lineTo(u(47f), u(44f)); lineTo(u(13f), u(44f)); close() }
    drawPath(tri, shadow(u(3f))); drawPath(tri, fill(RED)); drawPath(tri, line(WHITE, u(2f)))
    drawRoundRect(RectF(u(28.4f), u(24f), u(31.6f), u(35f)), u(1.6f), u(1.6f), fill(WHITE))
    drawCircle(u(30f), u(39.5f), u(1.9f), fill(WHITE))
}

/** 병원 — 색을 바꿔 쓰는 사각형 + 흰 십자 */
fun hospitalBitmap(d: Float, color: Int): Bitmap = bitmap(32, 32, d) { u ->
    val r = RectF(u(3f), u(3f), u(29f), u(29f))
    drawRoundRect(RectF(u(3f), u(5f), u(29f), u(31f)), u(6f), u(6f), shadow(u(3f)))
    drawRoundRect(r, u(6f), u(6f), fill(color)); drawRoundRect(r, u(6f), u(6f), line(WHITE, u(1.5f)))
    drawRect(RectF(u(8.5f), u(13.5f), u(23.5f), u(18.5f)), fill(WHITE)); drawRect(RectF(u(13.5f), u(8.5f), u(18.5f), u(23.5f)), fill(WHITE))
}

/** 센터(출동 출발지·복귀 목적지) — 회색 집 */
fun baseBitmap(d: Float): Bitmap = bitmap(30, 30, d) { u ->
    val house = Path().apply {
        moveTo(u(15f), u(4f)); lineTo(u(27f), u(14f)); lineTo(u(23f), u(14f)); lineTo(u(23f), u(26f))
        lineTo(u(7f), u(26f)); lineTo(u(7f), u(14f)); lineTo(u(3f), u(14f)); close()
    }
    drawPath(house, shadow(u(2.5f))); drawPath(house, fill(0xFF5A6676.toInt())); drawPath(house, line(WHITE, u(1.5f)))
    drawRect(RectF(u(12f), u(18f), u(18f), u(26f)), fill(WHITE))
}

/**
 * 아이콘 아래에 이름 글자를 그려 넣은 그림. 지도 SDK의 라벨 글자는 쓰지 않는다 — 글자가 아이콘 옆에 붙으면 SDK가 아이콘+글자 전체의
 * 중심을 좌표에 맞춰서 아이콘이 길에서 벗어나 보인다. 여기서는 아이콘이 그림의 정중앙에 오고 글자는 그 아래(위쪽은 같은 높이의 빈 공간)에
 * 있어서, 라벨 중심 = 아이콘 중심 = 실제 좌표다.
 */
fun withCaption(icon: Bitmap, caption: String, d: Float): Bitmap {
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 12f * d; typeface = Typeface.DEFAULT_BOLD; color = 0xFF14213D.toInt(); textAlign = Paint.Align.CENTER
    }
    val text = TextUtils.ellipsize(caption, TextPaint(paint), 150f * d, TextUtils.TruncateAt.END).toString()
    val fm = paint.fontMetrics
    val textH = fm.descent - fm.ascent
    val gap = 2f * d
    val w = maxOf(icon.width.toFloat(), paint.measureText(text) + 12f * d)
    val h = icon.height + 2f * (gap + textH)
    val bmp = Bitmap.createBitmap(w.toInt(), h.toInt(), Bitmap.Config.ARGB_8888)
    val c = Canvas(bmp)
    c.drawBitmap(icon, (w - icon.width) / 2f, (h - icon.height) / 2f, null)
    val baseline = (h + icon.height) / 2f + gap - fm.ascent
    val halo = Paint(paint).apply { style = Paint.Style.STROKE; strokeWidth = 3f * d; color = WHITE; strokeJoin = Paint.Join.ROUND }
    c.drawText(text, w / 2f, baseline, halo)
    c.drawText(text, w / 2f, baseline, paint)
    return bmp
}
