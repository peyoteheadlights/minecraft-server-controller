package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Backup
import io.github.peyoteheadlights.mcsc.core.Backups
import io.github.peyoteheadlights.mcsc.core.ChangeList
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.FolderPicker
import io.github.peyoteheadlights.mcsc.core.Offsite
import io.github.peyoteheadlights.mcsc.core.Permissions
import io.github.peyoteheadlights.mcsc.core.Tone
import io.github.peyoteheadlights.mcsc.core.UndoRedo
import io.github.peyoteheadlights.mcsc.core.WorldImport
import io.github.peyoteheadlights.mcsc.core.WorldPoint
import io.github.peyoteheadlights.mcsc.core.WorldRestore

/** A button in a row of them. */
data class Press(val label: String, val onClick: () -> Unit, val danger: Boolean = false, val enabled: Boolean = true)

/** A row of buttons under a card's text, wrapping on a narrow phone. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun Presses(presses: List<Press>) {
    if (presses.isEmpty()) return
    val colors = LocalColors.current
    FlowRow(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (press in presses) {
            OutlinedButton(
                onClick = press.onClick,
                enabled = press.enabled,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = if (press.danger) colors.danger else colors.accentInk),
            ) { Text(press.label) }
        }
    }
}

/** What the last button did, read out to screen readers too. */
@Composable
fun SaidNote(said: Said?) {
    val colors = LocalColors.current
    if (said == null) return
    Note(
        said.text,
        color = if (said.good) colors.success else colors.danger,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
    )
}

/** A thing to confirm, with its title, words and button. */
private data class Confirming(val title: String, val body: String, val confirm: String, val run: () -> Unit)

/**
 * Back up now, Save world, Undo and Redo, every backup with
 * Check, Download, Restore and Delete, the second copy off the PC, and the
 * worlds. A download goes to a file the person picks, with the sign-in in
 * a header; nothing else ever leaves the PC.
 */
@Composable
fun BackupsScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit, onRestoreWorld: () -> Unit) {
    val world = vm.pages(serverId).world
    val strings = vm.strings
    var asking by remember { mutableStateOf<Confirming?>(null) }
    var picking by remember { mutableStateOf(false) }
    // The backup waiting for the picker: id, name and size, kept if the
    // screen is rebuilt (the phone turned) while the picker is open.
    var saving by rememberSaveable { mutableStateOf<Triple<Long, String, Long?>?>(null) }
    val save = rememberZipSaver { open, discard ->
        val waiting = saving
        saving = null
        if (waiting == null) {
            // Nothing to put in the file the picker just made: remove it.
            discard()
        } else {
            val (id, name, size) = waiting
            world.download(Backup(id = id, name = name, sizeBytes = size), open, discard, strings)
        }
    }
    LaunchedEffect(serverId) { world.loadBackups() }

    ServerFrame(
        vm, serverId,
        title = t("page.backups"),
        onBack = onBack,
        refreshing = false,
        onRefresh = world::loadBackups,
        overlay = {
            if (picking) {
                FolderPickerDialog(vm, t("offsite.pick_title"), world.offsite?.directory, onPick = {
                    picking = false
                    world.setOffsite(it, strings)
                }, onDismiss = { picking = false })
            }
            asking?.let { ask ->
                Confirm(ask.title, ask.body, ask.confirm, danger = true, onConfirm = {
                    asking = null
                    ask.run()
                }, onDismiss = { asking = null })
            }
            world.restoring?.let { ask ->
                RestoreDialog(vm, ask.backup, ask.willHappen, onRestore = { world.restore(it, strings) }, onDismiss = world::cancelRestore)
            }
            world.moving?.let { ask ->
                val (title, body) = ChangeList.ask(strings, ask.direction, ask.change, rememberNow())
                StartAfterDialog(title, body, t("changes.${ask.direction}"), onConfirm = { world.move(it, strings) }, onDismiss = world::cancelMove)
            }
        },
    ) {
        val busy = world.busy
        item {
            Presses(
                listOfNotNull(
                    Press(t(if (busy == "backup") "backup.working" else "action.back_up_now"), { world.backUp(strings) }, enabled = busy == null)
                        .takeIf { vm.canDo(Permissions.BACKUPS_CREATE) },
                    Press(t("backups.save_world"), { world.saveWorld(strings) }, enabled = busy == null)
                        .takeIf { vm.canControl() },
                ),
            )
        }
        item { SaidNote(world.said) }
        world.downloading?.let { (name, done, size) ->
            item {
                val share = if (size != null && size > 0) " ${done * 100 / size}%" else " " + Display.bytes(strings, done)
                Note(t("mobile.backups.downloading", "name" to name) + share)
            }
        }
        world.changes?.takeIf { it.undo.isNotEmpty() || it.redo.isNotEmpty() }?.let { lists ->
            item { UndoRedoCard(vm, world, lists, busy) }
        }

        item { SectionTitle(t("backups.list")) }
        val list = world.backups
        emptyOrProblem(Read(list.value?.backups, list.problem, list.loading), "backups.none", "backups.none_hint", onRetry = world::loadBackups)
        items(list.value?.backups.orEmpty(), key = { it.id }) { backup ->
            BackupCard(vm, backup, world.offsite, busy,
                onCheck = { world.check(backup, strings) },
                onDownload = {
                    saving = Triple(backup.id, backup.name, backup.sizeBytes)
                    save(backup.name)
                },
                onRestore = { world.askRestore(backup, strings) },
                onCopy = { world.copyAgain(backup, strings) },
                onDelete = {
                    asking = Confirming(
                        strings.t("backups.delete_title", "name" to backup.name),
                        strings.t("backups.delete_body"),
                        strings.t("backups.delete_confirm"),
                    ) { world.delete(backup, strings) }
                },
            )
        }
        Backups.keeping(strings, list.value?.retention)?.let { item { Note(it, color = LocalColors.current.text3) } }

        item { SectionTitle(t("page.world")) }
        item { Card { Item(t("world.lead"), onClick = onRestoreWorld) } }

        offsiteCard(vm, world.offsite, busy, onChoose = { picking = true }) { world.offsiteOff(strings) }
        worldsCard(vm, world)
    }
}

