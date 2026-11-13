package com.turnwise.driver

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class FixesTest {
    private val t = 1794026405123L   // 2026-11-07T04:40:05.123Z

    private fun fix(speed: Float? = 10f, bearing: Float? = 90f, accuracy: Float? = 5f) =
        fixToPoint("trp_1", t, 12.9757, 77.6061, speed, bearing, accuracy)

    @Test fun `timestamp is the device fix time in UTC with a trailing Z`() {
        val p = fix()
        assertEquals("2026-11-07T04:40:05.123Z", p.ts)
        assertEquals("trp_1", p.trip_id)
        assertEquals(12.9757, p.lat); assertEquals(77.6061, p.lon)
    }

    @Test fun `moving fix keeps speed heading and accuracy`() {
        val p = fix(speed = 12.5f, bearing = 274f, accuracy = 6.5f)
        assertEquals(12.5, p.speed); assertEquals(274.0, p.heading); assertEquals(6.5, p.accuracy)
    }

    @Test fun `heading is null when stationary or slower than half a metre per second`() {
        assertNull(fix(speed = 0f).heading)
        assertNull(fix(speed = 0.4f).heading)
        assertEquals(90.0, fix(speed = 0.5f).heading)
    }

    @Test fun `heading is null when the phone reported no speed or no bearing`() {
        assertNull(fix(speed = null).heading)
        assertNull(fix(bearing = null).heading)
        assertNull(fix(speed = null).speed)
    }

    @Test fun `heading is always inside 0 to 360 exclusive`() {
        assertEquals(0.0, fix(bearing = 360f).heading)        // the contract forbids 360 itself
        assertEquals(350.0, fix(bearing = -10f).heading)
        assertEquals(10.0, fix(bearing = 370f).heading)
    }

    @Test fun `bad sensor values become null or zero, never garbage`() {
        assertNull(fix(speed = Float.NaN).speed)
        assertNull(fix(speed = Float.NaN).heading)
        assertNull(fix(bearing = Float.NaN).heading)
        assertEquals(0.0, fix(speed = -1f).speed)
        assertNull(fix(accuracy = null).accuracy)
        assertNull(fix(accuracy = -5f).accuracy)
        assertNull(fix(accuracy = Float.NaN).accuracy)
    }
}
