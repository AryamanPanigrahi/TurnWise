package com.turnwise.driver

import com.turnwise.driver.core.GpsPoint
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

private val TS: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneOffset.UTC)

/** Below this speed a phone's GPS heading is noise, so the contract wants null (gps.md). */
const val MIN_HEADING_SPEED_MPS = 0.5f

/**
 * Turn the numbers of an Android `Location` into a contract GPS point.
 *
 * Takes plain values (not a Location) so it can be unit-tested on a normal JVM.
 * Pass null where the phone did not report a value (`hasSpeed()` etc. was false).
 */
fun fixToPoint(
    tripId: String, timeMs: Long, lat: Double, lon: Double,
    speed: Float?, bearing: Float?, accuracy: Float?,
): GpsPoint {
    val v = speed?.takeIf { !it.isNaN() }?.coerceAtLeast(0f)
    val heading = bearing
        ?.takeIf { !it.isNaN() && v != null && v >= MIN_HEADING_SPEED_MPS }
        ?.let { ((it % 360f) + 360f) % 360f }                 // [0, 360): 360 itself is not allowed
    return GpsPoint(
        trip_id = tripId,
        ts = TS.format(Instant.ofEpochMilli(timeMs)),          // device fix time, UTC, trailing Z
        lat = lat, lon = lon,
        speed = v?.toDouble(),
        heading = heading?.toDouble(),
        accuracy = accuracy?.takeIf { !it.isNaN() && it >= 0f }?.toDouble(),
    )
}