/** The Undo and Redo lists (changesCard in backups.js): the newest change,
 * the one undone last, and the next few Undo would go on to. */
@Composable
private fun UndoRedoCard(vm: AppViewModel, world: WorldPages, lists: UndoRedo, busy: String?) {
    val strings = vm.strings
    val colors = LocalColors.current
    val now = rememberNow()
    val canRestore = vm.canDo(Permissions.BACKUPS_RESTORE)
    Column {
        SectionTitle(t("changes.title"))
        Card {
            Note(ChangeList.next(strings, lists, now), color = colors.text, modifier = Modifier.padding(top = 10.dp))
            ChangeList.nextRedo(strings, lists, now)?.let { Note(it, color = colors.text) }
            val later = ChangeList.later(strings, lists, now)
            if (later.isNotEmpty()) Note(t("changes.then") + "\n" + later.joinToString("\n") { "• $it" })
            val laterRedo = ChangeList.laterRedo(strings, lists, now)
            if (laterRedo.isNotEmpty()) Note(t("mobile.changes.then_redo") + "\n" + laterRedo.joinToString("\n") { "• $it" })
            lists.blockedBy?.let { Note(t("world.busy", "job" to it), color = colors.warning) }
            if (canRestore) {
                Presses(
                    listOf(
                        Press(t("changes.undo"), { world.askMove("undo") }, danger = true,
                            enabled = busy == null && ChangeList.canMove(lists, "undo", canRestore)),
                        Press(t("changes.redo"), { world.askMove("redo") }, danger = true,
                            enabled = busy == null && ChangeList.canMove(lists, "redo", canRestore)),
                    ),
                )
            }
        }
    }
}

@Composable
private fun BackupCard(
    vm: AppViewModel,
    backup: Backup,
    offsite: Offsite?,
    busy: String?,
    onCheck: () -> Unit,
    onDownload: () -> Unit,
    onRestore: () -> Unit,
    onCopy: () -> Unit,
    onDelete: () -> Unit,
) {
    val strings = vm.strings
    val colors = LocalColors.current
    val kind = Backups.kind(backup.kind)?.let { t(it.key) } ?: backup.kind ?: t("value.unknown")
    val status = Backups.status(backup.status)
    val (copyText, copyTone) = Backups.copy(strings, backup.copy)
    val idle = busy == null
    Card {
        Item(
            if (vm.technical) backup.name else Display.dateTime(strings, backup.createdAt),
            subtitle = listOfNotNull(
                kind,
                t(status.key),
                Display.bytes(strings, backup.sizeBytes),
                Display.dateTime(strings, backup.createdAt).takeIf { vm.technical },
            ).joinToString(" · "),
        )
        Note(t("offsite.col") + ": " + copyText, color = if (copyTone == Tone.NEUTRAL) colors.text2 else colors.tone(copyTone))
        Presses(
            listOfNotNull(
                Press(t(if (busy == "check:${backup.id}") "backups.checking" else "backups.verify"), onCheck, enabled = idle),
                Press(t("backups.download"), onDownload, enabled = idle)
                    .takeIf { vm.canDo(Permissions.BACKUPS_DOWNLOAD) && Backups.onDisk(backup) },
                Press(t(if (busy == "restore:${backup.id}") "mobile.backups.restore_working" else "backups.restore"), onRestore, enabled = idle)
                    .takeIf { vm.canDo(Permissions.BACKUPS_RESTORE) && Backups.onDisk(backup) },
                Press(t(if (busy == "copy:${backup.id}") "offsite.copying" else "offsite.copy_now"), onCopy, enabled = idle)
                    .takeIf { Backups.canCopyAgain(backup, offsite, vm.canDo(Permissions.BACKUPS_CREATE)) },
                Press(t("backups.delete"), onDelete, danger = true, enabled = idle)
                    .takeIf { vm.canDo(Permissions.BACKUPS_DELETE) },
            ),
        )
    }
}

