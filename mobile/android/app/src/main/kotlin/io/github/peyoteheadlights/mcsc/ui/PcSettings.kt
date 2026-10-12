package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.AlertSettings
import io.github.peyoteheadlights.mcsc.core.Device
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.ExportSizes
import io.github.peyoteheadlights.mcsc.core.HelpFiles
import io.github.peyoteheadlights.mcsc.core.OldCopy
import io.github.peyoteheadlights.mcsc.core.PcSettings
import io.github.peyoteheadlights.mcsc.core.PcUpdate
import io.github.peyoteheadlights.mcsc.core.PowerStatus
import io.github.peyoteheadlights.mcsc.core.PcSettingsView
import io.github.peyoteheadlights.mcsc.core.StartupReport
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.UpdateStatus
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Settings > PC settings, owner only (the dashboard's App settings): alerts,
 * signed-in devices, the app update, Export everything, Get help, keeping
 * the PC awake, start with Windows and maintenance mode.
 */
class PcPages(
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    var view: Read<PcSettingsView> by mutableStateOf(Read())
        private set
    var power: PowerStatus? by mutableStateOf(null)
        private set
    var update: UpdateStatus? by mutableStateOf(null)
        private set
    var oldCopy: OldCopy? by mutableStateOf(null)
        private set
    var sizes: ExportSizes? by mutableStateOf(null)
        private set
    var devices: Read<List<Device>> by mutableStateOf(Read())
        private set
    var startup: Read<StartupReport> by mutableStateOf(Read())
        private set
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    /** The checks before updating, while the confirmation is open. */
    var checks: UpdateStatus? by mutableStateOf(null)
        private set
    /** The version asked for, while the PC updates itself and this phone waits. */
    var updating: String? by mutableStateOf(null)
        private set
    var updateLost by mutableStateOf(false)
        private set

    var exporting: PcSettings.Exporting? by mutableStateOf(null)
        private set
    /** What a help file would hold, while its confirmation is open. */
    var helpFiles: HelpFiles? by mutableStateOf(null)
        private set

    fun load() {
        val c = client() ?: return
        view = view.copy(loading = true)
        scope.launch {
            view = try {
                Read(c.pcSettings())
            } catch (e: AgentException) {
                noted(e)
                Read(view.value, problem = Message.of(e))
            }
            // The rest is shown when the PC answers; a part it can't read is left out.
            power = runCatching { c.power() }.getOrNull()
            if (updating == null) update = runCatching { c.updates() }.getOrNull()
            oldCopy = runCatching { c.oldCopy().oldCopy }.getOrNull()
            sizes = runCatching { c.exportSizes() }.getOrNull()
        }
    }

    /** Only the update, for the "Version … is out" on the Settings tab. */
    fun loadUpdate() {
        val c = client() ?: return
        if (updating != null) return
        scope.launch { runCatching { c.updates() }.getOrNull()?.let { update = it } }
    }

    fun clearSaid() {
        said = null
    }

    private fun run(what: String, strings: Strings, work: suspend (AgentClient) -> Said?) {
        val c = client() ?: return
        if (busy != null) return
        busy = what
        said = null
        scope.launch {
            said = try {
                work(c)
            } catch (e: AgentException) {
                noted(e)
                Said(Message.of(e).text(strings), good = false)
            }
            busy = null
        }
    }

    // ------------------------------------------------------------ settings
    fun saveAlerts(before: AlertSettings, after: AlertSettings, strings: Strings) = run("alerts", strings) { c ->
        val changes = PcSettings.changes(before, after)
        if (changes.isEmpty()) return@run Said(strings.t("settings.nothing_changed"), good = true)
        val (text, good) = PcSettings.saved(strings, c.savePcSettings(changes))
        view = Read(c.pcSettings())
        Said(text, good)
    }

    private fun saveOne(what: String, key: String, on: Boolean, strings: Strings, done: String) = run(what, strings) { c ->
        val result = c.savePcSettings(kotlinx.serialization.json.buildJsonObject { put(key, kotlinx.serialization.json.JsonPrimitive(on)) })
        view = Read(c.pcSettings())
        if (key == "power.keep_awake") power = runCatching { c.power() }.getOrNull()
        val (text, good) = PcSettings.saved(strings, result)
        Said(if (good) done else text, good)
    }

    fun keepAwake(on: Boolean, strings: Strings) =
        saveOne("awake", "power.keep_awake", on, strings, strings.t(if (on) "awake.turned_on" else "awake.turned_off"))

    fun dailyCheck(on: Boolean, strings: Strings) =
        saveOne("daily", "updates.check", on, strings, strings.t("settings.saved"))

    fun maintenance(on: Boolean, strings: Strings) = run("maintenance", strings) { c ->
        val set = c.maintenance(on)
        view = Read(c.pcSettings())
        Said(strings.t(if (set.maintenance) "appset.maintenance_on" else "appset.maintenance_off"), good = true)
    }

    fun testAlert(channel: String, strings: Strings) = run("test:$channel", strings) { c ->
        val sent = c.testAlert(channel).sent
        Said(strings.t(if (sent) "appset.test_sent" else "appset.test_failed"), good = sent)
    }

    fun checkStartup() {
        val c = client() ?: return
        startup = startup.copy(loading = true, problem = null)
        scope.launch {
            startup = try {
                Read(c.startupCheck())
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    // ------------------------------------------------------------ signed-in devices
    fun loadDevices() {
        val c = client() ?: return
        devices = devices.copy(loading = true)
        scope.launch {
            devices = try {
                Read(c.devices().sessions)
            } catch (e: AgentException) {
                noted(e)
                Read(devices.value, problem = Message.of(e))
            }
        }
    }

    fun signOut(device: Device, strings: Strings) = run(device.id, strings) { c ->
        c.signOutDevice(device.id)
        devices = Read(c.devices().sessions)
        Said(strings.t("mobile.account.signed_out_device", "device" to (device.label ?: strings.t("security.device_unknown"))), good = true)
    }

    /** Signs everyone out, this phone too: [onDone] takes it to the sign-in screen. */
    fun signEveryoneOut(strings: Strings, onDone: () -> Unit) = run("everyone", strings) { c ->
        c.signEveryoneOut()
        onDone()
        null
    }

    // ------------------------------------------------------------ the app update
    fun checkForUpdate(strings: Strings) = run("check", strings) { c ->
        val now = c.checkForUpdate()
        update = now
        when {
            now.error != null -> Said(strings.t("update.check_failed", "reason" to now.error), good = false)
            now.available -> Said(strings.t("update.available", "version" to now.latest?.version.orEmpty()), good = true)
            else -> Said(strings.t("update.up_to_date", "version" to now.current), good = true)
        }
    }

    /** Reads who is playing, then the confirmation opens. */
    fun askToUpdate(strings: Strings) = run("checks", strings) { c ->
        checks = c.updateChecks()
        null
    }

    fun cancelUpdate() {
        checks = null
    }

    /** Starts the update, then waits for the PC to come back by itself. */
    fun install(strings: Strings) {
        val c = client() ?: return
        val before = checks ?: update ?: return
        val target = before.latest?.version ?: return
        checks = null
        busy = "update"
        said = null
        updateLost = false
        scope.launch {
            try {
                c.installUpdate()
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
                busy = null
                return@launch
            }
            updating = target
            val started = System.currentTimeMillis()
            while (true) {
                delay(5_000)
                // While it restarts the PC doesn't answer: that is expected, not a problem to show.
                val now = try {
                    c.updates()
                } catch (e: AgentException) {
                    null
                }
                if (now != null && PcUpdate.back(before, now, target)) {
                    update = now
                    oldCopy = runCatching { c.oldCopy().oldCopy }.getOrNull()
                    PcUpdate.lastResult(strings, now.lastResult)?.let { said = Said(it, good = now.lastResult?.ok == true) }
                    break
                }
                if (System.currentTimeMillis() - started > PcUpdate.WAIT_SECONDS * 1000L) {
                    updateLost = true
                    break
                }
            }
            updating = null
            busy = null
        }
    }

    fun removeOldCopy(strings: Strings) = run("oldcopy", strings) { c ->
        val result = c.removeOldCopy()
        oldCopy = runCatching { c.oldCopy().oldCopy }.getOrNull()
        Said(PcUpdate.oldCopyRemoved(strings, result), good = true)
    }

    // ------------------------------------------------------------ export and get help
    fun export(worlds: Boolean, backups: Boolean, secrets: Boolean, passphrase: String, folder: String, strings: Strings) =
        run("export", strings) { c ->
            exporting = PcSettings.Exporting.Running(null, null)
            try {
                val started = c.startExport(PcSettings.exportBody(worlds, backups, secrets, passphrase, folder))
                var state = PcSettings.exporting(c.exportJob(started.jobId))
                exporting = state
                while (state is PcSettings.Exporting.Running) {
                    delay(1_000)
                    state = PcSettings.exporting(c.exportJob(started.jobId))
                    exporting = state
                }
                Said(PcSettings.exportSaid(strings, state).orEmpty(), good = state is PcSettings.Exporting.Saved)
            } finally {
                exporting = null
            }
        }

    fun askForHelpFile(strings: Strings) = run("help", strings) { c ->
        helpFiles = c.helpFiles()
        null
    }

    fun cancelHelpFile() {
        helpFiles = null
    }

    /** Makes the help file, brings it to this phone and opens the share menu. */
    fun makeHelpFile(folder: File, strings: Strings, share: (File) -> Unit) = run("help", strings) { c ->
        helpFiles = null
        val made = c.makeHelpFile()
        val file = withContext(Dispatchers.IO) {
            folder.mkdirs()
            folder.listFiles()?.forEach { it.delete() }
            File(folder, made.filename.substringAfterLast('/').substringAfterLast('\\').ifBlank { "help.zip" })
        }
        try {
            withContext(Dispatchers.IO) { file.outputStream().use { c.downloadHelpFile(made, it) } }
        } catch (e: Exception) {
            file.delete()
            throw e
        }
        share(file)
        Said(strings.t("mobile.pc.help_made"), good = true)
    }
}

// ------------------------------------------------------------ screens

/** Settings > PC settings (owner only). */
@Composable
fun PcSettingsScreen(vm: AppViewModel, onBack: () -> Unit, onDevices: () -> Unit, onAlerts: () -> Unit) {
    val pages = vm.pcSettings
    val colors = LocalColors.current
    val strings = vm.strings
    val context = LocalContext.current
    var asking by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        pages.clearSaid()
        pages.load()
    }
    val view = pages.view.value

    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.pc.title"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            pages.view.problem?.let { item { ProblemNote(it, onRetry = pages::load) } }
            item { SaidNote(pages.said) }
            item {
                Card {
                    Item(t("mobile.pc.devices"), subtitle = t("mobile.pc.devices_hint"), onClick = onDevices)
                    Item(t("appset.alerts"), onClick = onAlerts)
                }
            }

            // The app update.
            pages.update?.let { status -> item { UpdateCard(vm, status, onAsk = { pages.askToUpdate(strings) }, onPage = { openLink(context, it) }) } }
            pages.oldCopy?.takeIf { it.offer }?.let { old ->
                item { SectionTitle(t("oldcopy.title")) }
                item {
                    Card {
                        Note(t("oldcopy.body", "path" to old.path))
                        Note(t("oldcopy.keeps"), color = colors.text3)
                        if (old.problems.isNotEmpty()) {
                            Note(t("oldcopy.cant") + "\n" + old.problems.joinToString("\n"), color = colors.danger)
                        } else {
                            TextButton(onClick = { asking = "oldcopy" }, enabled = pages.busy == null, modifier = Modifier.padding(start = 6.dp)) {
                                Text(t(if (pages.busy == "oldcopy") "oldcopy.removing" else "oldcopy.remove"), color = colors.danger)
                            }
                        }
                    }
                }
            }

            if (view != null) {
                val awake = PcSettings.keepAwake(view)
                item { SectionTitle(t("awake.title")) }
                item {
                    Card {
                        Item(
                            t("awake.label"),
                            subtitle = pages.power?.let { PcSettings.awake(strings, it) },
                            trailing = { Switch(checked = awake, enabled = pages.busy == null, onCheckedChange = { pages.keepAwake(it, strings) }) },
                        )
                        pages.power?.problem?.let { Note(it, color = colors.danger) }
                        pages.power?.let { power ->
                            val notes = PcSettings.stillSleeps(strings, power)
                            if (notes.isNotEmpty()) Note(t("awake.still_title") + "\n" + notes.joinToString("\n"), color = colors.warning)
                            val battery = power.battery
                            if (vm.technical && battery?.present == true) {
                                Note(
                                    t(
                                        "awake.battery",
                                        "percent" to (battery.percent?.toString() ?: t("value.unknown")),
                                        "source" to t(if (battery.pluggedIn == true) "awake.plugged_in" else "awake.on_battery"),
                                    ),
                                    color = colors.text3,
                                )
                            }
                        }
                    }
                }
                item { SectionTitle(t("appset.maintenance")) }
                item {
                    Card {
                        Item(
                            t("appset.maintenance_label"),
                            trailing = {
                                Switch(
                                    checked = PcSettings.maintenance(view),
                                    enabled = pages.busy == null,
                                    onCheckedChange = { pages.maintenance(it, strings) },
                                )
                            },
                        )
                    }
                }
            }

            item { SectionTitle(t("export.title")) }
            item { ExportCard(vm, pages) }

            item { SectionTitle(t("gethelp.title")) }
            item {
                Card {
                    Note(t("gethelp.lead"))
                    TextButton(onClick = { pages.askForHelpFile(strings) }, enabled = pages.busy == null, modifier = Modifier.padding(start = 6.dp)) {
                        Text(t(if (pages.busy == "help") "gethelp.listing" else "mobile.pc.help_share"))
                    }
                }
            }

            item { SectionTitle(t("appset.startup")) }
            item { StartupCard(vm, pages) }
        }
    }

    pages.checks?.let { check ->
        Confirm(
            title = t("update.confirm_title", "version" to check.latest?.version.orEmpty()),
            body = PcUpdate.confirmBody(strings, check),
            confirm = PcUpdate.confirmLabel(strings, check),
            danger = (check.playersOnline ?: 0) > 0,
            onConfirm = { pages.install(strings) },
            onDismiss = pages::cancelUpdate,
        )
    }
    pages.helpFiles?.let { files ->
        Confirm(
            title = t("gethelp.confirm_title"),
            body = t("gethelp.confirm_body") + "\n" +
                files.files.joinToString("\n") { f -> f.name + " " + (f.size?.let { Display.bytes(strings, it) } ?: strings.t("gethelp.made_now")) } +
                "\n\n" + t("gethelp.never"),
            confirm = t("mobile.pc.help_share"),
            danger = false,
            onConfirm = {
                pages.makeHelpFile(sharedFolder(context), strings) { shareFile(context, it, strings.t("mobile.pc.help_share")) }
            },
            onDismiss = pages::cancelHelpFile,
        )
    }
    if (asking == "oldcopy") {
        Confirm(
            title = t("oldcopy.confirm_title"),
            body = t("oldcopy.confirm_body", "path" to pages.oldCopy?.path.orEmpty()),
            confirm = t("oldcopy.remove"),
            danger = true,
            onConfirm = {
                asking = null
                pages.removeOldCopy(strings)
            },
            onDismiss = { asking = null },
        )
    }
    // While the PC updates itself nothing else can be done with it.
    if (pages.updating != null) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text(t("mobile.pc.updating")) },
            text = {
                Column(verticalArrangement = Gap) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    Text(t("mobile.pc.updating_hint"))
                }
            },
            confirmButton = {},
            containerColor = colors.float,
            titleContentColor = colors.text,
            textContentColor = colors.text2,
        )
    }
}

