package com.example.travelmate_traveller

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Base64
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.net.Inet4Address
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec

internal fun Context.configureLocalBackend(messenger: BinaryMessenger) {
    val connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    MethodChannel(messenger, "travelmate/local_backend").setMethodCallHandler { call, result ->
        when (call.method) {
            "network" -> {
                val network = connectivity.activeNetwork
                val capabilities = network?.let { connectivity.getNetworkCapabilities(it) }
                if (network == null ||
                    capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) != true ||
                    capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
                ) {
                    result.success(null)
                } else {
                    val subnets = connectivity.getLinkProperties(network)?.linkAddresses
                        .orEmpty().filter { it.address is Inet4Address }
                        .map { "${it.address.hostAddress}/${it.prefixLength}" }
                    result.success(mapOf("handle" to network.networkHandle, "subnets" to subnets))
                }
            }
            "verify" -> {
                val verified = runCatching {
                    val key = Base64.decode(call.argument<String>("publicKey"), Base64.NO_WRAP)
                    val proof = Base64.decode(call.argument<String>("proof"), Base64.NO_WRAP)
                    val message = call.argument<String>("message") ?: return@runCatching false
                    val publicKey = KeyFactory.getInstance("RSA").generatePublic(X509EncodedKeySpec(key))
                    val signature = Signature.getInstance("SHA256withRSA")
                    signature.initVerify(publicKey)
                    signature.update(message.toByteArray(Charsets.US_ASCII))
                    signature.verify(proof)
                }.getOrDefault(false)
                result.success(verified)
            }
            else -> result.notImplemented()
        }
    }
}
