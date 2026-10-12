package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.CpuCores
import io.github.peyoteheadlights.mcsc.core.Crossplay
import io.github.peyoteheadlights.mcsc.core.Duplicate
import io.github.peyoteheadlights.mcsc.core.Memory
import io.github.peyoteheadlights.mcsc.core.RawText
import io.github.peyoteheadlights.mcsc.core.RemoveServer
import io.github.peyoteheadlights.mcsc.core.ServerColors
import io.github.peyoteheadlights.mcsc.core.ServerForm
import io.github.peyoteheadlights.mcsc.core.VersionChange

/**
 * Server settings: how Command Block runs this server (Game settings are
 * the game's own rules). Name and color, what happens after a crash,
 * sleep when empty, backups kept, and the start and stop limits. Save
 * sends only what changed; a refused value says why under its field.
 * Someone who may only look sees it all read-only.
 */
@Composable
fun ServerSettingsScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit, onRemoved: () -> Unit) {
    val setup = vm.pages(serverId).setup
    val strings = vm.strings
    val canEdit = ServerForm.editable(vm.me)
    var asking by remember { mutableStateOf<SetupAsk?>(null) }
    LaunchedEffect(serverId) {
        setup.clearSaid()
        setup.loadSettings()
        setup.loadMemory()
        setup.loadVersion()
        setup.loadCrossplay()
        if (Duplicate.allowed(vm.me)) setup.loadCopyOptions()
    }

    ServerFrame(
        vm, serverId,
        title = t("page.server_settings"),
        onBack = onBack,
        refreshing = setup.settings.loading,
        onRefresh = {
            setup.loadSettings()
            setup.loadMemory()
            setup.loadVersion()
            setup.loadCrossplay()
        },
        overlay = {
            when (asking) {
                SetupAsk.CHANGE -> setup.report?.value?.let { checked ->
                    Confirm(
                        t("version.confirm_title", "name" to VersionChange.target(checked)), t("version.confirm_body"), t("version.confirm_button"),
                        danger = VersionChange.danger(checked),
                        onConfirm = {
                            asking = null
                            setup.changeVersion(strings)
                        },
                        onDismiss = { asking = null },
                    )
                }
                SetupAsk.ROLL_BACK -> Confirm(
                    t("version.back_title"), t("version.back_body"), t("version.back_button"), danger = false,
                    onConfirm = {
                        asking = null
                        setup.rollBack(strings)
                    },
                    onDismiss = { asking = null },
                )
                SetupAsk.CROSSPLAY_ON -> Confirm(
                    t("cross.on_title"), Crossplay.confirm(strings, setup.crossPort), t("cross.on_button"), danger = false,
                    onConfirm = {
                        asking = null
                        setup.setCrossplay(true, strings)
                    },
                    onDismiss = { asking = null },
                )
                SetupAsk.REMOVE -> Confirm(
                    t("serverset.remove_title", "name" to (vm.servers.list.firstOrNull { it.id == serverId }?.name ?: serverId)),
                    t("serverset.remove_body"), t("serverset.remove_confirm"), danger = true,
                    onConfirm = {
                        asking = null
                        setup.removeServer(strings, onRemoved)
                    },
                    onDismiss = { asking = null },
                )
                null -> Unit
            }
        },
    ) {
        val read = setup.settings
        val settings = read.value
        item { Note(t("mobile.serverset.intro"), color = LocalColors.current.text, modifier = Modifier.padding(top = 8.dp)) }
        if (!canEdit && vm.me != null) item { Note(t("mobile.serverset.read_only"), color = LocalColors.current.text3) }
        read.problem?.let { problem -> item { ProblemNote(problem, onRetry = setup::loadSettings) } }
        if (settings == null) {
            if (read.problem == null) item { Note(t("mobile.common.loading")) }
            return@ServerFrame
        }

        item { SectionTitle(t("serverset.identity")) }
        item {
            Card {
                SettingField(
                    label = t("serverset.name"),
                    kind = "text",
                    value = setup.edits[ServerForm.NAME] ?: ServerForm.initial(settings, ServerForm.NAME),
                    locked = !canEdit,
                    problem = setup.fieldProblems[ServerForm.NAME],
                ) { setup.edit(ServerForm.NAME, it.take(ServerForm.NAME_LIMIT)) }
                ColorPicker(
                    palette = settings.palette.map { it.id to it.hex },
                    current = setup.color ?: settings.color,
                    locked = !canEdit,
                    onPick = setup::pickColor,
                )
            }
        }
        for (group in ServerForm.GROUPS) {
            item { SectionTitle(t(group.titleKey)) }
            item {
                Card {
                    for (field in group.fields) {
                        SettingField(
                            label = t(field.labelKey),
                            hint = field.hintKey?.let { key ->
                                t(key, "minutes" to ServerForm.initial(settings, "monitor.crash_window_minutes"))
                            },
                            kind = field.kind,
                            value = setup.edits[field.key] ?: ServerForm.initial(settings, field.key),
                            locked = !canEdit,
                            problem = setup.fieldProblems[field.key],
                        ) { setup.edit(field.key, it) }
                    }
                    if (group.titleKey == "serverset.sleep") Note(ServerForm.sleepLine(strings, settings))
                    group.noteKey?.let { Note(t(it), color = LocalColors.current.text3) }
                }
            }
        }
        if (canEdit) {
            item {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { setup.saveSettings(strings) }, enabled = setup.busy == null) {
                        Text(t(if (setup.busy == "settings") "action.saving" else "mobile.serverset.save"))
                    }
                }
            }
        }
        item { SaidNote(setup.said) }
        item { SectionTitle(t("serverset.cpu")) }
        item { Card { CoresCard(vm, setup, canEdit) } }
        item { SectionTitle(t("version.title")) }
        item { Card { VersionCard(vm, setup, canEdit) { asking = it } } }
        item { SectionTitle(t("cross.title")) }
        item { Card { CrossplayCard(vm, setup, canEdit) { asking = it } } }
        item { SectionTitle(t("memory.title")) }
        item { Card { MemoryCard(vm, setup, canEdit, bedrock = vm.servers.list.firstOrNull { it.id == serverId }?.edition == "bedrock") } }
        setup.memory.value?.let { memory ->
            if (RawText.allowed(vm.me, vm.technical)) {
                item {
                    Card {
                        val saved = memory.jvmArgs.joinToString(" ")
                        var typed by remember(saved) { mutableStateOf(saved) }
                        RawEditor(
                            vm,
                            title = t("mobile.raw.args_title"),
                            hint = t("mobile.raw.args_hint"),
                            text = typed,
                            onText = { typed = it },
                            changes = { RawText.argChanges(memory.jvmArgs, RawText.args(typed)) },
                            busy = setup.busy != null,
                            onSave = { setup.saveJavaOptions(RawText.args(typed), strings) },
                        )
                    }
                }
            }
        }
        if (Duplicate.allowed(vm.me)) {
            item { SectionTitle(t("dup.title")) }
            item { Card { DuplicateCard(vm, setup, serverId) } }
        }
        if (RemoveServer.allowed(vm.me)) {
            item { SectionTitle(t("serverset.remove")) }
            item { Card { RemoveCard(vm, setup) { asking = it } } }
        }
    }
}

