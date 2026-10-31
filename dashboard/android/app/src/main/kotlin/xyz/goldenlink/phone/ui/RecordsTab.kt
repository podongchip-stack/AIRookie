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
import xyz.goldenlink.core.Handover
import xyz.goldenlink.core.RecordDates
import xyz.goldenlink.core.RecordHospital
import xyz.goldenlink.core.ResponseGroup
import xyz.goldenlink.phone.PhoneModel
import java.time.LocalDate
import java.time.ZoneOffset

// [기록] 탭 — 날짜를 고르면 그날의 사건 목록, 사건을 누르면 병원 응답(이송 확정·수용 승인·거부·무응답), 병원을 누르면 그 병원 응답과 사건 인계확인서 전체.
// 이 기기에 쌓인 기록이다. 같은 구급차의 다른 기기와 맞추는 동기화는 hub 보관소가 필요하다(README "기록 동기화 계약").

private fun groupColors(g: ResponseGroup): Pair<Color, Color> = when (g) {
    ResponseGroup.CONFIRMED -> AD.green to AD.greenSoft
    ResponseGroup.APPROVED -> AD.blue to AD.blueSoft
    ResponseGroup.REJECTED -> AD.red to AD.redSoft
    ResponseGroup.NO_REPLY -> AD.ink3 to AD.chip
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsTab(m: PhoneModel) {
    @Suppress("UNUSED_EXPRESSION") m.recordsRev  // 기록이 바뀌면 다시 읽는다
    val dates = m.records.dates()
    if (dates.isEmpty()) {
        StatusPanel(Icons.Filled.History, AD.gray, "아직 기록이 없습니다", "사건이 진행되면 병원 응답과 인계확인서가 날짜별로 여기에 쌓입니다.")
        return
    }
    val today = RecordDates.of(System.currentTimeMillis())
    var selected by remember { mutableStateOf(if (today in dates) today else dates.last()) }
    if (selected !in dates) selected = dates.last()
    var picking by remember { mutableStateOf(false) }
    var openCase by remember { mutableStateOf<String?>(null) }
    var detail by remember { mutableStateOf<Pair<CaseRecord, RecordHospital>?>(null) }
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
                CaseCard(c, expanded = openCase == c.caseId, onToggle = { openCase = if (openCase == c.caseId) null else c.caseId }) { h -> detail = c to h }
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
    detail?.let { (c, h) -> HospitalDetail(c, h) { detail = null } }
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
private fun CaseCard(c: CaseRecord, expanded: Boolean, onToggle: () -> Unit, onHospital: (RecordHospital) -> Unit) {
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
                    Text(g.label, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg)
                    for (h in list) {
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(bg).clickable { onHospital(h) }.padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(h.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = AD.ink, modifier = Modifier.weight(1f), maxLines = 1)
                            if (g == ResponseGroup.REJECTED) Text(DisplayLabels.reject(h.rejectReason), fontSize = 12.sp, color = fg)
                        }
                    }
                }
            }
        }
    }
}

/** 병원 응답 + 사건 인계확인서 전체(읽기 전용) — 인계확인서는 사건 하나에 하나라 병원마다 같고, 응답만 병원 것으로 맨 위에 둔다 */
@Composable
private fun HospitalDetail(c: CaseRecord, h: RecordHospital, onClose: () -> Unit) {
    val (fg, bg) = groupColors(h.group)
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().background(AD.bg).safeDrawingPadding()) {
            Row(Modifier.fillMaxWidth().background(AD.white).padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("닫기", color = AD.ink3, modifier = Modifier.clickable(onClick = onClose))
                Spacer(Modifier.weight(1f))
                Text("${RecordDates.timeOf(c.startedAt)} 사건", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                Spacer(Modifier.weight(1f))
                Spacer(Modifier.width(28.dp))
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(bg).padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(h.group.label, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg)
                    Text(h.name, fontSize = 18.sp, fontWeight = FontWeight.Black, color = AD.navy)
                    if (h.group == ResponseGroup.REJECTED) Text("사유: ${DisplayLabels.reject(h.rejectReason)}", fontSize = 13.sp, color = AD.ink)
                    val dist = listOfNotNull(h.distanceKm?.let { "%.1fkm".format(it) }, h.etaMin?.let { "ETA ${Math.round(it)}분" }).joinToString(" · ")
                    if (dist.isNotEmpty()) Text(dist, fontSize = 12.sp, color = AD.ink3)
                }
                for (section in 1..5) {
                    Text(Handover.sections[section - 1], fontSize = 15.sp, fontWeight = FontWeight.Bold, color = AD.navy)
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.white).border(1.dp, AD.line, RoundedCornerShape(12.dp)).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        for (f in Handover.fields.filter { it.section == section }) {
                            val v = (c.handover[f.id] ?: "").trim()
                            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text(f.label + if (f.required) " *" else "", fontSize = 11.5.sp, color = AD.sub)
                                Text(v.ifEmpty { "미입력" }, fontSize = 14.sp, fontWeight = if (v.isEmpty()) FontWeight.Normal else FontWeight.SemiBold, color = if (v.isEmpty()) AD.muted else AD.ink)
                            }
                        }
                    }
                }
            }
        }
    }
}
