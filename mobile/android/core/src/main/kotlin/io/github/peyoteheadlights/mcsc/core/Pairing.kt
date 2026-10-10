package io.github.peyoteheadlights.mcsc.core

import java.net.URI
import java.net.URISyntaxException

/** The agent's port when an address is typed without one (config.example.yaml). */
const val DEFAULT_PORT = 8765

/**
 * Which PC the app talks to: its address and, from the pairing code, the
 * SHA-256 fingerprint of its certificate (64 lowercase hex digits).
 *
 * The pairing code is an ordinary link (agent/pairing.py):
 *   https://<address>:<port>/?pair=1&fp=<certificate SHA-256>&api=<API version>
 * A typed address has no fingerprint: the app then only accepts a
 * certificate the phone already trusts, or one the person confirms by
 * comparing the fingerprint shown in the dashboard.
 */
data class Pairing(
    val host: String,
    val port: Int,
    val fingerprint: String?,
    val apiVersion: Int? = null,
) {
    val origin: String
        get() = "https://${if (host.contains(':')) "[$host]" else host}:$port"

    /** The same address and port: a new code for this PC (a renewed
     * certificate) may keep the sign-in. Anything else is another PC, and
     * the sign-in is never sent there. */
    fun samePc(other: Pairing): Boolean = host.equals(other.host, ignoreCase = true) && port == other.port
}

sealed class PairingProblem(val key: String) {
    /** Nothing that looks like an address or a pairing link. */
    data object NotAnAddress : PairingProblem("mobile.pair.error_not_address")

    /** http:// or another scheme: only HTTPS is ever used. */
    data object NotHttps : PairingProblem("mobile.pair.error_not_https")

    /** A pairing link whose fingerprint isn't 64 hex digits. */
    data object BadFingerprint : PairingProblem("mobile.pair.error_bad_code")
}

class PairingParseException(val problem: PairingProblem) : Exception(problem.key)

object PairingLink {
    private val HEX64 = Regex("^[0-9a-fA-F]{64}$")
    private val HOST = Regex("^[A-Za-z0-9.-]+$|^\\[?[0-9A-Fa-f:]+]?$")

    /** A scanned code or a typed address. Throws [PairingParseException]. */
    fun parse(input: String): Pairing {
        val text = input.trim()
        if (text.isEmpty() || text.any { it.isWhitespace() }) {
            throw PairingParseException(PairingProblem.NotAnAddress)
        }
        val withScheme = when {
            text.startsWith("https://", ignoreCase = true) -> text
            text.contains("://") -> throw PairingParseException(PairingProblem.NotHttps)
            else -> "https://$text"
        }
        val uri = try {
            URI(withScheme)
        } catch (e: URISyntaxException) {
            throw PairingParseException(PairingProblem.NotAnAddress)
        }
        val host = uri.host?.trim('[', ']')
        if (host.isNullOrEmpty() || !HOST.matches(host) || uri.userInfo != null) {
            throw PairingParseException(PairingProblem.NotAnAddress)
        }
        val port = if (uri.port == -1) DEFAULT_PORT else uri.port
        if (port !in 1..65535) throw PairingParseException(PairingProblem.NotAnAddress)
        val query = parseQuery(uri.rawQuery)
        if (query["pair"] != "1") return Pairing(host.lowercase(), port, null)
        val fp = query["fp"] ?: throw PairingParseException(PairingProblem.BadFingerprint)
        if (!HEX64.matches(fp)) throw PairingParseException(PairingProblem.BadFingerprint)
        return Pairing(host.lowercase(), port, fp.lowercase(), query["api"]?.toIntOrNull())
    }

    private fun parseQuery(raw: String?): Map<String, String> {
        if (raw.isNullOrEmpty()) return emptyMap()
        return raw.split('&').mapNotNull { part ->
            val eq = part.indexOf('=')
            if (eq <= 0) null else part.substring(0, eq) to java.net.URLDecoder.decode(part.substring(eq + 1), "UTF-8")
        }.toMap()
    }
}

/** "ab12…" as the dashboard shows it in Technical mode: pairs split by colons. */
fun formatFingerprint(hex: String): String =
    hex.uppercase().chunked(2).joinToString(":")
