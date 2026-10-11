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
import okhttp3.MultipartBody
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

    /** Work the agent answers only once done (a backup, a restore) gave no
     * answer in time. It may still be running on the PC; the screen reads
     * it again when the PC says it finished. */
    class StillWorking : AgentException("mobile.error.still_working")

    /** Any other refusal, in the agent's words, with its error number.
     * A form the agent refused also has each value's reason, by key. */
    class Failed(
        val status: Int,
        val reason: String?,
        val requestId: String?,
        val problems: Map<String, String> = emptyMap(),
    ) : AgentException("mobile.error.failed", reason)
}

/** Writing a download into the phone's own file failed (the phone is
 * full, or the place picked stopped taking it): not the PC's fault. */
class SaveFileException(cause: IOException) : IOException(cause.message, cause)

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
    /** How long work the agent answers only when done may take. */
    private val slowSeconds: Long = SLOW_SECONDS,
) {
    val trust = PinnedTrust(pairing.fingerprint, strict, systemTrust)

    val http: OkHttpClient = trust.applyTo(baseClient.newBuilder())
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        // Stopping a server waits until Minecraft has saved and exited.
        .callTimeout(150, TimeUnit.SECONDS)
        .build()

    /** For work the agent answers only when it is done (a backup, a
     * restore): it sends nothing until then, so after [slowSeconds] with no
     * answer the app says the PC may still be working ([AgentException.StillWorking]). */
    private val slowHttp: OkHttpClient = http.newBuilder()
        .readTimeout(slowSeconds, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.SECONDS)
        .build()

    private val files: OkHttpClient = http.newBuilder()
        .readTimeout(2, TimeUnit.MINUTES)
        .callTimeout(0, TimeUnit.SECONDS)
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
    // Backups, Restore world, Schedules and Performance. Making a backup,
    // a restore and Run now answer only once the work is done, which can
    // take minutes for a big world, so those wait as long as it takes.

    suspend fun backups(serverId: String): BackupList = get("${server(serverId)}/backups", BackupList.serializer())

    suspend fun backUp(serverId: String): BackupMade =
        call(post("${server(serverId)}/backups", JsonObject(emptyMap())), BackupMade.serializer(), slow = true)

    /** Opens the archive on the PC and checks it, now. */
    suspend fun checkBackup(serverId: String, backupId: Long): BackupCheck =
        get("${server(serverId)}/backups/$backupId/verify", BackupCheck.serializer(), slow = true)

    /** Without [confirm], only what would happen; nothing changes. */
    suspend fun restoreBackup(serverId: String, backupId: Long, confirm: Boolean, startAfter: Boolean = false): Restored =
        call(
            post("${server(serverId)}/backups/$backupId/restore", Backups.restoreBody(confirm, startAfter)),
            Restored.serializer(),
            slow = confirm,
        )

    suspend fun deleteBackup(serverId: String, backupId: Long): BackupDeleted =
        call(request("${server(serverId)}/backups/$backupId").delete().build(), BackupDeleted.serializer())

    /** Copies one backup to the second-copy folder (again). */
    suspend fun copyBackup(serverId: String, backupId: Long): BackupCopied =
        call(post("${server(serverId)}/backups/$backupId/copy", JsonObject(emptyMap())), BackupCopied.serializer(), slow = true)

    suspend fun offsite(serverId: String): Offsite = get("${server(serverId)}/backups/offsite", Offsite.serializer())

    /** Turns second copies off. Choosing a folder needs the PC's folder list. */
    suspend fun turnOffsiteOff(serverId: String): Offsite = call(
        request("${server(serverId)}/backups/offsite").put(buildJsonObject { put("directory", "") }.toBody()).build(),
        Offsite.serializer(),
    )

    /**
     * Streams a backup's zip into [out], with the sign-in in a header (never
     * in the address), and returns the bytes written. [progress] gets the
     * bytes so far and the size, when the PC said it. A failure writing to
     * [out] is a [SaveFileException], not the PC's.
     */
    suspend fun downloadBackup(
        serverId: String,
        backupId: Long,
        out: java.io.OutputStream,
        progress: (Long, Long?) -> Unit = { _, _ -> },
    ): Long = withContext(Dispatchers.IO) {
        val path = "${server(serverId)}/backups/$backupId/download"
        val current = token() ?: throw AgentException.SignedOut()
        val request = Request.Builder().url(pairing.origin + path).header("Authorization", "Bearer $current").get().build()
        val response = try {
            files.newCall(request).execute()
        } catch (e: IOException) {
            log.line("GET ${request.url.encodedPath} -> no answer")
            throw translate(e)
        }
        response.use {
            log.line("GET ${request.url.encodedPath} -> ${it.code}")
            if (!it.isSuccessful || !it.header("Content-Type").orEmpty().startsWith("application/zip")) {
                read(it, request, JsonObject.serializer(), signedIn = true)
                throw AgentException.NotAnAgent()
            }
            val body = it.body ?: throw AgentException.NotAnAgent()
            val size = body.contentLength().takeIf { n -> n >= 0 }
            var written = 0L
            body.byteStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = try {
                        input.read(buffer)
                    } catch (e: IOException) {
                        throw translate(e)
                    }
                    if (n < 0) break
                    try {
                        out.write(buffer, 0, n)
                    } catch (e: IOException) {
                        throw SaveFileException(e)
                    }
                    written += n
                    progress(written, size)
                }
            }
            if (size != null && written != size) throw AgentException.Unreachable()
            written
        }
    }

    suspend fun worlds(serverId: String): WorldList = get("${server(serverId)}/worlds", WorldList.serializer())

    /** Asks Minecraft to save the world now (save-all flush). */
    suspend fun saveWorld(serverId: String): Requested =
        call(post("${server(serverId)}/worlds/save", JsonObject(emptyMap())), Requested.serializer())

    suspend fun worldTimeline(serverId: String): WorldTimeline =
        get("${server(serverId)}/world/timeline", WorldTimeline.serializer())

    /** Puts back only the world from that backup; the server must be off. */
    suspend fun restoreWorld(serverId: String, backupId: Long): Restored {
        val body = buildJsonObject {
            put("backup_id", backupId)
            put("confirm", true)
        }
        return call(post("${server(serverId)}/world/undo", body), Restored.serializer(), slow = true)
    }

    /** This server's recent tasks, newest first. */
    suspend fun jobs(serverId: String, limit: Int = 20): JobList =
        get("/api/jobs?server_id=${path(serverId)}&limit=${limit.coerceIn(1, 200)}", JobList.serializer())

    /** Undoes a finished change by restoring the backup made just before it. */
    suspend fun undoJob(jobId: String): JobUndone =
        call(post("/api/jobs/${path(jobId)}/undo", JsonObject(emptyMap())), JobUndone.serializer(), slow = true)

    suspend fun schedules(serverId: String): ScheduleList = get("${server(serverId)}/schedules", ScheduleList.serializer())

    suspend fun addSchedule(serverId: String, body: JsonObject): ScheduleSaved =
        call(post("${server(serverId)}/schedules", body), ScheduleSaved.serializer())

    suspend fun updateSchedule(serverId: String, scheduleId: Long, body: JsonObject): ScheduleSaved =
        call(request("${server(serverId)}/schedules/$scheduleId").put(body.toBody()).build(), ScheduleSaved.serializer())

    suspend fun deleteSchedule(serverId: String, scheduleId: Long): Ok =
        call(request("${server(serverId)}/schedules/$scheduleId").delete().build(), Ok.serializer())

    suspend fun runSchedule(serverId: String, scheduleId: Long): ScheduleRan =
        call(post("${server(serverId)}/schedules/$scheduleId/run", JsonObject(emptyMap())), ScheduleRan.serializer(), slow = true)

    /** The graphs' samples for the last [hours] (1 to 168), the values now
     * and, with [storage], the disk use (slow: the PC walks the server folder). */
    suspend fun performance(serverId: String, hours: Int, storage: Boolean = true): Performance =
        get("${server(serverId)}/performance?hours=${hours.coerceIn(1, 168)}&storage=$storage", Performance.serializer())

    /** The health checks. Can take a few seconds: the PC asks Tailscale. */
    suspend fun serverHealth(serverId: String): ServerHealth =
        get("${server(serverId)}/health/server", ServerHealth.serializer())

    // ------------------------------------------------------------------
    // Mods / Plugins / Packs and Game settings. Mods change only while the
    // server is stopped; the agent refuses otherwise, in its own words.
    // Installs, updates and imports answer once done, so they wait.

    suspend fun mods(serverId: String): ModList = get("${server(serverId)}/mods", ModList.serializer())

    /** Turns a mod or plugin on or off without removing it. */
    suspend fun setModEnabled(serverId: String, filename: String, enabled: Boolean): ModChanged =
        call(post("${server(serverId)}/mods/${if (enabled) "enable" else "disable"}", fileBody(filename)), ModChanged.serializer())

    /** What else needs a mod, asked before removing it. */
    suspend fun modImpact(serverId: String, filename: String): ModImpact =
        get("${server(serverId)}/mods/impact?filename=${path(filename)}", ModImpact.serializer())

    /** Removes a mod; its file is kept so it can be put back. */
    suspend fun removeMod(serverId: String, filename: String): ModRemoved =
        call(post("${server(serverId)}/mods/remove", fileBody(filename)), ModRemoved.serializer())

    suspend fun updateMod(serverId: String, filename: String, versionId: String?): ModUpdated {
        val body = buildJsonObject {
            put("filename", filename)
            put("version_id", versionId)
        }
        return call(post("${server(serverId)}/mods/update", body), ModUpdated.serializer(), slow = true)
    }

    /** The copies of a mod kept on this server, newest first. */
    suspend fun modVersions(serverId: String, modId: String): ModVersions =
        get("${server(serverId)}/mods/versions/${path(modId)}", ModVersions.serializer())

    suspend fun rollBackMod(serverId: String, modId: String, archivePath: String): ModRolledBack {
        val body = buildJsonObject {
            put("mod_id", modId)
            put("archive_path", archivePath)
        }
        return call(post("${server(serverId)}/mods/rollback", body), ModRolledBack.serializer())
    }

    suspend fun modHistory(serverId: String, limit: Int = 100): ModHistory =
        get("${server(serverId)}/mods/history?limit=${limit.coerceIn(1, 500)}", ModHistory.serializer())

    /** What Update all would change, checked on Modrinth now. */
    suspend fun updateAllPlan(serverId: String): UpdateAllPlan =
        get("${server(serverId)}/mods/update-all", UpdateAllPlan.serializer())

    /** Updates the ticked ones as one change (one backup, all or nothing). */
    suspend fun updateAll(serverId: String, body: JsonObject): UpdateAllResult =
        call(post("${server(serverId)}/mods/update-all", body), UpdateAllResult.serializer(), slow = true)

    /** Modrinth results that fit this server's type and Minecraft version. */
    suspend fun searchMods(serverId: String, query: String, offset: Int = 0): ModSearch =
        get("${server(serverId)}/mods/search?q=${path(query)}&limit=$SEARCH_PAGE&offset=${offset.coerceAtLeast(0)}", ModSearch.serializer())

    suspend fun modProject(serverId: String, slug: String): ModProject =
        get("${server(serverId)}/mods/project/${path(slug)}", ModProject.serializer())

    suspend fun installMod(serverId: String, slug: String, versionId: String?, withDependencies: Boolean): ModInstalled {
        val body = buildJsonObject {
            put("project", slug)
            put("version_id", versionId)
            put("install_dependencies", withDependencies)
        }
        return call(post("${server(serverId)}/mods/install", body), ModInstalled.serializer(), slow = true)
    }

    suspend fun dependencies(serverId: String): DependencyReport =
        get("${server(serverId)}/mods/dependencies", DependencyReport.serializer())

    /** What installing the missing ones would download. Nothing is yet. */
    suspend fun planDependencies(serverId: String): DependencyPlan =
        call(post("${server(serverId)}/mods/dependencies/plan", JsonObject(emptyMap())), DependencyPlan.serializer())

    suspend fun installDependencies(serverId: String): DependencyInstall =
        call(post("${server(serverId)}/mods/dependencies/install", JsonObject(emptyMap())), DependencyInstall.serializer(), slow = true)

    /** Adds a mod or plugin file (.jar) picked on the phone. */
    suspend fun uploadMod(serverId: String, file: PickedFile): ModUploaded =
        call(upload("${server(serverId)}/mods/upload", file), ModUploaded.serializer(), slow = true)

    /** Reads a modpack (.mrpack) and says what importing it here would do. */
    suspend fun inspectModpack(serverId: String, file: PickedFile): ModpackInspected =
        call(upload("/api/modpacks/inspect?server_id=${path(serverId)}", file), ModpackInspected.serializer(), slow = true)

    /** Throws away a modpack read but not imported. */
    suspend fun forgetModpack(token: String): Ok =
        call(request("/api/modpacks/${path(token)}").delete().build(), Ok.serializer())

    suspend fun importModpack(serverId: String, token: String): ModpackImported {
        val body = buildJsonObject {
            put("token", token)
            put("confirm", true)
        }
        return call(post("${server(serverId)}/modpack", body), ModpackImported.serializer(), slow = true)
    }

    /** A Bedrock server's behavior and resource packs. */
    suspend fun addons(serverId: String): AddonList = get("${server(serverId)}/addons", AddonList.serializer())

    suspend fun uploadAddon(serverId: String, file: PickedFile): AddonResult =
        call(upload("${server(serverId)}/addons/upload", file), AddonResult.serializer(), slow = true)

    suspend fun setAddonEnabled(serverId: String, uuid: String, enabled: Boolean): AddonResult = call(
        request("${server(serverId)}/addons/${path(uuid)}").put(buildJsonObject { put("enabled", enabled) }.toBody()).build(),
        AddonResult.serializer(),
    )

    suspend fun removeAddon(serverId: String, uuid: String): AddonResult =
        call(request("${server(serverId)}/addons/${path(uuid)}").delete().build(), AddonResult.serializer())

    suspend fun gameSettings(serverId: String): GameSettings =
        get("${server(serverId)}/game-settings", GameSettings.serializer())

    /** Saves only [values], the ones changed. A refused one comes back as
     * [AgentException.Failed] with each value's reason in its problems. */
    suspend fun saveGameSettings(serverId: String, values: JsonObject): GameSettingsSaved = call(
        request("${server(serverId)}/game-settings").put(buildJsonObject { put("values", values) }.toBody()).build(),
        GameSettingsSaved.serializer(),
    )

    // ------------------------------------------------------------------
    private fun server(id: String) = "/api/servers/${path(id)}"

    private fun path(id: String) = java.net.URLEncoder.encode(id, "UTF-8").replace("+", "%20")

    private fun request(path: String): Request.Builder =
        Request.Builder().url(pairing.origin + path).header("Accept", "application/json")

    private fun JsonObject.toBody(): RequestBody = toString().toRequestBody(jsonType)

    private fun post(path: String, body: JsonObject): Request = request(path).post(body.toBody()).build()

    private fun fileBody(filename: String) = buildJsonObject { put("filename", filename) }

    /** A file picked on the phone, sent as the dashboard's upload form does. */
    private fun upload(path: String, file: PickedFile): Request {
        val form = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", file.name, file.body())
            .build()
        return request(path).post(form).build()
    }

    private suspend fun <T> get(path: String, serializer: KSerializer<T>, signedIn: Boolean = true, slow: Boolean = false): T =
        call(request(path).get().build(), serializer, signedIn, slow)

    private suspend fun <T> call(request: Request, serializer: KSerializer<T>, signedIn: Boolean = true, slow: Boolean = false): T =
        withContext(Dispatchers.IO) {
            val withToken = if (signedIn) {
                val current = token() ?: throw AgentException.SignedOut()
                request.newBuilder().header("Authorization", "Bearer $current").build()
            } else {
                request
            }
            val started = System.nanoTime()
            val response = try {
                (if (slow) slowHttp else http).newCall(withToken).execute()
            } catch (e: IOException) {
                log.line("${request.method} ${request.url.encodedPath} -> no answer")
                // Only the wait for the answer runs this long; a PC that is
                // off fails to connect within seconds.
                val waited = System.nanoTime() - started
                if (slow && e is java.net.SocketTimeoutException && waited >= TimeUnit.SECONDS.toNanos(slowSeconds) * 9 / 10) {
                    throw AgentException.StillWorking()
                }
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
                else -> throw AgentException.Failed(
                    response.code,
                    reason,
                    response.header("X-Request-ID"),
                    if (isJson) problems(text) else emptyMap(),
                )
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

    private fun problems(text: String): Map<String, String> = runCatching {
        val found = (AgentJson.parseToJsonElement(text) as JsonObject)["problems"] as? JsonObject
        found?.mapNotNull { (key, value) -> (value as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull?.let { key to it } }?.toMap()
    }.getOrNull().orEmpty()

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

        const val SLOW_SECONDS = 30L * 60
        const val SEARCH_PAGE = 20
        val REC_ACTIONS = listOf("snooze", "dismiss", "restore")
    }
}