/** Undo or Redo: what goes back and what would be lost, "start the server after", then yes or no. */
@Composable
private fun StartAfterDialog(title: String, body: String, confirm: String, onConfirm: (Boolean) -> Unit, onDismiss: () -> Unit) {
    val colors = LocalColors.current
    var startAfter by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                Text(body)
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 10.dp)) {
                    Checkbox(checked = startAfter, onCheckedChange = { startAfter = it })
                    Text(t("backups.start_after"))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(startAfter) }, colors = ButtonDefaults.textButtonColors(contentColor = colors.danger)) {
                Text(confirm)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}

/** What the agent says a restore will do, "start the server after", then yes or no. */
@Composable
private fun RestoreDialog(vm: AppViewModel, backup: Backup, willHappen: List<String>, onRestore: (Boolean) -> Unit, onDismiss: () -> Unit) {
    val colors = LocalColors.current
    var startAfter by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(t("backups.restore_title")) },
        text = {
            Column {
                Text(t("backups.restore_question", "name" to backup.name, "when" to Display.dateTime(vm.strings, backup.createdAt)))
                for (step in willHappen) Text("• $step", modifier = Modifier.padding(top = 6.dp))
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 10.dp)) {
                    Checkbox(checked = startAfter, onCheckedChange = { startAfter = it })
                    Text(t("backups.start_after"))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onRestore(startAfter) }, colors = ButtonDefaults.textButtonColors(contentColor = colors.danger)) {
                Text(t("backups.restore_confirm"))
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}

private fun LazyListScope.offsiteCard(vm: AppViewModel, offsite: Offsite?, busy: String?, onChoose: () -> Unit, onTurnOff: () -> Unit) {
    item { SectionTitle(t("offsite.title")) }
    item {
        val colors = LocalColors.current
        val canEdit = vm.canDo(Permissions.PC_SETTINGS)
        Card {
            Note(t("offsite.lead"), color = colors.text, modifier = Modifier.padding(top = 10.dp))
            val folder = offsite?.directory.orEmpty()
            when {
                offsite == null -> Note(t("value.unknown"))
                folder.isEmpty() -> Note(t("offsite.off"))
                offsite.unavailable != null ->
                    Note(t("offsite.folder_unavailable", "folder" to folder, "reason" to offsite.unavailable), color = colors.warning)
                else -> Note(t("offsite.folder_ok", "folder" to folder))
            }
            if (vm.technical) offsite?.subfolder?.let { Note(it, color = colors.text3) }
            // Choosing a folder needs the PC folder picker, which is the owner's.
            val canPick = canEdit && FolderPicker.allowed(vm.me)
            if (canEdit && !canPick) Note(t("mobile.offsite.choose_on_pc"), color = colors.text3)
            if (canEdit && offsite != null) {
                Presses(
                    listOfNotNull(
                        Press(t(if (folder.isEmpty()) "offsite.choose" else "offsite.change"), onChoose, enabled = busy == null).takeIf { canPick },
                        Press(t(if (busy == "offsite") "action.saving" else "offsite.turn_off"), onTurnOff, enabled = busy == null)
                            .takeIf { folder.isNotEmpty() },
                    ),
                )
            }
        }
    }
}

private fun LazyListScope.worldsCard(vm: AppViewModel, world: WorldPages) {
    val read = world.worlds
    val worlds = read.value?.worlds ?: return
    item { SectionTitle(t("backups.worlds")) }
    item {
        val strings = vm.strings
        val now = rememberNow()
        Card {
            for (w in worlds) {
                val last = w.lastBackup?.createdAt?.let { Display.ago(strings, it, now) } ?: t("time.never")
                val lastText = if (vm.technical && w.lastBackup?.name != null) "${w.lastBackup?.name} ($last)" else last
                Item(
                    w.label,
                    subtitle = if (!w.exists) t("backups.world_missing")
                    else listOf(
                        Display.bytes(strings, w.sizeBytes),
                        t("backups.col_modified") + ": " + Display.dateTime(strings, w.modified),
                        t("backups.col_last_backup") + ": " + lastText,
                    ).joinToString(" · "),
                )
            }
        }
    }
}

