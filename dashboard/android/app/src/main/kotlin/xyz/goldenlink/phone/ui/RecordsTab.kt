package xyz.goldenlink.phone.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import xyz.goldenlink.core.CaseRecord
import xyz.goldenlink.core.DisplayLabels
import xyz.goldenlink.core.HospitalRecordEvent
import xyz.goldenlink.core.RecordDates
import xyz.goldenlink.core.ResponseGroup
import xyz.goldenlink.phone.PhoneModel
import java.time.LocalDate
import java.time.ZoneOffset

// [기록] 탭 — 날짜별 사건 목록과 병원 응답(이송 확정·수용 승인·거부·무응답), 병원별 응답 이력.
// hub 보관소와 변경 순번으로 동기화한 구급차별 로컬 복사본. 오프라인에서도 조회한다.

private fun groupColors(g: ResponseGroup): Pair<Color, Color> = when (g) {
    ResponseGroup.CONFIRMED -> AD.green to AD.greenSoft
    ResponseGroup.APPROVED -> AD.blue to AD.blueSoft
    ResponseGroup.REJECTED -> AD.red to AD.redSoft
    ResponseGroup.NO_REPLY -> AD.ink3 to AD.chip
}

@Composable
fun RecordsTab(m: PhoneModel) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(m.recordSyncStatus, fontSize = 11.sp, color = AD.sub, modifier = Modifier.weight(1f))
            Icon(Icons.Filled.Refresh, "기록 동기화", tint = AD.navy, modifier = Modifier.size(32.dp).clip(CircleShape).clickable { m.syncRecords() }.padding(5.dp))
        }
        if (m.handoverConflict != null) {
            Card {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("다른 기기의 인계확인서 수정과 겹칩니다. 내 수정은 기기에 보관되어 있습니다.", fontSize = 12.sp, color = AD.ink)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("서버 기록 사용", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.blue, modifier = Modifier.clickable { m.resolveHandover(false) })
                        Text("내 수정으로 다시 저장", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = AD.blue, modifier = Modifier.clickable { m.resolveHandover(true) })
                    }
                }
            }
        }
        RecordsContent(m)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecordsContent(m: PhoneModel) {
    @Suppress("UNUSED_EXPRESSION") m.recordsRev  // 기록이 바뀌면 다시 읽는다
    val dates = m.records.dates()
    if (dates.isEmpty()) {
        StatusPanel(Icons.Filled.History, AD.gray, "아직 기록이 없습니다", "사건이 진행되면 병원 응답 이력이 날짜별로 여기에 쌓입니다.")
        return
    }
    val today = RecordDates.of(System.currentTimeMillis())
    var selected by remember { mutableStateOf(if (today in dates) today else dates.last()) }
    if (selected !in dates) selected = dates.last()
    var picking by remember { mutableStateOf(false) }
    var openCase by remember { mutableStateOf<String?>(null) }
    var responseLog by remember { mutableStateOf<CaseRecord?>(null) }
    val cases = m.records.load(selected)
    val idx = dates.indexOf(selected)

    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ArrowButton(left = true, enabled = idx > 0) { selected = dates[idx - 1] }
            Text(selected, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                modifier = Modifier.weight(1f).clip(CircleShape).background(AD.blueSoft).clickable { picking = true }.padding(vertical = 10.dp))
            ArrowButton(left = false, enabled = idx < dates.lastIndex) { selected = dates[idx + 1] }
        }
        Text("사건 ${cases.size}건", fontSize = 12.sp, color = AD.ink3, modifier = Modifier.padding(horizontal = 4.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(cases, key = { it.caseId }) { c ->
                CaseCard(c, expanded = openCase == c.caseId, onToggle = { openCase = if (openCase == c.caseId) null else c.caseId }, onMore = { responseLog = c })
            }
            item { Spacer(Modifier.size(8.dp)) }
        }
    }

    if (picking) {
        val state = rememberDatePickerState(
            initialSelectedDateMillis = LocalDate.parse(selected).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli(),
            selectableDates = object : SelectableDates {
                // 기록이 있는 날짜만 고를 수 있다
                override fun isSelectableDate(utcTimeMillis: Long): Boolean =
                    java.time.Instant.ofEpochMilli(utcTimeMillis).atZone(ZoneOffset.UTC).toLocalDate().toString() in dates
            },
        )
        DatePickerDialog(onDismissRequest = { picking = false }, confirmButton = {
            TextButton({
                state.selectedDateMillis?.let { ms -> java.time.Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate().toString().takeIf { it in dates }?.let { selected = it } }
                picking = false
            }) { Text("선택") }
        }, dismissButton = { TextButton({ picking = false }) { Text("취소") } }) { DatePicker(state) }
    }
    responseLog?.let { c -> CaseResponseLog(c) { responseLog = null } }
}