/** Which CPU cores the server may use, who else uses each, and what the
 * running server really got; or why this PC can't limit them. */
@Composable
private fun CoresCard(vm: AppViewModel, setup: SetupPages, canEdit: Boolean) {
    val colors = LocalColors.current
    val cpu = setup.settings.value?.cpu ?: return
    val count = cpu.logicalCores
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        if (!cpu.supported || count == null || count == 0) {
            Text(cpu.unsupportedReason ?: t("serverset.cpu_unreadable"), color = colors.text2)
            return@Column
        }
        val all = setup.everyCore()
        val picked = setup.pickedCores()
        val shared = CpuCores.sharedBy(cpu)
        SettingField(t("serverset.all_cores", "count" to count), "bool", all.toString(), locked = !canEdit, problem = null) {
            setup.setAllCores(it == "true")
        }
        if (!all) {
            for (core in 0 until count) {
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = core in picked, onCheckedChange = { setup.toggleCore(core) }, enabled = canEdit)
                    Column {
                        Text(t("serverset.core", "n" to core + 1), color = colors.text)
                        shared[core]?.let { Text(t("serverset.core_shared", "names" to it.joinToString(", ")), color = colors.text2) }
                    }
                }
            }
        }
        Text(CpuCores.nowLine(vm.strings, cpu), color = colors.text2, modifier = Modifier.padding(top = 8.dp))
        cpu.status.problems.firstOrNull()?.let { Text(it, color = colors.danger, modifier = Modifier.padding(top = 4.dp)) }
        if (canEdit) {
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { setup.saveCores(vm.strings) }, enabled = setup.busy == null) {
                    Text(t(if (setup.busy == "cores") "action.saving" else "action.save"))
                }
                OutlinedButton(onClick = { setup.pickHalf(count) }, enabled = setup.busy == null) { Text(t("serverset.half_cores")) }
            }
        }
    }
}

/** The memory slider: bounded by the PC's memory, with the warning when
 * every running server together may use more than the PC has. */
