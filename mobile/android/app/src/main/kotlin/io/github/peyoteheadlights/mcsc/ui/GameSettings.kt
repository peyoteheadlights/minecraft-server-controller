package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.GameForm
import io.github.peyoteheadlights.mcsc.core.GameSetting
import io.github.peyoteheadlights.mcsc.core.Permissions
import io.github.peyoteheadlights.mcsc.core.RawText

/**
 * Game settings: the PC page's fields in its groups, each with its hint.
 * The seed is shown but locked once the world exists; someone who may not
 * edit settings sees them all read-only. Save sends only what changed, and
 * a refused value (a port in use, a number out of range) says why under
 * the field. Saved while running, it offers Restart now, which asks first.
 */
@Composable
fun GameSettingsScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val content = vm.pages(serverId).content
    val strings = vm.strings
    val canEdit = vm.canDo(Permissions.SETTINGS_GAME)
    var restarting by remember { mutableStateOf(false) }
    LaunchedEffect(serverId) {
        content.clearSaid()
        content.loadGame()
    }

    ServerFrame(
        vm, serverId,
        title = t("page.game_settings"),
        onBack = onBack,
        refreshing = false,
        onRefresh = content::loadGame,
        overlay = {
            if (restarting) {
                Confirm(t("confirm.restart_title"), t("confirm.restart_body"), t("action.restart"), danger = false, onConfirm = {
                    restarting = false
                    content.gameRestarted()
                    vm.act(serverId, "restart")
                }, onDismiss = { restarting = false })
            }
        },
    ) {
        val read = content.game
        val settings = read.value
        item { Note(t("game.intro"), color = LocalColors.current.text, modifier = Modifier.padding(top = 8.dp)) }
        if (!canEdit && vm.me != null) item { Note(t("mobile.game.read_only"), color = LocalColors.current.text3) }
        read.problem?.let { problem -> item { ProblemNote(problem, onRetry = content::loadGame) } }
        if (settings == null) {
            if (read.problem == null) item { Note(t("mobile.common.loading")) }
            return@ServerFrame
        }
        if (!settings.exists) item { Card { Item(t("game.no_file")) } }
        if (settings.restartNeeded) item { Note(t("game.restart_needed"), color = LocalColors.current.warning) }
        else if (settings.running && canEdit) item { Note(t("game.after_restart"), color = LocalColors.current.text3) }

        for (group in GameForm.groups(settings)) {
            item { SectionTitle(t(group.titleKey)) }
            item {
                Card {
                    for (field in group.fields) {
                        Field(vm, field, content.edits[field.key] ?: GameForm.initial(field), GameForm.locked(field, canEdit), content.fieldProblems[field.key]) {
                            content.edit(field.key, it)
                        }
                    }
                }
            }
        }
        if (canEdit) {
            item {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { content.saveGame(strings) }, enabled = content.busy == null && content.gameChanged()) {
                        Text(t(if (content.busy == "game") "action.saving" else "game.save"))
                    }
                }
            }
            item { Note(t("game.copy_kept"), color = LocalColors.current.text3) }
        }
        if (canEdit && RawText.allowed(vm.me, vm.technical, Permissions.SETTINGS_GAME) && settings.exists) {
            item { SectionTitle(t("game.raw_title")) }
            item {
                Card {
                    var typed by remember(settings.text) { mutableStateOf(settings.text) }
                    RawEditor(
                        vm,
                        title = t("game.raw_label"),
                        hint = t("game.raw_hint", "file" to settings.file),
                        text = typed,
                        onText = { typed = it },
                        changes = { RawText.propertyChanges(settings.text, typed) },
                        busy = content.busy != null,
                        onSave = { content.saveGameText(typed, strings) },
                    )
                }
            }
        }
        item { SaidNote(content.said) }
        if (content.gameRestart && vm.canControl()) {
            item { Presses(listOf(Press(t("action.restart_now"), { restarting = true }))) }
        }
    }
}

/** One setting: a switch, choices, or a box for a number or words. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Field(vm: AppViewModel, field: GameSetting, value: String, locked: Boolean, problem: String?, onChange: (String) -> Unit) {
    val colors = LocalColors.current
    val strings = vm.strings
    val label = GameForm.LABELS[field.key]?.first?.let { t(it) } ?: field.key
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        when (field.kind) {
            "bool" -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, color = colors.text, modifier = Modifier.weight(1f))
                Switch(checked = value == "true", onCheckedChange = { onChange(it.toString()) }, enabled = !locked)
            }
            "choice" -> {
                Text(label, color = colors.text)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (choice in field.choices) {
                        FilterChip(
                            selected = value == choice,
                            onClick = { onChange(choice) },
                            enabled = !locked,
                            label = { Text(GameForm.choiceLabel(strings, choice)) },
                        )
                    }
                }
            }
            else -> OutlinedTextField(
                value = value,
                onValueChange = { typed -> onChange(field.maxLength?.let { typed.take(it) } ?: typed) },
                label = { Text(label) },
                singleLine = true,
                readOnly = locked,
                enabled = !locked,
                isError = problem != null,
                keyboardOptions = KeyboardOptions(keyboardType = if (field.kind == "int" || field.kind == "port") KeyboardType.Number else KeyboardType.Text),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        problem?.let { Text(it, color = colors.danger, modifier = Modifier.padding(top = 4.dp)) }
        GameForm.fileProblem(strings, field)?.let { Text(it, color = colors.warning, modifier = Modifier.padding(top = 4.dp)) }
        GameForm.hint(strings, field).takeIf { it.isNotBlank() }?.let { Text(it, color = colors.text2, modifier = Modifier.padding(top = 4.dp)) }
    }
}
