package xyz.goldenlink.phone.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import xyz.goldenlink.core.BodyEdits
import xyz.goldenlink.core.BodyGeometry
import xyz.goldenlink.core.BodyMark
import xyz.goldenlink.core.BodyShapeData
import xyz.goldenlink.core.InjuryMapper
import xyz.goldenlink.core.InjuryRisk
import xyz.goldenlink.core.InjuryTier
import xyz.goldenlink.core.MappedInjury
import xyz.goldenlink.core.PatientInfo
import xyz.goldenlink.core.Pt
import xyz.goldenlink.phone.PhoneModel

// 외상 등록 페이지 — 아이패드 BodyInjuryCard를 폰 한 열로 옮겼다. 사람 그림에서 부위를 탭으로만 고른다(드래그는 가로 페이지 넘김과 부딪친다).
// 부위는 통화 요약의 글자에서 낱말 규칙으로 찾고(AI 아님), 색은 위험도 규칙(전문의 검토 전 초안)이다. 순위·병원 선택에는 쓰지 않는다.

private fun InjuryTier.color(): Color = when (this) { InjuryTier.HIGH -> AD.red; InjuryTier.MEDIUM -> AD.orange; InjuryTier.LOW -> AD.lime }
private fun InjuryTier.soft(): Color = when (this) { InjuryTier.HIGH -> AD.redSoft; InjuryTier.MEDIUM -> AD.orangeSoft; InjuryTier.LOW -> AD.limeSoft }

/** 통화 요약 + 구급대원이 고친 것으로 그린 그림의 재료 */
private class BodyView(p: PatientInfo, e: BodyEdits) {
    private val injuries: List<MappedInjury> = InjuryMapper.parse(p)
    private val specific = injuries.filter { it.marks.isNotEmpty() && !it.isMulti }
    /** 그림에 칠할 항목 — 구체적인 게 하나도 없을 때만 "다발성"이 몸 전체를 칠한다 */
    val located: List<MappedInjury> = if (specific.isEmpty()) injuries.filter { it.marks.isNotEmpty() } else specific
    /** 선 없이 따로 둘 항목 — 부위를 못 찾은 것 + (구체적 부위가 있을 때의) 다발성 */
    val unlocated: List<MappedInjury> = injuries.filter { it.marks.isEmpty() || (it.isMulti && specific.isNotEmpty()) }
    val callMarks: Set<BodyMark> = located.flatMap { it.marks }.toSet()
    val vital = InjuryRisk.vitalTier(p)

    /** 부위별 위험도 — 그 부위에 걸린 항목 중 가장 높은 등급 */
    val tiers: Map<BodyMark, InjuryTier> = buildMap {
        for (injury in located) for (mark in injury.marks) {
            if (mark in e.removed) continue
            put(mark, maxOf(get(mark) ?: InjuryTier.LOW, InjuryRisk.tier(injury.text, mark.region)))
        }
        for (mark in e.added) {
            val text = (listOf("외상") + (e.cares[mark] ?: emptyList())).joinToString(" ")
            put(mark, maxOf(get(mark) ?: InjuryTier.LOW, InjuryRisk.tier(text, mark.region)))
        }
    }

    /** 부위를 못 찾은 항목의 등급 — 의식 저하·호흡 곤란 같은 적색 깃발을 놓치지 않게 같이 매긴다 */
    val generalTier: InjuryTier = maxOf(unlocated.maxOfOrNull { InjuryRisk.tier(it.text, null) } ?: InjuryTier.LOW, vital.tier)
    val showsGeneral: Boolean = unlocated.isNotEmpty() || vital.reason != null

    /** 번호는 머리부터 발끝 순서 */
    val numbered: List<Pair<Int, BodyMark>> =
        tiers.keys.sortedWith(compareBy({ it.region.ordinal }, { it.side.label })).mapIndexed { i, m -> (i + 1) to m }

