import java.io.File
import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.1.10"
    id("org.jetbrains.kotlin.plugin.serialization") version "2.1.10"
    id("org.jetbrains.intellij.platform") version "2.10.4"
}

group = "io.orenlab.codeclone"
version = "0.3.9"

val platformVersion = providers.gradleProperty("codeclone.platformVersion").orElse("2025.2.6.1")

val defaultLocalIdeCandidates = listOf(
    "/Applications/PyCharm.app",
    "/Applications/PyCharm Professional.app",
    "/Applications/PyCharm CE.app",
    "/Applications/IntelliJ IDEA.app",
)

fun File.readIdeVersion(): String? = runCatching {
    ProcessBuilder(
        "/usr/libexec/PlistBuddy",
        "-c",
        "Print CFBundleShortVersionString",
        "$absolutePath/Contents/Info.plist",
    ).start().inputStream.bufferedReader().readText().trim()
}.getOrNull()

fun File.isPyCharmInstall(): Boolean = name.contains("PyCharm", ignoreCase = true)

fun File.isPyCharmCommunity(): Boolean =
    name.contains("CE", ignoreCase = true) || name.equals("PyCharm CE.app", ignoreCase = true)

val resolvedLocalIde: File? = providers.gradleProperty("codeclone.localIde")
    .map { File(it) }
    .orNull
    ?.takeIf { it.exists() }
    ?: run {
        val installed = defaultLocalIdeCandidates.map { File(it) }.filter { it.exists() }
        if (installed.isEmpty()) {
            null
        } else {
            val platformPrefix = platformVersion.get().substringBeforeLast('.')
            installed.firstOrNull { ide ->
                ide.readIdeVersion()?.startsWith(platformPrefix) == true
            } ?: installed.firstOrNull { it.isPyCharmInstall() } ?: installed.first()
        }
    }

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
    testRuntimeOnly("junit:junit:4.13.2")
    intellijPlatform {
        val localIde = resolvedLocalIde
        if (localIde != null) {
            local(localIde.absolutePath)
            when {
                localIde.isPyCharmInstall() -> {
                    bundledPlugin("PythonCore")
                    if (!localIde.isPyCharmCommunity()) {
                        bundledPlugin("Pythonid")
                    }
                }
                else -> {
                    // IntelliJ IDEA does not bundle Python; resolve a compatible build from Marketplace.
                    compatiblePlugin("PythonCore")
                }
            }
        } else {
            pycharm(platformVersion.get())
            bundledPlugin("PythonCore")
            bundledPlugin("Pythonid")
        }
        testFramework(TestFrameworkType.Platform)
    }
}

kotlin {
    jvmToolchain(21)
}

intellijPlatform {
    pluginConfiguration {
        id = "io.orenlab.codeclone.jetbrains"
        name = "CodeClone"
        version = project.version.toString()
        description = provider { file("DESCRIPTION.md").readText().trim() }
        vendor {
            name = "orenlab"
            url = "https://github.com/orenlab/codeclone"
        }
        ideaVersion {
            sinceBuild = "252"
        }
    }
}

tasks {
    test {
        useJUnitPlatform()
    }
    withType<JavaCompile> {
        options.release.set(21)
    }
}
