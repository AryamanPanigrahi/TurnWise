package com.turnwise.driver

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.os.Looper
import com.turnwise.driver.core.EventSequencer
import com.turnwise.driver.core.GpsBuffer
import com.turnwise.driver.core.GpsUploader
import com.turnwise.driver.core.TrackingGate
import com.turnwise.driver.core.TripEvent
import com.turnwise.driver.core.UploadResult
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

/**
 * Runs for the length of one trip, with a visible notification (Android requires one
 * for location in the background):
 *
 *   GPS (1 Hz) -> core.GpsBuffer -> core.GpsUploader -> POST /v1/gps
 *   WS /v1/trips/{id}/events -> core.TripEvent -> spoken alert + banner on screen
 *
 * All decisions (what to buffer, when to retry, which events are duplicates) live in
 * `core`; this class only connects Android's GPS, network and speaker to it.
 * It stops GPS the moment the trip ends: no tracking outside a trip (CLAUDE.md rule 5).
 */
class TripService : Service(), LocationListener {
    private lateinit var prefs: Prefs
    private lateinit var api: TripApi
    private lateinit var io: ScheduledExecutorService
    private var tripId: String = ""
    private var gate = TrackingGate(consentRecorded = false, onDuty = false, activeTripId = null)
    private val buffer = GpsBuffer()
    private var uploader: GpsUploader? = null
    private val sequencer = EventSequencer()
    private var socket: WebSocket? = null
    @Volatile private var running = false
    private var sent = 0
    private var events = 0
    private var lastAccuracy: Float? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> start(intent.getStringExtra(EXTRA_TRIP).orEmpty())
            ACTION_STOP -> stop(endOnServer = true)
        }
        return START_NOT_STICKY           // if Android kills us, do not silently resume tracking
    }

    @SuppressLint("MissingPermission")    // MainActivity only starts the service after the permission is granted
    private fun start(trip: String) {
        if (running || trip.isEmpty()) return
        prefs = Prefs(this)
        if (prefs.consentAt == 0L) { stopSelf(); return }          // no consent, no tracking
        Speaker.init(this)
        tripId = trip
        api = TripApi(prefs.serverUrl, prefs.token)
        uploader = GpsUploader(buffer, api)
        gate = TrackingGate(consentRecorded = true, onDuty = true, activeTripId = trip)
        io = Executors.newSingleThreadScheduledExecutor()
        running = true
        TripBus.activeTripId = trip

        val note = notification()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTE_ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        else startForeground(NOTE_ID, note)

        val lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        try {
            lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, this, Looper.getMainLooper())
        } catch (e: Exception) {          // GPS switched off or permission revoked
            TripBus.post(Update.Banner("GPS is not available: ${e.message}", Update.Kind.ALERT))
        }
        scheduleUpload(2000)
        connect()
        TripBus.post(Update.Log("tracking started for $trip"))
    }

    private fun stop(endOnServer: Boolean) {
        if (!running) { stopSelf(); return }
        running = false
        gate = gate.copy(onDuty = false, activeTripId = null)       // nothing more is recorded from here
        (getSystemService(Context.LOCATION_SERVICE) as LocationManager).removeUpdates(this)
        socket?.close(1000, "trip ended")
        val trip = tripId
        io.execute {
            try { uploader?.uploadOnce() } catch (_: Exception) {}   // last fixes, best effort
            if (endOnServer) try { api.endTrip(trip) } catch (e: Exception) { TripBus.post(Update.Log("end failed: ${e.message}")) }
            TripBus.activeTripId = null
            TripBus.post(Update.Stopped)
        }
        io.shutdown()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        if (running) stop(endOnServer = false)
        super.onDestroy()
    }

    // -- GPS ----------------------------------------------------------------------------------
    override fun onLocationChanged(loc: Location) {
        if (!running) return
        val point = fixToPoint(
            tripId, loc.time, loc.latitude, loc.longitude,
            if (loc.hasSpeed()) loc.speed else null,
            if (loc.hasBearing()) loc.bearing else null,
            if (loc.hasAccuracy()) loc.accuracy else null)
        buffer.add(point, gate)
        lastAccuracy = if (loc.hasAccuracy()) loc.accuracy else null
        TripBus.post(Update.Position(loc.latitude, loc.longitude))
        status()
    }

    // Required on Android 8-10, where these have no default implementation.
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {
        TripBus.post(Update.Banner("GPS is switched off. Turn on location.", Update.Kind.ALERT))
    }
    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}

    // -- upload (core.GpsUploader decides retry / stop) ---------------------------------------
    private fun scheduleUpload(delayMs: Long) {
        if (!running) return
        io.schedule({
            val next = when (val r = uploader?.uploadOnce() ?: UploadResult.Nothing) {
                is UploadResult.Sent -> { sent += r.points; status(); 2000L }
                is UploadResult.Retry -> { TripBus.post(Update.Log("offline, retry in ${r.delayMs / 1000} s (${buffer.size()} fixes waiting)")); r.delayMs }
                is UploadResult.Rejected -> { TripBus.post(Update.Log("server rejected ${r.points} fixes")); 2000L }
                is UploadResult.Stop -> {
                    TripBus.post(Update.Banner("Trip stopped by the server (HTTP ${r.status}).", Update.Kind.ALERT))
                    android.os.Handler(Looper.getMainLooper()).post { stop(endOnServer = false) }
                    -1L
                }
                UploadResult.Nothing -> 2000L
            }
            if (next >= 0) scheduleUpload(next)
        }, delayMs, TimeUnit.MILLISECONDS)
    }

    // -- events -------------------------------------------------------------------------------
    private fun connect() {
        if (!running) return
        socket = api.openEvents(tripId, maxOf(0L, sequencer.lastSeq), object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (running) io.execute { handleEvent(text) }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = reconnect()
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = reconnect()
        })
    }

    private fun reconnect() {
        if (!running) return
        try { io.schedule({ connect() }, 2, TimeUnit.SECONDS) } catch (_: Exception) {}   // executor already shut down
    }

    private fun handleEvent(text: String) {
        val event = TripEvent.parse(text) ?: return
        if (!sequencer.accept(event)) return                         // duplicate after a reconnect
        events++
        val lang = prefs.lang
        val (name, kind) = when (event) {
            is TripEvent.OffRoute -> "off_route" to Update.Kind.ALERT
            is TripEvent.BackOnRoute -> "back_on_route" to Update.Kind.OK
            is TripEvent.DecisionPointAhead -> "decision_point_ahead" to Update.Kind.INFO
            is TripEvent.Arrived -> { TripBus.post(Update.Banner(getString(R.string.arrived), Update.Kind.OK)); status(); return }
            is TripEvent.Unknown -> return
        }
        val data = try { Json.parseToJsonElement(text).jsonObject["data"] as? JsonObject } catch (_: Exception) { null }
        val sentence = try {
            api.sayEvent(lang, name, data)
        } catch (e: Exception) {
            // The server could not phrase it. A wrong-way warning is still given, from the phone's own copy.
            when (event) {
                is TripEvent.OffRoute -> FallbackAlerts.offRoute(lang)
                is TripEvent.BackOnRoute -> FallbackAlerts.backOnRoute(lang)
                else -> null
            }
        }
        if (sentence != null) {
            Speaker.speak(sentence, lang)
            TripBus.post(Update.Banner(sentence, kind))
        }
        TripBus.post(Update.Log("$name: ${sentence ?: "(silent)"}"))
        status()
    }

    private fun status() {
        val acc = lastAccuracy?.let { " • GPS ±${it.toInt()} m" } ?: ""
        TripBus.post(Update.Status("sent $sent • waiting ${buffer.size()} • events $events$acc"))
    }

    private fun notification(): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_trip), NotificationManager.IMPORTANCE_LOW))
        return Notification.Builder(this, CHANNEL)
            .setContentTitle(getString(R.string.note_title))
            .setContentText(getString(R.string.note_text))
            .setSmallIcon(R.drawable.ic_stat_trip)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_START = "com.turnwise.driver.START"
        const val ACTION_STOP = "com.turnwise.driver.STOP"
        const val EXTRA_TRIP = "trip_id"
        private const val CHANNEL = "trip"
        private const val NOTE_ID = 1
    }
}