    fun text(mark: BodyMark, e: BodyEdits): String {
        var texts = located.filter { mark in it.marks }.map { it.text }
        if (texts.isEmpty()) texts = listOf("외상(구급대원 확인)")
        texts = texts + (e.cares[mark] ?: emptyList()).map { "처치 $it" }
        return texts.joinToString(" · ")
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BodyPage(m: PhoneModel, p: PatientInfo) {
    val e = m.bodyEdits
    val v = BodyView(p, e)
    var back by remember { mutableStateOf(false) }
    var tapped by remember { mutableStateOf<BodyMark?>(null) }

    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Card {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text("외상 부위", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    }
                    p.ktasLevel?.let { Pill("KTAS $it", ktasColor(it), ktasSoft(it), bold = true) }
                    if (v.tiers.isNotEmpty()) Pill("${v.tiers.size}곳", AD.red, AD.redSoft, bold = true)
                    FaceSwitch(back, v) { back = it; tapped = null }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                    Figure(v, back, Modifier.weight(0.42f)) { tapped = it }
                    Column(Modifier.weight(0.58f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        val shown = v.numbered.filter { BodyGeometry.visible(it.second.region, back) }
                        for ((n, mark) in shown) CalloutBox(n, mark, v.tiers[mark] ?: InjuryTier.LOW, v.text(mark, e))
                        if (shown.isEmpty() && v.unlocated.isEmpty()) {
                            Text(if (back) "뒷모습에 표시된 부위가 없습니다" else "통화 요약에 외상 항목이 없습니다", fontSize = 12.sp, color = AD.muted)
                        }
                        if (!back && v.showsGeneral) GeneralBox(v)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    for (t in listOf(InjuryTier.HIGH, InjuryTier.MEDIUM, InjuryTier.LOW)) {
                        Box(Modifier.size(7.dp).clip(CircleShape).background(t.color()))
                        Text(t.label, fontSize = 10.5.sp, fontWeight = FontWeight.SemiBold, color = AD.ink3)
                    }
                }
            }
        }
        SendBar(m)
        Spacer(Modifier.size(8.dp))
    }
    tapped?.let { BodyEditDialog(m, it, v) { tapped = null } }
}

/** [앞 | 뒤] — 반대쪽에만 있는 부위 수를 배지로 알려 준다(등·허리가 뒤에 있는 걸 놓치지 않게) */
@Composable
private fun FaceSwitch(back: Boolean, v: BodyView, onChange: (Boolean) -> Unit) {
    Row(Modifier.clip(CircleShape).background(AD.chip).clickable { onChange(!back) }.padding(2.dp)) {
        for (value in listOf(false, true)) {
            val on = back == value
            val hidden = v.tiers.keys.count { BodyGeometry.visible(it.region, value) && !BodyGeometry.visible(it.region, !value) }
            Row(Modifier.clip(CircleShape).background(if (on) AD.white else Color.Transparent).padding(horizontal = 10.dp, vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(if (value) "뒤" else "앞", fontSize = 12.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium, color = if (on) AD.navy else AD.ink3)
                if (!on && hidden > 0) Text("$hidden", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Color.White,
                    modifier = Modifier.clip(CircleShape).background(AD.red).padding(horizontal = 5.dp))
            }
        }
    }
}

private fun List<Pt>.toPath(w: Float, h: Float): Path = Path().also { path ->
    forEachIndexed { i, q -> if (i == 0) path.moveTo((q.x * w).toFloat(), (q.y * h).toFloat()) else path.lineTo((q.x * w).toFloat(), (q.y * h).toFloat()) }
    if (isNotEmpty()) path.close()
}

/** 사람 모양 — 실루엣을 통째로 그리고 다친 부위만 그 영역으로 오려 위험도 색으로 덧칠한다. 부위는 탭으로 고른다 */
@Composable
private fun Figure(v: BodyView, back: Boolean, modifier: Modifier, onTap: (BodyMark) -> Unit) {
    val measurer = rememberTextMeasurer()
    val height = 330.dp
    val width = height * BodyShapeData.RATIO.toFloat()
    Box(modifier.heightIn(min = height), contentAlignment = Alignment.TopCenter) {
        Canvas(Modifier.size(width, height).pointerInput(back) {
            detectTapGestures { o ->
                BodyGeometry.hit(Pt(o.x.toDouble() / size.width, o.y.toDouble() / size.height), back)?.let(onTap)
            }
        }) {
            val w = size.width; val h = size.height
            val body = BodyGeometry.outline.toPath(w, h)
            // 뒷모습은 좌표계를 통째로 뒤집어 그린다 — 보이는 좌우만 바뀐다
            scale(if (back) -1f else 1f, 1f, pivot = Offset(w / 2, h / 2)) {
                drawPath(body, AD.navy)
                for ((_, mark) in v.numbered) {
                    if (!BodyGeometry.visible(mark.region, back)) continue
                    val region = BodyGeometry.region(mark, back).toPath(w, h)
                    clipPath(region) { drawPath(body, (v.tiers[mark] ?: InjuryTier.LOW).color()) }
                }
                clipPath(body) {
                    val dash = PathEffect.dashPathEffect(floatArrayOf(6f, 6f))
                    for ((a, b) in BodyGeometry.dividers(back)) {
                        drawLine(Color.White.copy(alpha = 0.22f), Offset((a.x * w).toFloat(), (a.y * h).toFloat()),
                            Offset((b.x * w).toFloat(), (b.y * h).toFloat()), strokeWidth = 2f, pathEffect = dash)
                    }
                }
            }
            // 번호 동그라미는 뒤집지 않고 자리만 뒤집는다(글자가 거울상이 되지 않게)
            for ((n, mark) in v.numbered) {
                if (!BodyGeometry.visible(mark.region, back)) continue
                val a = BodyGeometry.anchor(mark, back)
                val c = Offset((a.x * w).toFloat(), (a.y * h).toFloat())
                val color = (v.tiers[mark] ?: InjuryTier.LOW).color()
                drawCircle(color, radius = 9.dp.toPx(), center = c)
                drawCircle(Color.White, radius = 9.dp.toPx(), center = c, style = Stroke(1.5.dp.toPx()))
                val t = measurer.measure("$n", TextStyle(color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold))
                drawText(t, topLeft = Offset(c.x - t.size.width / 2f, c.y - t.size.height / 2f))
            }
        }
    }
}

@Composable
private fun CalloutBox(n: Int, mark: BodyMark, tier: InjuryTier, text: String) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(AD.white).border(1.5.dp, tier.soft(), RoundedCornerShape(10.dp))
        .padding(horizontal = 8.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.Top) {
        Text("$n", fontSize = 11.sp, fontWeight = FontWeight.ExtraBold, color = Color.White, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            modifier = Modifier.size(20.dp).clip(CircleShape).background(tier.color()).padding(top = 2.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(mark.label, fontSize = 12.5.sp, fontWeight = FontWeight.Bold, color = tier.color())
                Pill(tier.label, tier.color(), tier.soft())
            }
            Text(text, fontSize = 12.sp, color = AD.ink)
        }
    }
}

@Composable
private fun GeneralBox(v: BodyView) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(AD.chip).padding(horizontal = 8.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("부위 미상 · 전신 증상", fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold, color = AD.muted)
            if (v.generalTier > InjuryTier.LOW) Pill(v.generalTier.label, v.generalTier.color(), v.generalTier.soft())
        }
        if (v.unlocated.isNotEmpty()) Text(v.unlocated.joinToString(" · ") { it.text }, fontSize = 12.sp, color = AD.ink3)
        v.vital.reason?.let { Text(it, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold, color = v.vital.tier.color()) }
    }
}