@Composable
private fun UpdateCard(vm: AppViewModel, status: UpdateStatus, onAsk: () -> Unit, onPage: (String) -> Unit) {
    val pages = vm.pcSettings
    val colors = LocalColors.current
    val strings = vm.strings
    val now = rememberNow()
    val shows = PcUpdate.shows(status, pages.updating)
    SectionTitle(t("update.title"))
    Card {
        val lead = when (shows) {
            PcUpdate.Shows.READY, PcUpdate.Shows.CANT_INSTALL -> t("update.available", "version" to status.latest?.version.orEmpty())
            PcUpdate.Shows.UPDATING -> t("mobile.pc.updating")
            else -> if (status.checkedAt != null) t("update.up_to_date", "version" to status.current) else t("update.current", "version" to status.current)
        }
        Item(lead, subtitle = status.checkedAt?.let { t("update.checked", "when" to Display.ago(strings, it, now)) })
        if (shows == PcUpdate.Shows.READY || shows == PcUpdate.Shows.CANT_INSTALL) {
            val notes = PcUpdate.notes(status.latest)
            if (notes.isNotEmpty()) Note(t("update.whats_new") + "\n" + notes.joinToString("\n") { "• $it" })
            status.cannotInstallReason?.let { Note(it, color = colors.text3) }
            status.latest?.page?.let { page -> Item(t("update.release_page"), external = true, onClick = { onPage(page) }) }
        }
        status.error?.let { Note(t("update.check_failed", "reason" to it), color = colors.danger) }
        PcUpdate.lastResult(strings, status.lastResult)?.let { Note(it, color = if (status.lastResult?.ok == true) colors.text3 else colors.danger) }
        if (pages.updateLost) Note(t("mobile.pc.update_lost"), color = colors.danger)
        pages.view.value?.let { view ->
            Item(
                t("mobile.pc.daily_check"),
                trailing = { Switch(checked = PcSettings.dailyCheck(view), enabled = pages.busy == null, onCheckedChange = { pages.dailyCheck(it, strings) }) },
            )
        }
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Gap) {
            if (shows == PcUpdate.Shows.READY) {
                Button(onClick = onAsk, enabled = pages.busy == null) { Text(t(if (pages.busy == "checks") "update.installing" else "update.install")) }
            }
            OutlinedButton(onClick = { pages.checkForUpdate(strings) }, enabled = pages.busy == null) {
                Text(t(if (pages.busy == "check") "update.checking" else "update.check_now"))
            }
        }
    }
}

