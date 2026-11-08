package com.example.travelmate_traveller

import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.os.Build
import android.net.Uri
import android.util.Base64
import java.io.File
import java.security.SecureRandom
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private lateinit var checkoutChannel: MethodChannel
    private var initialCheckoutLink: String? = null
    private lateinit var notificationChannel: MethodChannel
    private var initialNotification: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
            NotificationChannel("travelmate_updates", "TravelMate updates", NotificationManager.IMPORTANCE_HIGH)
        )
        initialNotification = notificationId(intent)
        notificationChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "travelmate/notifications")
        notificationChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "binding" -> {
                    val file = File(noBackupFilesDir, "travelmate_push_binding")
                    val existing = if (file.exists()) file.readText() else ""
                    val binding = if (existing.matches(Regex("[A-Za-z0-9_-]{43}"))) existing else
                        Base64.encodeToString(SecureRandom().generateSeed(32), Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
                    if (binding != existing) file.writeText(binding)
                    result.success(binding)
                }
                "initial" -> { result.success(initialNotification); initialNotification = null }
                "clear" -> { manager.cancelAll(); result.success(null) }
                "show" -> {
                    val id = call.argument<String>("notificationId")
                    if (id == null || !id.matches(Regex("[a-f0-9]{64}"))) result.error("invalid", "Invalid notification", null)
                    else {
                        val tap = Intent(this, MainActivity::class.java).putExtra("notificationId", id)
                            .setData(Uri.parse("travelmate://notification/$id"))
                            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                        val pending = PendingIntent.getActivity(this, id.hashCode(), tap, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "travelmate_updates") else Notification.Builder(this)
                        manager.notify(id, 0, builder.setSmallIcon(R.drawable.ic_notification)
                            .setContentTitle("TravelMate — Update").setContentText("You have a TravelMate update. Open the app to view it securely.")
                            .setVisibility(Notification.VISIBILITY_PRIVATE).setAutoCancel(true).setContentIntent(pending).build())
                        result.success(null)
                    }
                }
                else -> result.notImplemented()
            }
        }
        if (BuildConfig.USE_FIREBASE_EMULATOR) {
            MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "travelmate/firebase_emulator")
                .setMethodCallHandler { call, result ->
                    if (call.method == "configuration") {
                        // FlutterFire keeps this SDK implementation-scoped; do not add another SDK version.
                        val firebase = Class.forName("com.google.firebase.FirebaseApp")
                        val apps = firebase.getMethod("getApps", android.content.Context::class.java)
                            .invoke(null, this) as List<*>
                        val projects = apps.map { app ->
                            val options = firebase.getMethod("getOptions").invoke(app)
                            options.javaClass.getMethod("getProjectId").invoke(options)
                        }
                        result.success(mapOf(
                            "package" to packageName,
                            "emulatorBuild" to true,
                            "productionResourcesAbsent" to (resources.getIdentifier("google_app_id", "string", packageName) == 0),
                            "projects" to projects
                        ))
                    } else result.notImplemented()
                }
        }
        initialCheckoutLink = checkoutLink(intent)
        checkoutChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "travelmate/checkout_return"
        )
        checkoutChannel.setMethodCallHandler { call, result ->
            if (call.method == "getInitialLink") {
                result.success(initialCheckoutLink)
                initialCheckoutLink = null
            } else {
                result.notImplemented()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        notificationId(intent)?.let { id ->
            if (::notificationChannel.isInitialized) notificationChannel.invokeMethod("tap", id)
            else initialNotification = id
        }
        checkoutLink(intent)?.let { link ->
            if (::checkoutChannel.isInitialized) {
                checkoutChannel.invokeMethod("onLink", link)
            } else {
                initialCheckoutLink = link
            }
        }
    }

    private fun checkoutLink(intent: Intent?): String? {
        val data = intent?.data ?: return null
        return if (
            data.scheme == "travelmate" &&
            data.host == "checkout" &&
            data.path == "/return"
        ) data.toString() else null
    }

    private fun notificationId(intent: Intent?): String? = intent?.getStringExtra("notificationId")
        ?.takeIf { it.matches(Regex("[a-f0-9]{64}")) }
}
