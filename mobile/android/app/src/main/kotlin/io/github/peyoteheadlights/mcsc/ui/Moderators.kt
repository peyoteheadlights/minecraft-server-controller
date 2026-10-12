package io.github.peyoteheadlights.mcsc.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Device
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.InviteCode
import io.github.peyoteheadlights.mcsc.core.Levels
import io.github.peyoteheadlights.mcsc.core.Moderator
import io.github.peyoteheadlights.mcsc.core.ModeratorList
import io.github.peyoteheadlights.mcsc.core.Moderators
import io.github.peyoteheadlights.mcsc.core.PermissionCatalogue
import io.github.peyoteheadlights.mcsc.core.Strings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/** The id the screens use for the "New servers" set of an "All servers" moderator. */
const val NEW_SERVERS = "+new"

/** The owner's moderators: the list, adding one, their permissions and invites. */
class ModeratorPages(
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    var list: Read<ModeratorList> by mutableStateOf(Read())
        private set
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    /** The invite just made, shown once: the agent keeps only its hash. */
    var invite: InviteCode? by mutableStateOf(null)
        private set

    fun moderator(name: String): Moderator? = list.value?.helpers?.firstOrNull { it.username == name }

    fun load() {
        val c = client() ?: return
        list = list.copy(loading = true)
        scope.launch {
            list = try {
                Read(c.moderators())
            } catch (e: AgentException) {
                noted(e)
                Read(list.value, problem = Message.of(e))
            }
        }
    }

    fun clearSaid() {
        said = null
    }

    private fun run(what: String, strings: Strings, work: suspend (AgentClient) -> Unit) {
        val c = client() ?: return
        busy = what
        said = null
        scope.launch {
            try {
                work(c)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            }
            busy = null
            load()
        }
    }

    fun add(name: String, servers: List<String>?, permissions: Set<String>, strings: Strings, onAdded: (String) -> Unit) =
        run("add", strings) { c ->
            val added = c.addModerator(name.trim(), servers, permissions)
            invite = added.invite
            onAdded(added.username)
        }

    fun save(name: String, body: JsonObject, strings: Strings) = run("save", strings) { c ->
        c.saveModerator(name, body)
        said = Said(strings.t("mobile.mod.saved"), good = true)
    }

    /** A new invite; with [forgetPassword] the owner's Reset password. */
    fun newInvite(name: String, forgetPassword: Boolean, strings: Strings, onMade: () -> Unit) =
        run(if (forgetPassword) "reset" else "invite", strings) { c ->
            invite = c.inviteModerator(name, forgetPassword)
            onMade()
        }

    fun cancelInvite(name: String, strings: Strings) = run("cancel", strings) { c ->
        c.cancelInvite(name)
        invite = null
        said = Said(strings.t("mobile.mod.invite_cancelled"), good = true)
    }

    fun remove(name: String, strings: Strings, onRemoved: () -> Unit) = run("remove", strings) { c ->
        c.removeModerator(name)
        said = Said(strings.t("mobile.mod.removed", "name" to name), good = true)
        onRemoved()
    }
}

/** "Your account": a moderator's password and their own signed-in devices. */
class AccountPages(
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    var devices: Read<List<Device>> by mutableStateOf(Read())
        private set
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    /** Only this account's devices: the owner's list (ticket 08) has everyone's. */
    fun load(user: String?) {
        val c = client() ?: return
        devices = devices.copy(loading = true)
        scope.launch {
            devices = try {
                Read(c.devices().sessions.filter { user == null || it.user == user })
            } catch (e: AgentException) {
                noted(e)
                Read(devices.value, problem = Message.of(e))
            }
        }
    }

    fun changePassword(current: String, new: String, strings: Strings, onChanged: () -> Unit) {
        val c = client() ?: return
        busy = "password"
        said = null
        scope.launch {
            try {
                c.changePassword(current, new)
                said = Said(strings.t("account.changed"), good = true)
                onChanged()
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            }
            busy = null
        }
    }

    fun signOut(device: Device, user: String?, strings: Strings) {
        val c = client() ?: return
        busy = device.id
        said = null
        scope.launch {
            try {
                c.signOutDevice(device.id)
                said = Said(strings.t("mobile.account.signed_out_device", "device" to (device.label ?: device.id)), good = true)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            }
            busy = null
            load(user)
        }
    }
}

