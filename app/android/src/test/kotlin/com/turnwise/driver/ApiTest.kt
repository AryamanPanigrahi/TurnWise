package com.turnwise.driver

import com.turnwise.driver.core.GpsBatch
import com.turnwise.driver.core.GpsBuffer
import com.turnwise.driver.core.GpsUploader
import com.turnwise.driver.core.TrackingGate
import com.turnwise.driver.core.TripEvent
import com.turnwise.driver.core.UploadResult
import com.turnwise.driver.core.toJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The API client against a fake server speaking the backend's JSON (backend/schemas.py, field.py). */
class ApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: TripApi

    @BeforeTest fun up() {
        server = MockWebServer(); server.start()
        api = TripApi(server.url("/").toString(), "tok-123")      // base url with a trailing slash on purpose
    }

    @AfterTest fun down() { server.shutdown() }

    private fun json(body: String, code: Int = 200) =
        MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)

    @Test fun `create trip sends the token and both places and reads the reply`() {
        server.enqueue(json("""{"trip_id":"trp_abc","length_m":17852.0,"decision_points":7}""", 201))
        val trip = api.createTrip(Place(12.9757, 77.6061), Place(12.8456, 77.6603))
        assertEquals(TripCreated("trp_abc", 17852.0, 7), trip)

        val req = server.takeRequest()
        assertEquals("POST", req.method); assertEquals("/v1/trips", req.path)
        assertEquals("Bearer tok-123", req.getHeader("Authorization"))
        assertEquals("""{"origin":{"lat":12.9757,"lon":77.6061},"destination":{"lat":12.8456,"lon":77.6603}}""",
            req.body.readUtf8())
    }

    @Test fun `which_branch names the options and other questions send empty slots`() {
        server.enqueue(json("""{"answer_key":"which_branch.flyover","facts":{"on_route":"flyover","distance_m":350}}"""))
        server.enqueue(json("""{"answer_key":"eta","facts":{"eta_s":600,"remaining_m":9000}}"""))
        val a = api.ask("trp_abc", "which_branch")
        assertEquals("which_branch.flyover", a.answer_key)
        assertEquals(JsonPrimitive(350), a.facts["distance_m"])
        api.ask("trp_abc", "eta")

        assertEquals("""{"trip_id":"trp_abc","intent":"which_branch","slots":{"options":["flyover","service_road"]}}""",
            server.takeRequest().body.readUtf8())
        assertEquals("""{"trip_id":"trp_abc","intent":"eta","slots":{}}""", server.takeRequest().body.readUtf8())
    }

    @Test fun `sentences come from the server and null means stay silent`() {
        server.enqueue(json("""{"text":"Take the flyover, 350 metres ahead.","template":"which_branch"}"""))
        server.enqueue(json("""{"text":null,"template":null}"""))
        val answer = AskResponse("which_branch.flyover", JsonObject(mapOf("distance_m" to JsonPrimitive(350))))
        assertEquals("Take the flyover, 350 metres ahead.", api.sayAnswer("kn", answer))
        assertNull(api.sayEvent("en", "arrived", null))

        assertEquals("""{"lang":"kn","answer_key":"which_branch.flyover","facts":{"distance_m":350}}""",
            server.takeRequest().body.readUtf8())
        assertEquals("""{"lang":"en","event":"arrived","data":{}}""", server.takeRequest().body.readUtf8())
    }

    @Test fun `route for the map is parsed`() {
        server.enqueue(json("""{"route":[[12.9,77.6],[12.8,77.7]],"length_m":100.0,"decision_points":[{"at_m":50}]}"""))
        val r = api.route("trp_abc")
        assertEquals(listOf(listOf(12.9, 77.6), listOf(12.8, 77.7)), r.route)
        assertEquals("/field/api/trips/trp_abc/route", server.takeRequest().path)
    }

    @Test fun `a refusal from the server is an ApiException with the status`() {
        server.enqueue(json("""{"detail":"could not plan a route"}""", 502))
        val e = assertFailsWith<ApiException> { api.createTrip(Place(0.0, 0.0), Place(1.0, 1.0)) }
        assertEquals(502, e.status)
        assertTrue("could not plan a route" in e.message.orEmpty())
    }

    @Test fun `end trip posts to the trip`() {
        server.enqueue(MockResponse().setResponseCode(204))
        api.endTrip("trp_abc")
        assertEquals("/v1/trips/trp_abc/end", server.takeRequest().path)
    }

    @Test fun `core uploader sends buffered fixes through this client and stops on 409`() {
        val gate = TrackingGate(consentRecorded = true, onDuty = true, activeTripId = "trp_abc")
        val buffer = GpsBuffer()
        repeat(3) { i -> buffer.add(fixToPoint("trp_abc", 1794026405000L + i * 1000, 12.9, 77.6, 10f, 90f, 5f), gate) }
        val uploader = GpsUploader(buffer, api)

        server.enqueue(json("""{"accepted":3,"duplicates":0,"late":0}""", 202))
        assertEquals(UploadResult.Sent(3), uploader.uploadOnce())
        val req = server.takeRequest()
        assertEquals("/v1/gps", req.path); assertEquals("Bearer tok-123", req.getHeader("Authorization"))
        assertTrue(req.body.readUtf8().startsWith("""{"points":[{"trip_id":"trp_abc","ts":"2026-11-07T04:40:05.000Z","""))

        buffer.add(fixToPoint("trp_abc", 1794026409000L, 12.9, 77.6, 10f, 90f, 5f), gate)
        server.enqueue(json("""{"detail":"trip is not active"}""", 409))
        assertEquals(UploadResult.Stop(409), uploader.uploadOnce())
        assertEquals(1, buffer.size())                               // kept, not lost
    }

    @Test fun `events socket authenticates with the header and delivers backend events core can parse`() {
        val got = LinkedBlockingQueue<String>()
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                // exactly what backend/registry.py publishes
                webSocket.send("""{"event":"arrived","trip_id":"trp_abc","ts":"2026-11-07T04:49:49.000Z","seq":15,"data":{"stop_id":"stp_abc_1","distance_m":16}}""")
                webSocket.send("""{"event":"off_route","trip_id":"trp_abc","ts":"2026-11-07T04:41:00.000Z","seq":16,"data":{"reason":"distance","deviation_m":42,"confidence":1.0,"recovery":{"action":"reroute"}}}""")
            }
        }))
        val ws = api.openEvents("trp_abc", 14, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) { got.add(text) }
        })
        val arrived = TripEvent.parse(got.poll(5, TimeUnit.SECONDS)!!)
        val off = TripEvent.parse(got.poll(5, TimeUnit.SECONDS)!!)
        ws.cancel()

        assertIs<TripEvent.Arrived>(arrived); assertEquals("stp_abc_1", arrived.stopId)
        assertIs<TripEvent.OffRoute>(off); assertEquals("reroute", off.recovery.action)
        val req = server.takeRequest()
        assertEquals("/v1/trips/trp_abc/events?last_seq=14", req.path)
        assertEquals("Bearer tok-123", req.getHeader("Authorization"))
    }

    @Test fun `gps batch json matches the contract shape`() {
        val p = fixToPoint("trp_abc", 1794026405000L, 12.9, 77.6, null, null, null)
        assertEquals("""{"points":[{"trip_id":"trp_abc","ts":"2026-11-07T04:40:05.000Z","lat":12.9,"lon":77.6,"speed":null,"heading":null,"accuracy":null}]}""",
            GpsBatch(listOf(p)).toJson())
    }
}
