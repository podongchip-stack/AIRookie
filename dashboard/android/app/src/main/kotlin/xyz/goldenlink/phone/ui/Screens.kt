package xyz.goldenlink.phone.ui

import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.snap
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import xyz.goldenlink.core.MatchHospital
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.AddIcCall
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.BottomSheetScaffold
import androidx.compose.material3.rememberBottomSheetScaffoldState
import androidx.compose.material3.rememberStandardBottomSheetState
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.RoadRoute
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Straight
import androidx.compose.material.icons.filled.TurnLeft
import androidx.compose.material.icons.filled.TurnRight
import xyz.goldenlink.core.GPS
import xyz.goldenlink.core.SceneCandidate
import xyz.goldenlink.phone.CallSession
import xyz.goldenlink.phone.CaseEditSync
import androidx.compose.ui.graphics.graphicsLayer
import xyz.goldenlink.phone.HospitalModel
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

internal val cardShape = RoundedCornerShape(18.dp)

// ── 공용 조각 ──

@Composable
fun Pill(text: String, fg: Color = AD.ink3, bg: Color = AD.chip, bold: Boolean = false, modifier: Modifier = Modifier) {
    Text(text, color = fg, fontSize = 11.sp, fontWeight = if (bold) FontWeight.Bold else FontWeight.Medium, maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = modifier.clip(CircleShape).background(bg).padding(horizontal = 9.dp, vertical = 3.dp))
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
fun PhoneApp(m: PhoneModel, hospital: HospitalModel) {
    when {
        m.accessRequired -> AccessCodeEntry(m)
        // 병원 접근 코드(H-<hpid>)로 들어왔으면 구급대 화면 대신 수신 전화 화면(병원 모드, 2026-11-04)
        m.hospitalId.isNotBlank() -> {
            DisposableEffect(m.hospitalId) {
                hospital.start()
                onDispose { hospital.stop() }
            }
            HospitalApp(hospital, onChangeCode = { m.resetAccess() })
        }
        else -> PhoneMain(m)
    }
}

/** 첫 실행(또는 [접근 코드 변경] 뒤)의 구급대 접근 코드 입력 — 아이폰 AccessCodeEntry와 같은 화면·규칙 */
@Composable
private fun AccessCodeEntry(m: PhoneModel) {
    var code by remember { mutableStateOf("") }
    var hub by remember { mutableStateOf(m.settings.hubBase) }
    var showHub by remember { mutableStateOf(false) }
    MaterialTheme(colorScheme = lightColorScheme(primary = AD.blue, background = AD.bg, surface = AD.white)) {
        Column(Modifier.fillMaxSize().background(AD.bg).safeDrawingPadding().verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp).padding(top = 64.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Text("골든링크", fontSize = 28.sp, fontWeight = FontWeight.Black, color = AD.navy)
            Text("접근 코드", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = AD.ink)
            Text("구급대 코드(P-…)를 입력하면 해당 구급대의 사건과 이송 정보를 확인하고, 병원 코드(H-…)를 입력하면 구급대의 전화를 받는 병원 모드로 들어갑니다.",
                fontSize = 14.sp, color = AD.sub)
            OutlinedTextField(code, { code = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                label = { Text("접근 코드") }, placeholder = { Text("예: P-SEL0111 · H-A1100017") },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { m.submitAccess(code, hub) }))
            m.accessError?.let { Text(it, fontSize = 13.sp, color = AD.red) }
            val enabled = !m.accessChecking && code.isNotBlank()
            Box(Modifier.fillMaxWidth().height(48.dp).clip(RoundedCornerShape(12.dp)).background(if (enabled) AD.blue else AD.gray)
                .clickable(enabled = enabled) { m.submitAccess(code, hub) }, contentAlignment = Alignment.Center) {
                Text(if (m.accessChecking) "코드 확인 중…" else "입장", color = AD.white, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            }
            Text("시연: 역삼119안전센터 구급 1\n휴대폰 P-SEL0111 · 태블릿 A-SEL0111", fontSize = 13.sp, color = AD.sub)
            Text(if (showHub) "서버 연결 설정 ▲" else "서버 연결 설정 ▼", fontSize = 14.sp, color = AD.ink3,
                modifier = Modifier.clickable { showHub = !showHub })
            if (showHub) OutlinedTextField(hub, { hub = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                label = { Text("hub 주소") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        }
    }
}

@Composable
private fun PhoneMain(m: PhoneModel) {
    var showSettings by remember { mutableStateOf(false) }
    MaterialTheme(colorScheme = lightColorScheme(primary = AD.blue, background = AD.bg, surface = AD.white)) {
        Box(Modifier.fillMaxSize().background(AD.bg)) {
            // 헤더 아래 끝(화면 맨 위 기준) — 지도는 헤더 뒤(상태바 밑까지)로 이어지고, 다른 화면은 이 아래에서 시작한다
            val density = LocalDensity.current
            var headerBottomPx by remember { mutableIntStateOf(0) }
            val headerBottom = with(density) { headerBottomPx.toDp() }
            // 통화가 진행 중이거나 끝난 직후엔 탭과 상관없이 통화 화면(예전 그대로) — 통화 중에 화면이 바뀌면 안 된다
            val inCallFlow = m.call != null
            val top = topScreen(m)
            // 화면 영역: 위로는 화면 맨 위까지(지도가 헤더 뒤로 이어진다), 아래는 키보드·시스템 바 위의 탭 바까지
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom))) {
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    // 통화 지도는 항상 아래에 깔아 둔다 — 다른 탭·통화 화면에 가려져도 지도를 없애지 않아서, 돌아올 때 다시 불러오느라 느려지지 않는다
                    Waiting(m, mapVisible = top == null, topInset = headerBottom)
                    // 그 위의 화면은 겹쳐 바뀌며 서서히 나타나고 사라진다
                    // 통화 종료 화면(전달됨 · 확인)에서 나갈 때는 서서히 지우지 않고 바로 바꾼다 — 통화가 지워지는 순간 그 화면이
                    // "정리하는 중"으로 되돌아간 채 220ms 동안 남아 깜빡이고, 지도의 전달 애니메이션이 가려졌다
                    val lastTop = remember { arrayOfNulls<String>(1) }
                    // 지도에서 다른 화면으로 나갈 때도 바로 바꾼다 — 서서히 나타나면 아래 지도가 비쳐 보였다가 화면이 바뀐다
                    val fade = if (lastTop[0] == "ended" || lastTop[0] == null || top == null) snap<Float>() else tween(220)
                    SideEffect { lastTop[0] = top }
                    Crossfade(top, animationSpec = fade, label = "screen") { key ->
                        if (key != null) Box(Modifier.fillMaxSize().background(AD.bg)
                            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
                            .padding(horizontal = 16.dp).padding(top = headerBottom + 10.dp)) { ScreenLayer(m, key) }
                    }
                }
                if (!inCallFlow) Box(Modifier.padding(start = 16.dp, end = 16.dp, top = 10.dp)) { TabBar(m) }
            }
            // 헤더 — 지도 위에 떠 있다
            Column(Modifier.align(Alignment.TopCenter).fillMaxWidth()
                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
                .padding(horizontal = 16.dp).padding(top = 6.dp)
                .onGloballyPositioned { headerBottomPx = it.boundsInRoot().bottom.toInt() },
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Header(m) { showSettings = true }
                CaseEditStatusView(m.caseEdits, onlyPending = true)
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

/** 기기 간 수정 동기화 상태 — onlyPending이면 보낼 수정이 남았거나 충돌일 때만 보인다 */
@Composable
fun CaseEditStatusView(sync: CaseEditSync, onlyPending: Boolean = false) {
    if (onlyPending && sync.pendingCount == 0 && sync.conflicts.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(sync.status, fontSize = 12.sp, color = if (sync.conflicts.isEmpty()) AD.sub else AD.orange)
        if (sync.conflicts.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("서버 값 사용", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AD.blue, modifier = Modifier.clickable { sync.resolve(false) })
                Text("내 수정으로 다시 저장", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AD.blue, modifier = Modifier.clickable { sync.resolve(true) })
            }
        }
    }
}

@Composable
private fun Header(m: PhoneModel, onSettings: () -> Unit) {
    Column(Modifier.fillMaxWidth().shadow(6.dp, cardShape).clip(cardShape).background(AD.white).border(1.dp, AD.line, cardShape)
        .padding(horizontal = 14.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // 로고와 구급차 이름이 남는 폭 전체를 쓴다 — 이름 칩과 빈 칸(Spacer)이 폭을 반씩 나눠 가져 이름이 항상 잘렸다
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(buildAnnotatedString {
                    withStyle(SpanStyle(color = AD.navy)) { append("골든") }
                    withStyle(SpanStyle(color = AD.blue)) { append("링크") }
                }, fontSize = 19.sp, fontWeight = FontWeight.Black, maxLines = 1)
                Pill(m.identity?.name ?: m.apid ?: "구급대 미지정", AD.ink3, AD.white, bold = true, modifier = Modifier.weight(1f, fill = false))
            }
            ConnectionDot(m.connection)
            val inCall = m.call != null && m.call?.phase != PhoneModel.LocalCall.Phase.ENDED
            Box(Modifier.size(36.dp).clip(CircleShape).background(AD.chip).clickable(enabled = !inCall, onClick = onSettings),
                contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Settings, "설정", tint = AD.ink3, modifier = Modifier.size(18.dp))
            }
        }
    }
}

/** 지도 위에 덮는 화면의 종류 — null이면 지도가 보인다. 통화 화면은 탭과 상관없이 먼저(통화 중에 화면이 바뀌면 안 된다) */
private fun topScreen(m: PhoneModel): String? {
    val call = m.call
    val status = m.status
    return when {
        call != null && call.phase != PhoneModel.LocalCall.Phase.ENDED -> "incall"
        call?.phase == PhoneModel.LocalCall.Phase.ENDED -> "ended"
        m.tab == PhoneModel.Tab.PATIENT -> "patient"
        m.tab == PhoneModel.Tab.TRANSPORT -> "transport"
        m.tab == PhoneModel.Tab.RECORDS -> "records"
        status != null && status.state == "calling" -> "other"
        else -> null
    }
}

@Composable
private fun ScreenLayer(m: PhoneModel, key: String) {
    when (key) {
        "incall" -> m.call?.let { InCallView(m, it) }
        "ended" -> EndedView(m)
        "other" -> m.status?.let { status ->
            StatusPanel(Icons.Filled.Phone, AD.green,
                "${if (status.device == "phone") "다른 휴대폰" else "구급차 대시보드"}에서 통화 중",
                "${status.hospitalName ?: "병원"}과 통화하고 있습니다. 통화가 끝나면 다시 걸 수 있습니다.")
        }
        "patient" -> PatientTab(m)
        "transport" -> TransportTab(m)
        "records" -> RecordsTab(m)
    }
}

@Composable
private fun Waiting(m: PhoneModel, mapVisible: Boolean, topInset: Dp) {
    // 연결·신원 확인·첫 위치가 오기 전에는 "출동 대기 중 → 위치 받는 중 → 지도"처럼 패널이 연달아 바뀌지 않게 조용한 로딩 하나로 둔다
    // 한 번 준비된 뒤에는 잠깐 재연결돼도 지도를 지우지 않는다
    var ready by remember { mutableStateOf(false) }
    val booting = !ready && (m.connection != HubSocket.State.LIVE || (m.apid != null && (m.identity == null || (m.simOn && m.mySim == null))))
    LaunchedEffect(booting) { if (!booting) ready = true }
    // 지도가 아닌 안내 화면은 헤더 아래에서 시작한다(지도만 헤더 뒤로 이어진다)
    val panelModifier = Modifier.fillMaxSize().padding(horizontal = 16.dp).padding(top = topInset + 10.dp)
    when {
        booting -> Box(panelModifier, contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = AD.blue, strokeWidth = 2.dp, modifier = Modifier.size(28.dp))
        }
        m.apid == null -> Box(panelModifier) { StatusPanel(Icons.Filled.Phone, AD.blue, "출동 대기 중", "상황이 발생하면 출동하는 구급대의 전화 앱으로 자동 전환됩니다.") }
        !m.simOn -> Box(panelModifier) { StatusPanel(Icons.Filled.DirectionsCar, AD.gray, "출동 시뮬레이션이 꺼져 있습니다",
            "휴대폰 전화 앱은 출동 시뮬레이션에서만 씁니다.") }
        m.mySim?.gps == null -> Box(panelModifier) { StatusPanel(Icons.Filled.DirectionsCar, AD.gray, m.phase.label, "구급차 위치를 받는 중입니다.", pulse = true) }
        else -> CallMapScreen(m, mapVisible, topInset)
    }
}

// ── 지도 화면 (통화 탭 기본) ──

/** 지도가 배경. 출동 중엔 현장까지 선과 ETA, 현장에선 hub가 추천한 병원 목록 → 전화, 병원 응답 중엔 활성 존 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CallMapScreen(m: PhoneModel, visible: Boolean, topInset: Dp) {
    val sim = m.mySim
    val ambulanceGps = sim?.gps ?: return
    val phase = m.phase
    val sentMode = m.onScene && m.sent && !m.wantsExtraCall
    val scene = m.sceneHospitals  // hub 추천 순서 그대로, 받지 않은(취소한) 병원만 맨 아래
    // 현장 후보는 hub 도착 시간순 — 전달된 뒤에는 실제로 정보가 간 병원(매칭 결과)을 쓴다
    val ordered = scene.filter { it.firstCallRecommended == true && !m.isSkipped(it) } + scene.filter { it.firstCallRecommended != true || m.isSkipped(it) }
    var tappedId by remember(m.caseId) { mutableStateOf<String?>(null) }
    // 목록은 hub 첫 연락 규칙(이동·병상·전문의·도착 유효 확률 + 다른 구급차 점유) 그대로 — hub가 추천한 병원이 첫 연락 대상
    val nearest = scene.firstOrNull { it.firstCallRecommended == true && !m.isSkipped(it) }
    val target = scene.firstOrNull { it.hospitalId == tappedId } ?: nearest

    val hospitals: List<Pair<String, String>> =
        if (sentMode) m.result?.hospitals?.map { it.hospitalId to it.name } ?: emptyList() else if (m.onScene) ordered.map { it.hospitalId to it.name } else emptyList()
    val pins = buildList {
        // 병원에 도착하면 구급차는 병원 핀 위에 겹쳐 핀을 가리므로 그리지 않는다(도착은 카드가 알린다)
        if (phase != AmbulancePhase.at_hospital) add(MapPin("ambulance", m.identity?.name ?: sim.apid, ambulanceGps, MapPin.Kind.AMBULANCE))
        // 사건 현장 글자는 출동 중에만 — 도착하면 뗀다
        // 사건 현장은 출동·현장·이송 중에만 — 병원에 도착하거나 복귀하면 지운다
        val incidentLive = phase == AmbulancePhase.dispatching || phase == AmbulancePhase.on_scene || phase == AmbulancePhase.transporting || phase == AmbulancePhase.rerouting
        if (incidentLive) sim.incident?.let { add(MapPin("incident", if (phase == AmbulancePhase.dispatching) "사건 현장" else "", it, MapPin.Kind.INCIDENT)) }
        // 센터(출동 출발지·복귀 목적지) — 출동 중과 복귀 중에만
        if (phase == AmbulancePhase.dispatching || phase == AmbulancePhase.returning) sim.base?.let { add(MapPin("base", "센터", it, MapPin.Kind.BASE)) }
        // 이송 중과 병원에 도착했을 때는 목적지(확정) 병원만 — 이름 칩과 함께(도착하면 구급차 핀은 없고 이 병원 핀으로 지도가 맞춰진다)
        if (m.inTransport || phase == AmbulancePhase.at_hospital) m.destination?.let { d -> m.hospitalGps[d.hospitalId]?.let { add(MapPin(d.hospitalId, d.name, it, MapPin.Kind.SELECTED)) } }
        for ((id, name) in hospitals) {
            val gps = m.hospitalGps[id] ?: continue
            add(MapPin(id, name, gps, when {
                !sentMode && id == target?.hospitalId -> MapPin.Kind.SELECTED
                !sentMode && id == nearest?.hospitalId -> MapPin.Kind.RECOMMENDED
                else -> MapPin.Kind.HOSPITAL
            }))
        }
    }

    // 이동 중(출동·이송·복귀)인지 — 도로 경로와 카메라 맞춤이 이 값을 따른다
    val moving = phase == AmbulancePhase.dispatching || phase == AmbulancePhase.transporting || phase == AmbulancePhase.returning
    // 도로 경로 — hub 카카오 길찾기에서 남은 구간만. 경로가 없으면 출동 중에 한해 직선으로 대신한다.
    // 이동 중이 아니면(병원·기지에 도착했거나 대기) 그리지 않는다 — 도착한 자리에 남은 마지막 구간이 파란 선으로 보이고,
    // 카메라가 그 아주 짧은 선에 맞춰 크게 확대되던 문제
    val route: List<GPS> = if (!moving) emptyList() else run {
        val path = sim.path
        val rest = if (path != null) RoadRoute.remaining(path, ambulanceGps.lat, ambulanceGps.lng).map { GPS(it[0], it[1]) } else emptyList()
        if (rest.size >= 2) rest else sim.incident?.takeIf { phase == AmbulancePhase.dispatching }?.let { listOf(ambulanceGps, it) } ?: emptyList()
    }
    // 활성 존 — 병원 응답 단계(매칭 결과가 있을 때)에서만, 구급차 중심 5km 폭 단위
    val zoneKm: Double? = if (m.onScene) 5.0 * m.activeZone else null
    var recenter by remember { mutableIntStateOf(0) }
    var overlayPx by remember { mutableIntStateOf(0) }
    // 카메라를 다시 맞추는 때(아이폰과 같다): 출동·이송·복귀 중엔 사건·병원·도로 경로가 바뀔 때, 현장에선 응답 존이 생기거나 넓어질 때,
    // 그 뒤엔 전화할 병원을 바꿀 때
    val routeKey: Any? = if (moving) listOf(phase, sim.caseId, sim.hospitalId, sim.path?.size, sim.path?.lastOrNull()) else null
    // 내비게이션 시점 — 출동·이송·복귀 중 도로 경로가 있으면 기본으로 켠다. [경로 전체] 버튼으로 일반 지도와 오간다(단계가 바뀌면 다시 내비 시점)
    val restPoints = route.map { listOf(it.lat, it.lng) }
    val navAvailable = moving && route.size >= 2 && (sim.path?.size ?: 0) > 2
    var navMode by remember(phase) { mutableStateOf(true) }
    val navigate = navAvailable && navMode
    // 위치 변화로 속도를 재기 전에도 배율을 맞추도록, hub가 준 도로 ETA와 시연 배속으로 처음 속도를 추정한다(남은 길이 ÷ 시연 화면 시간)
    val navSpeedHint = if (navigate) sim.etaSec?.let { eta -> sim.speedup?.let { up -> if (eta > 0 && up > 0) RoadRoute.lengthM(restPoints) / (eta / up) else null } } else null
    // 이 구간(단계·사건)의 내비 시점이 준비됐는지 — 새 구간이면 첫 프레임부터 로딩이 지도·배너·카드를 덮는다
    val navSession = listOf(phase, sim.caseId)
    var readySession by remember { mutableStateOf<Any?>(null) }
    val navLoading = navigate && readySession != navSession
    val navTurn = if (navigate) RoadRoute.nextTurn(restPoints) else null
    val navRemainM = if (navigate) RoadRoute.lengthM(restPoints) else 0.0
    val zoneFitKey: Any? = if (zoneKm != null) listOf(m.caseId, zoneKm) else null
    val sceneKey: Any? = if (m.onScene && !sentMode && target != null) listOf(m.caseId, target.hospitalId) else null

    // 현장(전달 전)에는 병원 리스트 시트가 항상 떠 있다 — 접힌 채로는 제목만 보이고, 위로 끌면 병원 목록이 펼쳐진다
    val sheetMode = m.onScene && !sentMode
    // 이송 중에는 목적지 병원 카드를 지도 위 고정 카드가 아니라 위로 끌어올리는 시트로 둔다 — 접어 두면 지도가 넓게 보인다
    val transportSheet = m.inTransport
    val anySheet = sheetMode || transportSheet
    // 요약이 병원들에 전달되는 연출 — 병원이 많으면 앞의 8곳만 날리고, 숫자는 전체를 센다
    val show = m.deliveryShow?.takeIf { it.caseId == m.caseId && sentMode }
    val deliveryTargets = if (show != null) (m.result?.hospitals ?: emptyList()).mapNotNull { h -> m.hospitalGps[h.hospitalId]?.let { DeliveryTarget(h.name, it) } }.take(DeliveryTimeline.MAX_TARGETS) else emptyList()
    // 이송 시트는 접었을 때 머리말과 병원 이름 줄까지만 보이게 그 높이를 재서 접힌 높이로 쓴다(안내 문장이 반쯤 잘려 보이던 문제)
    var transportHeaderPx by remember { mutableIntStateOf(0) }
    val peek = if (transportSheet) (if (transportHeaderPx > 0) with(LocalDensity.current) { transportHeaderPx.toDp() } + 30.dp else 124.dp) else 108.dp
    // 통화가 취소·미응답으로 끝나 지도로 돌아오면 병원 리스트 시트를 펼친다(지도는 계속 떠 있으므로 상태 변화로 처리)
    val sheetState = rememberBottomSheetScaffoldState(rememberStandardBottomSheetState(skipHiddenState = true))
    val listState = rememberLazyListState()
    // 취소한 병원이 맨 아래로 내려가도 스크롤이 아래에 남아 있지 않게, 돌아오면 목록을 맨 위로 올리고 시트를 펼친다
    LaunchedEffect(m.reopenList, visible, sheetMode) {
        if (m.reopenList && visible) { if (sheetMode) runCatching { listState.scrollToItem(0); sheetState.bottomSheetState.expand() }; m.reopenList = false }
    }
    val peekPx = with(LocalDensity.current) { peek.roundToPx() }
    // 목적지 병원이 수용할 수 없게 되면(재선택 대기) 다시 고를 병원 목록이 바로 보이게 시트를 펼친다
    LaunchedEffect(transportSheet, m.phase) { if (transportSheet && m.phase == AmbulancePhase.rerouting) runCatching { sheetState.bottomSheetState.expand() } }
    val mapArea: @Composable () -> Unit = {
        Box(Modifier.fillMaxSize()) {
            CallMap(pins, route = route, zoneKm = zoneKm, recenter = recenter,
                routeKey = routeKey, zoneFitKey = zoneFitKey, sceneKey = sceneKey, bottomOverlayPx = if (anySheet) peekPx else overlayPx,
                active = visible, topOverlayPx = with(LocalDensity.current) { (topInset + (if (navigate) 96.dp else 12.dp)).roundToPx() }, navigate = navigate, navSession = navSession, navSpeedHintMps = navSpeedHint, onNavReady = { readySession = navSession },
                deliveryFit = if (show != null && deliveryTargets.isNotEmpty()) listOf(ambulanceGps) + deliveryTargets.map { it.gps } else null,
                overlay = if (show != null && deliveryTargets.isNotEmpty()) { project -> DeliveryOverlay(show, ambulanceGps, deliveryTargets, project) { m.finishDelivery() } } else null,
                onPin = { id -> if (m.onScene && !sentMode && scene.any { it.hospitalId == id }) tappedId = id }, modifier = Modifier.fillMaxSize())
            // 내비 시점이 가능하면 [경로 전체 보기] ↔ [내비 시점] 전환, 아니면 [내 위치]
            val toggle = navAvailable
            Icon(if (!toggle) Icons.Filled.MyLocation else if (navigate) Icons.Filled.Map else Icons.Filled.Navigation,
                if (!toggle) "내 위치" else if (navigate) "경로 전체 보기" else "내비 시점", tint = AD.navy,
                modifier = Modifier.align(Alignment.TopEnd).padding(end = 16.dp, top = topInset + 8.dp).size(44.dp).clip(CircleShape)
                    .background(AD.white.copy(alpha = 0.96f)).border(1.dp, AD.line, CircleShape)
                    .clickable { if (toggle) navMode = !navMode else recenter++ }.padding(10.dp))
            if (navigate) NavBanner(navTurn, navRemainM, Modifier.align(Alignment.TopStart).padding(start = 16.dp, top = topInset + 8.dp, end = 70.dp))
            if (!anySheet) Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().animateContentSize().onSizeChanged { overlayPx = it.height }.padding(10.dp).clip(cardShape).background(AD.white.copy(alpha = 0.96f))
                .border(1.dp, AD.line, cardShape).padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if ((phase == AmbulancePhase.dispatching || phase == AmbulancePhase.transporting || phase == AmbulancePhase.returning) && (sim.path?.size ?: 0) <= 2) {
                    Text("도로 경로를 받지 못했습니다. hub의 경로 API 연결을 확인해 주세요.", fontSize = 11.sp, color = AD.orange)
                }
                when {
                    show != null -> DeliveryCard(show, deliveryTargets.size, m.caseId?.let { m.sentCount[it] } ?: hospitals.size)
                    sentMode -> {
                        val n = m.caseId?.let { m.sentCount[it] } ?: hospitals.size
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Icon(Icons.Filled.CheckCircle, null, tint = AD.green, modifier = Modifier.size(26.dp))
                            Text("후보 병원 ${n}곳에 전달됐습니다", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                        }
                        BigButton("추가 통화", AD.blue, Icons.Filled.AddIcCall) { m.wantsExtraCall = true }
                    }
                    phase == AmbulancePhase.at_hospital -> {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Icon(Icons.Filled.CheckCircle, null, tint = AD.green, modifier = Modifier.size(26.dp))
                            Column {
                                Text("${m.destination?.name ?: "병원"}에 도착했습니다", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                                Text("병원이 환자 수용을 확인하면 이어서 마무리됩니다", fontSize = 12.5.sp, color = AD.sub)
                            }
                        }
                    }
                    else -> {
                        val eta = sim.etaSec?.let { max(1, ceil(it / 60).toInt()) }
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Pill(phase.label, phaseColor(phase), phaseColor(phase).copy(alpha = 0.12f), bold = true)
                            if (phase == AmbulancePhase.dispatching && eta != null) Text("현장까지 약 ${eta}분", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                        }
                        if (navigate) Text("남은 ${distanceLabel(navRemainM)}" + (sim.etaSec?.let { " · 도착 ${arrivalClock(it)}" } ?: ""), fontSize = 13.sp, color = AD.sub)
                    }
                }
            }
        }
    }

    // 다른 화면이 덮는 동안은 지도 위 시트·카드도 함께 투명하게 — 덮는 화면의 첫 프레임 전에 아래 패널이 비치지 않게(지도·시트 상태는 그대로 둔다)
    Box(Modifier.fillMaxSize().clip(RoundedCornerShape(bottomStart = 18.dp, bottomEnd = 18.dp)).graphicsLayer { alpha = if (visible) 1f else 0f }) {
        // 지도는 시트가 있든 없든 항상 이 자리에 둔다 — 현장 → 전달로 시트가 사라질 때 지도를 다른 자리로 옮기면
        // 지도가 지워졌다 새로 만들어져 기본 위치에서 다시 뜬 뒤에야 구급차로 맞춰진다(상황 전파 때 시선이 튀던 원인)
        run {
            val scope = rememberCoroutineScope()
            val listMax = (LocalConfiguration.current.screenHeightDp * 0.5f).dp
            BottomSheetScaffold(
                scaffoldState = sheetState, sheetPeekHeight = if (anySheet) peek else 0.dp, containerColor = Color.Transparent,
                sheetContainerColor = if (anySheet) AD.white else Color.Transparent, sheetShape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
                sheetShadowElevation = if (anySheet) 8.dp else 0.dp, sheetTonalElevation = 0.dp, sheetSwipeEnabled = anySheet,
                sheetDragHandle = { if (anySheet) Box(Modifier.padding(top = 8.dp, bottom = 4.dp).size(36.dp, 4.dp).clip(CircleShape).background(AD.control)) },
                sheetContent = {
                    if (sheetMode) Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("병원 리스트", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                        // 아래는 펼쳤을 때만 보인다
                        Text("hub 추천순 · 이동·병상·전문의·도착 유효 확률과 다른 사건의 연락·이송을 반영합니다", fontSize = 12.sp, color = AD.sub)
                        if (m.wantsExtraCall) Text("추가 통화 닫기", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.ink3,
                            modifier = Modifier.clickable { m.wantsExtraCall = false })
                        when {
                            m.scene == null -> Box(Modifier.fillMaxWidth().height(160.dp), contentAlignment = Alignment.Center) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    CircularProgressIndicator(color = AD.blue, strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
                                    Text("추천 병원을 확인하고 있습니다", fontSize = 13.sp, color = AD.sub)
                                }
                            }
                            scene.isEmpty() -> Text("현재 탐색 범위에 병원이 없습니다", fontSize = 14.sp, color = AD.sub,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp), textAlign = TextAlign.Center)
                            else -> LazyColumn(Modifier.heightIn(max = listMax), state = listState, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                items(scene, key = { it.hospitalId }) { h ->
                                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(AD.bg).padding(12.dp),
                                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                            Text((if (h.firstCallRecommended == true && !m.isSkipped(h)) "추천 · " else "") + h.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                                            Text(distanceText(h), fontSize = 14.sp, color = AD.ink)
                                            Text(h.firstCallReason ?: "추천 후보", fontSize = 12.sp, color = AD.sub)
                                            if (m.isSkipped(h)) Text("전화 미응답 이력", fontSize = 12.sp, color = AD.orange)
                                        }
                                        val enabled = !m.sceneCallBlocked && !m.paused && m.call == null
                                        Row(Modifier.heightIn(min = 44.dp).clip(RoundedCornerShape(12.dp)).background(if (enabled) AD.blue else AD.control)
                                            .clickable(enabled = enabled) { m.dial(h) }.padding(horizontal = 12.dp),
                                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                            Icon(Icons.Filled.Call, null, tint = Color.White, modifier = Modifier.size(16.dp))
                                            Text("전화", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                                        }
                                    }
                                }
                            }
                        }
                    } else if (transportSheet) TransportSheet(m, listMax) { transportHeaderPx = it }
                },
            ) { mapArea() }
        }
        // 내비 시점이 준비되는 동안은 로딩만 — 지도가 구급차 위치로 옮겨 가는 장면과 아래 시트·카드를 보이지 않는다
        AnimatedVisibility(navLoading, Modifier.fillMaxSize(), enter = fadeIn(), exit = fadeOut(tween(350))) {
            Column(Modifier.fillMaxSize().background(AD.bg), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator(color = AD.blue, strokeWidth = 3.dp, modifier = Modifier.size(34.dp))
                Spacer(Modifier.height(14.dp))
                Text("현재 위치를 불러오는 중…", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
            }
        }
    }
}

/** 내비게이션 상단 안내 — 다음 회전까지 거리·방향, 회전이 없으면 직진 거리 */
@Composable
private fun NavBanner(turn: RoadRoute.Turn?, remainM: Double, modifier: Modifier = Modifier) {
    val angle = turn?.angleDeg ?: 0.0
    val icon = when {
        turn == null || Math.abs(angle) < 35 -> Icons.Filled.Straight
        angle > 0 -> Icons.Filled.TurnRight
        else -> Icons.Filled.TurnLeft
    }
    val side = if (angle > 0) "우" else "좌"
    val what = when {
        turn == null -> "직진"
        Math.abs(angle) >= 135 -> "${side}측 유턴"
        Math.abs(angle) >= 60 -> "${side}회전"
        else -> "${side}측 방향"
    }
    Row(modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(AD.navy).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(icon, null, tint = Color.White, modifier = Modifier.size(34.dp))
        Column {
            Text(if (turn == null) "$what · ${distanceLabel(remainM)}" else "${distanceLabel(turn.distanceM)} 앞 $what",
                color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Black, maxLines = 1)
            if (turn != null) Text("목적지까지 ${distanceLabel(remainM)}", color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp)
        }
    }
}

/** 100m 아래는 10m 단위, 1km 아래는 50m 단위, 그 위는 소수 한 자리 km */
private fun distanceLabel(m: Double): String = when {
    m < 100 -> "${(Math.round(m / 10.0) * 10).coerceAtLeast(10)}m"
    m < 1000 -> "${Math.round(m / 50.0) * 50}m"
    else -> "%.1fkm".format(m / 1000.0)
}

private fun arrivalClock(etaSec: Double): String =
    java.text.SimpleDateFormat("HH:mm", java.util.Locale.KOREA).format(java.util.Date(System.currentTimeMillis() + (etaSec * 1000).toLong()))

@Composable
private fun BigButton(text: String, color: Color, icon: ImageVector? = null, enabled: Boolean = true, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = 46.dp).clip(RoundedCornerShape(14.dp)).background(color).clickable(enabled = enabled, onClick = onClick),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) { Icon(icon, null, tint = Color.White, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)) }
        Text(text, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
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
                Text(if (connecting) "전화 응답 대기" else mmss((now - call.startedAt) / 1000), fontSize = 30.sp, fontWeight = FontWeight.Bold,
                    color = if (connecting) AD.muted else AD.ink)
                LevelMeter(m.session?.level ?: 0f, active = !connecting)
            }
        }
        Card(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (call.webrtc) "실제 통화" else "실시간 자막", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                Spacer(Modifier.weight(1f))
                if (!call.webrtc) Pill("AI · Qwen3-ASR", AD.blue, AD.blueSoft)
            }
            Spacer(Modifier.height(8.dp))
            val lines = m.transcriptLines
            val state = rememberLazyListState()
            LaunchedEffect(lines.size) { if (lines.isNotEmpty()) state.animateScrollToItem(lines.size - 1) }
            if (call.webrtc) {
                // 실제 통화(WebRTC, 2026-11-04): 음성은 병원 앱과 직접 주고받고, 이 통화 동안은 음성 인식·요약이 연결돼 있지 않다(다음 단계)
                Text(if (connecting) "병원 앱이 받으면 음성 연결을 확인한 뒤 통화가 시작됩니다."
                    else "병원 담당자와 통화 중입니다. 이 통화는 음성 인식·요약에 연결돼 있지 않습니다.", fontSize = 13.sp, color = AD.muted)
            } else if (lines.isEmpty()) {
                Text(if (connecting) "병원 응답 대기 중입니다. 연결 후 녹음이 시작됩니다." else "말이 끊길 때마다 인식된 문장이 여기에 뜹니다.", fontSize = 13.sp, color = AD.muted)
            }
            LazyColumn(state = state, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(lines) { _, line ->
                    Text(line, fontSize = 14.sp, color = AD.ink, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                        .background(AD.bg).padding(horizontal = 10.dp, vertical = 7.dp))
                }
            }
        }
        if (connecting && !call.webrtc) Text("미응답 · 다음 병원", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.orange, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().clickable { m.noAnswerNext() }.padding(vertical = 4.dp))
        // [취소]는 아무것도 보내지 않고, [통화 종료]([전송])를 눌러야만 음성을 처리한다. 현장 첫 통화는 끝낸 뒤 이송확정/이송불가를 고른다
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(AD.redSoft).border(2.dp, AD.red, cardShape)
                .clickable { m.cancelCall() }, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Cancel, null, tint = AD.red, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(10.dp))
                Text(if (call.webrtc && !connecting) "통화 종료" else "취소", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = AD.red)
            }
            // 실제 통화는 종료 버튼 하나다(요약·이송 판단이 없다) — 병원 앱이 받기 전엔 [취소], 통화 중엔 [통화 종료]
            if (!call.webrtc) Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(if (connecting) AD.control else AD.blue)
                .clickable(enabled = !connecting) { m.sendCall() }, horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically) {
                if (call.followup) Icon(Icons.AutoMirrored.Filled.Send, null, tint = Color.White, modifier = Modifier.size(26.dp))
                else Icon(Icons.Filled.CallEnd, null, tint = Color.White, modifier = Modifier.size(26.dp))
                Spacer(Modifier.width(10.dp))
                Text(if (call.followup) "전송" else "통화 종료", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
        Text(if (call.webrtc) "실제 통화입니다 · 종료하면 통화만 끝나고 요약·이송 판단은 만들어지지 않습니다"
            else if (call.followup) "취소하면 아무것도 전달되지 않습니다 · 전송을 눌러야 기기에서 음성을 인식·구조화해 병원에 보냅니다"
            else "취소하면 아무것도 전달되지 않습니다 · 통화를 끝낸 뒤 이송확정·이송불가를 고릅니다 (그때까지 요약은 병원에 가지 않습니다)",
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
    // 현장 첫 통화는 구급대원이 이송 여부를 고른 뒤부터 센다 — 판단 전엔 요약이 hub에 붙잡혀 있는 게 정상이다(2026-11-04)
    val waitingSince = if (followup) m.call?.endedAt else m.call?.decidedAt
    val timedOut = sent == null && serverWaitOver && (waitingSince?.let { now - it > 90_000 } ?: false)
    val failed = stage is CallSession.Stage.Failed
    val finished = sent != null || timedOut || stage == CallSession.Stage.NoSpeech || failed
    // 현장 첫 통화는 끝난 뒤 이송확정/이송불가를 고른다(2026-11-04) — 요약이 만들어지지 못한 경우엔 고를 것이 없다
    val decision = m.call?.decision
    val awaiting = !followup && decision == null && sent == null && !timedOut && stage != CallSession.Stage.NoSpeech && !failed
    val confirming = decision == "confirm" && sent == null
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
                            awaiting -> "통화가 끝났습니다 — 이송 여부를 선택하세요"
                            confirming -> "${hospital}(으)로 이송 확정 중…"
                            else -> stageTitle(stage)
                        }, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                        Text("${if (followup) "추가 통화" else "통화"}: $hospital", fontSize = 12.sp, color = AD.sub)
                    }
                }
                if (awaiting) {
                    // [이송확정]은 통화한 병원으로 바로 출발하고 요약은 그 병원에만 간다. [이송불가]는 요약을 존 안 다른 후보 병원 전체에 동시에 전달한다
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(AD.green).clickable { m.decideTransport(true) },
                            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.CheckCircle, null, tint = Color.White, modifier = Modifier.size(26.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("이송확정", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = Color.White)
                        }
                        Row(Modifier.weight(1f).height(72.dp).clip(cardShape).background(AD.redSoft).border(2.dp, AD.red, cardShape)
                            .clickable { m.decideTransport(false) }, horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Cancel, null, tint = AD.red, modifier = Modifier.size(26.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("이송불가", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = AD.red)
                        }
                    }
                    Text("이송확정: $hospital(으)로 바로 출발합니다 · 요약은 이 병원에만 전달됩니다\n이송불가: 요약을 존 안 다른 후보 병원 전체에 동시에 전달합니다",
                        fontSize = 11.5.sp, color = AD.sub)
                }
                // 진행 단계 — 음성 인식(AI) → 구조화(AI) → 병원 전달(규칙). 판단 전에는 전달 단계가 시작되지 않는다
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    StepRow("남은 음성 인식", "AI", stepState(0, stage, sent))
                    StepRow("환자 정보 구조화 (MF_BERT)", "AI", stepState(1, stage, sent))
                    StepRow(if (confirming) "통화 병원에 요약 전달 · 이송 확정" else "존 안 후보 병원에 동시 전달", "규칙",
                        if (awaiting) Step.PENDING else stepState(2, stage, sent))
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