@Composable
private fun ExportCard(vm: AppViewModel, pages: PcPages) {
    val colors = LocalColors.current
    val strings = vm.strings
    var worlds by rememberSaveable { mutableStateOf(true) }
    var backups by rememberSaveable { mutableStateOf(false) }
    var secrets by rememberSaveable { mutableStateOf(false) }
    var passphrase by remember { mutableStateOf("") }
    var folder by rememberSaveable { mutableStateOf<String?>(null) }
    var picking by remember { mutableStateOf(false) }
    val totals = pages.sizes?.let { PcSettings.totals(it) }
    fun size(n: Long?) = if (totals == null) strings.t("value.unknown") else Display.bytes(strings, n)

    Card {
        Note(t("export.lead"))
        Note(t("mobile.pc.export_hint"), color = colors.text3)
        Tick(t("export.always", "size" to size(totals?.files)), checked = true, enabled = false) {}
        Tick(t("export.worlds", "size" to size(totals?.worlds)), checked = worlds) { worlds = it }
        Tick(t("export.backups", "size" to size(totals?.backups)), checked = backups) { backups = it }
        Tick(t("export.secrets"), checked = secrets) { secrets = it }
        if (secrets) {
            Column(Modifier.padding(horizontal = 16.dp)) {
                PasswordField(passphrase, { passphrase = it }, t("export.passphrase"), hint = t("export.passphrase_hint"))
            }
        }
        Item(t("mobile.pc.export_folder"), subtitle = folder ?: t("mobile.pc.export_pick"), onClick = { picking = true })
        when (val state = pages.exporting) {
            is PcSettings.Exporting.Running -> {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Gap) {
                    Text(state.step ?: t("export.working"), color = colors.text2)
                    val progress = state.progress
                    if (progress != null) {
                        LinearProgressIndicator(progress = { progress.toFloat() }, modifier = Modifier.fillMaxWidth())
                    } else {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    }
                }
            }
            else -> Button(
                onClick = {
                    val chosen = folder ?: return@Button
                    pages.export(worlds, backups, secrets, passphrase, chosen, strings)
                    passphrase = ""
                },
                enabled = pages.busy == null && PcSettings.canExport(folder, secrets, passphrase),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            ) { Text(t("export.button")) }
        }
        Note(t("export.other_side"), color = colors.text3)
    }
    if (picking) {
        FolderPickerDialog(
            vm,
            title = t("mobile.pc.export_pick"),
            start = folder,
            onPick = {
                folder = it
                picking = false
            },
            onDismiss = { picking = false },
        )
    }
}

