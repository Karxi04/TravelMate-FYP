package com.example.travelmate_traveller

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private lateinit var checkoutChannel: MethodChannel
    private var initialCheckoutLink: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
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
}
