package xyz.goldenlink.phone.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.automirrored.filled.PhoneCallback
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.AddIcCall
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.SceneCandidate
import xyz.goldenlink.phone.CallSession
import xyz.goldenlink.phone.HubSocket
import xyz.goldenlink.phone.PhoneModel
import kotlin.math.PI
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.sin

// 화면 디자인 — 아이폰 앱(dashboard/iphone/GoldenLinkPhone/Views.swift)과 같은 색·카드 언어·화면 순서:
// 연회색 바탕 + 흰 카드(둥근 18) · 남색 글자 · 알약 칩 · 병상/AI 유효/전문의 세 칸 · AI(파랑)와 규칙(회색) 출처 구분.
// 화면 순서: 통화 중 > 통화 끝(전송 처리) > 다른 기기 통화 중 > 현장(병원 목록 / 전달됨 · 추가 통화) > 이송 중(목적지 병원과 통화) > 대기·출동

/** 디자인 색 (dashboard/src/components/ambulance/ambulance-design.ts와 같은 값) */
object AD {
    val bg = Color(0xFFF4F6FA)
    val line = Color(0xFFE3E7EE)
    val control = Color(0xFFD3D9E3)
    val ink = Color(0xFF1B2430)
    val navy = Color(0xFF14213D)
    val ink3 = Color(0xFF4A5565)
    val sub = Color(0xFF5A6676)
    val muted = Color(0xFF7A8594)
    val chip = Color(0xFFF1F3F6)
    val blue = Color(0xFF1F4E9C)
    val blueSoft = Color(0xFFE8EEF8)
    val green = Color(0xFF168A55)
    val greenSoft = Color(0xFFE3F3EB)
    val lime = Color(0xFF4E8B1F)
    val limeSoft = Color(0xFFEEF5E6)
    val orange = Color(0xFFC75B00)
    val orangeSoft = Color(0xFFFFF1E0)
    val red = Color(0xFFD93025)
    val redSoft = Color(0xFFFDECEA)
    val gray = Color(0xFF9AA3B0)
    val white = Color.White
}

private val cardShape = RoundedCornerShape(18.dp)

// ── 공용 조각 ──

@Composable
fun Pill(text: String, fg: Color = AD.ink3, bg: Color = AD.chip, bold: Boolean = false) {
    Text(text, color = fg, fontSize = 11.sp, fontWeight = if (bold) FontWeight.Bold else FontWeight.Medium, maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.clip(CircleShape).background(bg).padding(horizontal = 9.dp, vertical = 3.dp))
}

@Composable
fun Card(border: Color = AD.line, borderWidth: Dp = 1.dp, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier.fillMaxWidth().clip(cardShape).background(AD.white).border(borderWidth, border, cardShape).padding(14.dp),
        content = content,
    )
}

/** 병상 · AI 유효 · 전문의 한 칸(대시보드 후보 카드와 같은 모양) */
@Composable
fun StatBox(label: String, value: String, fg: Color, bg: Color, modifier: Modifier = Modifier, valueColor: Color? = null) {
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(bg).padding(horizontal = 10.dp, vertical = 6.dp)) {
        Text(label, color = fg, fontSize = 11.sp, fontWeight = FontWeight.Medium)
        Text(value, color = valueColor ?: fg, fontSize = 19.sp, fontWeight = FontWeight.Black, maxLines = 1)
    }
}

@Composable
fun Dot(color: Color, size: Dp = 8.dp) = Box(Modifier.size(size).clip(CircleShape).background(color))

@Composable
private fun pulseAlpha(active: Boolean): Float {
    if (!active) return 1f
    val t = rememberInfiniteTransition(label = "pulse")
    val a by t.animateFloat(1f, 0.35f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    return a
}

/** 구급대 단계 색 — 관제 지도 구급차 마커 색과 같은 규칙(대기 회색 · 출동 주황 · 현장 빨강 · 이송 파랑 · 병원 초록) */
fun phaseColor(phase: AmbulancePhase): Color = when (phase) {
    AmbulancePhase.idle -> AD.gray
    AmbulancePhase.dispatching -> AD.orange
    AmbulancePhase.on_scene -> AD.red
    AmbulancePhase.transporting -> AD.blue
    AmbulancePhase.at_hospital, AmbulancePhase.rerouting -> AD.green
    AmbulancePhase.returning -> AD.sub
}

fun mmss(sec: Long): String {
    val t = max(0L, sec)
    return "%02d:%02d".format(t / 60, t % 60)
}

/** 1초마다 바뀌는 지금 시각(통화 시간·대기 시간 표시용) */
@Composable
fun nowEverySecond(): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(1000); now = System.currentTimeMillis() } }
    return now
}