/** 이송 중 시트 — 접으면 머리 부분(상태·병원 이름·[통화])만, 위로 끌어올리면 안내가 보인다. 재선택 대기에는 다시 고를 병원 목록 */
@Composable
private fun TransportSheet(m: PhoneModel, listMax: Dp, onHeaderHeight: (Int) -> Unit) {
    val rerouting = m.phase == AmbulancePhase.rerouting
    val dest = m.destination
    val eta = m.mySim?.etaSec?.let { max(1, ceil(it / 60).toInt()) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // 접었을 때 보이는 머리 — 이 높이가 접힌 시트의 높이가 된다
        Column(Modifier.onSizeChanged { onHeaderHeight(it.height) }, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pill(if (rerouting) "재선택 대기" else "병원 이송 중", if (rerouting) AD.red else AD.blue, if (rerouting) AD.redSoft else AD.blueSoft, bold = true)
                when {
                    m.transportHeld -> Text("통화 내용 반영 중 — 이송 잠시 멈춤", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.blue)
                    !rerouting && eta != null -> Text("도착까지 약 ${eta}분", fontSize = 12.sp, color = AD.sub)
                }
            }
            if (rerouting) {
                Text("목적지 병원이 수용할 수 없게 됐습니다", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = AD.navy)
            } else {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text("목적지 병원", fontSize = 11.5.sp, color = AD.sub)
                        Text(dest?.name ?: "확정 병원", fontSize = 20.sp, fontWeight = FontWeight.Black, color = AD.navy, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    if (dest != null) {
                        Row(Modifier.height(46.dp).clip(RoundedCornerShape(14.dp)).background(if (m.paused) AD.control else AD.green)
                            .alpha(if (m.transportCallBlocked) 0.45f else 1f)
                            .clickable(enabled = !m.transportCallBlocked) { m.dial(dest.hospitalId, dest.name) }.padding(horizontal = 16.dp),
                            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Call, null, tint = Color.White, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("통화", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
        // 아래는 위로 끌어올렸을 때만 보인다
        if (rerouting) {
            Column(Modifier.heightIn(max = listMax).verticalScroll(rememberScrollState())) { ReselectList(m) }
        } else {
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
        }
    }
}

/** 재선택 — 이송 승인한(지금 보낼 수 있는) 병원이 있으면 바로 보여 주고, 없으면 수용 불가·제외된 병원을 뺀 후보에 다시 전화할 수 있게 한다 */
@Composable
private fun ReselectList(m: PhoneModel) {
    val hospitals = m.result?.hospitals ?: emptyList()
    val ready = hospitals.filter(::canTransportNow)
    val skipped = m.caseId?.let { m.skippedHospitals[it] } ?: emptySet()
    // 수용 불가(병원 거절·병상 없음)·이 사건에서 제외된 병원은 뺀다. 전화를 받지 않은 병원은 남기되 맨 아래로
    val callable = hospitals.filter { it.status != "rejected" && it.excluded != true && it.unavailableReason == null }
        .let { all -> all.filterNot { it.hospitalId in skipped } + all.filter { it.hospitalId in skipped } }
    // 이송 승인을 보낸 뒤 hub가 확정하고 구급차 단계가 이송 중으로 넘어갈 때까지는 승인 병원이 목록에서 빠진다 — 전화 목록으로 바뀌지 않게 붙잡는다
    val deciding = m.confirmed ?: hospitals.firstOrNull { it.hospitalId == m.pendingConfirmId }
    if (deciding != null) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(color = AD.blue, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
            Text("${deciding.name}(으)로 이송을 확정하고 있습니다", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = AD.navy)
        }
    } else if (ready.isNotEmpty() && m.waitingDispatcher != null) {
        DispatcherWaitBanner(m.waitingDispatcher!!)
    } else if (ready.isNotEmpty()) {
        Text("승인한 병원이 있습니다 — 바로 이송 승인하세요", fontSize = 12.5.sp, color = AD.ink3)
        Column(Modifier.heightIn(max = 240.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            ready.forEach { h ->
                val requesting = m.pendingConfirmId == h.hospitalId
                ReselectRow(h, "이송 승인", if (requesting) AD.control else AD.green, enabled = !requesting, icon = Icons.Filled.CheckCircle) { m.approve(h.hospitalId) }
            }
        }
    } else {
        Text("승인한 병원이 없습니다. 수용 불가 병원을 뺀 후보에게 다시 전화하세요", fontSize = 12.5.sp, color = AD.ink3)
        if (callable.isEmpty()) {
            Text("전화할 수 있는 후보가 없습니다. 범위를 넓혀 다시 요청 중입니다.", fontSize = 13.sp, color = AD.orange)
        } else {
            val enabled = !m.paused && m.call == null
            Column(Modifier.heightIn(max = 240.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                callable.forEach { h ->
                    ReselectRow(h, "전화", if (enabled) AD.blue else AD.control, enabled = enabled, icon = Icons.Filled.Call,
                        note = if (h.hospitalId in skipped) "전화 미응답 이력" else null) { m.dial(h.hospitalId, h.name) }
                }
            }
        }
    }
}

@Composable
private fun ReselectRow(h: MatchHospital, label: String, color: Color, enabled: Boolean, icon: ImageVector, note: String? = null, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(AD.bg).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(h.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
            val dist = (h.roadDistanceKm ?: h.distanceKm).let { "%.1fkm".format(it) } + (h.etaMin ?: h.travelMin)?.let { " · ${it.roundToInt()}분" }.orEmpty()
            Text(dist, fontSize = 13.sp, color = AD.ink)
            if (note != null) Text(note, fontSize = 12.sp, color = AD.orange)
        }
        Row(Modifier.heightIn(min = 44.dp).clip(RoundedCornerShape(12.dp)).background(color).clickable(enabled = enabled, onClick = onClick).padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(icon, null, tint = Color.White, modifier = Modifier.size(16.dp))
            Text(label, color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
    }
}

// ── 안내 카드 ──

@Composable
internal fun StatusPanel(icon: ImageVector, tint: Color, title: String, detail: String, pulse: Boolean = false) {
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
    // 정상 연동은 점만 — 글자가 폭을 차지해 구급차 이름 칩이 "자동…"처럼 잘렸다. 연결 중·재연결 중일 때만 글자로 알린다
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Dot(color)
        if (state != HubSocket.State.LIVE) Text(text, fontSize = 11.5.sp, fontWeight = FontWeight.Medium, color = color)
    }
}

// ── 설정 ──

@Composable
private fun SettingsDialog(m: PhoneModel, onClose: () -> Unit) {
    val s = m.settings
    var hub by remember { mutableStateOf(s.hubBase) }
    var recordToken by remember { mutableStateOf(m.recordAccess.token(s.apid.trim().uppercase())) }
    var onDevice by remember { mutableStateOf(s.onDevice) }
    var realCall by remember { mutableStateOf(s.realCall) }
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
                    if (!m.recordAccess.save(recordToken, s.apid.trim().uppercase())) return@clickable
                    s.onDevice = onDevice
                    s.realCall = realCall
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
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("구급대 코드: P-${s.apid.trim().uppercase()}", fontWeight = FontWeight.SemiBold, color = AD.ink, modifier = Modifier.weight(1f))
                    Text("접근 코드 변경", color = AD.blue, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.clickable {
                        m.resetAccess()
                        onClose()
                    })
                }
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(recordToken, { recordToken = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    label = { Text("기록 동기화 키 (운영자 발급)") }, visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
                Text("과거 기록은 같은 구급차 ID와 동기화 키가 있어야 내려받습니다.", fontSize = 11.sp, color = AD.sub)
            }
            Card {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("실제 통화(WebRTC)", modifier = Modifier.weight(1f), color = AD.ink)
                    Switch(realCall, { realCall = it }, colors = SwitchDefaults.colors(checkedTrackColor = AD.blue))
                }
                Text("켜면 병원을 눌러 거는 전화가 시연 연출이 아니라 병원 코드로 접속한 앱과 연결되는 실제 음성 통화가 됩니다. " +
                    "이 통화 동안은 음성 인식·요약이 연결돼 있지 않습니다(다음 단계).", fontSize = 11.5.sp, color = AD.sub)
            }
            Card {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("기기 안에서 음성 인식·구조화", modifier = Modifier.weight(1f), color = AD.ink)
                    Switch(onDevice, { onDevice = it }, colors = SwitchDefaults.colors(checkedTrackColor = AD.blue))
                }
                Text("끄면 웹 전화 앱처럼 음성을 hub로 보내 중앙 voice가 처리합니다. 켜면 음성은 기기 밖으로 나가지 않고, " +
                    "통화를 끝낼 때 구조화된 요약만 hub로 보냅니다(공개 도메인 가능).", fontSize = 11.5.sp, color = AD.sub)
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
