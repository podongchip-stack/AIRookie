package xyz.goldenlink.phone.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import xyz.goldenlink.core.BedLive
import xyz.goldenlink.core.DisplayLabels
import xyz.goldenlink.core.MatchHospital
import xyz.goldenlink.phone.PhoneModel
import kotlin.math.roundToInt

// [이송] 탭 — 아이패드 구급차 앱의 병원 리스트(CandidateCard)와 [이송 승인]을 폰 한 열로 옮겼다.
// 순위는 hub가 정한 순서 그대로다(앱이 다시 정렬하지 않는다). 병원이 수용 승인한 병원에만 [이송 승인]이 열린다 — 최종 결정은 구급대원이다.

private val approveColor = Color(0xFFB45309)

/** 지금 이 환자를 실제로 보낼 수 있는 승인 병원인가 — 아이패드 HospitalRules.canTransportNow와 같은 규칙 */
fun canTransportNow(h: MatchHospital): Boolean {
    if (h.status != "approved" || h.unavailableReason != null || h.excluded == true) return false
    if (h.demoteReasons?.any { it == "beds_full" || it == "severe_blocked" } == true) return false
    if (h.bedCountUnknown == true || h.bedDataStale == true) return true
    return (h.availableBedCount ?: 1) > 0
}

@Composable
fun TransportTab(m: PhoneModel) {
    val r = m.result
    if (r == null) {
        StatusPanel(Icons.Filled.LocalHospital, AD.gray, "병원 응답을 기다리는 중",
            if (m.hasIncident) "통화가 후보 병원에 전달되면 수용 승인·불가 응답이 여기에 모입니다." else "새 사건이 들어오면 후보 병원이 여기에 나타납니다.")
        return
    }
    val now = nowEverySecond()
    val confirmed = m.confirmed
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Column(Modifier.padding(horizontal = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("후보 병원", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    val ok = r.hospitals.count { canTransportNow(it) }
                    Text(if (confirmed != null) "이송 확정 · ${confirmed.name}" else "${r.hospitals.size}곳 · 승인 ${ok}곳", fontSize = 12.sp,
                        color = if (confirmed != null) AD.green else AD.ink3, fontWeight = if (confirmed != null) FontWeight.Bold else FontWeight.Normal)
                }
                Text(if (m.inTransport) "이송 중에도 새로 승인한 병원이 있으면 다시 고를 수 있습니다." else "병원이 수용을 승인하면 [이송 승인]이 열립니다. 순서는 hub가 정한 그대로입니다.",
                    fontSize = 11.5.sp, color = AD.sub)
            }
        }
        items(r.hospitals, key = { it.hospitalId }) { h ->
            CandidateCard(m, h, recommended = confirmed == null && h.hospitalId == r.hospitals.firstOrNull { canTransportNow(it) }?.hospitalId, now = now)
        }
        item { Spacer(Modifier.height(8.dp)) }
    }
}

/** 병원 한 곳 — 이름·거리·ETA·상태 | 병상·AI 유효·전문의 | 칩 | 정보 유효성 | [이송 승인] */
@Composable
private fun CandidateCard(m: PhoneModel, h: MatchHospital, recommended: Boolean, now: Long) {
    val confirmedHere = m.confirmed?.hospitalId == h.hospitalId
    val requesting = m.pendingConfirmId == h.hospitalId && !confirmedHere
    val unavailable = h.status == "pending" && h.unavailableReason != null
    val statusKey = if (unavailable) "rejected" else h.status
    val live = h.bedReliability?.let { BedLive.of(it, now) }

    Card(modifier = Modifier.alpha(if (statusKey == "rejected" && !confirmedHere) 0.72f else 1f),
        border = if (confirmedHere) AD.green else if (recommended) approveColor else AD.control,
        borderWidth = if (confirmedHere) 3.dp else if (recommended) 2.dp else 1.dp) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(h.name, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy, maxLines = 2)
                    Text(distanceText(h), fontSize = 12.sp, color = AD.ink3)
                }
                Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (recommended) Pill("추천", approveColor, AD.orangeSoft, bold = true)
                    val (fg, bg) = statusColors(statusKey)
                    Pill(statusText(h, requesting, confirmedHere, unavailable), fg, bg, bold = true)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BedBox(h, Modifier.weight(1f))
                if (live != null) {
                    val (fg, bg) = validityColors(live.rArrive)
                    StatBox("AI 유효", BedLive.pct(live.rArrive) + if (h.bedReliability?.confirmedAgeSec != null) " ✓" else "", fg, bg, Modifier.weight(1f))
                } else StatBox("AI 유효", "—", AD.ink3, AD.chip, Modifier.weight(1f))
                StatBox("전문의", h.specialtyMatch?.doctorCount?.let { "${it}명" } ?: "—", AD.ink3, AD.chip, Modifier.weight(1f), valueColor = AD.navy)
            }
            val chips = chipsOf(h)
            if (chips.isNotEmpty()) {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    chips.forEach { (text, fg, bg) -> Pill(text, fg, bg) }
                }
            }
            ValidityLine(h, live)
            ActionButton(m, h, confirmedHere, requesting, statusKey)
        }
    }
}

