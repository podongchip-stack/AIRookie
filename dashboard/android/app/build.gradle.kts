import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "xyz.goldenlink.phone"
    compileSdk = 35

    defaultConfig {
        applicationId = "xyz.goldenlink.phone"
        minSdk = 29  // 갤럭시 S10 이후. 모델(약 4.6GB)을 돌릴 메모리가 있는 기종만 대상
        targetSdk = 35
        versionCode = 1
        versionName = "2.0"
        ndk { abiFilters += listOf("arm64-v8a") }  // 갤럭시는 arm64. x86 에뮬레이터 라이브러리를 빼 APK를 줄인다
        // 카카오맵 네이티브 앱 키 — 저장소에 올리지 않는 local.properties(KAKAO_NATIVE_APP_KEY) 또는 같은 이름의 환경변수에서 읽는다. 없으면 지도 자리에 안내가 뜬다
        val local = rootProject.file("local.properties").takeIf { it.isFile }?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }
        val kakaoKey = local?.getProperty("KAKAO_NATIVE_APP_KEY") ?: System.getenv("KAKAO_NATIVE_APP_KEY") ?: ""
        buildConfigField("String", "KAKAO_NATIVE_APP_KEY", "\"$kakaoKey\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")  // 사내 시연용 설치(스토어 배포 아님)
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    testOptions { unitTests.all { it.useJUnitPlatform() } }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
}

dependencies {
    implementation(project(":core"))
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.30.0")  // PC 대조(check_*.py)와 같은 버전
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.kakao.maps.open:android:2.12.19")  // 카카오맵 SDK v2 — 통화 화면의 후보 병원 지도

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")

    testImplementation("org.junit.jupiter:junit-jupiter:5.11.3")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}
