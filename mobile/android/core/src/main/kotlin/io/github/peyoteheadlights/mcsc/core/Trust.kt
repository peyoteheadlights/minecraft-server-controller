package io.github.peyoteheadlights.mcsc.core

import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSession
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import okhttp3.OkHttpClient
import okhttp3.internal.tls.OkHostnameVerifier

/** SHA-256 of a certificate's DER bytes, as 64 lowercase hex digits. */
fun certificateFingerprint(certificate: X509Certificate): String =
    MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
        .joinToString("") { "%02x".format(it) }

/** The certificate wasn't the one the pairing code named. */
class CertificateMismatchException(val presented: String) :
    CertificateException("The PC's certificate doesn't match the pairing code.")

/** No pin matched and the phone doesn't trust the certificate either. */
class CertificateNotTrustedException(val presented: String, cause: Throwable?) :
    CertificateException("The PC's certificate isn't trusted.", cause)

/**
 * How the app checks the agent's certificate. Certificate checks are never
 * switched off; a certificate passes in exactly one of two ways:
 *
 *  1. Its SHA-256 equals [pin], the fingerprint from the pairing code (the
 *     PC's own certificate from installer/make_certs.py, whoever issued it).
 *  2. Not [strict], and the phone's own trust store accepts it with the
 *     normal checks (a Tailscale certificate, renewed every few months).
 *
 * While pairing from a code, [strict] is on: only the certificate the code
 * names is accepted, so a different one is refused even if trusted.
 */
class PinnedTrust(
    private val pin: String?,
    private val strict: Boolean,
    private val system: X509TrustManager = systemTrustManager(),
) : X509TrustManager {
    /** The fingerprint of the certificate the PC last presented. */
    @Volatile
    var lastPresented: String? = null
        private set

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("No certificate was presented.")
        val presented = certificateFingerprint(leaf)
        lastPresented = presented
        if (pin != null && presented == pin) {
            leaf.checkValidity()
            return
        }
        if (strict && pin != null) throw CertificateMismatchException(presented)
        try {
            system.checkServerTrusted(chain, authType)
        } catch (e: Exception) {
            // Any refusal (some trust stores throw more than CertificateException)
            // is a refusal: never fall through to accepting.
            if (pin != null) throw CertificateMismatchException(presented)
            throw CertificateNotTrustedException(presented, e)
        }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
        throw CertificateException("This app never accepts client connections.")

    override fun getAcceptedIssuers(): Array<X509Certificate> = system.acceptedIssuers

    /**
     * The pinned certificate is accepted for the address it was paired with
     * even if its names don't include it (a typed Tailscale IP, say); any
     * other certificate must name the host, as usual.
     */
    val hostnameVerifier: HostnameVerifier = HostnameVerifier { host: String, session: SSLSession ->
        val leaf = session.peerCertificates.firstOrNull() as? X509Certificate
        if (pin != null && leaf != null && certificateFingerprint(leaf) == pin) {
            true
        } else {
            OkHostnameVerifier.verify(host, session)
        }
    }

    fun applyTo(builder: OkHttpClient.Builder): OkHttpClient.Builder {
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(this), null)
        return builder.sslSocketFactory(context.socketFactory, this).hostnameVerifier(hostnameVerifier)
    }

    companion object {
        fun systemTrustManager(): X509TrustManager {
            val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            factory.init(null as KeyStore?)
            return factory.trustManagers.filterIsInstance<X509TrustManager>().first()
        }
    }
}