// ------------------------------------------------------------ screens

@Composable
private fun SaidNote(said: Said?) {
    said?.let { Note(it.text, color = if (it.good) LocalColors.current.success else LocalColors.current.danger) }
}

/** Settings > Moderators (owner only). */
@Composable
fun ModeratorsScreen(vm: AppViewModel, onBack: () -> Unit, onOpen: (String) -> Unit, onAdd: () -> Unit) {
    val pages = vm.moderators
    val now = rememberNow()
    LaunchedEffect(Unit) { pages.load() }
    Scaffold(containerColor = LocalColors.current.sheet, topBar = { Bar(t("mobile.mod.title"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { Note(t("mobile.mod.lead")) }
            pages.list.problem?.let { item { ProblemNote(it, onRetry = pages::load) } }
            val list = pages.list.value
            if (list != null) {
                item {
                    Card {
                        if (list.helpers.isEmpty()) Item(t("mobile.mod.none"))
                        for (mod in list.helpers) {
                            Item(
                                mod.username,
                                subtitle = when {
                                    mod.inviteWaiting -> t("mobile.mod.invite_waiting")
                                    else -> mod.lastUsed?.let { t("mobile.mod.last_used", "time" to Display.ago(vm.strings, it, now)) }
                                        ?: t("mobile.mod.never_used")
                                },
                                onClick = { onOpen(mod.username) },
                            )
                        }
                    }
                }
            } else if (pages.list.problem == null) {
                item { Note(t("mobile.common.loading")) }
            }
            item {
                Button(onClick = onAdd, modifier = Modifier.fillMaxWidth().padding(16.dp)) { Text(t("mobile.mod.add")) }
            }
        }
    }
}

/** Add moderator: the name, the servers and the level, then the invite. */
@Composable
fun AddModeratorScreen(vm: AppViewModel, onBack: () -> Unit, onAdded: (String) -> Unit) {
    val pages = vm.moderators
    val colors = LocalColors.current
    LaunchedEffect(Unit) {
        pages.clearSaid()
        if (!pages.list.loaded) pages.load()
    }
    val list = pages.list.value
    var name by rememberSaveable { mutableStateOf("") }
    var all by rememberSaveable { mutableStateOf(false) }
    var picked by rememberSaveable { mutableStateOf(listOf<String>()) }
    var level by rememberSaveable { mutableStateOf(Levels.LOOK_AFTER_IT) }
    LaunchedEffect(list?.permissions?.defaultLevel) { list?.permissions?.defaultLevel?.let { level = it } }
    val nameOk = Moderators.nameOk(name)
    val ready = list != null && nameOk && (all || picked.isNotEmpty()) && pages.busy == null

    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.mod.add"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(t("mobile.mod.name")) },
                    singleLine = true,
                    isError = name.isNotBlank() && !nameOk,
                    supportingText = { Text(t(if (name.isNotBlank() && !nameOk) "mobile.mod.name_bad" else "mobile.mod.name_hint")) },
                    keyboardOptions = KeyboardOptions(autoCorrectEnabled = false),
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                )
            }
            pages.list.problem?.let { item { ProblemNote(it, onRetry = pages::load) } }
            if (list != null) {
                item { SectionTitle(t("mobile.mod.servers")) }
                item {
                    Card {
                        Item(
                            t("mobile.mod.all_servers"),
                            subtitle = t("mobile.mod.all_servers_hint"),
                            trailing = { Switch(checked = all, onCheckedChange = { all = it }) },
                        )
                        if (!all) {
                            for (server in list.servers) {
                                Tick(server.name, server.id in picked) { on -> picked = if (on) picked + server.id else picked - server.id }
                            }
                        }
                    }
                }
                if (!all && picked.isEmpty()) item { Note(t("mobile.mod.pick_a_server"), color = colors.text3) }
                item { SectionTitle(t("mobile.mod.level")) }
                item { LevelChoices(list.permissions, level) { level = it } }
            }
            item { SaidNote(pages.said) }
            item {
                Button(
                    onClick = {
                        val permissions = Moderators.level(level, list!!.permissions)
                        pages.add(name, if (all) null else picked, permissions, vm.strings) { onAdded(it) }
                    },
                    enabled = ready,
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                ) { Text(t(if (pages.busy == "add") "helpers.adding" else "mobile.mod.add")) }
            }
        }
    }
}

