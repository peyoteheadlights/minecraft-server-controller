package io.github.peyoteheadlights.mcsc.core

/**
 * The app's own request log for "Copy diagnostics": method, path and the
 * answer's status, newest [size] lines. [AgentClient] only ever writes
 * those, never headers, bodies, the sign-in token or a password.
 */
class RequestLog(private val size: Int = 50, private val clock: () -> Long = System::currentTimeMillis) : AgentLog {
    private val lines = ArrayDeque<String>()

    @Synchronized
    override fun line(text: String) {
        val stamp = java.time.Instant.ofEpochMilli(clock()).toString()
        lines.addLast("$stamp $text")
        while (lines.size > size) lines.removeFirst()
    }

    @Synchronized
    fun recent(): List<String> = lines.toList()
}

/**
 * What "Copy diagnostics" puts on the clipboard, to paste into "Report a
 * problem". Enough to tell versions and what failed; nothing that signs in
 * or finds the PC: no token, no password, no address, no fingerprint.
 */
object Diagnostics {
    data class Facts(
        val appVersion: String,
        val platform: String,
        val osVersion: String,
        val device: String,
        val agentVersion: String?,
        val agentApi: Int?,
        val paired: Boolean,
        val pinned: Boolean,
        val signedIn: Boolean,
        val lockScreenAlerts: Boolean?,
        val lastProblem: String?,
    )

    fun text(facts: Facts, log: List<String>): String = buildString {
        appendLine("App: ${facts.appVersion} (${facts.platform} ${facts.osVersion}, ${facts.device})")
        appendLine("Agent: ${facts.agentVersion ?: "Unknown"}, API ${facts.agentApi?.toString() ?: "Unknown"}")
        appendLine("Paired: ${yes(facts.paired)}, certificate pinned: ${yes(facts.pinned)}, signed in: ${yes(facts.signedIn)}")
        appendLine("Lock-screen alerts: ${facts.lockScreenAlerts?.let(::yes) ?: "Unknown"}")
        appendLine("Last problem: ${facts.lastProblem ?: "None"}")
        if (log.isNotEmpty()) {
            appendLine()
            appendLine("Recent requests:")
            log.forEach { appendLine(it) }
        }
    }.trimEnd()

    private fun yes(value: Boolean) = if (value) "yes" else "no"
}
