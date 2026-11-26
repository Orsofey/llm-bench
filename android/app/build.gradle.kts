plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.orsofey.llmbench"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.orsofey.llmbench"
        minSdk = 24
        targetSdk = 36
        versionCode = 2
        versionName = "1.2.0"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            isDebuggable = false
        }
        debug {
            isMinifyEnabled = false
            isShrinkResources = false
            isDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    buildFeatures {
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf("META-INF/LICENSE*", "META-INF/NOTICE*")
    }
}

val pythonCommand = providers.gradleProperty("llmBenchPython").orElse("python")

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(pythonCommand.get())
    }
}

// Единый источник правды: Python-движок и web/ берутся из корня проекта.
tasks.register<Sync>("syncPythonEngine") {
    from(rootDir.parentFile) {
        include("app.py", "bench.py", "verify.py", "public_bench.py", "model_catalog.py", "android_bridge.py")
        include("web/**")
        include("public_data/**")
    }
    into(layout.projectDirectory.dir("src/main/python"))
}

tasks.named("preBuild") {
    dependsOn("syncPythonEngine")
}

tasks.configureEach {
    if (name == "mergeDebugPythonSources" || name == "mergeReleasePythonSources") {
        dependsOn("syncPythonEngine")
    }
}