@Composable
private fun Tick(text: String, checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .toggleable(value = checked, enabled = enabled, role = Role.Checkbox, onValueChange = onChange)
            .padding(horizontal = 16.dp),
    ) {
        Checkbox(checked = checked, onCheckedChange = null, enabled = enabled)
        Text(text, color = LocalColors.current.text, modifier = Modifier.padding(start = 12.dp))
    }
}

@Composable
private fun StartupCard(vm: AppViewModel, pages: PcPages) {
    val colors = LocalColors.current
    val read = pages.startup
    Card {
        Note(t("appset.startup_hint"))
        read.problem?.let { Note(it.text(vm.strings), color = colors.danger) }
        read.value?.let { report ->
            val good = PcSettings.verdictGood(report)
            Item(t(PcSettings.verdict(report)))
            Note(
                PcSettings.startupRows(vm.strings, report, vm.technical).joinToString("\n") { (name, value) -> "$name: $value" },
                color = when (good) { true -> colors.text2; false -> colors.danger; null -> colors.text3 },
            )
            if (report.problems.isNotEmpty()) Note(report.problems.joinToString("\n"), color = colors.danger)
        }
        TextButton(onClick = pages::checkStartup, enabled = !read.loading, modifier = Modifier.padding(start = 6.dp)) {
            Text(t(if (read.loading) "appset.startup_asking" else "appset.startup_check"))
        }
    }
}

