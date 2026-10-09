// The Android app (app/) and its plain-Kotlin logic (core/), which has no
// Android in it so its tests run on any JVM.
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
    }
}
rootProject.name = "server-controller"
include(":core")
// The Android app needs the Android SDK. Leave it out with
// -PcoreOnly=true to build and test only core/ (as on a plain JVM).
if (providers.gradleProperty("coreOnly").orNull != "true") {
    include(":app")
}