// ── 루트 ──

@Composable
fun PhoneApp(m: PhoneModel) {
    var showSettings by remember { mutableStateOf(false) }
    MaterialTheme(colorScheme = lightColorScheme(primary = AD.blue, background = AD.bg, surface = AD.white)) {
        Box(Modifier.fillMaxSize().background(AD.bg)) {
            Column(Modifier.fillMaxSize().safeDrawingPadding().padding(horizontal = 16.dp).padding(top = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Header(m) { showSettings = true }
                Box(Modifier.weight(1f).fillMaxWidth()) { Content(m) }
                Footer(m)
            }
            // 일시정지 등 잠깐 뜨는 안내
            AnimatedVisibility(m.notice != null, Modifier.align(Alignment.TopCenter).safeDrawingPadding().padding(top = 8.dp),
                enter = slideInVertically() + fadeIn(), exit = slideOutVertically() + fadeOut()) {
                Row(Modifier.clip(CircleShape).background(AD.navy).padding(horizontal = 18.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Filled.PauseCircle, null, tint = Color(0xFFFFB86B))
                    Text(m.notice ?: "", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
        if (showSettings) SettingsDialog(m) { showSettings = false }
        m.error?.let { e ->
            AlertDialog(onDismissRequest = { m.error = null }, confirmButton = { TextButton({ m.error = null }) { Text("확인") } },
                title = { Text("알림") }, text = { Text(e) })
        }
    }
}

@Composable
private fun Header(m: PhoneModel, onSettings: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(cardShape).background(AD.white).border(1.dp, AD.line, cardShape)
        .padding(horizontal = 14.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(buildAnnotatedString {
                withStyle(SpanStyle(color = AD.navy)) { append("골든") }
                withStyle(SpanStyle(color = AD.blue)) { append("링크") }
            }, fontSize = 19.sp, fontWeight = FontWeight.Black)
            Pill("v2.0", AD.blue, AD.blueSoft, bold = true)
            Spacer(Modifier.weight(1f))
            ConnectionDot(m.connection)
            val inCall = m.call != null && m.call?.phase != PhoneModel.LocalCall.Phase.ENDED
            Box(Modifier.size(36.dp).clip(CircleShape).background(AD.chip).clickable(enabled = !inCall, onClick = onSettings),
                contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Settings, "설정", tint = AD.ink3, modifier = Modifier.size(18.dp))
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Pill(m.identity?.name ?: m.apid ?: (if (m.autoFollow) "자동 전환 대기" else "구급대 미지정"), AD.ink3, AD.white, bold = true)
            m.mySim?.let { Pill(it.phaseEnum.label, phaseColor(it.phaseEnum), phaseColor(it.phaseEnum).copy(alpha = 0.12f), bold = true) }
            Spacer(Modifier.weight(1f))
            Text("전화 앱", fontSize = 11.sp, color = AD.muted)
        }
    }
}

@Composable
private fun Footer(m: PhoneModel) {
    Column(Modifier.fillMaxWidth().padding(bottom = 4.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Legend(AD.blue, "AI 처리"); Legend(AD.gray, "규칙 기반 · API"); Legend(AD.orange, "판단은 사람")
        }
        if (m.modelStatus.isNotEmpty()) Text(m.modelStatus, fontSize = 10.5.sp, color = AD.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun Legend(color: Color, text: String) = Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
    Dot(color); Text(text, fontSize = 10.5.sp, color = AD.ink3)
}

@Composable
private fun Content(m: PhoneModel) {
    val call = m.call
    val status = m.status
    when {
        call != null && call.phase != PhoneModel.LocalCall.Phase.ENDED -> InCallView(m, call)
        call?.phase == PhoneModel.LocalCall.Phase.ENDED -> EndedView(m)
        status != null && status.state == "calling" -> StatusPanel(Icons.Filled.Phone, AD.green,
            "${if (status.device == "phone") "다른 휴대폰" else "구급차 대시보드"}에서 통화 중",
            "${status.hospitalName ?: "병원"}과 통화하고 있습니다. 통화가 끝나면 다시 걸 수 있습니다.")
        m.onScene -> if (m.sent && !m.wantsExtraCall) SentView(m) else HospitalListView(m)
        m.inTransport -> TransportCallView(m)
        else -> Waiting(m)
    }
}

@Composable
private fun Waiting(m: PhoneModel) {
    when {
        m.apid == null -> StatusPanel(Icons.Filled.Phone, AD.blue, "출동 대기 중", "상황이 발생하면 출동하는 구급대의 전화 앱으로 자동 전환됩니다.")
        m.identity != null && !m.simOn -> StatusPanel(Icons.Filled.DirectionsCar, AD.gray, "출동 시뮬레이션이 꺼져 있습니다",
            "휴대폰 전화 앱은 출동 시뮬레이션에서만 씁니다.")
        else -> {
            val phase = m.mySim?.phaseEnum ?: AmbulancePhase.idle
            val eta = m.mySim?.etaSec?.let { max(1, ceil(it / 60).toInt()) }
            StatusPanel(if (phase == AmbulancePhase.dispatching) Icons.Filled.LocalShipping else Icons.Filled.DirectionsCar,
                phaseColor(phase), phase.label,
                (if (phase == AmbulancePhase.dispatching && eta != null) "현장까지 약 ${eta}분 (실제 도로 기준)\n" else "") +
                    "현장에 도착하면 전화할 병원 목록이 여기에 뜹니다. 출동은 구급차 대시보드에서 합니다.",
                pulse = phase == AmbulancePhase.dispatching)
        }
    }
}

// ── 병원 목록 (현장 도착 뒤) ──

@Composable
private fun HospitalListView(m: PhoneModel) {
    val all = m.scene?.hospitals ?: emptyList()
    // 추천 병원을 맨 위로, 나머지는 hub가 보낸 도착 시간순 그대로
    val ordered = all.filter { it.firstCallRecommended == true } + all.filter { it.firstCallRecommended != true }
    if (all.isEmpty()) {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = AD.blue)
            Spacer(Modifier.height(10.dp))
            Text("병원 목록을 받는 중…", fontSize = 13.sp, color = AD.sub)
        }
        return
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Column(Modifier.padding(horizontal = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("전화할 병원", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    Text("도착 시간순 · ${all.size}곳", fontSize = 12.sp, color = AD.ink3)
                    Spacer(Modifier.weight(1f))
                    Pill("규칙 기반")
                }
                Text(if (m.wantsExtraCall) "추가 통화 — 바뀐 환자 상태를 말하면 기존 환자 정보에 덧붙여 후보 병원에 다시 전달됩니다."
                    else "한 곳과 통화하면 그 내용이 후보 병원 전체에 동시에 전달됩니다.", fontSize = 11.5.sp, color = AD.sub)
                if (m.wantsExtraCall) Text("추가 통화 닫기", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.ink3,
                    modifier = Modifier.padding(top = 2.dp).clickable { m.wantsExtraCall = false })
            }
        }
        m.scene?.reportedSymptom?.let { symptom ->
            item {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.orangeSoft).padding(horizontal = 12.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.AutoMirrored.Filled.PhoneCallback, null, tint = AD.orange, modifier = Modifier.size(18.dp))
                    Text(buildAnnotatedString {
                        withStyle(SpanStyle(color = AD.ink3)) { append("신고 내용: ") }
                        withStyle(SpanStyle(color = AD.navy, fontWeight = FontWeight.Bold)) { append(symptom) }
                    }, fontSize = 13.sp, modifier = Modifier.weight(1f))
                    Text("현장과 다를 수 있음", fontSize = 10.5.sp, color = AD.muted)
                }
            }
        }
        if (m.sceneCallBlocked) {
            item {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.orangeSoft).padding(horizontal = 12.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Filled.Lock, null, tint = AD.orange, modifier = Modifier.size(18.dp))
                    Text(buildAnnotatedString {
                        append("시연 콘솔이 ")
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("정해진 상황 선택") }
                        append(" 중이라 전화를 걸 수 없습니다. 콘솔에서 ")
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("음성으로 확인") }
                        append("을 고르면 전화할 수 있습니다.")
                    }, fontSize = 13.sp, color = AD.navy, modifier = Modifier.weight(1f))
                }
            }
        }
        items(ordered, key = { it.hospitalId }) { h -> HospitalCard(h, enabled = !m.sceneCallBlocked) { m.dial(h) } }
        item { Spacer(Modifier.height(8.dp)) }
    }
}

