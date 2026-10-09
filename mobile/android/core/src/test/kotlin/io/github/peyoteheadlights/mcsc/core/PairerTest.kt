package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PairerTest {
    private val range = ApiRange(1, 1)

    private fun pairer(trust: javax.net.ssl.X509TrustManager = TestAgent.trustingNothing()) =
        Pairer(range, systemTrust = trust)

    @Test
    fun `the code's certificate is accepted even though the phone doesn't trust it`() = runBlocking {
        TestAgent(names = listOf("some-other-name")).use { agent ->
            agent.server.enqueue(agent.health())
            val result = pairer().check(agent.pairing())
            assertTrue(result.toString(), result is PairResult.Paired)
            result as PairResult.Paired
            assertEquals(agent.fingerprint, result.pairing.fingerprint)
            assertEquals(1, result.pairing.apiVersion)
            assertEquals("/api/health", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `a different certificate from the code's is refused, even a trusted one`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.health())
            val result = pairer(TestAgent.trusting(agent.certificate)).check(agent.pairing("00".repeat(32)))
            assertTrue(result.toString(), result is PairResult.Refused)
            val problem = (result as PairResult.Refused).problem
            assertTrue(problem is AgentException.CertificateChanged)
            assertEquals(agent.fingerprint, (problem as AgentException.CertificateChanged).presented)
            // Nothing was asked of it: the handshake failed first.
            assertEquals(0, agent.server.requestCount)
        }
    }

    @Test
    fun `a typed address with a certificate the phone trusts pairs and pins it`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.health())
            val result = pairer(TestAgent.trusting(agent.certificate)).check(agent.pairing(pin = null))
            result as PairResult.Paired
            assertEquals(agent.fingerprint, result.pairing.fingerprint)
        }
    }

    @Test
    fun `a typed address with an unknown certificate asks the person to compare`() = runBlocking {
        TestAgent().use { agent ->
            val result = pairer().check(agent.pairing(pin = null))
            assertTrue(result.toString(), result is PairResult.ConfirmFingerprint)
            assertEquals(agent.fingerprint, (result as PairResult.ConfirmFingerprint).fingerprint)
            assertEquals(0, agent.server.requestCount)
            agent.server.enqueue(agent.health())
            val confirmed = pairer().confirm(result.pairing, result.fingerprint)
            assertTrue(confirmed.toString(), confirmed is PairResult.Paired)
        }
    }

    @Test
    fun `something that isn't the agent is refused`() = runBlocking {
        val answers = listOf(
            MockResponse().setHeader("Content-Type", "text/html").setBody("<html>router</html>"),
            MockResponse().setHeader("Content-Type", "application/json").setBody("""{"ok": true}"""),
            MockResponse().setHeader("Content-Type", "application/json").setBody("not json"),
            MockResponse().setResponseCode(404).setHeader("Content-Type", "application/json").setBody("""{"detail":"Not Found"}"""),
            MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json").setBody("""{"detail":"no"}"""),
        )
        for (answer in answers) {
            TestAgent().use { agent ->
                agent.server.enqueue(answer)
                val result = pairer().check(agent.pairing())
                assertTrue(result.toString(), result is PairResult.Refused)
                assertTrue((result as PairResult.Refused).problem is AgentException.NotAnAgent)
            }
        }
    }

    @Test
    fun `an address nothing answers at is unreachable`() = runBlocking {
        val port = TestAgent().use { it.port }
        val result = pairer().check(Pairing("localhost", port, "ab".repeat(32)))
        assertTrue(result.toString(), (result as PairResult.Refused).problem is AgentException.Unreachable)
    }

    @Test
    fun `an agent with an API this app doesn't speak is named, not paired`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.health(api = 2))
            assertEquals(PairResult.Incompatible(Compatibility.AgentTooNew(2)), pairer().check(agent.pairing()))
        }
        assertEquals(Compatibility.AgentTooOld(1), compatibility(1, ApiRange(2, 3)))
        assertEquals(Compatibility.Ok, compatibility(2, ApiRange(2, 3)))
    }
}
