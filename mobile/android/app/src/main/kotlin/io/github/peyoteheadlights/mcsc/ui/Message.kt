package io.github.peyoteheadlights.mcsc.ui

import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Strings

/** Something to say, as a strings key and its values, so it follows the
 * person's choice of Simple or Technical words. */
data class Message(val key: String, val values: Map<String, String> = emptyMap()) {
    fun text(strings: Strings): String = strings.t(key, *values.map { it.key to it.value }.toTypedArray())

    companion object {
        /** What went wrong, in the agent's own words where it gave some. */
        fun of(e: AgentException): Message = when (e) {
            is AgentException.SignInRefused ->
                if (e.reason.isBlank()) Message("mobile.error.failed_no_reason", mapOf("status" to "401"))
                else Message(e.key, mapOf("reason" to e.reason))
            is AgentException.NotAllowed ->
                if (e.reason.isBlank()) Message(e.key) else Message("mobile.error.sign_in", mapOf("reason" to e.reason))
            is AgentException.Failed -> {
                // Read once: a property from the core module can't be smart-cast.
                val reason = e.reason
                if (reason.isNullOrBlank()) Message("mobile.error.failed_no_reason", mapOf("status" to e.status.toString()))
                else Message(e.key, mapOf("reason" to reason))
            }
            else -> Message(e.key)
        }
    }
}
