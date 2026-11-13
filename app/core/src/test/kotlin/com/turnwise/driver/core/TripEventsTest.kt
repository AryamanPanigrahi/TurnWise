package com.turnwise.driver.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class TripEventsTest {
    private fun env(event: String, seq: Long, data: String = "{}") =
        """{"event":"$event","trip_id":"trp_1","ts":"2026-11-05T04:31:09.120Z","seq":$seq,"data":$data,"extra":1}"""

    @Test fun parsesEveryContractEvent() {
        val off = TripEvent.parse(env("off_route", 1,
            """{"recovery":{"action":"u_turn","distance_m":300},"deviation_m":45,"confidence":0.95}"""))
        assertIs<TripEvent.OffRoute>(off)
        assertEquals(Recovery("u_turn", 300.0), off.recovery)

        assertIs<TripEvent.BackOnRoute>(TripEvent.parse(env("back_on_route", 2)))

        val dp = TripEvent.parse(env("decision_point_ahead", 3,
            """{"type":"flyover_vs_service","on_route":"flyover","alternatives":["service_road"],
               "distance_m":400,"landmark":"Indian Oil pump","confidence":0.9,"new_field":true}"""))
        assertIs<TripEvent.DecisionPointAhead>(dp)
        assertEquals("flyover", dp.fact.on_route)

        val arr = TripEvent.parse(env("arrived", 4, """{"stop_id":"stp_9","distance_m":12}"""))
        assertIs<TripEvent.Arrived>(arr); assertEquals("stp_9", arr.stopId)
    }

    @Test fun unknownEventsAreKeptForSeqButInvalidFramesAreNull() {
        assertIs<TripEvent.Unknown>(TripEvent.parse(env("heartbeat", 5)))
        assertNull(TripEvent.parse("not json"))
        assertNull(TripEvent.parse(env("off_route", 1, "{}"))) // missing recovery
        assertNull(TripEvent.parse("""{"event":"arrived"}"""))
    }

    @Test fun sequencerDropsDuplicatesAndCountsGaps() {
        val s = EventSequencer()
        fun e(seq: Long) = TripEvent.BackOnRoute("trp_1", "t", seq)
        assertTrue(s.accept(e(1))); assertFalse(s.accept(e(1)))
        assertTrue(s.accept(e(2))); assertTrue(s.accept(e(5)))
        assertFalse(s.accept(e(3)))
        assertEquals(1, s.gaps); assertEquals(5, s.lastSeq)
    }
}
