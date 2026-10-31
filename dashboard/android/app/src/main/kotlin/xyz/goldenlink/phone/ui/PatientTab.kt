package xyz.goldenlink.phone.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.MedicalServices
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.DisplayLabels
import xyz.goldenlink.core.Handover
import xyz.goldenlink.core.PatientInfo
import kotlinx.coroutines.launch
import xyz.goldenlink.phone.PhoneModel

// [환자 정보] 탭 — 아이패드 구급차 앱의 같은 이름 화면(CallSummaryCard · 추가 정보 · HandoverCard)을 세로 한 열로 옮겼다.
// 위부터: 통화 요약·구조화(+수정·확인) → 추가 정보 전송 → 인계확인서. 통화 요약은 AI, 병원에 가는 값은 구급대원이 확인한 값이다.

fun ktasColor(k: Int): Color = when (k) {
    1 -> Color(0xFFD93025); 2 -> Color(0xFFE8590C); 3 -> Color(0xFFC75B00); 4 -> Color(0xFF4E8B1F); else -> Color(0xFF168A55)
}

fun ktasSoft(k: Int): Color = when (k) { 1, 2 -> AD.redSoft; 3 -> AD.orangeSoft; else -> AD.greenSoft }

/** 중증도 알약 색·문구 — Theme.severity */
private fun severity(tag: String?): Triple<Color, Color, String> = when (tag) {
    "high" -> Triple(AD.redSoft, AD.red, "중증 의심")
    "medium" -> Triple(AD.orangeSoft, AD.orange, "중등도 의심")
    "low" -> Triple(AD.greenSoft, AD.green, "경증 의심")
    else -> Triple(AD.chip, AD.ink3, "중증도 미상")
}

@Composable
fun PatientTab(m: PhoneModel) {
    val p = m.patient
    if (p == null) {
        // 통화 요약이 오기 전 — 지금 뭘 하는 단계인지만 보여 준다(빈 서식을 보여주지 않는다)
        when {
            !m.hasIncident -> StatusPanel(Icons.Filled.DirectionsCar, AD.gray, "출동 대기 중", "새 사건이 들어오면 자동으로 환자 정보 화면으로 넘어갑니다.")
            m.phase == AmbulancePhase.dispatching -> StatusPanel(Icons.Filled.LocalShipping, AD.blue, "현장으로 이송 중",
                "사고 현장으로 이동하고 있습니다. 현장에 도착하면 상황 판단으로 넘어갑니다.", pulse = true)
            else -> StatusPanel(Icons.Filled.MedicalServices, AD.orange, "상황 판단 중",
                if (m.status?.state == "calling") "통화 내용을 받아 환자 정보를 구조화하고 있습니다."
                else "현장 확인 중입니다. 통화가 요약되면 환자 정보가 올라옵니다.", pulse = m.status?.state == "calling")
        }
        return
    }
    // 가운데(통화 요약)가 기본 — 왼쪽에 외상, 오른쪽에 인계확인서
    val pager = rememberPagerState(initialPage = 1) { PAGES.size }
    val scope = rememberCoroutineScope()
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        PageBar(pager.currentPage) { scope.launch { pager.animateScrollToPage(it) } }
        HorizontalPager(pager, Modifier.weight(1f), pageSpacing = 12.dp, verticalAlignment = Alignment.Top) { page ->
            when (page) {
                0 -> BodyPage(m, p)
                1 -> Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    SummaryCard(m, p)
                    ExtraNoteCard(m, p)
                    Spacer(Modifier.size(8.dp))
                }
                else -> Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    HandoverCard(m, p)
                    Spacer(Modifier.size(8.dp))
                }
            }
        }
    }
}

private val PAGES = listOf("외상", "통화 요약", "인계확인서")

