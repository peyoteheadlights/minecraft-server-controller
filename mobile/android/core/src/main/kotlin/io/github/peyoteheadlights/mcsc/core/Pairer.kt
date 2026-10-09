package io.github.peyoteheadlights.mcsc.core

import javax.net.ssl.X509TrustManager
import okhttp3.OkHttpClient

/** Which agent API versions this app works with (mobile/version.json). */
data class ApiRange(val min: Int, val max: Int)

sealed class Compatibility {
    data object Ok : Compatibility()

    /** The agent is older than this app needs: update the app on the PC. */
    data class AgentTooOld(val agentApi: Int) : Compatibility()

    /** The agent is newer than this app knows: update the phone app. */
    data class AgentTooNew(val agentApi: Int) : Compatibility()
}

fun compatibility(agentApi: Int, range: ApiRange): Compatibility = when {
    agentApi < range.min -> Compatibility.AgentTooOld(agentApi)
    agentApi > range.max -> Compatibility.AgentTooNew(agentApi)
    else -> Compatibility.Ok
}

/** What checking an address found. */
sealed class PairResult {
    /** It is this app's agent, with the certificate the code named (or one
     * the phone trusts) and an API this app speaks: save [pairing]. */
    data class Paired(val pairing: Pairing, val health: Health) : PairResult()

    /** A typed address with a certificate the phone doesn't trust: show
     * [fingerprint] and ask the person to compare it with the dashboard's. */
    data class ConfirmFingerprint(val pairing: Pairing, val fingerprint: String) : PairResult()

    data class Refused(val problem: AgentException) : PairResult()

    data class Incompatible(val compatibility: Compatibility) : PairResult()
}

/**
 * Checks an address before anything else is sent to it: only /api/health,
 * which needs no sign-in and reveals nothing. Refuses a certificate that
 * isn't the one the pairing code names, and an answer that isn't the agent's.
 */
class Pairer(
    private val range: ApiRange,
    private val baseClient: OkHttpClient = OkHttpClient(),
    private val log: AgentLog = AgentLog { },
    private val systemTrust: X509TrustManager = PinnedTrust.systemTrustManager(),
) {
    suspend fun check(pairing: Pairing): PairResult {
        val client = AgentClient(
            pairing,
            token = { null },
            log = log,
            strict = pairing.fingerprint != null,
            baseClient = baseClient,
            systemTrust = systemTrust,
        )
        val health = try {
            client.health()
        } catch (e: AgentException.CertificateNotTrusted) {
            val seen = e.presented ?: return PairResult.Refused(e)
            return PairResult.ConfirmFingerprint(pairing, seen)
        } catch (e: AgentException.CertificateChanged) {
            return PairResult.Refused(e)
        } catch (e: AgentException.Failed) {
            return PairResult.Refused(AgentException.NotAnAgent())
        } catch (e: AgentException.SignInRefused) {
            return PairResult.Refused(AgentException.NotAnAgent())
        } catch (e: AgentException.NotAllowed) {
            return PairResult.Refused(AgentException.NotAnAgent())
        } catch (e: AgentException) {
            return PairResult.Refused(e)
        }
        val api = health.apiVersion
        if (!health.ok || api == null || health.agentUptime == null) {
            return PairResult.Refused(AgentException.NotAnAgent())
        }
        val fit = compatibility(api, range)
        if (fit != Compatibility.Ok) return PairResult.Incompatible(fit)
        // A typed address the phone trusts: remember the certificate it
        // showed, so a different one later is noticed.
        val pinned = pairing.copy(fingerprint = pairing.fingerprint ?: client.trust.lastPresented, apiVersion = api)
        return PairResult.Paired(pinned, health)
    }

    /** The person compared the fingerprint and it matches the dashboard's. */
    suspend fun confirm(pairing: Pairing, fingerprint: String): PairResult =
        check(pairing.copy(fingerprint = fingerprint))
}
