package xyz.goldenlink.phone.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import xyz.goldenlink.phone.HospitalModel

/**
 * 병원 모드 화면(2026-11-04) — 구급대 앱의 실제 통화를 받는 간단한 화면. 상태별로 필요한 것만 보여 준다:
 * 수신 대기(병원명·연결 상태) / 전화 수신(구급대명·받기·거절) / 연결 중(취소 없이 종료) / 통화 중(통화 시간·종료) / 종료 안내(잠깐).
 * 지도·환자 편집 같은 구급대원 화면으로는 가지 않는다.
 */
@Composable
fun HospitalApp(m: HospitalModel, onChangeCode: () -> Unit) {
    val context = LocalContext.current
    var micDenied by remember { mutableStateOf(false) }
    val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) m.accept() else micDenied = true
    }
    MaterialTheme(colorScheme = lightColorScheme(primary = AD.blue, background = AD.bg, surface = AD.white)) {
        Box(Modifier.fillMaxSize().background(AD.bg).safeDrawingPadding().padding(horizontal = 20.dp, vertical = 16.dp)) {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                // 맨 위: 병원 이름과 연결 상태
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("골든링크", fontSize = 18.sp, fontWeight = FontWeight.Black, color = AD.navy)
                    Pill(m.hospitalName ?: m.hospitalId, AD.ink3, AD.white, bold = true, modifier = Modifier.weight(1f, fill = false))
                    Spacer(Modifier.weight(1f))
                    val live = m.connection == xyz.goldenlink.phone.HubSocket.State.LIVE
                    Dot(if (live) AD.green else AD.orange)
                    Text(if (live) "수신 대기" else "연결 중…", fontSize = 12.sp, color = AD.sub)
                }
                val call = m.call
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    when {
                        call == null -> Idle(m, onChangeCode)
                        call.phase == HospitalModel.Phase.INCOMING -> Incoming(call, micDenied,
                            onAccept = {
                                if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) m.accept()
                                else mic.launch(Manifest.permission.RECORD_AUDIO)
                            }, onReject = { m.reject() })
                        else -> InCall(m, call)
                    }
                }
                m.notice?.let {
                    Text(it, fontSize = 14.sp, color = AD.white, textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(AD.navy).padding(12.dp))
                }
            }
        }
    }
}

@Composable
private fun Idle(m: HospitalModel, onChangeCode: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(Icons.Filled.Call, null, tint = AD.blue, modifier = Modifier.size(52.dp))
        Text(m.hospitalName ?: "병원", fontSize = 24.sp, fontWeight = FontWeight.Black, color = AD.navy, textAlign = TextAlign.Center)
        Text("구급대의 전화를 기다리는 중입니다", fontSize = 15.sp, color = AD.sub)
        Spacer(Modifier.height(24.dp))
        Text("접근 코드 변경", fontSize = 13.sp, color = AD.blue, fontWeight = FontWeight.Bold,
            modifier = Modifier.clickable { onChangeCode() }.padding(8.dp))
    }
}

@Composable
private fun Incoming(call: HospitalModel.UiCall, micDenied: Boolean, onAccept: () -> Unit, onReject: () -> Unit) {
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Pill("전화 수신", AD.red, AD.redSoft, bold = true)
        Text(call.ambulanceName ?: "구급대", fontSize = 28.sp, fontWeight = FontWeight.Black, color = AD.navy, textAlign = TextAlign.Center)
        Text("환자 이송 관련 전화입니다", fontSize = 14.sp, color = AD.sub)
        if (micDenied) Text("마이크 권한이 꺼져 있어 받을 수 없습니다. 설정 앱에서 켜 주세요.", fontSize = 13.sp, color = AD.red, textAlign = TextAlign.Center)
        Spacer(Modifier.height(20.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(Modifier.weight(1f).height(76.dp).clip(RoundedCornerShape(20.dp)).background(AD.redSoft).border(2.dp, AD.red, RoundedCornerShape(20.dp))
                .clickable { onReject() }, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.CallEnd, null, tint = AD.red, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(8.dp))
                Text("거절", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = AD.red)
            }
            Row(Modifier.weight(1f).height(76.dp).clip(RoundedCornerShape(20.dp)).background(AD.green).clickable { onAccept() },
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Call, null, tint = Color.White, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(8.dp))
                Text("전화 받기", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
    }
}

@Composable
private fun InCall(m: HospitalModel, call: HospitalModel.UiCall) {
    val connecting = call.phase != HospitalModel.Phase.ACTIVE
    val now = nowEverySecond()
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Pill(if (connecting) "연결 중…" else "통화 중", if (connecting) AD.orange else AD.red, if (connecting) AD.orangeSoft else AD.redSoft, bold = true)
        Text(call.ambulanceName ?: "구급대", fontSize = 28.sp, fontWeight = FontWeight.Black, color = AD.navy, textAlign = TextAlign.Center)
        Text(if (connecting) "음성 연결을 확인하는 중입니다" else mmss(((now - (call.activeSince ?: now)) / 1000).coerceAtLeast(0)),
            fontSize = 32.sp, fontWeight = FontWeight.Bold, color = if (connecting) AD.muted else AD.ink)
        if (!connecting) {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                RoundToggle(if (m.muted) Icons.Filled.MicOff else Icons.Filled.Mic, if (m.muted) "음소거 해제" else "음소거", m.muted) { m.toggleMute() }
                RoundToggle(Icons.Filled.VolumeUp, "스피커", m.speaker) { m.toggleSpeaker() }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth().height(72.dp).clip(RoundedCornerShape(20.dp)).background(AD.red).clickable { m.hangup() },
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.CallEnd, null, tint = Color.White, modifier = Modifier.size(28.dp))
            Spacer(Modifier.width(10.dp))
            Text("통화 종료", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        }
    }
}

@Composable
private fun RoundToggle(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, on: Boolean, onClick: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Box(Modifier.size(56.dp).clip(RoundedCornerShape(28.dp)).background(if (on) AD.blue else AD.chip).clickable { onClick() },
            contentAlignment = Alignment.Center) {
            Icon(icon, label, tint = if (on) Color.White else AD.ink3, modifier = Modifier.size(26.dp))
        }
        Text(label, fontSize = 11.sp, color = AD.sub)
    }
}
