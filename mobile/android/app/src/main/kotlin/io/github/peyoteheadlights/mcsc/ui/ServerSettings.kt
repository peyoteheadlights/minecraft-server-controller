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
import io.github.peyoteheadlights.mcsc.core.ServerColors
import io.github.peyoteheadlights.mcsc.core.ServerForm

/**
 * Server settings: how Command Block runs this server (Game settings are
 * the game's own rules). Name and color, what happens after a crash,
 * sleep when empty, backups kept, and the start and stop limits. Save
 * sends only what changed; a refused value says why under its field.
 * Someone who may only look sees it all read-only.
 */
@Composable
fun ServerSettingsScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val setup = vm.pages(serverId).setup
    val strings = vm.strings
    val canEdit = ServerForm.editable(vm.me)
    LaunchedEffect(serverId) {
        setup.clearSaid()
        setup.loadSettings()
    }

    ServerFrame(
        vm, serverId,
        title = t("page.server_settings"),
        onBack = onBack,
        refreshing = setup.settings.loading,
        onRefresh = setup::loadSettings,
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
private fun ColorPicker(palette: List<Pair<String, String>>, current: String?, locked: Boolean, onPick: (String) -> Unit) {
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