@Composable
private fun MemoryCard(vm: AppViewModel, setup: SetupPages, canEdit: Boolean, bedrock: Boolean) {
    val colors = LocalColors.current
    val read = setup.memory
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        read.problem?.let { Text(it.text(vm.strings), color = colors.danger) }
        val memory = read.value ?: return@Column
        Text(t("memory.label"), color = colors.text)
        Text(memory.totalMb?.let { t("memory.pc_has", "total" to Memory.gb(it)) } ?: t("memory.pc_unknown"), color = colors.text2)
        if (!Memory.slider(memory)) {
            if (!memory.takesMemoryLimit) Text(Memory.noSlider(vm.strings, memory, bedrock), color = colors.text2, modifier = Modifier.padding(top = 4.dp))
            return@Column
        }
        val chosen = setup.memoryChoice ?: Memory.start(memory)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Slider(
                value = chosen.toFloat(),
                onValueChange = setup::slideMemory,
                valueRange = memory.minMb.toFloat()..(memory.totalMb ?: memory.minMb).toFloat(),
                enabled = canEdit,
                modifier = Modifier.weight(1f),
            )
            Text(Memory.gb(chosen), color = colors.text, modifier = Modifier.padding(start = 8.dp))
        }
        Text(Memory.nowLine(vm.strings, memory), color = colors.text2)
        Memory.warning(vm.strings, memory, chosen)?.let { Text(it, color = colors.warning, modifier = Modifier.padding(top = 4.dp)) }
        if (canEdit) {
            Button(onClick = { setup.saveMemory(vm.strings) }, enabled = setup.busy == null, modifier = Modifier.padding(top = 8.dp)) {
                Text(t(if (setup.busy == "memory") "action.saving" else "memory.save"))
            }
        }
    }
}

/** One setting: a switch, or a box for a number or words. */
@Composable
fun SettingField(
    label: String,
    kind: String,
    value: String,
    locked: Boolean,
    problem: String?,
    hint: String? = null,
    onChange: (String) -> Unit,
) {
    val colors = LocalColors.current
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        if (kind == "bool") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, color = colors.text, modifier = Modifier.weight(1f))
                Switch(checked = value == "true", onCheckedChange = { onChange(it.toString()) }, enabled = !locked)
            }
        } else {
            OutlinedTextField(
                value = value,
                onValueChange = onChange,
                label = { Text(label) },
                singleLine = true,
                readOnly = locked,
                enabled = !locked,
                isError = problem != null,
                keyboardOptions = KeyboardOptions(keyboardType = if (kind == "text") KeyboardType.Text else KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        problem?.let { Text(it, color = colors.danger, modifier = Modifier.padding(top = 4.dp)) }
        hint?.takeIf { it.isNotBlank() }?.let { Text(it, color = colors.text2, modifier = Modifier.padding(top = 4.dp)) }
    }
}

/** The palette as dots, and a box for any color typed as #RRGGBB. The
 * preview is the server's badge, so its text is checked to stay readable. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ColorPicker(palette: List<Pair<String, String>>, current: String?, locked: Boolean, onPick: (String) -> Unit) {
    val colors = LocalColors.current
    var typed by remember(current) { mutableStateOf(current.orEmpty()) }
    val typedColor = ServerForm.color(typed)
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        Text(t("serverset.color"), color = colors.text)
        FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            for ((id, hex) in palette) {
                val chosen = hex.equals(current, ignoreCase = true)
                val name = t("color.$id")
                Box(
                    Modifier
                        .size(36.dp)
                        .background(hexColor(hex) ?: colors.neutral, CircleShape)
                        .border(if (chosen) 3.dp else 1.dp, if (chosen) colors.text else colors.border, CircleShape)
                        .semantics { contentDescription = name; selected = chosen }
                        .clickable(enabled = !locked) { onPick(hex) },
                )
            }
        }
        OutlinedTextField(
            value = typed,
            onValueChange = { text ->
                typed = text.take(7)
                ServerForm.color(typed)?.let(onPick)
            },
            label = { Text(t("serverset.custom_color")) },
            singleLine = true,
            readOnly = locked,
            enabled = !locked,
            isError = typed.isNotBlank() && typedColor == null,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        Text(
            t(if (typed.isNotBlank() && typedColor == null) "mobile.serverset.color_bad" else "mobile.serverset.color_hint"),
            color = if (typed.isNotBlank() && typedColor == null) colors.danger else colors.text2,
            modifier = Modifier.padding(top = 4.dp),
        )
        ServerColors.rgb(current)?.let { rgb ->
            val fill = ServerColors.fillWithText(rgb)
            Box(
                Modifier.padding(top = 8.dp).background(hexColor(ServerColors.hex(fill.fill)) ?: colors.neutral, CircleShape)
                    .padding(horizontal = 12.dp, vertical = 4.dp),
            ) { Text(current.orEmpty().uppercase(), color = hexColor(ServerColors.hex(fill.text)) ?: colors.text) }
        }
    }
}