/** 적은 것을 한 번에 보내는 줄 — 고친 게 없으면 아예 안 보인다. 부위마다 보내면 병원에 쪽지가 여러 장 가서 한 번에 낸다 */
@Composable
private fun SendBar(m: PhoneModel) {
    val e = m.bodyEdits
    if (e.isEmpty && e.signature == m.bodySentSignature) return
    val sent = e.signature == m.bodySentSignature
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.chip).padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (sent) Pill("병원에 전달함", AD.green, AD.greenSoft, bold = true) else Pill("전달 전", AD.orange, AD.orangeSoft, bold = true)
        Text("부위 ${e.markCount}곳 · 처치 ${e.careLines.size}건", fontSize = 11.5.sp, color = if (sent) AD.muted else AD.ink3, modifier = Modifier.weight(1f))
        if (!sent) Row(Modifier.clip(CircleShape).background(if (m.paused) AD.gray else AD.blue).clickable { m.sendBodyEdits() }.heightIn(min = 32.dp)
            .padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(Icons.AutoMirrored.Filled.Send, null, tint = Color.White, modifier = Modifier.size(14.dp))
            Text("병원에 전달", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        }
    }
}

/** 부위 하나를 고치는 칸 — 외상 있음/없음과 그 부위에 한 처치. 여기서는 보내지 않고 [적용]으로 도해에만 반영한다 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BodyEditDialog(m: PhoneModel, mark: BodyMark, v: BodyView, onClose: () -> Unit) {
    val fromCall = mark in v.callMarks
    var on by remember { mutableStateOf(v.tiers.containsKey(mark)) }
    val cares = remember { mutableStateListOf<String>().apply { addAll(m.bodyEdits.cares[mark] ?: emptyList()) } }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.safeDrawingPadding().padding(12.dp).clip(cardShape).background(AD.white).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(mark.label, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold, color = AD.navy)
                if (fromCall) Pill("통화 요약", AD.blue, AD.blueSoft)
                Spacer(Modifier.weight(1f))
                Text("닫기", color = AD.ink3, fontSize = 13.sp, modifier = Modifier.clickable(onClick = onClose))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (value in listOf(true, false)) {
                    val sel = on == value
                    Text(if (value) "외상 있음" else "외상 없음", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = if (sel) Color.White else AD.ink3,
                        modifier = Modifier.clip(CircleShape).background(if (sel) (if (value) AD.red else AD.gray) else AD.chip)
                            .clickable { on = value; if (!value) cares.clear() }.padding(horizontal = 14.dp, vertical = 8.dp))
                }
            }
            if (on) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (o in BodyEdits.careOptions) {
                        val sel = o in cares
                        Text(o, fontSize = 12.5.sp, fontWeight = if (sel) FontWeight.Bold else FontWeight.Medium, color = if (sel) Color.White else AD.ink3,
                            modifier = Modifier.clip(CircleShape).background(if (sel) AD.blue else AD.chip)
                                .clickable { if (sel) cares.remove(o) else cares.add(o) }.padding(horizontal = 12.dp, vertical = 7.dp))
                    }
                }
            }
            Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp)).background(AD.blue)
                .clickable { m.bodyEdits = m.bodyEdits.applied(mark, on, cares.toList(), fromCall); onClose() },
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Text("적용", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}
