package com.turnwise.driver.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.JsonNull
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class GpsTest {
    private val gate = TrackingGate(consentRecorded = true, onDuty = true, activeTripId = "trp_1")

    private fun pt(i: Int, trip: String = "trp_1") =
        GpsPoint(trip, "2026-11-07T04:30:%02d.000Z".format(i % 60), 12.97 + i * 1e-4, 77.6, 11.0, null, 5.0)

    @Test fun batchJsonMatchesContract() {
        val json = GpsBatch(listOf(pt(1))).toJson()
        val p = Json.parseToJsonElement(json).jsonObject["points"]!!.jsonArray[0].jsonObject
        assertEquals(setOf("trip_id", "ts", "lat", "lon", "speed", "heading", "accuracy"), p.keys)
        assertEquals(JsonNull, p["heading"])
    }

    @Test fun gateBlocksWithoutConsentDutyOrTrip() {
        val b = GpsBuffer()
        assertFalse(b.add(pt(1), gate.copy(consentRecorded = false)))
        assertFalse(b.add(pt(1), gate.copy(onDuty = false)))
        assertFalse(b.add(pt(1), gate.copy(activeTripId = null)))
        assertFalse(b.add(pt(1, trip = "trp_other"), gate))
        assertTrue(b.add(pt(1), gate))
        assertEquals(1, b.size())
    }

    @Test fun repeatedFixIsDropped() {
        val b = GpsBuffer()
        assertTrue(b.add(pt(1), gate)); assertFalse(b.add(pt(1), gate))
    }

    @Test fun batchesAreCappedAtContractLimitAndAckRemovesThem() {
        val b = GpsBuffer()
        repeat(1000) { b.add(pt(it).copy(ts = "t$it"), gate) }
        val first = b.nextBatch()!!
        assertEquals(600, first.points.size)
        assertEquals(600, b.nextBatch(5000)!!.points.size)
        b.ack(first)
        assertEquals(400, b.size())
        assertEquals("t600", b.nextBatch()!!.points[0].ts)
    }

    @Test fun capacityDropsOldestAndCounts() {
        val b = GpsBuffer(capacity = 3)
        repeat(5) { b.add(pt(it), gate) }
        assertEquals(3, b.size()); assertEquals(2, b.dropped)
        assertEquals(pt(2).ts, b.nextBatch()!!.points[0].ts)
    }

    @Test fun uploaderHandlesEachStatus() {
        val b = GpsBuffer(); repeat(3) { b.add(pt(it), gate) }
        var status = 503
        val up = GpsUploader(b, { status }, baseDelayMs = 1000, maxDelayMs = 5000)
        assertEquals(UploadResult.Retry(1000), up.uploadOnce())
        assertEquals(UploadResult.Retry(2000), up.uploadOnce())
        assertEquals(UploadResult.Retry(4000), up.uploadOnce())
        assertEquals(UploadResult.Retry(5000), up.uploadOnce()) // capped
        assertEquals(3, b.size()) // nothing lost while failing
        status = 403
        assertEquals(UploadResult.Stop(403), up.uploadOnce()); assertEquals(3, b.size())
        status = 202
        assertEquals(UploadResult.Sent(3), up.uploadOnce()); assertEquals(0, b.size())
        assertEquals(UploadResult.Nothing, up.uploadOnce())
    }

    @Test fun uploaderDropsUnfixableBatchAndRetriesOnNetworkError() {
        val b = GpsBuffer(); b.add(pt(1), gate)
        assertIs<UploadResult.Retry>(GpsUploader(b, { throw java.io.IOException("down") }).uploadOnce())
        assertEquals(1, b.size())
        assertEquals(UploadResult.Rejected(1), GpsUploader(b, { 422 }).uploadOnce())
        assertNull(b.nextBatch())
    }
}