/** 가로로 밀어 넘기는 세 페이지의 표시줄 — 누르면 그 페이지로 간다 */
@Composable
private fun PageBar(current: Int, onSelect: (Int) -> Unit) {
    // 아래 탭바(알약)와 겹쳐 보이지 않게 밑줄 탭으로 — 배경 없이 글자 + 선택된 곳에만 파란 밑줄
    Row(Modifier.fillMaxWidth().drawBehind { drawLine(AD.line, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx()) }) {
        PAGES.forEachIndexed { i, title ->
            val on = i == current
            Column(Modifier.weight(1f).clickable { onSelect(i) }, horizontalAlignment = Alignment.CenterHorizontally) {
                Text(title, fontSize = 14.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium, color = if (on) AD.blue else AD.muted,
                    textAlign = TextAlign.Center, modifier = Modifier.padding(vertical = 8.dp))
                Box(Modifier.fillMaxWidth().height(2.5.dp).background(if (on) AD.blue else Color.Transparent))
            }
        }
    }
}

// ── 통화 요약 · 구조화 ──

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SummaryCard(m: PhoneModel, p: PatientInfo) {
    var showEdit by remember { mutableStateOf(false) }
    var showTranscript by remember { mutableStateOf(false) }
    Card {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("통화 요약 · 구조화", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                }
                Text("수정", color = AD.blue, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.clip(CircleShape).background(AD.blueSoft).clickable { showEdit = true }.padding(horizontal = 14.dp, vertical = 7.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Pill("AI 처리", AD.blue, AD.blueSoft, bold = true)
                if (p.confirmedBy == "paramedic") Pill("구급대원 확인", AD.green, AD.greenSoft, bold = true)
                else Pill("확인 전", AD.orange, AD.orangeSoft, bold = true)
                if ((p.callRound ?: 1) > 1) Pill("${p.callRound}차 통화로 갱신", AD.orange, AD.orangeSoft, bold = true)
            }
            Field("예상 병명") { Text(p.expectedDiagnosis ?: "—", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = AD.navy) }
            Field("증상") {
                val s = p.injuryStatus ?: emptyList()
                if (s.isEmpty()) Text("—", fontSize = 12.sp, color = AD.muted)
                else FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) { s.forEach { Pill(it) } }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                val (bg, fg, label) = severity(p.severityTag)
                Pill(label, fg, bg, bold = true)
                p.ktasLevel?.let { Pill("KTAS $it", ktasColor(it), ktasSoft(it), bold = true) }
                val line = listOfNotNull(p.patient, p.chiefComplaint, p.consciousness?.let { "의식 $it" }).joinToString(" · ")
                if (line.isNotEmpty()) Text(line, fontSize = 12.sp, color = AD.ink3)
            }
            val onset = listOfNotNull(p.onset?.let { "발생 $it" }, p.requiredDepartment?.let { "필요 진료과 $it" }).joinToString(" · ")
            if (onset.isNotEmpty()) Text(onset, fontSize = 12.sp, color = AD.sub)
            p.vitals?.lastOrNull()?.text?.takeIf { it.isNotEmpty() }?.let { v ->
                Text(buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = AD.navy)) { append("활력징후  ") }
                    append(v)
                    if ((p.vitals?.size ?: 0) > 1) withStyle(SpanStyle(color = AD.muted)) { append("  (측정 ${p.vitals?.size}회 중 최근)") }
                }, fontSize = 12.sp, color = AD.ink3)
            }
            p.previousCalls?.takeIf { it.isNotEmpty() }?.let { prev ->
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(AD.chip).padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    prev.forEach { u ->
                        Text("${u.callRound}차 통화 · ${severity(u.severityTag).third} · ${u.expectedDiagnosis ?: ""}${u.ktasLevel?.let { " · KTAS $it" } ?: ""}",
                            fontSize = 11.5.sp, color = AD.sub)
                    }
                }
            }
            val lines = m.transcriptLines
            if (lines.isNotEmpty()) {
                Text(if (showTranscript) "자막 접기" else "자막 ${lines.size}줄", color = AD.blue, fontSize = 11.sp, fontWeight = FontWeight.Medium,
                    modifier = Modifier.clip(CircleShape).background(AD.blueSoft).clickable { showTranscript = !showTranscript }.padding(horizontal = 10.dp, vertical = 3.dp))
                if (showTranscript) {
                    Column(Modifier.fillMaxWidth().heightIn(max = 140.dp).clip(RoundedCornerShape(10.dp)).background(AD.chip).padding(8.dp)
                        .verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        lines.takeLast(30).forEach { Text(it, fontSize = 12.sp, color = AD.ink) }
                    }
                }
            }
            // 맞으면 한 번에 확인 — 수정 없이 hub에 "구급대원 확인"만 알린다
            if (p.confirmedBy != "paramedic") {
                Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp)).background(AD.green)
                    .clickable { m.sendPatientOverride(null, null, null, null, null) },
                    horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                    Text("맞습니다 · 확인", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
    if (showEdit) SummaryEditDialog(m, p) { showEdit = false }
}