@Composable
private fun LevelChoices(catalogue: PermissionCatalogue, selected: String, onPick: (String) -> Unit) {
    Card(Modifier.selectableGroup()) {
        for (level in catalogue.levels) {
            Radio(t("mobile.mod.level_${level.id}"), t("mobile.mod.level_${level.id}_hint"), selected == level.id) { onPick(level.id) }
        }
        // A set that is none of the levels: shown, never picked.
        if (selected == Levels.CUSTOM) Radio(t("mobile.mod.level_custom"), null, true, enabled = false) {}
    }
}

@Composable
private fun Radio(title: String, subtitle: String?, selected: Boolean, enabled: Boolean = true, onSelect: () -> Unit) {
    Box(Modifier.selectable(selected = selected, enabled = enabled, role = Role.RadioButton, onClick = onSelect)) {
        Item(title, subtitle = subtitle, trailing = { RadioButton(selected = selected, onClick = null, enabled = enabled) })
    }
}

@Composable
private fun Tick(title: String, checked: Boolean, subtitle: String? = null, onChange: (Boolean) -> Unit) {
    Box(Modifier.toggleable(value = checked, role = Role.Checkbox, onValueChange = onChange)) {
        Item(title, subtitle = subtitle, trailing = { Checkbox(checked = checked, onCheckedChange = null) })
    }
}

