// Everything the app decides that doesn't need Android: reading the pairing
// code, the certificate check, talking to the agent, the wording, the
// server colors and what the widget shows. Tested on a plain JVM.
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

// Built for Java 17 (what Android's tools need) with whichever JDK runs Gradle.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
    api(libs.coroutines.core)
    api(libs.serialization.json)
    api(libs.okhttp)
    testImplementation(libs.junit)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.okhttp.tls)
}

// The tests read the shared files the dashboard generates (mobile/shared).
tasks.test {
    systemProperty("mcsc.shared", rootProject.file("../shared").absolutePath)
}