@Composable
private fun Field(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, fontSize = 11.5.sp, color = AD.sub)
        content()
    }
}

/** 통화 요약 확인·수정 — 바뀐 칸만 hub `patient_override`로 보낸다. 아무 칸도 안 고치면 "수정 없이 확인". 순위 칸이 바뀌면 hub가 다시 매칭한다 */
@Composable
private fun SummaryEditDialog(m: PhoneModel, p: PatientInfo, onClose: () -> Unit) {
    var diagnosis by remember { mutableStateOf(p.expectedDiagnosis ?: "") }
    var symptoms by remember { mutableStateOf((p.injuryStatus ?: emptyList()).joinToString(", ")) }
    var ktas by remember { mutableStateOf(p.ktasLevel ?: 0) }
    var department by remember { mutableStateOf(p.requiredDepartment ?: "") }
    var complaint by remember { mutableStateOf(p.chiefComplaint ?: "") }

    val symptomList = symptoms.split(',', ';', '\n').map { it.trim() }.filter { it.isNotEmpty() }
    // 예상 병명은 hub가 빈 값을 받지 않는다 — 지웠으면 보내지 않는다
    val diagnosisChanged = diagnosis.trim().isNotEmpty() && diagnosis.trim() != (p.expectedDiagnosis ?: "")
    val symptomsChanged = symptomList != (p.injuryStatus ?: emptyList<String>())
    val ktasChanged = ktas != 0 && ktas != p.ktasLevel
    val deptChanged = department.trim() != (p.requiredDepartment ?: "")
    val complaintChanged = complaint.trim() != (p.chiefComplaint ?: "")

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.safeDrawingPadding().padding(12.dp).clip(cardShape).background(AD.bg).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("취소", color = AD.ink3, modifier = Modifier.clickable(onClick = onClose))
                Spacer(Modifier.weight(1f))
                Text("통화 요약 확인·수정", fontWeight = FontWeight.Bold, color = AD.navy, fontSize = 16.sp)
                Spacer(Modifier.weight(1f))
                Text("확인·전송", color = AD.blue, fontWeight = FontWeight.Bold, modifier = Modifier.clickable {
                    if (m.sendPatientOverride(
                            expectedDiagnosis = if (diagnosisChanged) diagnosis.trim() else null,
                            injuryStatus = if (symptomsChanged) symptomList else null,
                            ktasLevel = if (ktasChanged) ktas else null,
                            requiredDepartment = if (deptChanged) department.trim() else null,
                            chiefComplaint = if (complaintChanged) complaint.trim() else null)) onClose()
                })
            }
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(diagnosis, { diagnosis = it }, label = { Text("예상 병명") }, modifier = Modifier.fillMaxWidth(),
                    supportingText = { if (diagnosis.isBlank()) Text("비울 수 없습니다 — 그대로 두려면 손대지 않아도 됩니다") })
                OutlinedTextField(symptoms, { symptoms = it }, label = { Text("증상 (쉼표로 구분)") }, modifier = Modifier.fillMaxWidth())
                Text("KTAS", fontSize = 12.sp, color = AD.sub)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (k in 0..5) {
                        val on = ktas == k
                        Text(if (k == 0) "—" else "$k", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = if (on) Color.White else AD.ink3,
                            modifier = Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(if (on) AD.blue else AD.chip)
                                .clickable { ktas = k }.padding(vertical = 10.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    }
                }
                OutlinedTextField(department, { department = it }, label = { Text("필요 진료과") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(complaint, { complaint = it }, label = { Text("주 호소") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        }
    }
}

// ── 추가 정보 ──

/** 통화 요약에 없는 것(보호자 동승·복용약·특이사항)을 구급대원이 적어 후보 병원들에 보낸다 */
@Composable
private fun ExtraNoteCard(m: PhoneModel, p: PatientInfo) {
    var text by remember { mutableStateOf("") }
    // 인계확인서·외상 도해 처치는 각자 자리에서 따로 보이므로 여기서는 직접 적은 것만 센다
    val mine = (p.extraNotes ?: emptyList()).filter { !it.text.startsWith("[인계확인서]") && !it.text.startsWith("[처치]") }
    Card {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Column {
                Text("추가 정보", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
            }
            mine.takeLast(3).forEach { Text("· ${it.text}", fontSize = 12.sp, color = AD.ink3) }
            OutlinedTextField(text, { text = it }, modifier = Modifier.fillMaxWidth(), minLines = 2, maxLines = 4,
                placeholder = { Text("예: 보호자 동승, 와파린 복용 중") })
            Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp))
                .background(if (text.isBlank() || m.paused) AD.control else AD.blue)
                .clickable(enabled = text.isNotBlank()) { if (m.sendExtraNote(text)) text = "" },
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.AutoMirrored.Filled.Send, null, tint = Color.White, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Text("병원에 전달", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

// ── 인계확인서 ──

@Composable
private fun HandoverCard(m: PhoneModel, p: PatientInfo) {
    val caseId = m.caseId
    var edits by remember(caseId) { mutableStateOf(m.settings.handoverEdits(caseId)) }
    var showSheet by remember { mutableStateOf(false) }
    val auto = Handover.auto(p, m.confirmed, m.identity?.name, m.apid, m.phaseTimes.toMap(), m.mySim?.incident, m.incidentAddress, m.bodyEdits.careLines)
    val values = auto + edits
    fun value(id: String) = (values[id] ?: "").trim()

    // 서식에서 여섯 칸(기도·호흡·순환·약품·고정·기타)으로 나뉜 처치를 카드에서는 한 줄씩으로 묶는다
    val careText = Handover.careFieldIds.flatMap { id ->
        val v = value(id)
        val label = Handover.field(id)?.label
        if (v.isEmpty() || label == null) emptyList() else v.split(", ").map { it.trim() }.filter { it.isNotEmpty() }.map { "$label $it" }
    }.joinToString("\n")
    val sentCount = (p.extraNotes ?: emptyList()).count { it.text.startsWith("[인계확인서]") }

    Card {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("인계확인서", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                }
                Row(Modifier.clip(CircleShape).background(AD.blueSoft).clickable { showSheet = true }.padding(horizontal = 12.dp, vertical = 7.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Icon(Icons.Filled.EditNote, null, tint = AD.blue, modifier = Modifier.size(16.dp))
                    Text("수정", color = AD.blue, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                }
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for (f in Handover.fields.filter { it.summary }) {
                    // 처치 줄은 "기타 소견" 바로 위에 둔다
                    if (f.id == "notes" && careText.isNotEmpty()) SummaryRow("처치", careText, tag = "자동")
                    val v = value(f.id)
                    SummaryRow(if (f.id == "notes") "기타 소견(증상·발생)" else f.label, v.ifEmpty { "미입력" }, empty = v.isEmpty(),
                        tag = if (f.id in edits) "수정" else if (v.isEmpty()) null else "자동")
                }
            }
            if (sentCount > 0) Pill("병원에 전달 ${sentCount}회", AD.green, AD.greenSoft, bold = true)
        }
    }
    if (showSheet) HandoverSheet(m, auto, edits, caseId, onSaved = { edits = it }) { showSheet = false }
}

@Composable
private fun SummaryRow(label: String, text: String, empty: Boolean = false, tag: String? = null) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        Text(label, fontSize = 11.5.sp, color = AD.sub, modifier = Modifier.width(86.dp))
        Text(text, fontSize = 13.sp, fontWeight = if (empty) FontWeight.Normal else FontWeight.SemiBold, color = if (empty) AD.muted else AD.ink,
            modifier = Modifier.weight(1f))
        if (tag != null) Pill(tag, if (tag == "수정") AD.orange else AD.blue, if (tag == "수정") AD.orangeSoft else AD.blueSoft)
    }
}

/** 인계확인서 전체 — 전체 화면. 칸마다 이름(필수는 *)과 입력. 자동으로 채운 칸에는 "자동", 고친 칸에는 "수정" 표시.
 *  [저장 · 병원에 전달]을 누르면 자동값과 다른 칸만 기기에 저장하고 적힌 칸 전체를 한 덩이 글로 병원에도 보낸다 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun HandoverSheet(m: PhoneModel, auto: Map<String, String>, edits: Map<String, String>, caseId: String?,
                          onSaved: (Map<String, String>) -> Unit, onClose: () -> Unit) {
    val draft = remember { mutableStateMapOf<String, String>().apply { putAll(auto); putAll(edits) } }
    // 서식을 연 뒤 사람이 손댄 칸 — 열어 둔 채 새 통화·출동 소식이 와도 이 칸은 덮지 않는다
    val touched = remember { mutableStateListOf<String>() }
    LaunchedEffect(auto) {
        for ((id, v) in auto) if (id !in touched && id !in edits) draft[id] = v
    }
    fun set(id: String, v: String) { draft[id] = v; if (id !in touched) touched += id }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().background(AD.bg).safeDrawingPadding()) {
            Row(Modifier.fillMaxWidth().background(AD.white).padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("취소", color = AD.ink3, modifier = Modifier.clickable(onClick = onClose))
                Column(Modifier.weight(1f)) {
                    Text("출동 및 처치 기록지", fontSize = 15.sp, fontWeight = FontWeight.Black, color = AD.navy)
                }
                Text("자동값", color = AD.ink3, fontSize = 13.sp, modifier = Modifier.clickable {
                    draft.clear(); draft.putAll(auto); touched.clear()
                })
                Text("저장·전달", color = if (m.paused) AD.gray else AD.blue, fontWeight = FontWeight.Bold, modifier = Modifier.clickable(enabled = !m.paused) {
                    // 자동값과 다른 칸만 저장해야 통화가 갱신될 때 안 고친 칸이 따라 바뀐다
                    val out = Handover.fields.mapNotNull { f ->
                        val v = (draft[f.id] ?: "").trim()
                        if (v != (auto[f.id] ?: "").trim()) f.id to v else null
                    }.toMap()
                    m.settings.saveHandoverEdits(caseId, out)
                    caseId?.let { m.snapshotCase(it) }
                    onSaved(out)
                    m.sendExtraNote(Handover.message(draft))
                    onClose()
                })
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                for (section in 1..5) {
                    Text(Handover.sections[section - 1], fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.white).border(1.dp, AD.line, RoundedCornerShape(12.dp)).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        for (f in Handover.fields.filter { it.section == section }) {
                            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Text(f.label + if (f.required) " *" else "", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = AD.ink3)
                                    if (f.id in edits) Pill("수정", AD.orange, AD.orangeSoft)
                                    else if (!auto[f.id].isNullOrEmpty()) Pill("자동", AD.blue, AD.blueSoft)
                                }
                                when (val k = f.kind) {
                                    is Handover.Kind.Choice -> FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                        for (o in k.options) {
                                            val on = draft[f.id] == o
                                            Text(o, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = if (on) Color.White else AD.ink3,
                                                modifier = Modifier.clip(CircleShape).background(if (on) AD.blue else AD.chip)
                                                    .clickable { set(f.id, if (on) "" else o) }.padding(horizontal = 12.dp, vertical = 7.dp))
                                        }
                                    }
                                    else -> OutlinedTextField(draft[f.id] ?: "", { set(f.id, it) }, modifier = Modifier.fillMaxWidth(),
                                        singleLine = k is Handover.Kind.Text, minLines = if (k is Handover.Kind.Multiline) 2 else 1, maxLines = 6)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
