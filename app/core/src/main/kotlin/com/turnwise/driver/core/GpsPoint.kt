package com.turnwise.driver.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * One GPS fix, exactly as `POST /v1/gps` expects it (docs/contracts/gps.md).
 *
 * Units: degrees, m/s, degrees clockwise from north, metres. `ts` is the
 * device fix time in UTC ISO-8601 with a trailing `Z`, not the send time.
 */
@Serializable
data class GpsPoint(
    val trip_id: String,
    val ts: String,
    val lat: Double,
    val lon: Double,
    val speed: Double? = null,
    val heading: Double? = null,
    val accuracy: Double? = null,
)

@Serializable
data class GpsBatch(val points: List<GpsPoint>)

/** Response body of a `202 Accepted`. */
@Serializable
data class GpsAccepted(val accepted: Int, val duplicates: Int = 0)

internal val ContractJson = Json {
    ignoreUnknownKeys = true   // contracts/README: consumers ignore unknown fields
    explicitNulls = true       // send "speed": null, as the contract shows
    encodeDefaults = true
}

fun GpsBatch.toJson(): String = ContractJson.encodeToString(this)
