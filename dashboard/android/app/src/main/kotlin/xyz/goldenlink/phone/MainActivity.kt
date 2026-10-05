package xyz.goldenlink.phone

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import xyz.goldenlink.phone.ui.PhoneApp

class MainActivity : ComponentActivity() {
    private val model: PhoneModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (!granted) model.error = "마이크 권한이 꺼져 있습니다. 설정 앱에서 켜 주세요."
            }
            val notify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
            LaunchedEffect(Unit) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) notify.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            LaunchedEffect(model.needsMicPermission) {
                if (model.needsMicPermission > 0) mic.launch(Manifest.permission.RECORD_AUDIO)
            }
            // 통화 중엔 화면을 켜 둔다(시연 중 화면이 꺼져 흐름이 끊기지 않게 — 녹음 자체는 포그라운드 서비스로 이어진다)
            LaunchedEffect(model.call) {
                if (model.call != null) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            PhoneApp(model)
        }
    }
}