@Composable
private fun HospitalCard(h: SceneCandidate, enabled: Boolean = true, onCall: () -> Unit) {
    val recommended = h.firstCallRecommended == true
    Card(modifier = Modifier.alpha(if (enabled) 1f else 0.45f), border = if (recommended) AD.green else AD.control, borderWidth = if (recommended) 2.dp else 1.dp) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(h.name, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy, maxLines = 2)
                    Text(distanceText(h), fontSize = 12.sp, color = AD.ink3)
                }
                if (recommended) Pill("첫 연락 추천", AD.green, AD.greenSoft, bold = true) else Pill("통화 전", bold = true)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // 미상을 0이나 "없음"으로 보이면 안 된다(대시보드와 같은 원칙) — 미상은 회색, 확인된 만실만 빨강
                when {
                    h.bedCountUnknown -> StatBox("병상", "미상", AD.ink3, AD.chip, Modifier.weight(1f))
                    h.availableBedCount <= 0 -> StatBox("병상", "없음", AD.red, AD.redSoft, Modifier.weight(1f))
                    else -> StatBox("병상", "${h.availableBedCount}석", AD.lime, AD.limeSoft, Modifier.weight(1f))
                }
                // 도착 시 유효 확률(AI) — ≥80% 파랑, 50~80% 회색, <50% 빨강
                val p = h.bedReliability?.rArrive
                if (p == null) {
                    StatBox("AI 유효", "—", AD.ink3, AD.chip, Modifier.weight(1f))
                } else {
                    val (fg, bg) = when { p >= 0.8 -> AD.blue to AD.blueSoft; p >= 0.5 -> AD.ink3 to AD.chip; else -> AD.red to AD.redSoft }
                    StatBox("AI 유효", "${(p * 100).roundToInt()}%", fg, bg, Modifier.weight(1f))
                }
                val doctors = (h.specialties ?: emptyList()).sumOf { it.doctorCount }
                StatBox("전문의", if (doctors > 0) "${doctors}명" else "—", AD.ink3, AD.chip, Modifier.weight(1f), valueColor = AD.navy)
            }
            val specialties = h.specialties ?: emptyList()
            if (h.emergencyLevel != null || specialties.isNotEmpty()) {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    h.emergencyLevel?.takeIf { it.endsWith("센터") }?.let { Pill(it) }
                    specialties.take(4).forEach { Pill("${it.department} ${it.doctorCount}", AD.blue, AD.blueSoft) }
                }
            }
            Row(Modifier.fillMaxWidth().heightIn(min = 46.dp).clip(RoundedCornerShape(14.dp)).background(if (recommended) AD.green else AD.blue)
                .clickable(enabled = enabled, onClick = onCall), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Call, null, tint = Color.White, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("전화 걸기", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

private fun distanceText(h: SceneCandidate): String {
    val road = h.roadDistanceKm
    val dist = if (road != null) "%.1fkm".format(road) else "직선 %.1fkm".format(h.distanceKm)
    return h.etaMin?.let { "$dist · ETA ${it.roundToInt()}분" } ?: dist
}

// ── 통화 중 ──

@Composable
private fun InCallView(m: PhoneModel, call: PhoneModel.LocalCall) {
    val connecting = call.phase == PhoneModel.LocalCall.Phase.CONNECTING
    val now = nowEverySecond()
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Card {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(Modifier.clip(CircleShape).background(if (connecting) AD.orangeSoft else AD.redSoft).padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(Modifier.alpha(pulseAlpha(true))) { Dot(if (connecting) AD.orange else AD.red) }
                    Text(if (connecting) "연결 중…" else if (call.followup) "추가 통화 중" else "통화 중", fontSize = 12.sp,
                        fontWeight = FontWeight.Bold, color = if (connecting) AD.orange else AD.red)
                }
                Text(call.hospitalName, fontSize = 22.sp, fontWeight = FontWeight.Black, color = AD.navy, textAlign = TextAlign.Center)
                // 이송 중 추가 통화 — 통화 내용을 듣고 정보가 반영될 때까지 이동이 잠시 멈춘다
                if (m.transportHeld) Pill("이송 잠시 멈춤 · 통화 내용 반영 뒤 다시 출발", AD.blue, AD.blueSoft, bold = true)
                Text(if (connecting) "응급실 연결 중" else mmss((now - call.startedAt) / 1000), fontSize = 30.sp, fontWeight = FontWeight.Bold,
                    color = if (connecting) AD.muted else AD.ink)
                LevelMeter(m.session?.level ?: 0f, active = !connecting)
            }
        }
        Card(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("실시간 자막", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                Spacer(Modifier.weight(1f))
                Pill("AI · Qwen3-ASR", AD.blue, AD.blueSoft)
            }
            Spacer(Modifier.height(8.dp))
            val lines = m.transcriptLines
            val state = rememberLazyListState()
            LaunchedEffect(lines.size) { if (lines.isNotEmpty()) state.animateScrollToItem(lines.size - 1) }
            if (lines.isEmpty()) {
                Text(if (connecting) "곧 연결됩니다." else "말이 끊길 때마다 인식된 문장이 여기에 뜹니다.", fontSize = 13.sp, color = AD.muted)
            }
            LazyColumn(state = state, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(lines) { _, line ->
                    Text(line, fontSize = 14.sp, color = AD.ink, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                        .background(AD.bg).padding(horizontal = 10.dp, vertical = 7.dp))
                }
            }
        }
        // [취소]는 아무것도 보내지 않고, [전송]을 눌러야만 음성을 처리해 병원에 보낸다
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(AD.redSoft).border(2.dp, AD.red, cardShape)
                .clickable { m.cancelCall() }, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Cancel, null, tint = AD.red, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(10.dp))
                Text("취소", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = AD.red)
            }
            Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(if (connecting) AD.control else AD.blue)
                .clickable(enabled = !connecting) { m.sendCall() }, horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.AutoMirrored.Filled.Send, null, tint = Color.White, modifier = Modifier.size(26.dp))
                Spacer(Modifier.width(10.dp))
                Text("전송", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
        Text("취소하면 아무것도 전달되지 않습니다 · 전송을 눌러야 기기에서 음성을 인식·구조화해 병원에 보냅니다",
            fontSize = 10.5.sp, color = AD.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

/** 음성 레벨 막대(마이크 입력 크기 — 통화 시연 패널 파형과 같은 느낌) */
@Composable
private fun LevelMeter(level: Float, active: Boolean) {
    val shown by animateFloatAsState(if (active) max(0.12f, level.coerceIn(0f, 1f)) else 0.12f, tween(120), label = "level")
    val count = 24
    Row(Modifier.height(36.dp), horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
        repeat(count) { i ->
            // 가운데가 높은 고정 모양 × 지금 음량
            val shape = 0.35f + 0.65f * sin(i.toFloat() / (count - 1) * PI.toFloat())
            Box(Modifier.width(4.dp).height(max(4f, 34f * shape * shown).dp).clip(CircleShape)
                .background(if (active) AD.red.copy(alpha = 0.75f) else AD.control))
        }
    }
}

// ── 통화 종료 뒤 ──

@Composable
private fun EndedView(m: PhoneModel) {
    val stage = m.session?.stage
    val sent: Int? = if (m.delivered) m.caseId?.let { m.sentCount[it] } else null
    val hospital = m.call?.hospitalName ?: "병원"
    val followup = m.call?.followup == true
    val now = nowEverySecond()
    // 서버 음성 인식(모델 없음)은 결과가 hub 매칭으로만 온다 — 90초 넘게 안 오면 말이 인식되지 않은 것으로 본다
    val serverWaitOver = !m.models.ready || !m.settings.onDevice || m.session == null || stage == CallSession.Stage.Sent
    val timedOut = sent == null && serverWaitOver && (m.call?.endedAt?.let { now - it > 90_000 } ?: false)
    val failed = stage is CallSession.Stage.Failed
    val finished = sent != null || timedOut || stage == CallSession.Stage.NoSpeech || failed
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        Card(border = if (sent != null) AD.green else AD.line, borderWidth = if (sent != null) 2.dp else 1.dp) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(if (sent != null) Icons.Filled.CheckCircle else Icons.Filled.GraphicEq, null,
                        tint = if (sent != null) AD.green else AD.blue, modifier = Modifier.size(28.dp).alpha(pulseAlpha(sent == null)))
                    Column {
                        Text(when {
                            sent != null -> if (followup) "환자 정보에 덧붙여 ${sent}곳에 전달됐습니다" else "후보 병원 ${sent}곳에 전달됐습니다"
                            timedOut -> "전달되지 않았습니다"
                            else -> stageTitle(stage)
                        }, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                        Text("${if (followup) "추가 통화" else "통화"}: $hospital", fontSize = 12.sp, color = AD.sub)
                    }
                }
                // 진행 단계 — 음성 인식(AI) → 구조화(AI) → 병원 전달(규칙)
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    StepRow("남은 음성 인식", "AI", stepState(0, stage, sent))
                    StepRow("환자 정보 구조화 (MF_BERT)", "AI", stepState(1, stage, sent))
                    StepRow("존 안 후보 병원에 동시 전달", "규칙", stepState(2, stage, sent))
                }
                if (stage is CallSession.Stage.Failed) Text(stage.reason, fontSize = 12.sp, color = AD.red)
                if (timedOut) Text("인식된 말이 없었거나 음성 인식 서버에 닿지 않았습니다. 다시 걸 수 있습니다.", fontSize = 12.sp, color = AD.red)
                HorizontalDivider(color = AD.line)
                Text("병원 응답 확인·이송 승인은 구급차 대시보드에서 합니다.", fontSize = 12.sp, color = AD.sub)
                if (finished) {
                    Box(Modifier.fillMaxWidth().height(46.dp).clip(RoundedCornerShape(14.dp)).background(AD.blue).clickable { m.dismissEnded() },
                        contentAlignment = Alignment.Center) {
                        Text(if (sent != null) "확인" else "확인 · 다시 걸기", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

private fun stageTitle(s: CallSession.Stage?): String = when (s) {
    CallSession.Stage.Finishing -> "남은 음성을 인식하는 중…"
    CallSession.Stage.Structuring -> "환자 정보를 구조화하는 중…"
    CallSession.Stage.NoSpeech -> "인식된 말이 없어 전달하지 않았습니다"
    is CallSession.Stage.Failed -> "전달하지 못했습니다"
    else -> "환자 정보를 정리하는 중…"
}

private enum class Step { PENDING, ACTIVE, DONE, FAILED }

/** 0 인식 · 1 구조화 · 2 전달. 서버 STT 모드(모델 없음)는 hub의 매칭 결과(sent)만으로 판단한다 */
private fun stepState(index: Int, stage: CallSession.Stage?, sent: Int?): Step {
    if (sent != null) return Step.DONE
    return when (stage) {
        is CallSession.Stage.Failed, CallSession.Stage.NoSpeech, CallSession.Stage.Cancelled -> if (index == 0) Step.DONE else Step.FAILED
        CallSession.Stage.Finishing -> if (index == 0) Step.ACTIVE else Step.PENDING
        CallSession.Stage.Structuring -> when (index) { 0 -> Step.DONE; 1 -> Step.ACTIVE; else -> Step.PENDING }
        CallSession.Stage.Sent -> if (index < 2) Step.DONE else Step.ACTIVE
        else -> if (index == 0) Step.ACTIVE else Step.PENDING
    }
}

@Composable
private fun StepRow(title: String, source: String, state: Step) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(20.dp), contentAlignment = Alignment.Center) {
            when (state) {
                Step.DONE -> Icon(Icons.Filled.CheckCircle, null, tint = AD.green)
                Step.ACTIVE -> CircularProgressIndicator(color = AD.blue, strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                Step.FAILED -> Icon(Icons.Filled.Cancel, null, tint = AD.red)
                Step.PENDING -> Box(Modifier.size(18.dp).clip(CircleShape).border(2.dp, AD.control, CircleShape))
            }
        }
        Text(title, fontSize = 13.sp, fontWeight = if (state == Step.ACTIVE) FontWeight.Bold else FontWeight.Normal,
            color = if (state == Step.PENDING) AD.muted else AD.ink, modifier = Modifier.weight(1f))
        Pill(source, if (source == "AI") AD.blue else AD.ink3, if (source == "AI") AD.blueSoft else AD.chip)
    }
}

// ── 현장: 전달됨 · 추가 통화 ──

@Composable
private fun SentView(m: PhoneModel) {
    val n = m.caseId?.let { m.sentCount[it] } ?: 0
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        Card(border = AD.green, borderWidth = 2.dp) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Filled.CheckCircle, null, tint = AD.green, modifier = Modifier.size(28.dp))
                    Column {
                        Text("후보 병원 ${n}곳에 전달됐습니다", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                        Text("병원 응답 확인·이송 승인은 구급차 대시보드에서 합니다", fontSize = 12.sp, color = AD.sub)
                    }
                }
                HorizontalDivider(color = AD.line)
                Text("환자 상태가 바뀌었으면 다시 통화하세요. 새 통화 내용은 기존 환자 정보에 덧붙여 전달됩니다.", fontSize = 12.5.sp, color = AD.ink3)
                Row(Modifier.fillMaxWidth().height(46.dp).clip(RoundedCornerShape(14.dp)).background(AD.blueSoft).clickable { m.wantsExtraCall = true },
                    horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.AddIcCall, null, tint = AD.blue, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("추가 통화", color = AD.blue, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

// ── 이송 중: 목적지 병원과 통화 ──

/** 이송 중 환자 상태가 바뀌면 목적지 병원과 다시 통화한다. 새 요약은 환자 정보에 덧붙어 병원 화면에 반영되고,
 *  병원이 받을 수 없게 되면 병원 대시보드의 [이송 중 수용 철회]로 확정이 풀려 구급차는 다른 병원으로 재선택한다. */
@Composable
private fun TransportCallView(m: PhoneModel) {
    val rerouting = m.phase == AmbulancePhase.rerouting
    val dest = m.destination
    val eta = m.mySim?.etaSec?.let { max(1, ceil(it / 60).toInt()) }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        Card(border = if (rerouting) AD.red else AD.line, borderWidth = if (rerouting) 2.dp else 1.dp) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Pill(if (rerouting) "재선택 대기" else "병원 이송 중", if (rerouting) AD.red else AD.blue, if (rerouting) AD.redSoft else AD.blueSoft, bold = true)
                    when {
                        m.transportHeld -> Text("통화 내용 반영 중 — 이송 잠시 멈춤", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.blue)
                        !rerouting && eta != null -> Text("도착까지 약 ${eta}분", fontSize = 12.sp, color = AD.sub)
                    }
                }
                if (rerouting) {
                    Text("목적지 병원이 수용할 수 없게 됐습니다", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    Text("구급차 대시보드에서 승인한 다른 병원을 이송 승인하세요. 승인 병원이 없으면 범위를 넓혀 다시 요청합니다.",
                        fontSize = 12.5.sp, color = AD.ink3)
                } else {
                    Column {
                        Text("목적지 병원", fontSize = 11.5.sp, color = AD.sub)
                        Text(dest?.name ?: "확정 병원", fontSize = 20.sp, fontWeight = FontWeight.Black, color = AD.navy)
                    }
                    Text("이송 중 환자 상태가 바뀌면 목적지 병원과 통화하세요. 통화 내용은 환자 정보에 덧붙어 병원 화면에 바로 반영됩니다.",
                        fontSize = 12.5.sp, color = AD.ink3)
                    if (m.transportCallBlocked) {
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.orangeSoft).padding(horizontal = 12.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(Icons.Filled.Lock, null, tint = AD.orange, modifier = Modifier.size(18.dp))
                            Text(buildAnnotatedString {
                                append("시연 콘솔이 ")
                                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("정해진 상황 선택") }
                                append(" 중이라 전화를 걸 수 없습니다. 콘솔에서 ")
                                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("음성으로 통화") }
                                append("를 고르면 전화할 수 있습니다.")
                            }, fontSize = 13.sp, color = AD.navy, modifier = Modifier.weight(1f))
                        }
                    }
                    if (dest != null) {
                        Row(Modifier.fillMaxWidth().height(50.dp).clip(RoundedCornerShape(14.dp)).background(if (m.paused) AD.control else AD.green)
                            .alpha(if (m.transportCallBlocked) 0.45f else 1f)
                            .clickable(enabled = !m.transportCallBlocked) { m.dial(dest.hospitalId, dest.name) }, horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Call, null, tint = Color.White, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("목적지 병원과 통화", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

// ── 안내 카드 ──

@Composable
private fun StatusPanel(icon: ImageVector, tint: Color, title: String, detail: String, pulse: Boolean = false) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        Card {
            Column(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.size(68.dp).clip(CircleShape).background(tint.copy(alpha = 0.12f)), contentAlignment = Alignment.Center) {
                    Icon(icon, null, tint = tint, modifier = Modifier.size(32.dp).alpha(pulseAlpha(pulse)))
                }
                Text(title, fontSize = 19.sp, fontWeight = FontWeight.Bold, color = AD.navy, textAlign = TextAlign.Center)
                Text(detail, fontSize = 13.sp, color = AD.sub, textAlign = TextAlign.Center)
            }
        }
    }
}

@Composable
private fun ConnectionDot(state: HubSocket.State) {
    val (color, text) = when (state) {
        HubSocket.State.LIVE -> AD.green to "실시간 연동"
        HubSocket.State.CONNECTING -> AD.gray to "연결 중"
        HubSocket.State.RECONNECTING -> AD.red to "재연결 중"
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Dot(color)
        Text(text, fontSize = 11.5.sp, fontWeight = FontWeight.Medium, color = color)
    }
}

// ── 설정 ──

@Composable
private fun SettingsDialog(m: PhoneModel, onClose: () -> Unit) {
    val s = m.settings
    var hub by remember { mutableStateOf(s.hubBase) }
    var apid by remember { mutableStateOf(s.apid) }
    var onDevice by remember { mutableStateOf(s.onDevice) }
    var rms by remember { mutableStateOf(s.silenceRms) }
    var hold by remember { mutableStateOf(s.holdSec) }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.padding(16.dp).clip(cardShape).background(AD.bg).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("닫기", color = AD.ink3, modifier = Modifier.clickable(onClick = onClose))
                Spacer(Modifier.weight(1f))
                Text("설정", fontWeight = FontWeight.Bold, color = AD.navy, fontSize = 16.sp)
                Spacer(Modifier.weight(1f))
                Text("적용", color = AD.blue, fontWeight = FontWeight.Bold, modifier = Modifier.clickable {
                    s.hubBase = hub
                    s.apid = apid.trim().ifEmpty { "auto" }
                    s.onDevice = onDevice
                    s.silenceRms = rms
                    s.holdSec = hold
                    m.start()
                    onClose()
                })
            }
            Card {
                Text("hub", fontSize = 12.sp, color = AD.sub)
                OutlinedTextField(hub, { hub = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("https://app.rookie-goldenlink.xyz 또는 http://<PC IP>:5001") })
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(apid, { apid = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    label = { Text("구급차 ID (SEL0001 또는 auto)") },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters))
            }
            Card {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("기기 안에서 음성 인식·구조화", modifier = Modifier.weight(1f), color = AD.ink)
                    Switch(onDevice, { onDevice = it }, colors = SwitchDefaults.colors(checkedTrackColor = AD.blue))
                }
                Text("끄면 웹 전화 앱처럼 음성을 hub로 보내 중앙 voice가 처리합니다. 켜면 음성은 기기 밖으로 나가지 않고, " +
                    "[전송]을 누를 때 구조화된 요약만 hub로 보냅니다(공개 도메인 가능).", fontSize = 11.5.sp, color = AD.sub)
                val missing = m.models.missingFiles()
                if (onDevice && missing.isNotEmpty()) {
                    Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(Icons.Filled.Warning, null, tint = AD.orange, modifier = Modifier.size(16.dp))
                        Text("모델 폴더(${m.models.dir.path})에 파일 ${missing.size}개가 없습니다 — README '모델 넣기'",
                            fontSize = 11.sp, color = AD.orange)
                    }
                }
            }
            Card {
                Text("무음 감지", fontSize = 12.sp, color = AD.sub)
                Text("무음 기준 RMS ${"%.3f".format(rms)}", fontSize = 13.sp, color = AD.ink)
                Slider(rms, { rms = it }, valueRange = 0.002f..0.05f, colors = SliderDefaults.colors(thumbColor = AD.blue, activeTrackColor = AD.blue))
                Text("발화 끝 ${"%.1f".format(hold)}초", fontSize = 13.sp, color = AD.ink)
                Slider(hold, { hold = (it * 10).roundToInt() / 10f }, valueRange = 0.2f..1.5f,
                    colors = SliderDefaults.colors(thumbColor = AD.blue, activeTrackColor = AD.blue))
            }
        }
    }
}