private fun distanceText(h: MatchHospital): String {
    val dist = h.roadDistanceKm?.let { "%.1fkm".format(it) } ?: "직선 %.1fkm".format(h.distanceKm)
    val eta = h.etaMin
    val travel = h.travelMin
    return when {
        eta != null -> "$dist · ETA ${eta.roundToInt()}분"
        travel != null -> "$dist · 약 ${travel.roundToInt()}분(직선 추정)"
        else -> dist
    }
}

private fun statusText(h: MatchHospital, requesting: Boolean, confirmed: Boolean, unavailable: Boolean): String = when {
    requesting -> "확정 요청 중"
    unavailable -> "수용 불가 · ${DisplayLabels.reject(h.unavailableReason)}"
    h.status == "rejected" && h.rejectReason != null -> "수용 불가 · ${DisplayLabels.reject(h.rejectReason)}"
    else -> DisplayLabels.status(h.status)
}

/** 병원 상태 알약 색 — 판단 대기 주황 · 후보 등록 파랑 · 수용 불가 빨강 · 이송 확정 초록 */
private fun statusColors(s: String): Pair<Color, Color> = when (s) {
    "approved" -> AD.blue to AD.blueSoft
    "rejected" -> AD.red to AD.redSoft
    "confirmed" -> AD.green to AD.greenSoft
    else -> AD.orange to AD.orangeSoft
}

/** 도착 시 유효 확률 색 — 80% 이상 파랑(믿고 출발) · 50~80 회색(참고) · 50 미만 빨강(재확인 권장) */
private fun validityColors(p: Double): Pair<Color, Color> = when {
    p >= 0.8 -> AD.blue to AD.blueSoft
    p >= 0.5 -> AD.ink3 to AD.chip
    else -> AD.red to AD.redSoft
}

/** 병상 칸 — 미상을 0이나 "없음"으로 보이면 안 된다: 미상은 회색, 확인된 만실만 빨강 */
@Composable
private fun BedBox(h: MatchHospital, modifier: Modifier) {
    val cap = h.erBedCapacity?.let { "/$it" } ?: ""
    val avail = h.availableBedCount ?: 0
    when {
        h.bedCountUnknown == true -> StatBox("병상", "미상", AD.ink3, AD.chip, modifier)
        avail <= 0 -> StatBox(h.erOccupancyPct?.let { "병상 · $it%" } ?: "병상", if (h.erBedCapacity != null) "0$cap" else "없음", AD.red, AD.redSoft, modifier)
        else -> StatBox(listOfNotNull(if (h.bedDataStale == true) "병상 · 1일↑" else "병상", h.erOccupancyPct?.let { "$it%" }).joinToString(" · "),
            if (h.erBedCapacity != null) "$avail$cap" else "${avail}석", AD.lime, AD.limeSoft, modifier)
    }
}

/** 칩은 중요한 것부터 — 수용 불가 신고·차단 메시지·진료과 일치·이송 중 건수·센터 등급 */
private fun chipsOf(h: MatchHospital): List<Triple<String, Color, Color>> {
    val out = mutableListOf<Triple<String, Color, Color>>()
    if (h.demoteReasons?.contains("declared_no") == true) out += Triple("수용 불가 신고", AD.red, AD.redSoft)
    if (h.demoteReasons?.contains("severe_blocked") == true) out += Triple("병원 차단 메시지", AD.red, AD.redSoft)
    h.specialtyMatch?.let { sm ->
        val pct = ((sm.score ?: 0.0) * 100).roundToInt()
        out += when {
            sm.department == null -> Triple("진료과 정보 미상", AD.ink3, AD.chip)
            sm.basis != "exact" && (sm.score ?: 0.0) < 0.3 -> Triple("${sm.department} · 적합도 낮음 $pct%", AD.ink3, AD.chip)
            else -> Triple("${sm.department} · ${if (sm.basis == "exact") "필요 진료과 일치" else "적합도 $pct%"}", AD.blue, AD.blueSoft)
        }
    }
    h.inFlightCount?.takeIf { it > 0 }?.let { n ->
        out += Triple("이송 중 ${n}건" + (h.loadPenaltyMin?.takeIf { it > 0 }?.let { " · +${if (it % 1.0 == 0.0) it.toInt().toString() else "%.1f".format(it)}분" } ?: ""), AD.orange, AD.orangeSoft)
    }
    h.emergencyLevel?.takeIf { it.endsWith("센터") }?.let { out += Triple(it, AD.ink3, AD.chip) }
    return out
}

