// The Android app: Kotlin and Jetpack Compose, every screen native. Its
// words, colors and agent rules come from core/ and mobile/shared.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Lock-screen alerts need the Firebase project's google-services.json, which
// CI writes from a secret (mobile/README.md). Without it the app builds and
// works; only lock-screen alerts are off.
val hasFirebase = file("google-services.json").exists()
if (hasFirebase) {
    apply(plugin = "com.google.gms.google-services")
}

// One version for both apps: mobile/version.json.
val appVersion: String = Regex("\"app_version\"\\s*:\\s*\"([0-9]+\\.[0-9]+\\.[0-9]+)\"")
    .find(rootProject.file("../version.json").readText())!!.groupValues[1]
val versionNumber: Int = appVersion.split(".").map(String::toInt).let { (a, b, c) -> a * 10000 + b * 100 + c }

android {
    namespace = "io.github.peyoteheadlights.mcsc"
    compileSdk = 36

    defaultConfig {
        // Not tied to the app's name, which may still change.
        applicationId = "io.github.peyoteheadlights.mcsc"
        minSdk = 26
        targetSdk = 36
        versionCode = versionNumber
        versionName = appVersion
        buildConfigField("boolean", "HAS_FIREBASE", hasFirebase.toString())
    }

    // Release signing only where the key is: CI secrets or the PC that
    // builds a release. The key is never in the repository.
    val keystore = System.getenv("ANDROID_KEYSTORE_FILE")
    if (keystore != null) {
        signingConfigs {
            create("release") {
                storeFile = file(keystore)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystore != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    // The words, colors and versions the dashboard generates (mobile/shared).
    sourceSets {
        getByName("main") {
            assets.srcDir(rootProject.file("../shared"))
        }
    }

    lint {
        abortOnError = true
        // Version bumps are chosen on purpose, not by lint.
        disable += setOf("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion")
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(project(":core"))
    implementation(libs.coroutines.android)
    implementation(libs.coroutines.play)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.runtime)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.navigation.compose)
    implementation(libs.core.ktx)
    implementation(libs.biometric)
    implementation(libs.fragment)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    implementation(libs.mlkit.barcode)
    implementation(libs.work.runtime)
    implementation(libs.glance.appwidget)
    implementation(libs.browser)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)
}