/** PC settings > Signed-in devices: every account's, owner only. */
@Composable
fun DevicesScreen(vm: AppViewModel, onBack: () -> Unit) {
    val pages = vm.pcSettings
    val colors = LocalColors.current
    val strings = vm.strings
    val now = rememberNow()
    var asking by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        pages.clearSaid()
        pages.loadDevices()
    }
    val me = vm.me?.user ?: vm.user
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.pc.devices"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { Note(t("mobile.pc.devices_hint")) }
            item { SaidNote(pages.said) }
            pages.devices.problem?.let { item { ProblemNote(it, onRetry = pages::loadDevices) } }
            pages.devices.value?.let { devices ->
                if (devices.isEmpty()) item { Note(t("security.no_sessions")) }
                for ((user, list) in PcSettings.byAccount(devices, me)) {
                    item { SectionTitle(if (user == me) t("mobile.pc.you", "name" to user) else user) }
                    item {
                        Card {
                            for (device in list) {
                                Item(
                                    if (device.current) t("mobile.account.this_device") else device.label ?: t("security.device_unknown"),
                                    subtitle = device.lastUsed?.let { Display.ago(strings, it, now) },
                                    trailing = {
                                        if (!device.current) {
                                            TextButton(onClick = { pages.signOut(device, strings) }, enabled = pages.busy == null) {
                                                Text(t("mobile.account.sign_out_device"), color = colors.danger)
                                            }
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
                item {
                    TextButton(onClick = { asking = true }, enabled = pages.busy == null, modifier = Modifier.padding(start = 10.dp, top = 12.dp)) {
                        Text(t("security.revoke"), color = colors.danger)
                    }
                }
            }
        }
    }
    if (asking) {
        Confirm(
            title = t("security.revoke_title"),
            body = t("security.revoke_body"),
            confirm = t("security.revoke"),
            danger = true,
            onConfirm = {
                asking = false
                pages.signEveryoneOut(strings, vm::signedOutEverywhere)
            },
            onDismiss = { asking = false },
        )
    }
}

/** PC settings > Alerts: every alert setting the dashboard has. */
@Composable
fun AlertSettingsScreen(vm: AppViewModel, onBack: () -> Unit) {
    val pages = vm.pcSettings
    val colors = LocalColors.current
    LaunchedEffect(Unit) {
        pages.clearSaid()
        if (pages.view.value == null) pages.load()
    }
    val view = pages.view.value
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("appset.alerts"), onBack) }) { padding ->
        if (view == null) {
            Column(Modifier.padding(padding)) {
                pages.view.problem?.let { ProblemNote(it, onRetry = pages::load) } ?: Note(t("mobile.common.loading"))
            }
            return@Scaffold
        }
        AlertForm(vm, view, Modifier.padding(padding))
    }
}

@Composable
private fun AlertForm(vm: AppViewModel, view: PcSettingsView, modifier: Modifier) {
    val pages = vm.pcSettings
    val colors = LocalColors.current
    val strings = vm.strings
    val saved = remember(view) { PcSettings.alerts(view) }
    var edit by remember(view) { mutableStateOf(saved) }
    // What's typed, so a half-typed number isn't lost or saved.
    val typed = remember(view) {
        androidx.compose.runtime.mutableStateMapOf<String, String>().apply {
            for ((key, value) in saved.thresholds) put(key, Display.fixed(value, if (value % 1.0 == 0.0) 0 else 1))
            put("repeat", Display.fixed(saved.repeatSeconds, 0))
        }
    }
    val wrong = typed.filterValues { PcSettings.number(it) == null }.keys

    LazyColumn(contentPadding = ScreenPadding, modifier = modifier.fillMaxSize()) {
        item { SaidNote(pages.said) }
        item {
            Card {
                Channel(t("appset.discord"), edit.discord, if (view.secrets.discord) null else t("appset.discord_missing"), pages.busy == "test:discord",
                    onChange = { edit = edit.copy(discord = it) }, onTest = { pages.testAlert("discord", strings) }, enabled = pages.busy == null)
                Channel(t("appset.email"), edit.email, if (view.secrets.email) null else t("appset.email_missing"), pages.busy == "test:email",
                    onChange = { edit = edit.copy(email = it) }, onTest = { pages.testAlert("email", strings) }, enabled = pages.busy == null)
                if (vm.technical) {
                    val to = PcSettings.emailTo(view)
                    if (to.isNotEmpty()) Note(t("mobile.pc.email_to", "addresses" to to.joinToString(", ")), color = colors.text3)
                }
                Item(
                    t("appset.phone"),
                    subtitle = t("mobile.pc.phone_missing"),
                    trailing = { Switch(checked = edit.phone, onCheckedChange = { edit = edit.copy(phone = it) }) },
                )
                Note(t(if (vm.technical) "mobile.pc.secrets_technical" else "appset.secrets_note"), color = colors.text3)
            }
        }
        item { SectionTitle(t("appset.alert_details")) }
        item {
            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Gap) {
                    for ((key, label) in PcSettings.THRESHOLDS) {
                        NumberField(t(label), typed[key].orEmpty(), wrong = key in wrong) { text ->
                            typed[key] = text
                            PcSettings.number(text)?.let { edit = edit.copy(thresholds = edit.thresholds + (key to it)) }
                        }
                    }
                    NumberField(t("appset.repeat_alert"), typed["repeat"].orEmpty(), wrong = "repeat" in wrong) { text ->
                        typed["repeat"] = text
                        PcSettings.number(text)?.let { edit = edit.copy(repeatSeconds = it) }
                    }
                }
            }
        }
        item { SectionTitle(t("appset.which_events")) }
        item {
            Card {
                for ((key, on) in edit.events) {
                    // An event the phone has no words for shows the PC's own name for it.
                    val name = if (strings.has("alert_event.$key")) t("alert_event.$key") else key
                    Tick(name, checked = on) { edit = edit.copy(events = edit.events + (key to it)) }
                }
            }
        }
        item {
            Button(
                onClick = { pages.saveAlerts(saved, edit, strings) },
                enabled = pages.busy == null && wrong.isEmpty(),
                modifier = Modifier.fillMaxWidth().padding(16.dp),
            ) { Text(t(if (pages.busy == "alerts") "action.saving" else "appset.save_alerts")) }
        }
    }
}

@Composable
private fun Channel(
    name: String,
    on: Boolean,
    missing: String?,
    sending: Boolean,
    onChange: (Boolean) -> Unit,
    onTest: () -> Unit,
    enabled: Boolean,
) {
    Item(name, subtitle = missing, trailing = { Switch(checked = on, onCheckedChange = onChange) })
    TextButton(onClick = onTest, enabled = enabled, modifier = Modifier.padding(start = 6.dp)) {
        Text(t(if (sending) "appset.sending" else "appset.send_test"))
    }
}

@Composable
private fun NumberField(label: String, value: String, wrong: Boolean, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        singleLine = true,
        isError = wrong,
        supportingText = if (wrong) ({ Text(t("mobile.pc.number_wrong")) }) else null,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth(),
    )
}
