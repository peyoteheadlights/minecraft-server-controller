package io.github.peyoteheadlights.mcsc.core

import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import javax.net.ssl.X509TrustManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/** Why a request to the agent didn't give an answer. Each has a strings key. */
sealed class AgentException(val key: String, message: String? = null) : Exception(message ?: key) {
    /** No answer at all: the PC is off or asleep, the agent isn't running,
     * or this phone isn't on Tailscale (the dashboard's offline screen). */
    class Unreachable : AgentException("mobile.error.unreachable")

    /** The PC presented a different certificate from the one paired with. */
    class CertificateChanged(val presented: String?) : AgentException("mobile.error.certificate_changed")

    /** The PC's own certificate (the one paired with) has expired. */
    class CertificateExpired(val presented: String?) : AgentException("mobile.error.certificate_expired")

    /** A typed address whose certificate the phone doesn't trust. */
    class CertificateNotTrusted(val presented: String?) : AgentException("mobile.error.certificate_untrusted")

    /** Something answered, but not this app's agent. */
    class NotAnAgent : AgentException("mobile.error.not_agent")

    /** The sign-in ended (signed out on the PC, a helper removed, expired). */
    class SignedOut : AgentException("error.session_ended")

    /** Sign-in refused: the agent's own words ("Wrong username or password"). */
    class SignInRefused(val reason: String) : AgentException("mobile.error.sign_in", reason)

    /** The account isn't allowed to do that (403), in the agent's words. */
    class NotAllowed(val reason: String) : AgentException("mobile.error.not_allowed", reason)

    /** Any other refusal, in the agent's words, with its error number. */
    class Failed(val status: Int, val reason: String?, val requestId: String?) :
        AgentException("mobile.error.failed", reason)
}

/** Lines the client may log: method, path and status. Never headers, bodies
 * or the token; tests/NoSecretsTest checks that. */
fun interface AgentLog {
    fun line(text: String)
}

/**
 * Talks to one paired PC over HTTPS with the certificate check from
 * [PinnedTrust]. [token] is read for every request, from the phone's secure
 * storage; [onSignedOut] is called on a 401, so the app forgets the token
 * and locks itself out at once.
 */
