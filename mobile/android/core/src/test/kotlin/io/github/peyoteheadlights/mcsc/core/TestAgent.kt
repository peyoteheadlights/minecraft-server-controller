package io.github.peyoteheadlights.mcsc.core

import java.net.InetAddress
import javax.net.ssl.X509TrustManager
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate

/** A pretend agent on https://localhost with its own self-signed certificate,
 * like the one installer/make_certs.py makes. */
class TestAgent(names: List<String> = listOf("localhost"), expired: Boolean = false) : AutoCloseable {
    val certificate: HeldCertificate = HeldCertificate.Builder()
        .commonName("Minecraft Server Controller")
        .apply { names.forEach { addSubjectAlternativeName(it) } }
        .apply {
            if (expired) {
                val day = 86_400_000L
                val now = System.currentTimeMillis()
                validityInterval(now - 400 * day, now - day)
            }
        }
        .build()
    val server = MockWebServer()
    val fingerprint: String = certificateFingerprint(certificate.certificate)

    init {
        server.useHttps(
            HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(),
            false,
        )
        server.start(InetAddress.getByName("localhost"), 0)
    }

    val port: Int get() = server.port

    fun pairing(pin: String? = fingerprint) = Pairing("localhost", port, pin)

    fun json(body: String, code: Int = 200): MockResponse =
        MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)

    fun health(api: Int = 1) = json("""{"ok": true, "agent_uptime": 12.5, "auth_configured": true, "api_version": $api}""")

    override fun close() = server.shutdown()

    companion object {
        /** A phone whose own trust store accepts [certificate] (as it
         * would a Tailscale certificate): no pin needed. */
        fun trusting(certificate: HeldCertificate): X509TrustManager =
            HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build().trustManager

        /** A phone whose trust store holds only some unrelated authority. */
        fun trustingNothing(): X509TrustManager =
            HandshakeCertificates.Builder()
                .addTrustedCertificate(HeldCertificate.Builder().certificateAuthority(0).build().certificate)
                .build().trustManager
    }
}
