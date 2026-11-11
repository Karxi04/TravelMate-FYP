import java.util.Base64

plugins {
    id("com.android.application")
    // START: FlutterFire Configuration
    id("com.google.gms.google-services") apply false
    // END: FlutterFire Configuration
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val startupDefines = (project.findProperty("dart-defines") as? String).orEmpty()
    .split(",").filter { it.isNotBlank() }
    .map { String(Base64.getDecoder().decode(it), Charsets.UTF_8) }
val emulatorBuild = startupDefines.contains("USE_FIREBASE_EMULATOR=true")
val privateReviewDemo = startupDefines.contains("PRIVATE_REVIEW_DEMO=true")
val pushTestBuild = startupDefines.contains("PUSH_TEST_BUILD=true")
if (privateReviewDemo && !emulatorBuild) {
    throw GradleException("The private review demo requires Firebase emulators.")
}
if (startupDefines.any { it.startsWith("PUSH_TEST_BUILD=") && it !in listOf("PUSH_TEST_BUILD=true", "PUSH_TEST_BUILD=false") }) {
    throw GradleException("PUSH_TEST_BUILD must be true or false.")
}
if (pushTestBuild && (emulatorBuild || gradle.startParameter.taskNames.any { !it.contains("debug", ignoreCase = true) })) {
    throw GradleException("Push test builds require Android debug without Firebase emulators.")
}
if (startupDefines.any { it.startsWith("USE_FIREBASE_EMULATOR=") && it !in listOf("USE_FIREBASE_EMULATOR=true", "USE_FIREBASE_EMULATOR=false") }) {
    throw GradleException("USE_FIREBASE_EMULATOR must be true or false.")
}
if (emulatorBuild && gradle.startParameter.taskNames.any { !it.contains("debug", ignoreCase = true) }) {
    throw GradleException("Firebase Emulator builds must be explicitly debug builds.")
}
if (!emulatorBuild && !pushTestBuild) apply(plugin = "com.google.gms.google-services")

if (gradle.startParameter.taskNames.any { it.contains("release", ignoreCase = true) }) {
    val defines = (project.findProperty("dart-defines") as? String).orEmpty()
        .split(",").filter { it.isNotBlank() }
        .map { String(Base64.getDecoder().decode(it), Charsets.UTF_8) }
    if (!defines.contains("STANDALONE_MODE=true") &&
        defines.none { it.startsWith("API_BASE_URL=") && it.substringAfter("=").isNotBlank() }) {
        throw GradleException(
            "Cloud release requires --dart-define=API_BASE_URL=https://YOUR-BACKEND; " +
                "use --dart-define=STANDALONE_MODE=true only for an explicit FYP demo."
        )
    }
}

android {
    namespace = "com.example.travelmate_traveller"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        manifestPlaceholders["travelMateLabel"] = when {
            privateReviewDemo -> "TravelMate Private FYP Preview"
            pushTestBuild -> "TravelMate Push Sandbox"
            emulatorBuild -> "TravelMate Hermetic Test"
            else -> "TravelMate"
        }
        applicationId = if ((emulatorBuild && !privateReviewDemo) || pushTestBuild) "org.travelmate.hermetic.travelmate_hermetic" else "com.example.travelmate_traveller"
        buildConfigField("boolean", "USE_FIREBASE_EMULATOR", emulatorBuild.toString())
        buildConfigField("boolean", "PRIVATE_REVIEW_DEMO", privateReviewDemo.toString())
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildFeatures { buildConfig = true }
    if (emulatorBuild) {
        sourceSets.getByName("debug") {
            manifest.srcFile("src/emulator/AndroidManifest.xml")
            res.srcDir("src/emulator/res")
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

dependencies { testImplementation("junit:junit:4.12") }
