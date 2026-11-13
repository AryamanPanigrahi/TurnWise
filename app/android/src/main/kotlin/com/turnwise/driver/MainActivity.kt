package com.turnwise.driver

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.view.WindowManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import org.osmdroid.config.Configuration
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.CopyrightOverlay
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * The one screen of the field-test build: a map to pick the destination, Start/End,
 * five question buttons, and a banner showing (and speaking) what the engine says.
 *
 * It decides nothing about directions: every sentence comes from the server (rule 1).
 */
class MainActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var map: MapView
    private lateinit var banner: TextView
    private lateinit var status: TextView
    private lateinit var log: TextView
    private lateinit var server: EditText
    private lateinit var token: EditText
    private lateinit var lang: Spinner
    private lateinit var start: Button
    private lateinit var end: Button
    private lateinit var askButtons: List<Button>

    private val net = Executors.newSingleThreadExecutor()
    private val langs = listOf("en", "hi", "kn")
    private var destination: GeoPoint? = null
    private var destMarker: Marker? = null
    private var meMarker: Marker? = null
    private var routeLine: Polyline? = null
    private val onUpdate: (Update) -> Unit = { handle(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        // osmdroid: keep its tile cache in app-private storage and identify the app to the tile server
        Configuration.getInstance().load(applicationContext, getSharedPreferences("osmdroid", Context.MODE_PRIVATE))
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_main)
        Speaker.init(this)

        map = findViewById(R.id.map); banner = findViewById(R.id.banner); status = findViewById(R.id.status)
        log = findViewById(R.id.log); server = findViewById(R.id.server); token = findViewById(R.id.token)
        lang = findViewById(R.id.lang); start = findViewById(R.id.start); end = findViewById(R.id.end)
        askButtons = listOf(R.id.ask_branch to "which_branch", R.id.ask_side to "left_or_right",
            R.id.ask_distance to "distance_to_next", R.id.ask_wrong to "am_i_wrong", R.id.ask_eta to "eta")
            .map { (id, intent) -> findViewById<Button>(id).also { b -> b.setOnClickListener { ask(intent) } } }

        server.setText(prefs.serverUrl); token.setText(prefs.token)
        lang.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            listOf(getString(R.string.lang_en), getString(R.string.lang_hi), getString(R.string.lang_kn)))
        lang.setSelection(langs.indexOf(prefs.lang).coerceAtLeast(0))

        map.setTileSource(TileSourceFactory.MAPNIK)                  // OpenStreetMap tiles
        map.setMultiTouchControls(true)
        map.controller.setZoom(12.0)
        map.controller.setCenter(GeoPoint(12.9716, 77.5946))         // Bengaluru
        map.overlays.add(CopyrightOverlay(this))                     // "(c) OpenStreetMap contributors" (ODbL)
        map.overlays.add(0, MapEventsOverlay(object : MapEventsReceiver {
            override fun singleTapConfirmedHelper(p: GeoPoint): Boolean { pickDestination(p); return true }
            override fun longPressHelper(p: GeoPoint): Boolean = false
        }))

        start.setOnClickListener { onStartPressed() }
        end.setOnClickListener { stopTrip() }
        setTripUi(TripBus.activeTripId != null)
        if (prefs.consentAt == 0L) askConsent()
    }

    override fun onStart() { super.onStart(); TripBus.register(onUpdate); setTripUi(TripBus.activeTripId != null) }
    override fun onStop() { TripBus.unregister(onUpdate); super.onStop() }
    override fun onResume() { super.onResume(); map.onResume() }
    override fun onPause() { map.onPause(); super.onPause() }
    override fun onDestroy() { net.shutdown(); super.onDestroy() }

    // -- consent and permissions (DPDP: tracking only with recorded consent) ---------------------
    private fun askConsent() {
        AlertDialog.Builder(this)
            .setTitle(R.string.consent_title)
            .setMessage(R.string.consent_text)
            .setCancelable(false)
            .setPositiveButton(R.string.consent_yes) { _, _ -> prefs.consentAt = System.currentTimeMillis() }
            .setNegativeButton(R.string.consent_no) { _, _ -> say(getString(R.string.consent_needed), Update.Kind.ALERT) }
            .show()
    }

    private fun hasLocationPermission() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun requestPermissionsNeeded() {
        val wanted = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        requestPermissions(wanted.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (hasLocationPermission()) say(getString(R.string.permission_ok), Update.Kind.INFO)
        else say(getString(R.string.permission_needed), Update.Kind.ALERT)
    }

    // -- picking a destination ------------------------------------------------------------------
    private fun pickDestination(p: GeoPoint) {
        if (TripBus.activeTripId != null) return
        destination = p
        destMarker?.let { map.overlays.remove(it) }
        destMarker = Marker(map).apply {
            position = p; title = getString(R.string.destination)
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
        }.also { map.overlays.add(it) }
        map.invalidate()
        say(getString(R.string.ready), Update.Kind.INFO)
    }

    // -- trip lifecycle --------------------------------------------------------------------------
    private fun onStartPressed() {
        prefs.serverUrl = server.text.toString(); prefs.token = token.text.toString()
        prefs.lang = langs[lang.selectedItemPosition.coerceIn(0, langs.lastIndex)]
        val dest = destination
        when {
            prefs.consentAt == 0L -> return askConsent()
            !hasLocationPermission() -> return requestPermissionsNeeded()
            prefs.serverUrl.isEmpty() || prefs.token.isEmpty() -> return say(getString(R.string.need_server), Update.Kind.ALERT)
            dest == null -> return say(getString(R.string.tap_map), Update.Kind.ALERT)
        }
        start.isEnabled = false
        say(getString(R.string.waiting_gps), Update.Kind.INFO)
        currentLocation { here ->
            if (here == null) { start.isEnabled = true; say(getString(R.string.no_gps), Update.Kind.ALERT); return@currentLocation }
            say(getString(R.string.planning), Update.Kind.INFO)
            val api = TripApi(prefs.serverUrl, prefs.token)
            net.execute {
                try {
                    val trip = api.createTrip(Place(here.latitude, here.longitude), Place(dest!!.latitude, dest.longitude))
                    val route = try { api.route(trip.trip_id) } catch (_: Exception) { null }   // only for drawing
                    runOnUiThread { tripStarted(trip, route) }
                } catch (e: Exception) {
                    runOnUiThread { start.isEnabled = true; say(getString(R.string.start_failed, e.message), Update.Kind.ALERT) }
                }
            }
        }
    }

    private fun tripStarted(trip: TripCreated, route: RouteInfo?) {
        routeLine?.let { map.overlays.remove(it) }
        if (route != null && route.route.size >= 2) {
            val pts = route.route.map { GeoPoint(it[0], it[1]) }
            routeLine = Polyline(map).apply {
                setPoints(pts); outlinePaint.color = Color.rgb(11, 107, 203); outlinePaint.strokeWidth = 12f
            }.also { map.overlays.add(it) }
            map.post { map.zoomToBoundingBox(BoundingBox.fromGeoPoints(pts), true, 80) }
        }
        startForegroundService(Intent(this, TripService::class.java)
            .setAction(TripService.ACTION_START).putExtra(TripService.EXTRA_TRIP, trip.trip_id))
        TripBus.activeTripId = trip.trip_id
        setTripUi(true)
        append(getString(R.string.trip_log, trip.length_m / 1000.0, trip.decision_points))
        say(getString(R.string.trip_started), Update.Kind.OK)
    }

    private fun stopTrip() {
        startService(Intent(this, TripService::class.java).setAction(TripService.ACTION_STOP))
        end.isEnabled = false
    }

    private fun setTripUi(active: Boolean) {
        start.isEnabled = !active; end.isEnabled = active
        askButtons.forEach { it.isEnabled = active }
        server.isEnabled = !active; token.isEnabled = !active
        if (active) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    // -- questions -------------------------------------------------------------------------------
    private fun ask(intent: String) {
        val trip = TripBus.activeTripId ?: return
        val api = TripApi(prefs.serverUrl, prefs.token)
        val language = prefs.lang
        net.execute {
            try {
                val answer = api.ask(trip, intent)
                val sentence = api.sayAnswer(language, answer)
                runOnUiThread {
                    append("$intent -> ${answer.answer_key}")
                    if (sentence != null) {
                        Speaker.speak(sentence, language)
                        say(sentence, if (answer.answer_key == "am_i_wrong.off_route") Update.Kind.ALERT else Update.Kind.INFO)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { append(getString(R.string.ask_failed, e.message)) }
            }
        }
    }

    // -- updates from the service ------------------------------------------------------------------
    private fun handle(u: Update) {
        when (u) {
            is Update.Banner -> say(u.text, u.kind)
            is Update.Status -> status.text = u.text
            is Update.Log -> append(u.text)
            is Update.Position -> showMe(u.lat, u.lon)
            Update.Stopped -> { setTripUi(false); say(getString(R.string.trip_ended), Update.Kind.INFO) }
        }
    }

    private fun showMe(lat: Double, lon: Double) {
        val p = GeoPoint(lat, lon)
        val m = meMarker ?: Marker(map).apply {
            title = getString(R.string.you); setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
            icon = getDrawable(R.drawable.ic_me)
        }.also { meMarker = it; map.overlays.add(it) }
        m.position = p
        map.invalidate()
    }

    private fun say(text: String, kind: Update.Kind) {
        banner.text = text
        banner.setTextColor(getColor(when (kind) {
            Update.Kind.ALERT -> R.color.alert; Update.Kind.OK -> R.color.ok; Update.Kind.INFO -> R.color.info
        }))
    }

    private fun append(line: String) {
        val time = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        log.text = getString(R.string.log_line, time, line, log.text.toString().take(4000))
    }

    // -- one GPS fix for the trip's starting point ---------------------------------------------------
    @SuppressLint("MissingPermission")     // callers check hasLocationPermission() first
    private fun currentLocation(done: (Location?) -> Unit) {
        val lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (!lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) return done(null)
        if (Build.VERSION.SDK_INT >= 30) {
            lm.getCurrentLocation(LocationManager.GPS_PROVIDER, null, mainExecutor) { loc ->
                done(loc ?: lm.getLastKnownLocation(LocationManager.GPS_PROVIDER))
            }
        } else {
            @Suppress("DEPRECATION")
            lm.requestSingleUpdate(LocationManager.GPS_PROVIDER, object : LocationListener {
                override fun onLocationChanged(loc: Location) = done(loc)
                override fun onProviderEnabled(provider: String) {}
                override fun onProviderDisabled(provider: String) {}
                @Deprecated("Deprecated in Java")
                override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            }, Looper.getMainLooper())
        }
    }
}
