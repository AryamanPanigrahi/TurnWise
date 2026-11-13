package com.turnwise.driver.core

/** HTTP seam: the Android module implements this with its HTTP client. */
fun interface GpsTransport {
    /** POST the JSON body to `/v1/gps`; return the status code. Throw on network failure. */
    fun post(json: String): Int
}

sealed interface UploadResult {
    data object Nothing : UploadResult
    data class Sent(val points: Int) : UploadResult
    /** Network error or 5xx: keep the batch and try again after [delayMs]. */
    data class Retry(val delayMs: Long) : UploadResult
    /** 422: the server will never accept this batch, so it was dropped. */
    data class Rejected(val points: Int) : UploadResult
    /**
     * 401/403/409: unauthenticated, no consent, or the trip is no longer active.
     * Stop tracking and let the app sort out login or trip state; the batch is kept.
     */
    data class Stop(val status: Int) : UploadResult
}

/**
 * Sends one batch per [uploadOnce] call. The caller (a WorkManager job or a loop
 * on Android) decides when to call it, using the delay in [UploadResult.Retry].
 *
 * Retries back off exponentially (2 s, 4 s, 8 s... capped at 5 min) so a long
 * network drop doesn't drain the battery.
 */
class GpsUploader(
    private val buffer: GpsBuffer,
    private val transport: GpsTransport,
    private val baseDelayMs: Long = 2_000,
    private val maxDelayMs: Long = 300_000,
) {
    private var failures = 0

    fun uploadOnce(): UploadResult {
        val batch = buffer.nextBatch() ?: return UploadResult.Nothing
        val status = try {
            transport.post(batch.toJson())
        } catch (e: Exception) {
            return retry()
        }
        return when (status) {
            200, 202 -> { failures = 0; buffer.ack(batch); UploadResult.Sent(batch.points.size) }
            401, 403, 409 -> UploadResult.Stop(status)
            422 -> { failures = 0; buffer.ack(batch); UploadResult.Rejected(batch.points.size) }
            else -> retry()
        }
    }

    private fun retry(): UploadResult.Retry {
        val shift = minOf(failures, 20)
        failures++
        return UploadResult.Retry(minOf(maxDelayMs, baseDelayMs shl shift))
    }
}