/** One moderator: their servers with a summary each, their invite, Reset password and Remove. */
@Composable
fun ModeratorScreen(vm: AppViewModel, name: String, onBack: () -> Unit, onServer: (String) -> Unit, onInvite: () -> Unit) {
    val pages = vm.moderators
    val colors = LocalColors.current
    val now = rememberNow()
    var asking by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(name) {
        pages.clearSaid()
        if (!pages.list.loaded) pages.load()
    }
    val list = pages.list.value
    val mod = pages.moderator(name)

    Scaffold(containerColor = colors.sheet, topBar = { Bar(name, onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            pages.list.problem?.let { item { ProblemNote(it, onRetry = pages::load) } }
            item { SaidNote(pages.said) }
            if (list != null && mod != null) {
                if (mod.inviteWaiting) {
                    item { SectionTitle(t("mobile.mod.invite_waiting")) }
                    item {
                        Card {
                            mod.invite?.let { Item(t("mobile.mod.invite_expires", "time" to Display.dateTime(vm.strings, it.expiresAt))) }
                            Item(
                                t("mobile.mod.invite_new"),
                                subtitle = t("mobile.mod.invite_new_hint"),
                                onClick = { pages.newInvite(name, false, vm.strings, onInvite) },
                            )
                            Item(t("mobile.mod.invite_cancel"), onClick = { pages.cancelInvite(name, vm.strings) })
                        }
                    }
                } else {
                    item {
                        Note(mod.lastUsed?.let { t("mobile.mod.last_used", "time" to Display.ago(vm.strings, it, now)) } ?: t("mobile.mod.never_used"))
                    }
                }
                item { SectionTitle(t("mobile.mod.servers")) }
                item {
                    Card {
                        Item(
                            t("mobile.mod.all_servers"),
                            subtitle = t("mobile.mod.all_servers_hint"),
                            trailing = {
                                Switch(
                                    checked = mod.allServers,
                                    enabled = pages.busy == null,
                                    onCheckedChange = { on -> pages.save(name, Moderators.allServers(on, mod, list.permissions), vm.strings) },
                                )
                            },
                        )
                        for (access in mod.access) {
                            Item(
                                access.name,
                                subtitle = Moderators.summary(access.permissions.toSet(), list.permissions, vm.strings),
                                onClick = { onServer(access.id) },
                            )
                        }
                        if (mod.allServers) {
                            Item(
                                t("mobile.mod.new_servers"),
                                subtitle = Moderators.summary(mod.newServer.permissions.toSet(), list.permissions, vm.strings),
                                onClick = { onServer(NEW_SERVERS) },
                            )
                        }
                    }
                }
                item { SectionTitle(t("account.title")) }
                item {
                    Card {
                        Item(t("mobile.mod.reset"), onClick = { asking = "reset" })
                        Item(t("mobile.mod.remove"), onClick = { asking = "remove" })
                    }
                }
            } else if (list == null && pages.list.problem == null) {
                item { Note(t("mobile.common.loading")) }
            }
        }
    }

    when (asking) {
        "reset" -> Confirm(
            title = t("mobile.mod.reset_title", "name" to name),
            body = t("mobile.mod.reset_body"),
            confirm = t("mobile.mod.reset"),
            danger = true,
            onConfirm = {
                asking = null
                pages.newInvite(name, true, vm.strings, onInvite)
            },
            onDismiss = { asking = null },
        )
        "remove" -> Confirm(
            title = t("helpers.remove_title", "name" to name),
            body = t("mobile.mod.remove_body"),
            confirm = t("mobile.mod.remove"),
            danger = true,
            onConfirm = {
                asking = null
                pages.remove(name, vm.strings, onBack)
            },
            onDismiss = { asking = null },
        )
    }
}

/** One server of one moderator (or their "New servers" set): the level, the switches and where to save. */
@Composable
fun ModeratorServerScreen(vm: AppViewModel, name: String, serverId: String, onBack: () -> Unit) {
    val pages = vm.moderators
    val colors = LocalColors.current
    LaunchedEffect(name, serverId) {
        pages.clearSaid()
        if (!pages.list.loaded) pages.load()
    }
    val list = pages.list.value
    val mod = pages.moderator(name)
    if (list == null || mod == null) {
        Scaffold(containerColor = colors.sheet, topBar = { Bar(name, onBack) }) { padding ->
            Column(Modifier.padding(padding)) {
                pages.list.problem?.let { ProblemNote(it, onRetry = pages::load) } ?: Note(t("mobile.common.loading"))
            }
        }
        return
    }
    val catalogue = list.permissions
    val newServers = serverId == NEW_SERVERS
    val saved = if (newServers) mod.newServer.permissions.toSet() else mod.access.firstOrNull { it.id == serverId }?.permissions.orEmpty().toSet()
    val title = if (newServers) t("mobile.mod.new_servers") else mod.access.firstOrNull { it.id == serverId }?.name ?: serverId
    var perms by remember(name, serverId, saved) { mutableStateOf(saved) }
    var editing by rememberSaveable { mutableStateOf(false) }
    var picking by rememberSaveable { mutableStateOf(false) }
    val level = Moderators.levelOf(perms, catalogue)
    val busy = pages.busy != null

    Scaffold(containerColor = colors.sheet, topBar = { Bar("$name · $title", onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            if (newServers) item { Note(t("mobile.mod.new_servers_hint")) }
            item { SectionTitle(t("mobile.mod.level")) }
            item {
                LevelChoices(catalogue, level) { perms = Moderators.level(it, catalogue) }
                if (level == Levels.NONE) Note(t("mobile.mod.level_none"), color = colors.text3)
            }
            if (!editing && level != Levels.CUSTOM) {
                item { TextButton(onClick = { editing = true }, modifier = Modifier.padding(horizontal = 8.dp)) { Text(t("mobile.mod.change")) } }
            } else {
                for (group in catalogue.groups) {
                    val shown = Moderators.shown(group, vm.technical, catalogue)
                    if (shown.isEmpty()) continue
                    item { SectionTitle(t("mobile.mod.group_${group.id}")) }
                    item {
                        Card {
                            for (permission in shown) {
                                Tick(t(Moderators.switchKey(permission)), permission in perms) { on ->
                                    perms = Moderators.toggle(perms, permission, on, catalogue)
                                }
                            }
                        }
                    }
                }
                val hidden = Moderators.hiddenTicked(perms, vm.technical, catalogue)
                if (hidden > 0) item { Note(t("mobile.mod.more_technical", "count" to hidden)) }
            }
            if (Moderators.warns(perms, catalogue)) item { Note(t("mobile.mod.warn"), color = colors.warning) }
            item { SaidNote(pages.said) }
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Gap) {
                    if (newServers) {
                        Button(
                            onClick = { pages.save(name, Moderators.newServers(perms), vm.strings) },
                            enabled = !busy && perms != saved,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(t("mobile.mod.save")) }
                    } else {
                        Button(
                            onClick = { pages.save(name, Moderators.saveFor(listOf(serverId), perms), vm.strings) },
                            enabled = !busy && perms != saved,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(t("mobile.mod.save_here")) }
                        OutlinedButton(onClick = { picking = true }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                            Text(t("mobile.mod.save_for"))
                        }
                        OutlinedButton(
                            onClick = { pages.save(name, Moderators.applyToAll(list.servers.map { it.id }, perms, mod.allServers), vm.strings) },
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(t("mobile.mod.apply_all")) }
                    }
                }
            }
        }
    }

    if (picking) {
        var chosen by remember { mutableStateOf(setOf(serverId)) }
        AlertDialog(
            onDismissRequest = { picking = false },
            title = { Text(t("mobile.mod.pick_servers")) },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    for (server in list.servers) {
                        Tick(server.name, server.id in chosen) { on -> chosen = if (on) chosen + server.id else chosen - server.id }
                    }
                }
            },
            confirmButton = {
                TextButton(
                    enabled = chosen.isNotEmpty(),
                    onClick = {
                        picking = false
                        pages.save(name, Moderators.saveFor(chosen, perms), vm.strings)
                    },
                ) { Text(t("mobile.mod.save")) }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text(t("mobile.common.cancel")) } },
            containerColor = colors.float,
            titleContentColor = colors.text,
            textContentColor = colors.text2,
        )
    }
}

