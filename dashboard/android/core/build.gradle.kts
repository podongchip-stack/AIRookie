// 순수 Kotlin(JVM) — 안드로이드 없이 PC에서 테스트된다. 앱이 그대로 쓴다.
plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.kotlin.plugin.serialization")
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    // onnxruntime Java API — 앱은 onnxruntime-android(같은 ai.onnxruntime 패키지)를 넣고, PC 테스트는 데스크톱판으로 같은 코드를 돌린다
    compileOnly("com.microsoft.onnxruntime:onnxruntime:1.30.0")
    testImplementation("com.microsoft.onnxruntime:onnxruntime:1.30.0")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.3")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
    maxHeapSize = "2g"
    testLogging { events("passed", "skipped", "failed"); showStandardStreams = true; exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
}
