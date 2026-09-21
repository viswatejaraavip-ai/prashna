import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.google.gms.google-services")
}

// ---------------------------------------------------------------------------
// Firebase config guard. google-services.json is per-project and gitignored.
// Fail early with instructions instead of the plugin's cryptic error.
// ---------------------------------------------------------------------------
val googleServicesJson = file("google-services.json")
if (!googleServicesJson.exists()) {
    throw GradleException(
        """
        |
        |  Missing android/app/google-services.json
        |
        |  Prashna uses Firebase (phone OTP, Google sign-in, FCM). Download the
        |  config for Android package 'com.prashna.app' from the Firebase console
        |  (Project settings > Your apps) and save it as android/app/google-services.json.
        |  Full steps: docs/launch/ANDROID.md ("Firebase").
        |
        |  UI-only local build without a Firebase project:
        |      cp android/app/google-services.example.json android/app/google-services.json
        |  (sign-in and push will not work with the example file).
        |""".trimMargin()
    )
}

// Optional release signing from android/keystore.properties (gitignored).
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.udhyath.app"
    compileSdk = 36

    defaultConfig {
        // Two apps cannot share a package name on Play, so a fork must
        // change this -- and its Play Billing products and the backend's
        // PLAY_PACKAGE_NAME along with it. Pass -PapplicationId=... .
        applicationId = (project.findProperty("applicationId") as String?)
            ?: "com.prashna.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // WhatsApp support number placeholder (digits only, with country code).
        buildConfigField("String", "SUPPORT_WHATSAPP", "\"919000000000\"")
        // AGPL section 13: the app shows this to users in Settings.
        // A fork that changes the code must point it at its own repo.
        buildConfigField("String", "SOURCE_URL",
            "\"" + (project.findProperty("sourceUrl") as String?
                ?: "https://github.com/viswatejaraavip-ai/prashna") + "\"")
    }

    signingConfigs {
        if (keystoreProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // Default: emulator loopback to a backend on the dev machine.
            // Real phone over USB: `adb reverse tcp:8000 tcp:8000` and build
            // with -PapiBase=http://localhost:8000 (or point at a Cloud Run URL).
            val apiBase = (project.findProperty("apiBase") as String?) ?: "http://10.0.2.2:8000"
            buildConfigField("String", "API_BASE", "\"$apiBase\"")
        }
        release {
            // Live Cloud Run URL until a custom domain is mapped; override with -PreleaseApiBase=...
            val releaseApiBase = (project.findProperty("releaseApiBase") as String?)
                ?: "https://your-service.run.app"   // a fork MUST pass -PreleaseApiBase
            buildConfigField("String", "API_BASE", "\"$releaseApiBase\"")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    androidResources {
        // Only ship our five UI languages (+ base) — keeps library strings
        // from advertising locales we don't support.
        localeFilters += listOf("hi", "te", "ta", "kn", "ml")
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.05.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-process:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.9")
    implementation("androidx.datastore:datastore-preferences:1.1.7")
    implementation("androidx.work:work-runtime-ktx:2.10.1")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    implementation(platform("com.google.firebase:firebase-bom:33.16.0"))
    implementation("com.google.firebase:firebase-auth")
    implementation("com.google.firebase:firebase-messaging")

    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")

    implementation("com.android.billingclient:billing-ktx:8.0.0")

    testImplementation("junit:junit:4.13.2")
}

// StringsCompletenessTest reads res/ from disk: make resource edits re-run unit tests.
tasks.withType<Test>().configureEach {
    inputs.dir("src/main/res").withPathSensitivity(PathSensitivity.RELATIVE)
}