/** The invite just made: its QR code, Share, and the Tailscale reminder. */
@Composable
fun InviteScreen(vm: AppViewModel, name: String, onDone: () -> Unit) {
    val pages = vm.moderators
    val colors = LocalColors.current
    val context = LocalContext.current
    val invite = pages.invite?.takeIf { it.username == name }
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.mod.invite_title", "name" to name), onDone) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            if (invite == null) {
                item { Note(t("mobile.mod.invite_gone")) }
                return@LazyColumn
            }
            val url = invite.url
            val qr = invite.qr
            if (!invite.ok || url == null || qr == null) {
                item { Note(t("mobile.mod.no_code", "reason" to (invite.reason ?: t("value.unknown"))), color = colors.danger) }
                return@LazyColumn
            }
            item { Note(t("mobile.mod.invite_lead", "name" to name)) }
            item {
                Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                    QrCode(qr, Modifier.widthIn(max = 320.dp).fillMaxWidth(), t("mobile.mod.invite_title", "name" to name))
                }
            }
            item { Note(t("mobile.mod.invite_expires", "time" to Display.dateTime(vm.strings, invite.expiresAt))) }
            item {
                Button(
                    onClick = {
                        val message = vm.strings.t("mobile.mod.invite_message", "name" to name, "app" to Links.APP_DOWNLOAD, "link" to url)
                        shareText(context, message, vm.strings.t("mobile.mod.invite_share"))
                    },
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                ) { Text(t("mobile.mod.invite_share")) }
            }
            item {
                Card {
                    Item(t("mobile.mod.invite_tailscale", "name" to name))
                    Item(t("mobile.mod.invite_tailscale_how"), onClick = { openLink(context, Links.TAILSCALE_SHARE) }, external = true)
                }
            }
        }
    }
}

