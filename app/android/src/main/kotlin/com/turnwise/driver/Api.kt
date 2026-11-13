package com.turnwise.driver

import com.turnwise.driver.core.GpsTransport
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import java.util.concurrent.TimeUnit

// Request/response shapes: docs/contracts/ (ask.md) and backend/schemas.py, backend/field.py.
@Serializable data class Place(val lat: Double, val lon: Double)
@Serializable data class TripCreate(val origin: Place, val destination: Place)
@Serializable data class TripCreated(val trip_id: String, val length_m: Double, val decision_points: Int = 0)
@Serializable data class RouteInfo(val route: List<List<Double>>, val length_m: Double)
@Serializable data class AskRequest(val trip_id: String, val intent: String, val slots: JsonObject)
@Serializable data class AskResponse(val answer_key: String, val facts: JsonObject = JsonObject(emptyMap()))
@Serializable data class SayRequest(
    val lang: String,
    val answer_key: String? = null,
    val facts: JsonObject? = null,
    val event: String? = null,
    val data: JsonObject? = null,
)
@Serializable data class SayResponse(val text: String? = null)

/** The server answered, but not with 2xx. */
class ApiException(val status: Int, detail: String) : IOException("HTTP $status $detail")

/**
 * Everything the app says to the backend. Plain blocking calls: run them off the main thread.
 *
 * It is also the [GpsTransport] that `core`'s GpsUploader posts batches through.
 */
class TripApi(
    baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = defaultClient(),
) : GpsTransport {
    private val base = baseUrl.trim().trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val jsonType = "application/json".toMediaType()

    private fun request(path: String) = Request.Builder().url(base + path).header("Authorization", "Bearer $token")

    private fun call(req: Request): String {
        http.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ApiException(resp.code, body.take(200))
            return body
        }
    }

    private fun post(path: String, body: String) = call(request(path).post(body.toRequestBody(jsonType)).build())

    fun createTrip(origin: Place, destination: Place): TripCreated =
        json.decodeFromString(post("/v1/trips", json.encodeToString(TripCreate(origin, destination))))

    fun endTrip(tripId: String) { post("/v1/trips/$tripId/end", "") }

    fun route(tripId: String): RouteInfo =
        json.decodeFromString(call(request("/field/api/trips/$tripId/route").get().build()))

    fun ask(tripId: String, intent: String): AskResponse {
        // which_branch tells the engine which fork the driver means (ask.md)
        val slots = if (intent == "which_branch")
            JsonObject(mapOf("options" to JsonArray(listOf(JsonPrimitive("flyover"), JsonPrimitive("service_road")))))
        else JsonObject(emptyMap())
        return json.decodeFromString(post("/v1/ask", json.encodeToString(AskRequest(tripId, intent, slots))))
    }

    /** The sentence for an answer, phrased by the server's voice templates (null = nothing to say). */
    fun sayAnswer(lang: String, answer: AskResponse): String? =
        say(SayRequest(lang = lang, answer_key = answer.answer_key, facts = answer.facts))

    /** The sentence for a pushed event (null = stay silent). */
    fun sayEvent(lang: String, event: String, data: JsonObject?): String? =
        say(SayRequest(lang = lang, event = event, data = data ?: JsonObject(emptyMap())))

    private fun say(body: SayRequest): String? =
        json.decodeFromString<SayResponse>(post("/field/api/say", json.encodeToString(body))).text

    /** GpsTransport: POST a batch to /v1/gps and return the status code (core decides what it means). */
    override fun post(json: String): Int =
        http.newCall(request("/v1/gps").post(json.toRequestBody(jsonType)).build()).execute().use { it.code }

    /** Open the events stream. A native client can send the Authorization header on a WebSocket. */
    fun openEvents(tripId: String, lastSeq: Long, listener: WebSocketListener): WebSocket {
        val wsBase = if (base.startsWith("https")) "wss" + base.removePrefix("https") else "ws" + base.removePrefix("http")
        val req = Request.Builder().url("$wsBase/v1/trips/$tripId/events?last_seq=$lastSeq")
            .header("Authorization", "Bearer $token").build()
        return http.newWebSocket(req, listener)
    }

    companion object {
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)     // route planning can take a few seconds
            .pingInterval(15, TimeUnit.SECONDS)    // notice a dead events socket
            .build()
    }
}