/**
 * Restore world: the world as it was at a point in time. Every point is a
 * backup the agent checked; going back makes a backup of the world as it
 * is now first, and the server has to be off.
 */
@Composable
fun WorldRestoreScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val world = vm.pages(serverId).world
    val strings = vm.strings
    var asking by remember { mutableStateOf<WorldPoint?>(null) }
    var stopping by remember { mutableStateOf(false) }
    var pickingFolder by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val bedrock = vm.servers.list.firstOrNull { it.id == serverId }?.edition == "bedrock"
    val pickZip = rememberFilePicker { world.sendWorld(it, strings) }
    // Read again when the server starts or stops: importing needs it off.
    val state = vm.server[serverId]?.status?.state
    LaunchedEffect(serverId, state) { world.loadTimeline() }
    LaunchedEffect(serverId, bedrock) { if (!bedrock && WorldImport.canImport(vm.me)) world.loadSaves() }
    val now = rememberNow()

    ServerFrame(
        vm, serverId,
        title = t("page.world"),
        onBack = onBack,
        refreshing = false,
        onRefresh = world::loadTimeline,
        overlay = {
            asking?.let { point ->
                Confirm(
                    title = t("world.confirm_title", "when" to WorldRestore.whenLabel(strings, point.createdAt, now)),
                    body = t("world.confirm_body", "loss" to WorldRestore.lossLine(strings, point)) + "\n\n" + t("world.confirm_safety"),
                    confirm = t("world.confirm_action"),
                    danger = true,
                    onConfirm = {
                        asking = null
                        world.restoreWorld(point, strings)
                    },
                    onDismiss = { asking = null },
                )
            }
            if (stopping) {
                Confirm(
                    title = t("confirm.stop_title"),
                    body = t("confirm.stop_body"),
                    confirm = t("action.stop"),
                    danger = true,
                    onConfirm = {
                        stopping = false
                        vm.act(serverId, "stop")
                    },
                    onDismiss = { stopping = false },
                )
            }
            if (pickingFolder) {
                FolderPickerDialog(vm, t("import.pick_title"), null, onPick = {
                    pickingFolder = false
                    world.pickWorldFolder(it, strings)
                }, onDismiss = { pickingFolder = false })
            }
            world.worldRead?.let { read ->
                WorldReadDialog(vm, read, onReplace = { world.importWorld(strings) }, onCancel = world::forgetWorld)
            }
        },
    ) {
        val read = world.timeline
        val timeline = read.value
        item { Note(t("world.lead"), color = LocalColors.current.text, modifier = Modifier.padding(top = 8.dp)) }
        item { SaidNote(world.said) }
        val problem = read.problem
        when {
            problem != null -> item { ProblemNote(problem, world::loadTimeline) }
            timeline == null -> item { Note(t("mobile.common.loading")) }
            timeline.points.isEmpty() -> item { Card { Item(t("world.none"), subtitle = t("world.none_hint")) } }
            else -> {
                WorldRestore.blocked(strings, timeline)?.let { why -> item { Note(why, color = LocalColors.current.warning) } }
                val canRestore = vm.canDo(Permissions.BACKUPS_RESTORE)
                items(timeline.points, key = { it.backupId }) { point ->
                    val colors = LocalColors.current
                    val tags = listOfNotNull(
                        t("world.tag_safety").takeIf { point.kind == "safety" },
                        t("backup.unchecked").takeIf { !point.checked },
                    )
                    Card {
                        Item(
                            WorldRestore.whenLabel(strings, point.createdAt, now),
                            subtitle = (listOf(WorldRestore.lossLine(strings, point)) + tags).joinToString(" · "),
                        )
                        if (vm.technical) Note("${point.name} · ${Display.bytes(strings, point.sizeBytes)}", color = colors.text3)
                        when {
                            !point.checked -> Note(t("world.not_offered"), color = colors.text3)
                            canRestore -> Presses(
                                listOf(
                                    Press(
                                        t(if (world.busy == "world:${point.backupId}") "world.working" else "world.go_back"),
                                        { asking = point },
                                        danger = true,
                                        enabled = world.busy == null && timeline.canRestore,
                                    ),
                                ),
                            )
                        }
                    }
                }
                item { Note(t("world.footer"), color = LocalColors.current.text3) }
            }
        }
        worldImportCards(
            vm, world, timeline, bedrock,
            WorldImportActions(
                pickZip = pickZip,
                pickFolder = { pickingFolder = true },
                stop = { stopping = true },
                takeHome = {
                    world.takeHome(sharedFolder(context, "world"), strings) { shareFile(context, it, strings.t("mobile.download.share_title")) }
                },
            ),
        )
    }
}