/** A QR code from the agent's rows of 0 and 1, black on white with its quiet border, so it scans in dark mode too. */
@Composable
fun QrCode(rows: List<String>, modifier: Modifier = Modifier, label: String) {
    // Four squares of quiet border on each side.
    val cells = rows.size + 8
    Canvas(
        modifier
            .aspectRatio(1f)
            .background(Color.White)
            .semantics { contentDescription = label },
    ) {
        val cell = size.width / cells
        rows.forEachIndexed { y, row ->
            row.forEachIndexed { x, c ->
                if (c == '1') drawRect(Color.Black, Offset((x + 4) * cell, (y + 4) * cell), Size(cell + 0.5f, cell + 0.5f))
            }
        }
    }
}

/** The phone's share menu for some text (an invite). */
fun shareText(context: Context, text: String, title: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    try {
        context.startActivity(Intent.createChooser(send, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (ignored: ActivityNotFoundException) {
        // Nothing takes text: nothing to share it with.
    }
}

/** Settings > Your account: the name, the password and this account's own devices. */
@Composable
fun AccountScreen(vm: AppViewModel, onBack: () -> Unit) {
    val pages = vm.yourAccount
    val colors = LocalColors.current
    val now = rememberNow()
    val me = vm.me
    val user = me?.user ?: vm.user
    val owner = me?.isOwner == true
    var current by rememberSaveable { mutableStateOf("") }
    var new by rememberSaveable { mutableStateOf("") }
    var repeat by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(user) { pages.load(user) }
    val mismatch = repeat.isNotEmpty() && new != repeat
    val short = new.isNotEmpty() && new.length < 10

    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("account.title"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { Note(t(if (owner) "account.owner" else "account.helper", "name" to (user ?: t("value.unknown")))) }
            item { SectionTitle(t("account.change")) }
            if (owner) {
                item { Note(t("mobile.account.owner_forgot")) }
            } else {
                item {
                    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Gap) {
                        PasswordField(current, { current = it }, t("account.current"))
                        PasswordField(new, { new = it }, t("account.new"), error = if (short) t("mobile.invite.too_short") else null)
                        PasswordField(repeat, { repeat = it }, t("mobile.invite.repeat"), error = if (mismatch) t("mobile.invite.mismatch") else null)
                        Button(
                            onClick = {
                                pages.changePassword(current, new, vm.strings) {
                                    current = ""
                                    new = ""
                                    repeat = ""
                                    pages.load(user)
                                }
                            },
                            enabled = pages.busy == null && current.isNotEmpty() && new.length >= 10 && new == repeat,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(t(if (pages.busy == "password") "mobile.account.saving" else "account.change")) }
                        Note(t("mobile.account.forgot"), modifier = Modifier.padding(horizontal = 0.dp))
                    }
                }
            }
            item { SaidNote(pages.said) }
            item { SectionTitle(t("mobile.account.devices")) }
            pages.devices.problem?.let { item { ProblemNote(it) { pages.load(user) } } }
            pages.devices.value?.let { devices ->
                item {
                    Card {
                        if (devices.none { !it.current }) Item(t("mobile.account.no_devices"))
                        for (device in devices.sortedByDescending { it.current }) {
                            Item(
                                if (device.current) t("mobile.account.this_device") else device.label ?: t("value.unknown"),
                                subtitle = device.lastUsed?.let { Display.ago(vm.strings, it, now) },
                                trailing = {
                                    if (!device.current) {
                                        TextButton(onClick = { pages.signOut(device, user, vm.strings) }, enabled = pages.busy == null) {
                                            Text(t("mobile.account.sign_out_device"), color = colors.danger)
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun PasswordField(value: String, onChange: (String) -> Unit, label: String, error: String? = null, hint: String? = null) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        singleLine = true,
        isError = error != null,
        supportingText = (error ?: hint)?.let { { Text(it) } },
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
        modifier = Modifier.fillMaxWidth(),
    )
}
