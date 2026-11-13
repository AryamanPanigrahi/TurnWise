package com.turnwise.driver

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList

/** Settings kept on the phone. A debug/field-test build: the token is in app-private storage, not encrypted. */
class Prefs(ctx: Context) {
    private val p = ctx.getSharedPreferences("turnwise", Context.MODE_PRIVATE)
    var serverUrl: String
        get() = p.getString("server", "") ?: ""
        set(v) = p.edit().putString("server", v.trim()).apply()
    var token: String
        get() = p.getString("token", "") ?: ""
        set(v) = p.edit().putString("token", v.trim()).apply()
    var lang: String
        get() = p.getString("lang", "en") ?: "en"
        set(v) = p.edit().putString("lang", v).apply()
    /** When the driver agreed to location tracking (epoch ms), or 0 if never (DPDP: no consent, no tracking). */
    var consentAt: Long
        get() = p.getLong("consent_at", 0L)
        set(v) = p.edit().putLong("consent_at", v).apply()
}

/** What the trip service tells the screen. Delivered on the main thread. */
sealed interface Update {
    data class Banner(val text: String, val kind: Kind) : Update
    data class Status(val text: String) : Update
    data class Log(val text: String) : Update
    data class Position(val lat: Double, val lon: Double) : Update
    data object Stopped : Update
    enum class Kind { INFO, OK, ALERT }
}

object TripBus {
    private val main = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArrayList<(Update) -> Unit>()
    @Volatile var activeTripId: String? = null

    fun register(l: (Update) -> Unit) { listeners.add(l) }
    fun unregister(l: (Update) -> Unit) { listeners.remove(l) }
    fun post(u: Update) { main.post { listeners.forEach { it(u) } } }
}

/**
 * Speaks sentences with the phone's built-in voice: a stand-in for Sarvam TTS in this
 * field-test build. An alert interrupts whatever is being said (CLAUDE.md rule 2).
 */
object Speaker {
    private var tts: TextToSpeech? = null
    @Volatile private var ready = false

    fun init(ctx: Context) {
        if (tts != null) return
        tts = TextToSpeech(ctx.applicationContext) { status -> ready = status == TextToSpeech.SUCCESS }
    }

    fun speak(text: String, lang: String) {
        val t = tts ?: return
        if (!ready || text.isBlank()) return
        t.language = Locale(lang, "IN")                 // en-IN, hi-IN, kn-IN; falls back if the voice is missing
        t.speak(text, TextToSpeech.QUEUE_FLUSH, null, "turnwise")
    }
}

/**
 * Wrong-way lines kept ON the phone, copied from voice/templates/<lang>.yaml (`alerts`).
 * Used only when the server cannot be reached to phrase an alert: a wrong-way warning
 * must never be lost to a network hiccup.
 */
object FallbackAlerts {
    private val offRoute = mapOf(
        "en" to "Wrong way! Follow the screen.",
        "hi" to "गलत रास्ता! स्क्रीन देखिए।",
        "kn" to "ತಪ್ಪು ದಾರಿ! ಸ್ಕ್ರೀನ್ ನೋಡಿ.",
    )
    private val backOnRoute = mapOf(
        "en" to "You are back on route.",
        "hi" to "आप फिर से सही रास्ते पर हैं।",
        "kn" to "ಮತ್ತೆ ಸರಿಯಾದ ದಾರಿಗೆ ಬಂದಿದ್ದೀರಿ.",
    )

    fun offRoute(lang: String): String = offRoute[lang] ?: offRoute.getValue("en")
    fun backOnRoute(lang: String): String = backOnRoute[lang] ?: backOnRoute.getValue("en")
}