@Composable
private fun ArrowButton(left: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Row(Modifier.size(40.dp).clip(CircleShape).background(AD.chip).clickable(enabled = enabled, onClick = onClick),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Icon(if (left) Icons.AutoMirrored.Filled.KeyboardArrowLeft else Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = if (enabled) AD.navy else AD.control)
    }
}

/** 사건 하나 — 접힌 상태엔 시각·증상·응답 집계, 펼치면 응답 그룹별 병원 */
@Composable
private fun CaseCard(c: CaseRecord, expanded: Boolean, onToggle: () -> Unit, onMore: () -> Unit) {
    Card {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.clickable(onClick = onToggle), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text("${RecordDates.timeOf(c.startedAt)}  ${c.symptom ?: c.expectedDiagnosis ?: "증상 미상"}", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy, maxLines = 2)
                    Text(listOfNotNull(c.ambulanceName, "병원 ${c.hospitals.size}곳").joinToString(" · "), fontSize = 12.sp, color = AD.ink3)
                }
                c.ktasLevel?.let { Pill("KTAS $it", ktasColor(it), ktasSoft(it), bold = true) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (g in ResponseGroup.entries) {
                    val n = c.count(g)
                    if (n > 0) { val (fg, bg) = groupColors(g); Pill("${g.label} $n", fg, bg, bold = true) }
                }
            }
            if (expanded) {
                for (g in ResponseGroup.entries) {
                    val list = c.hospitals.filter { it.group == g }
                    if (list.isEmpty()) continue
                    val (fg, bg) = groupColors(g)
                    Text("${g.label} ${list.size}곳", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg)
                    for (h in if (g == ResponseGroup.NO_REPLY) list.take(3) else list) {
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(bg).padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(h.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = AD.ink, modifier = Modifier.weight(1f), maxLines = 1)
                            if (g == ResponseGroup.REJECTED) Text(DisplayLabels.reject(h.rejectReason), fontSize = 12.sp, color = fg)
                        }
                    }
                }
                Row(Modifier.fillMaxWidth().clickable(onClick = onMore).padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("더보기 · 전체 병원 응답 이력", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AD.blue, modifier = Modifier.weight(1f))
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = AD.blue)
                }
            }
        }
    }
}

/** 현재 응답 상태별 전체 병원과, 상태가 바뀌기 전의 승인·거절까지 함께 보존한 이력 */
@Composable
private fun CaseResponseLog(c: CaseRecord, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().background(AD.bg).safeDrawingPadding()) {
            Row(Modifier.fillMaxWidth().background(AD.white).padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("닫기", color = AD.ink3, modifier = Modifier.clickable(onClick = onClose))
                Spacer(Modifier.weight(1f))
                Text("전체 병원 응답 이력", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                Spacer(Modifier.weight(1f))
                Spacer(Modifier.width(28.dp))
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("${c.date} ${RecordDates.timeOf(c.startedAt)} · ${c.symptom ?: c.expectedDiagnosis ?: "증상 미상"}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = AD.ink)
                if (c.legacyImport == true) Text("기존 기기에서 이관한 기록으로, 이관 전 응답 변경 이력은 포함되지 않을 수 있습니다.", fontSize = 12.sp, color = AD.sub)
                for (group in ResponseGroup.entries) {
                    val hospitals = c.hospitals.filter { it.group == group }
                    if (hospitals.isEmpty()) continue
                    val (fg, _) = groupColors(group)
                    Text("${group.label} ${hospitals.size}곳", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = fg)
                    for (h in hospitals) {
                        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.white).border(1.dp, AD.line, RoundedCornerShape(12.dp)).padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(h.name, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                            Text(group.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg)
                            if (group == ResponseGroup.REJECTED) Text("사유: ${DisplayLabels.reject(h.rejectReason)}", fontSize = 12.sp, color = AD.ink)
                            val events = (c.events ?: emptyList()).filter { it.hospitalId == h.hospitalId }
                            if (events.isEmpty()) Text(if (group == ResponseGroup.NO_REPLY) "기록된 병원 응답이 없습니다." else "상세 응답 이력이 없습니다.", fontSize = 12.sp, color = AD.sub)
                            else for (e in events) RecordEventRow(e)
                        }
                    }
                }
                val others = (c.events ?: emptyList()).filter { e -> c.hospitals.none { it.hospitalId == e.hospitalId } }
                if (others.isNotEmpty()) {
                    Text("기타 병원 응답 이력", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = AD.ink3)
                    for (e in others) Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.white).border(1.dp, AD.line, RoundedCornerShape(12.dp)).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(e.hospitalId, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = AD.ink)
                        RecordEventRow(e)
                    }
                }
            }
        }
    }
}

@Composable
private fun RecordEventRow(e: HospitalRecordEvent) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(e.label + " · " + e.actor, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AD.ink)
        Text(e.timestamp, fontSize = 11.sp, color = AD.sub)
        e.reason?.let { Text(DisplayLabels.reject(it), fontSize = 12.sp, color = AD.ink) }
    }
}
