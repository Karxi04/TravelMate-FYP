allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val verificationBuildDir = System.getenv("TRAVELMATE_ANDROID_BUILD_DIR")
val newBuildDir: Directory = if (!verificationBuildDir.isNullOrBlank()) {
    rootProject.layout.dir(providers.provider { file(verificationBuildDir) }).get()
} else {
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
}
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
