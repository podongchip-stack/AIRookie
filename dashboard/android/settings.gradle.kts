// 골든링크 갤럭시(안드로이드) 앱 — 온디바이스 STT(Qwen3-ASR)·구조화(MF_BERT). 아이폰 앱(dashboard/iphone)과 같은 흐름.
// core: 모델·화면과 무관한 순수 로직(PC에서 ./gradlew :core:test로 Python 원본과 대조) / app: 안드로이드 앱
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven("https://devrepo.kakao.com/nexus/repository/kakaomap-releases/")  // 카카오맵 SDK
    }
}
rootProject.name = "GoldenLinkAndroid"
include(":core", ":app")
