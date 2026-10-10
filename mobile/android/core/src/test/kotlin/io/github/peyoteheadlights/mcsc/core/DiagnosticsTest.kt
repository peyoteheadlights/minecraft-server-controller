package io.github.peyoteheadlights.mcsc.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DiagnosticsTest {
    @Test
    fun `diagnostics have versions and requests, nothing that signs in or finds the PC`() {
        val log = RequestLog(size = 2, clock = { 0L })
        log.line("GET /api/servers -> 200")
        log.line("GET /api/alerts -> 401")
        log.line("POST /api/auth/login -> 200")
        assertEquals(2, log.recent().size)
        val text = Diagnostics.text(
            Diagnostics.Facts("0.1.0", "Android", "15", "Pixel 9", "1.3.0", 1, paired = true, pinned = true,
                signedIn = true, lockScreenAlerts = null, lastProblem = "mobile.error.unreachable"),
            log.recent(),
        )
        assertTrue(text, text.contains("App: 0.1.0 (Android 15, Pixel 9)"))
        assertTrue(text, text.contains("Lock-screen alerts: Unknown"))
        assertTrue(text, text.contains("POST /api/auth/login -> 200"))
        assertFalse(text, text.contains("/api/servers"))
        for (secret in listOf("token", "Bearer", "password", "ts.net", "fingerprint")) {
            assertFalse(secret, text.contains(secret, ignoreCase = true))
        }
    }
}