/** 정보 유효성 — 지금 / 도착 시 확률과 "왜"를 한 줄로: 정보 나이 · 도착까지 이동 · 병원 확인 · 1일 넘은 값 */
@Composable
private fun ValidityLine(h: MatchHospital, live: BedLive.Live?) {
    val br = h.bedReliability
    if (live == null || br == null) {
        Text(if (h.bedCountUnknown == true) "AI · 병상 미상 — 유효 확률을 내지 않습니다" else "AI · 병상 신뢰도 정보 없음", fontSize = 11.5.sp, color = AD.sub)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("AI · 병상 정보 지금 유효", fontSize = 11.5.sp, color = AD.sub)
            Text(BedLive.pct(live.authority), fontSize = 11.5.sp, fontWeight = FontWeight.Bold, color = validityColors(live.authority).first)
            Text("→ 도착 시", fontSize = 11.5.sp, color = AD.sub)
            Text(BedLive.pct(live.rArrive), fontSize = 11.5.sp, fontWeight = FontWeight.Bold, color = validityColors(live.rArrive).first)
        }
        // 가로 확률 막대
        Box(Modifier.fillMaxWidth().height(5.dp).clip(CircleShape).background(AD.line)) {
            Box(Modifier.fillMaxWidth(live.rArrive.coerceIn(0.0, 1.0).toFloat()).height(5.dp).clip(CircleShape).background(validityColors(live.rArrive).first))
        }
        val parts = mutableListOf<String>()
        live.ageSec?.let { parts += "정보 ${DisplayLabels.age(it)}" }
        parts += "도착까지 ${DisplayLabels.minutes(br.horizonSec)}"
        if (br.confirmedAgeSec != null) parts += "병원 확인 ✓"
        if (h.bedDataStale == true) parts += "⚠ 1일 넘은 값"
        Text(parts.joinToString(" · "), fontSize = 11.sp, color = AD.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun ActionButton(m: PhoneModel, h: MatchHospital, confirmedHere: Boolean, requesting: Boolean, statusKey: String) {
    val approvable = h.status == "approved" || h.status == "confirmed"
    @Composable
    fun big(text: String, bg: Color, fg: Color, onClick: (() -> Unit)? = null) {
        Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp)).background(bg)
            .let { if (onClick != null) it.clickable(onClick = onClick) else it },
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Text(text, color = fg, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
    }
    when {
        confirmedHere -> big("이송 확정됨", AD.greenSoft, AD.green)
        requesting -> big("확정 요청 중…", AD.orangeSoft, approveColor)
        approvable -> big("이송 승인", if (m.paused) AD.gray else approveColor, Color.White, onClick = if (m.paused) null else ({ m.approve(h.hospitalId) }))
        else -> big(if (h.excluded == true) "이 사건에서 제외됨" else if (statusKey == "rejected") "수용 불가" else "병원 응답 대기", AD.chip, AD.muted)
    }
}

/** 아래 탭 — [통화 | 환자 정보 | 이송]. 이송 칸엔 병원 응답 배지(승인 수, 없으면 후보 수)를 붙여 다른 탭에서도 응답이 온 걸 안다 */
@Composable
fun TabBar(m: PhoneModel) {
    val r = m.result
    val badge: Pair<String, Color>? = when {
        r == null -> m.scene?.let { it.hospitals.size.toString() to AD.gray }
        m.confirmed != null -> "확정" to AD.green
        else -> r.hospitals.count { canTransportNow(it) }.let { ok -> if (ok > 0) "승인 $ok" to AD.green else r.hospitals.size.toString() to AD.orange }
    }
    Row(Modifier.fillMaxWidth().clip(CircleShape).background(AD.chip).padding(3.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        for ((tab, title) in listOf(PhoneModel.Tab.CALL to "통화", PhoneModel.Tab.PATIENT to "환자 정보", PhoneModel.Tab.TRANSPORT to "이송", PhoneModel.Tab.RECORDS to "기록")) {
            val on = m.tab == tab
            Row(Modifier.weight(1f).heightIn(min = 38.dp).clip(CircleShape).background(if (on) AD.white else Color.Transparent)
                .clickable { m.tab = tab }, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Text(title, fontSize = 13.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium, color = if (on) AD.navy else AD.ink3, maxLines = 1)
                if (tab == PhoneModel.Tab.TRANSPORT && badge != null) {
                    Text(badge.first, color = Color.White, fontSize = 10.5.sp, fontWeight = FontWeight.Bold, maxLines = 1,
                        modifier = Modifier.padding(start = 5.dp).clip(CircleShape).background(badge.second).padding(horizontal = 6.dp, vertical = 1.dp))
                }
            }
        }
    }
}
