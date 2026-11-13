package com.turnwise.driver.core

/**
 * Where buffered fixes live. Android implements this on disk so fixes survive
 * the app being killed while the network is down; tests use [InMemoryPointStore].
 * Points are kept in the order they were added.
 */
interface PointStore {
    fun append(p: GpsPoint)
    fun peek(n: Int): List<GpsPoint>
    fun removeFirst(n: Int)
    fun size(): Int
}

class InMemoryPointStore : PointStore {
    private val q = ArrayDeque<GpsPoint>()
    override fun append(p: GpsPoint) { q.addLast(p) }
    override fun peek(n: Int): List<GpsPoint> = q.take(n)
    override fun removeFirst(n: Int) { repeat(minOf(n, q.size)) { q.removeFirst() } }
    override fun size(): Int = q.size
}

/**
 * Offline buffer for GPS fixes.
 *
 * - Records only while [TrackingGate] allows it (DPDP: on duty, on a trip, with consent).
 * - Drops a fix with the same `ts` as the previous one (some phones repeat fixes).
 * - Hands out batches of at most [MAX_BATCH] (the contract's limit) oldest-first,
 *   and forgets them only after the server accepted them ([ack]).
 * - Never grows past [capacity]: the oldest fixes are dropped first and counted,
 *   so a phone offline all day can't fill its storage.
 */
class GpsBuffer(
    private val store: PointStore = InMemoryPointStore(),
    private val capacity: Int = 8 * 3600, // 8 h at 1 Hz
) {
    var dropped: Long = 0
        private set
    private var lastTs: String? = null

    fun add(p: GpsPoint, gate: TrackingGate): Boolean {
        if (!gate.allows(p.trip_id)) return false
        if (p.ts == lastTs) return false
        lastTs = p.ts
        if (store.size() >= capacity) {
            store.removeFirst(1)
            dropped++
        }
        store.append(p)
        return true
    }

    fun nextBatch(max: Int = MAX_BATCH): GpsBatch? {
        val pts = store.peek(minOf(max, MAX_BATCH))
        return if (pts.isEmpty()) null else GpsBatch(pts)
    }

    /** Forget a batch the server accepted (or permanently rejected). */
    fun ack(batch: GpsBatch) = store.removeFirst(batch.points.size)

    fun size(): Int = store.size()

    companion object { const val MAX_BATCH = 600 }
}

/**
 * Whether GPS may be recorded right now (CLAUDE.md rule 5): only on duty, on the
 * active trip, and with consent recorded at onboarding.
 */
data class TrackingGate(
    val consentRecorded: Boolean,
    val onDuty: Boolean,
    val activeTripId: String?,
) {
    fun allows(tripId: String): Boolean =
        consentRecorded && onDuty && activeTripId != null && activeTripId == tripId
}
