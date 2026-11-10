package com.example.travelmate_traveller

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.net.Uri
import android.util.AtomicFile
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import org.json.JSONArray
import org.json.JSONObject

/** Uses the existing notification channel/tap bridge; no Flutter engine at alarm time. */
class TripReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        try { process(context,intent) }
        catch (_: Exception) { Log.w("TravelMate", "Trip reminder could not be processed.") }
    }
    private fun process(context: Context, intent: Intent) {
        synchronized(lock) {
            val state = read(context)
            if (intent.action != FIRE) {
                schedule(context, state)
                return
            }
            val id = intent.getStringExtra("notificationId") ?: return
            val row = items(state).firstOrNull { it.optString("id") == id } ?: return
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            channel(manager)
            val allowed = manager.areNotificationsEnabled() && (Build.VERSION.SDK_INT < 26 || manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE)
            val delivered = state.optJSONObject("delivered") ?: JSONObject()
            if (!TripReminderRules.due(System.currentTimeMillis(), row.optLong("triggerAt"), row.optLong("expiresAt"), delivered.has(id), allowed)) return
            val tap = Intent(context, MainActivity::class.java).putExtra("notificationId",id)
                .setData(Uri.parse("travelmate://notification/$id"))
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            val pending = PendingIntent.getActivity(context,0,tap,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val format = SimpleDateFormat("yyyy-MM-dd",Locale.ROOT).apply { timeZone=TimeZone.getTimeZone("Asia/Kuala_Lumpur") }
            val tomorrow = format.format(Date(System.currentTimeMillis()+86400000))
            val body = row.optString("title").take(150) + if (row.optString("startDate")==tomorrow) " starts tomorrow!" else " starts on ${row.optString("startDate")}."
            // Persist before notify: a repeated alarm/reboot cannot alert twice.
            delivered.put(id,row.optLong("expiresAt"))
            state.put("delivered",delivered)
            write(context,state)
            val builder=if (Build.VERSION.SDK_INT >= 26) Notification.Builder(context,CHANNEL) else Notification.Builder(context)
            manager.notify(id,0,builder.setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("TravelMate — Upcoming Trip").setContentText(body).setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE).setAutoCancel(true).setContentIntent(pending).build())
        }
    }
    companion object {
        private const val CHANNEL="travelmate_updates"
        private const val FIRE="travelmate.TRIP_REMINDER"
        private val lock=Any()
        private fun file(context: Context)=AtomicFile(File(context.noBackupFilesDir,"travelmate_trip_reminders.json"))
        private fun read(context: Context): JSONObject = try { JSONObject(file(context).openRead().bufferedReader().use { it.readText() }) } catch (_: Exception) { JSONObject() }
        private fun write(context: Context, state: JSONObject) {
            val file=file(context)
            val stream=file.startWrite()
            try { stream.write(state.toString().toByteArray(Charsets.UTF_8)); file.finishWrite(stream) }
            catch (error: Exception) { file.failWrite(stream); throw error }
        }
        private fun items(state: JSONObject): List<JSONObject> {
            val rows=state.optJSONArray("items") ?: return emptyList()
            return (0 until rows.length()).map { rows.getJSONObject(it) }
        }
        private fun alarm(context: Context,id: String)=PendingIntent.getBroadcast(context,0,
            Intent(context,TripReminderReceiver::class.java).setAction(FIRE).setData(Uri.parse("travelmate://reminder/$id")).putExtra("notificationId",id),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        private fun channel(manager: NotificationManager) {
            if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(CHANNEL,"TravelMate updates",NotificationManager.IMPORTANCE_HIGH))
        }
        private fun schedule(context: Context,state: JSONObject) {
            val now=System.currentTimeMillis()
            val delivered=state.optJSONObject("delivered") ?: JSONObject()
            val manager=context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            for (row in items(state)) {
                if (row.optLong("expiresAt")<=now || delivered.has(row.optString("id"))) continue
                // Inexact alarms avoid a second special-permission flow; Android may delay them.
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,maxOf(now+1000,row.optLong("triggerAt")),alarm(context,row.optString("id")))
            }
        }
        fun replace(context: Context,owner: String, rows: List<Map<String,Any>>) = synchronized(lock) {
            require(owner.matches(Regex("[a-f0-9]{64}")))
            require(rows.size<=500)
            rows.forEach { require(it["id"].toString().matches(Regex("[a-f0-9]{64}"))) }
            val state=read(context)
            val manager=context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val notices=context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val ids=rows.map { it["id"].toString() }.toSet()
            for (old in items(state)) {
                val id=old.optString("id")
                manager.cancel(alarm(context,id))
                if (state.optString("owner")!=owner || id !in ids) notices.cancel(id,0)
            }
            if (state.optString("owner")!=owner) state.remove("targets")
            state.put("owner",owner).put("items",JSONArray(rows))
            val delivered=state.optJSONObject("delivered") ?: JSONObject()
            delivered.keys().asSequence().toList().filter { delivered.optLong(it)<System.currentTimeMillis()-604800000 }.forEach { delivered.remove(it) }
            val targets=state.optJSONObject("targets") ?: JSONObject()
            targets.keys().asSequence().toList().filter { targets.getJSONObject(it).optLong("expiresAt")<System.currentTimeMillis()-604800000 }.forEach { targets.remove(it) }
            rows.forEach { targets.put(it["id"].toString(),JSONObject(it)) }
            state.put("delivered",delivered).put("targets",targets)
            write(context,state)
            schedule(context,state)
        }
        fun adoptOwner(context: Context,owner: String) = synchronized(lock) {
            require(owner.matches(Regex("[a-f0-9]{64}")))
            if (read(context).optString("owner")!=owner) {
                clear(context)
                write(context,read(context).put("owner",owner))
            }
        }
        fun clear(context: Context) = synchronized(lock) {
            val alarms=context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val notices=context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val state=read(context)
            for (row in items(state)) { val id=row.optString("id");alarms.cancel(alarm(context,id));notices.cancel(id,0) }
            // Retain only opaque delivered IDs across logout to prevent repeat alerts.
            write(context,JSONObject().put("delivered",state.optJSONObject("delivered") ?: JSONObject()))
        }
        fun target(context: Context,owner: String,id: String): Map<String,String>? = synchronized(lock) {
            val state=read(context)
            if (owner!=state.optString("owner")) return@synchronized null
            val row=state.optJSONObject("targets")?.optJSONObject(id) ?: return@synchronized null
            mapOf("tripId" to row.optString("tripId"))
        }
    }
}