class AgentClient(
    val pairing: Pairing,
    private val token: () -> String?,
    private val onSignedOut: () -> Unit = {},
    private val log: AgentLog = AgentLog { },
    strict: Boolean = false,
    baseClient: OkHttpClient = OkHttpClient(),
    systemTrust: X509TrustManager = PinnedTrust.systemTrustManager(),
) {
    val trust = PinnedTrust(pairing.fingerprint, strict, systemTrust)

    val http: OkHttpClient = trust.applyTo(baseClient.newBuilder())
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        // Stopping a server waits until Minecraft has saved and exited.
        .callTimeout(150, TimeUnit.SECONDS)
        .build()

    private val jsonType = "application/json".toMediaType()

    suspend fun health(): Health = get("/api/health", Health.serializer(), signedIn = false)

    suspend fun login(username: String, password: String, device: String): LoginResult {
        val body = buildJsonObject {
            put("username", username)
            put("password", password)
            put("device", device)
            put("label", device)
            // The app always keeps the sign-in, behind its own unlock.
            put("remember", true)
        }
        return call(post("/api/auth/login", body), LoginResult.serializer(), signedIn = false)
    }

    suspend fun logout() {
        runCatching { call(post("/api/auth/logout", JsonObject(emptyMap())), JsonObject.serializer()) }
    }

    suspend fun me(): Me = get("/api/auth/me", Me.serializer())

    suspend fun servers(): ServerList = get("/api/servers", ServerList.serializer())

    suspend fun status(serverId: String): ServerStatus =
        get("/api/servers/${path(serverId)}/status", ServerStatus.serializer())

    /** start, stop or restart. */
    suspend fun serverAction(serverId: String, action: String): ServerAction {
        require(action in QUICK_ACTIONS) { "Not an action the app offers: $action" }
        return call(
            post("/api/servers/${path(serverId)}/server/$action", JsonObject(emptyMap())),
            ServerAction.serializer(),
        )
    }

    suspend fun alerts(after: Long?, limit: Int = 50): AppAlerts {
        val query = buildString {
            append("?limit=").append(limit)
            if (after != null) append("&after=").append(after)
        }
        return get("/api/alerts$query", AppAlerts.serializer())
    }

    suspend fun phone(): AppPhone = get("/api/app/phone", AppPhone.serializer())

    suspend fun registerPhone(pushToken: String, platform: String, label: String): AppPhone {
        val body = buildJsonObject {
            put("token", pushToken)
            put("platform", platform)
            put("label", label)
        }
        return call(request("/api/app/phone").put(body.toBody()).build(), AppPhone.serializer())
    }

    suspend fun forgetPhone(): AppPhone =
        call(request("/api/app/phone").delete().build(), AppPhone.serializer())

    suspend fun version(): VersionInfo = get("/api/version", VersionInfo.serializer())

    // ------------------------------------------------------------------
    // One server's screens. Every route is the dashboard's own, with its
    // permissions; the agent refuses whatever the account may not do.

    /** The newest [lines] console lines (the agent keeps up to 500 here). */
    suspend fun consoleLog(serverId: String, lines: Int = 500): ConsoleLog =
        get("${server(serverId)}/logs?lines=${lines.coerceIn(1, 500)}", ConsoleLog.serializer())

    /** Empties the agent's console view; Minecraft's log files stay. */
    suspend fun clearConsole(serverId: String): Ok =
        call(post("${server(serverId)}/logs/clear", JsonObject(emptyMap())), Ok.serializer())

    /** Whether a command can be sent, and why it would need asking first. */
    suspend fun checkCommand(serverId: String, command: String): CommandCheck =
        get("${server(serverId)}/server/command/check?command=${path(command)}", CommandCheck.serializer())

    /** Writes one line to Minecraft's console (never a shell). [confirm]
     * only after the person said yes to the danger the check named. */
    suspend fun sendCommand(serverId: String, command: String, confirm: Boolean): CommandSent {
        val body = buildJsonObject {
            put("command", command)
            put("confirm", confirm)
        }
        return call(post("${server(serverId)}/server/command", body), CommandSent.serializer())
    }

    suspend fun chat(serverId: String, lines: Int = 200): ChatLog =
        get("${server(serverId)}/chat?lines=${lines.coerceIn(1, 400)}", ChatLog.serializer())

    /** Says [message] in the game as Server. It shows in the chat when the
     * console prints it back, so the app never adds it itself. */
    suspend fun sendChat(serverId: String, message: String): ChatSent =
        call(post("${server(serverId)}/chat", buildJsonObject { put("message", message) }), ChatSent.serializer())

    suspend fun players(serverId: String): PlayersPage = get("${server(serverId)}/players", PlayersPage.serializer())

    /** One of the player buttons. [confirm] is for kick and ban, after asking. */
    suspend fun playerAction(serverId: String, action: String, name: String, reason: String?, confirm: Boolean): PlayerActionResult {
        require(action in PlayerActions.ALL) { "Not a player action: $action" }
        val body = buildJsonObject {
            put("action", action)
            put("name", name)
            put("reason", reason?.takeIf { it.isNotBlank() })
            put("confirm", confirm)
        }
        return call(post("${server(serverId)}/players/actions", body), PlayerActionResult.serializer())
    }

    suspend fun playerActionStatus(serverId: String, actionId: String): PlayerActionStatus =
        get("${server(serverId)}/players/actions/${path(actionId)}", PlayerActionStatus.serializer())

    /** This server's events and the PC's own, newest first. */
    suspend fun events(serverId: String, limit: Int = 200): EventList =
        get("${server(serverId)}/events?limit=${limit.coerceIn(1, 500)}", EventList.serializer())

    suspend fun crashes(serverId: String, limit: Int = 50): CrashList =
        get("${server(serverId)}/crashes?limit=${limit.coerceIn(1, 200)}", CrashList.serializer())

    suspend fun crash(serverId: String, crashId: Long): Crash = get("${server(serverId)}/crashes/$crashId", Crash.serializer())

    suspend fun recommendations(serverId: String): Recommendations =
        get("${server(serverId)}/recommendations", Recommendations.serializer())

    /** snooze, dismiss or restore; the answer is the new list. */
    suspend fun recommendationAction(serverId: String, recId: String, action: String): Recommendations {
        require(action in REC_ACTIONS) { "Not a suggestion action: $action" }
        return call(
            post("${server(serverId)}/recommendations/${path(recId)}", buildJsonObject { put("action", action) }),
            Recommendations.serializer(),
        )
    }

    suspend fun gettingStarted(serverId: String): Checklist =
        get("${server(serverId)}/getting-started", Checklist.serializer())

    suspend fun hideGettingStarted(serverId: String): Checklist =
        call(post("${server(serverId)}/getting-started/dismiss", JsonObject(emptyMap())), Checklist.serializer())

    /** How friends join. Can take a few seconds: the PC asks Tailscale. */
    suspend fun join(serverId: String): JoinInfo = get("${server(serverId)}/join", JoinInfo.serializer())

    // ------------------------------------------------------------------
    private fun server(id: String) = "/api/servers/${path(id)}"

    private fun path(id: String) = java.net.URLEncoder.encode(id, "UTF-8").replace("+", "%20")

    private fun request(path: String): Request.Builder =
        Request.Builder().url(pairing.origin + path).header("Accept", "application/json")

    private fun JsonObject.toBody(): RequestBody = toString().toRequestBody(jsonType)

    private fun post(path: String, body: JsonObject): Request = request(path).post(body.toBody()).build()

    private suspend fun <T> get(path: String, serializer: KSerializer<T>, signedIn: Boolean = true): T =
        call(request(path).get().build(), serializer, signedIn)

    private suspend fun <T> call(request: Request, serializer: KSerializer<T>, signedIn: Boolean = true): T =
        withContext(Dispatchers.IO) {
            val withToken = if (signedIn) {
                val current = token() ?: throw AgentException.SignedOut()
                request.newBuilder().header("Authorization", "Bearer $current").build()
            } else {
                request
            }
            val response = try {
                http.newCall(withToken).execute()
            } catch (e: IOException) {
                log.line("${request.method} ${request.url.encodedPath} -> no answer")
                throw translate(e)
            }
            response.use { read(it, request, serializer, signedIn) }
        }

    private fun <T> read(response: Response, request: Request, serializer: KSerializer<T>, signedIn: Boolean): T {
        log.line("${request.method} ${request.url.encodedPath} -> ${response.code}")
        val text = response.body?.string().orEmpty()
        val isJson = response.header("Content-Type").orEmpty().contains("application/json")
        if (response.code == 401 && signedIn) {
            onSignedOut()
            throw AgentException.SignedOut()
        }
        if (!response.isSuccessful) {
            val reason = if (isJson) detail(text) else null
            when {
                response.code == 401 || response.code == 429 ->
                    throw AgentException.SignInRefused(reason ?: "")
                response.code == 403 -> throw AgentException.NotAllowed(reason ?: "")
                else -> throw AgentException.Failed(response.code, reason, response.header("X-Request-ID"))
            }
        }
        if (!isJson) throw AgentException.NotAnAgent()
        return try {
            AgentJson.decodeFromString(serializer, text)
        } catch (e: IllegalArgumentException) {
            throw AgentException.NotAnAgent()
        }
    }

    private fun detail(text: String): String? = runCatching {
        AgentJson.parseToJsonElement(text).let { it as? JsonObject }?.get("detail")?.jsonPrimitive?.contentOrNull
    }.getOrNull()

    internal fun translateFailure(e: IOException): AgentException = translate(e)

    private fun translate(e: IOException): AgentException {
        var cause: Throwable? = e
        while (cause != null) {
            when (cause) {
                is CertificateMismatchException -> return AgentException.CertificateChanged(cause.presented)
                is PinnedCertificateExpiredException -> return AgentException.CertificateExpired(cause.presented)
                is CertificateNotTrustedException -> return AgentException.CertificateNotTrusted(cause.presented)
            }
            cause = cause.cause
        }
        if (e is SSLException) return AgentException.NotAnAgent()
        return AgentException.Unreachable()
    }

    companion object {
        val QUICK_ACTIONS = listOf("start", "stop", "restart")
        val REC_ACTIONS = listOf("snooze", "dismiss", "restore")
    }
}
