package com.turnwise.driver.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement

/** Fact card (docs/contracts/fact_card.schema.json). Facts come only from the engine. */
@Serializable
data class FactCard(
    val type: String,
    val on_route: String,
    val alternatives: List<String> = emptyList(),
    val distance_m: Double,
    val landmark: String? = null,
    val confidence: Double,
)

@Serializable
data class Recovery(val action: String, val distance_m: Double? = null)

@Serializable
private data class Envelope(
    val event: String,
    val trip_id: String,
    val ts: String,
    val seq: Long,
    val data: JsonObject = JsonObject(emptyMap()),
)

@Serializable
private data class OffRouteData(val recovery: Recovery, val deviation_m: Double? = null,
                                val confidence: Double? = null)

@Serializable
private data class ArrivedData(val stop_id: String, val distance_m: Double? = null)

/** A message from `WS /v1/trips/{id}/events` (docs/contracts/events.md). */
sealed interface TripEvent {
    val tripId: String
    val ts: String
    val seq: Long

    data class OffRoute(override val tripId: String, override val ts: String, override val seq: Long,
                        val recovery: Recovery, val deviationM: Double?, val confidence: Double?) : TripEvent
    data class BackOnRoute(override val tripId: String, override val ts: String, override val seq: Long) : TripEvent
    data class DecisionPointAhead(override val tripId: String, override val ts: String, override val seq: Long,
                                  val fact: FactCard) : TripEvent
    data class Arrived(override val tripId: String, override val ts: String, override val seq: Long,
                       val stopId: String, val distanceM: Double?) : TripEvent
    /** An event type this app version doesn't know yet. Ignored, but it still advances `seq`. */
    data class Unknown(override val tripId: String, override val ts: String, override val seq: Long,
                       val event: String) : TripEvent

    companion object {
        /** Parse one WebSocket text frame. Returns null for a frame that isn't a valid envelope. */
        fun parse(text: String): TripEvent? = try {
            val env = ContractJson.decodeFromString(Envelope.serializer(), text)
            val d = env.data
            when (env.event) {
                "off_route" -> ContractJson.decodeFromJsonElement<OffRouteData>(d).let {
                    OffRoute(env.trip_id, env.ts, env.seq, it.recovery, it.deviation_m, it.confidence)
                }
                "back_on_route" -> BackOnRoute(env.trip_id, env.ts, env.seq)
                "decision_point_ahead" ->
                    DecisionPointAhead(env.trip_id, env.ts, env.seq, ContractJson.decodeFromJsonElement<FactCard>(d))
                "arrived" -> ContractJson.decodeFromJsonElement<ArrivedData>(d).let {
                    Arrived(env.trip_id, env.ts, env.seq, it.stop_id, it.distance_m)
                }
                else -> Unknown(env.trip_id, env.ts, env.seq, env.event)
            }
        } catch (e: SerializationException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }
}

/**
 * Drops duplicate and stale events and notices gaps, using the per-trip `seq`.
 * After a reconnect the server may resend events; each is acted on once.
 */
class EventSequencer {
    var lastSeq: Long = -1
        private set
    var gaps: Int = 0
        private set

    /** True if the event is new and should be acted on. */
    fun accept(e: TripEvent): Boolean {
        if (e.seq <= lastSeq) return false
        if (lastSeq >= 0 && e.seq > lastSeq + 1) gaps++
        lastSeq = e.seq
        return true
    }
}
