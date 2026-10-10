package io.github.peyoteheadlights.mcsc.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingLinkTest {
    private val fp = "AB".repeat(32)

    @Test
    fun `a pairing code gives the address, port, fingerprint and API`() {
        val p = PairingLink.parse("https://My-PC.tail1234.ts.net:9000/?pair=1&fp=$fp&api=1")
        assertEquals(Pairing("my-pc.tail1234.ts.net", 9000, fp.lowercase(), 1), p)
        assertEquals("https://my-pc.tail1234.ts.net:9000", p.origin)
    }

    @Test
    fun `a typed address uses the agent's port and has no fingerprint`() {
        val p = PairingLink.parse("  my-pc.tail1234.ts.net ")
        assertEquals(DEFAULT_PORT, p.port)
        assertNull(p.fingerprint)
        assertEquals(8000, PairingLink.parse("100.101.102.103:8000").port)
    }

    @Test
    fun `an IPv6 address keeps its brackets in the origin`() {
        val p = PairingLink.parse("[fd7a:115c:a1e0::1]:8765")
        assertEquals("https://[fd7a:115c:a1e0::1]:8765", p.origin)
    }

    @Test
    fun `http and other schemes are refused`() {
        for (text in listOf("http://my-pc:8765", "ftp://my-pc", "javascript://x")) {
            val e = assertThrows(PairingParseException::class.java) { PairingLink.parse(text) }
            assertEquals(PairingProblem.NotHttps, e.problem)
        }
    }

    @Test
    fun `things that aren't addresses are refused`() {
        for (text in listOf("", "my pc", "https://", "https://user:pw@my-pc", "https://my-pc:99999", "héllo")) {
            val e = assertThrows(PairingParseException::class.java) { PairingLink.parse(text) }
            assertEquals(text, PairingProblem.NotAnAddress, e.problem)
        }
    }

    @Test
    fun `a pairing code with a broken fingerprint is refused`() {
        for (bad in listOf("", "abc", "zz".repeat(32), fp + "00")) {
            val e = assertThrows(PairingParseException::class.java) {
                PairingLink.parse("https://my-pc:8765/?pair=1&fp=$bad")
            }
            assertEquals(PairingProblem.BadFingerprint, e.problem)
        }
        val e = assertThrows(PairingParseException::class.java) { PairingLink.parse("https://my-pc:8765/?pair=1") }
        assertEquals(PairingProblem.BadFingerprint, e.problem)
    }

    @Test
    fun `a new code keeps the sign-in only for the same address and port`() {
        val now = PairingLink.parse("https://my-pc.tail1234.ts.net:8765/?pair=1&fp=$fp")
        val renewed = PairingLink.parse("https://My-PC.tail1234.ts.net:8765/?pair=1&fp=${"ab".repeat(32)}")
        assertTrue(now.samePc(renewed))
        assertFalse(now.samePc(PairingLink.parse("https://my-pc.tail1234.ts.net:9000/?pair=1&fp=$fp")))
        assertFalse(now.samePc(PairingLink.parse("https://other-pc.tail1234.ts.net:8765/?pair=1&fp=$fp")))
    }

    @Test
    fun `fingerprints read as the dashboard shows them`() {
        assertEquals("AB:CD:01", formatFingerprint("abcd01"))
    }
}
