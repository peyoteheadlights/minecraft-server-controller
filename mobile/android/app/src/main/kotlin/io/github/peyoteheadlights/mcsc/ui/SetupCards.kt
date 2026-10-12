package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.material3.LocalTextStyle
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Crossplay
import io.github.peyoteheadlights.mcsc.core.Duplicate
import io.github.peyoteheadlights.mcsc.core.RawChange
import io.github.peyoteheadlights.mcsc.core.RawText
import io.github.peyoteheadlights.mcsc.core.RemoveServer

/** "Let Bedrock players join": its state, the port, and the agent's reason
 * when this kind of server can't have it. */
@Composable
fun CrossplayCard(vm: AppViewModel, setup: SetupPages, canEdit: Boolean, ask: (SetupAsk) -> Unit) {
    val colors = LocalColors.current
    val read = setup.crossplay
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Gap) {
        read.problem?.let { Text(it.text(vm.strings), color = colors.danger) }
        val info = read.value ?: return@Column
        Crossplay.whyNot(vm.strings, info)?.let { why ->
            Text(why, color = colors.text2)
            Text(t("cross.switch_type"), color = colors.text2)
            return@Column
        }
        Text(t("cross.what"), color = colors.text2)
        info.missingMod?.let { Text(t("cross.needs_mod", "mod" to it), color = colors.warning) }
        if (info.enabled) {
            Text(t("cross.address") + ": " + (info.address ?: t("value.unknown")), color = colors.text)
            info.addressUnknown?.let { Text(it, color = colors.text2) }
            Text(t("cross.ready") + ": " + Crossplay.ready(vm.strings, info), color = colors.text)
            Text(t("cross.names") + ": " + t("cross.names_value", "prefix" to info.usernamePrefix), color = colors.text2)
        } else {
            OutlinedTextField(
                value = setup.crossPort,
                onValueChange = setup::typePort,
                label = { Text(t("cross.port")) },
                singleLine = true,
                enabled = canEdit,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
            Text(t("cross.port_hint"), color = colors.text2)
        }
        if (canEdit) {
            if (info.enabled) {
                OutlinedButton(onClick = { setup.setCrossplay(false, vm.strings) }, enabled = setup.busy == null) {
                    Text(t(if (setup.busy == "crossplay") "cross.turning_off" else "cross.turn_off"))
                }
            } else {
                Button(onClick = { ask(SetupAsk.CROSSPLAY_ON) }, enabled = setup.busy == null) {
                    Text(t(if (setup.busy == "crossplay") "cross.turning_on" else "cross.turn_on"))
                }
            }
            Text(t("cross.stopped_first"), color = colors.text2)
        }
        if (info.differences.isNotEmpty()) {
            Text(t("cross.differences"), color = colors.text)
            for (line in info.differences) Text("• $line", color = colors.text2)
        }
    }
}

/** Duplicate: a copy with its own port and color; the world copied or
 * fresh. Runs as a task; the copy joins All servers when it is checked. */
@Composable
fun DuplicateCard(vm: AppViewModel, setup: SetupPages, serverId: String) {
    val colors = LocalColors.current
    val read = setup.copyOptions
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Gap) {
        Text(t("dup.intro"), color = colors.text2)
        read.problem?.let { Text(it.text(vm.strings), color = colors.danger) }
        val options = read.value ?: return@Column
        OutlinedTextField(
            value = setup.copyName,
            onValueChange = setup::nameCopy,
            label = { Text(t("dup.name")) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        // The folder is the agent's suggestion next to this one; typing a
        // path of your own is for Technical mode.
        OutlinedTextField(
            value = setup.copyFolder,
            onValueChange = setup::placeCopy,
            label = { Text(t("dup.folder")) },
            singleLine = true,
            readOnly = !vm.technical,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(t("dup.folder_hint"), color = colors.text2)
        Text(t("dup.world"), color = colors.text)
        for (world in Duplicate.worlds(options)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = setup.copyWorld == world, onClick = { setup.pickCopyWorld(world) })
                Column {
                    Text(t("dup.world_$world"), color = colors.text)
                    Text(t("dup.world_${world}_hint"), color = colors.text2)
                }
            }
        }
        if (options.running) Text(t("dup.running"), color = colors.text2)
        if (options.crossplay) Text(t("dup.crossplay"), color = colors.text2)
        Duplicate.progress(setup.copying, serverId)?.let { Text(t("mobile.version.working", "step" to it), color = colors.text) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { setup.duplicate(vm.strings) },
                enabled = setup.busy == null && setup.copying == null && Duplicate.ready(setup.copyName, setup.copyFolder),
            ) { Text(t(if (setup.busy == "duplicate") "dup.starting" else "dup.button")) }
        }
    }
}

/** Remove server: off the list, its folder, world and backups stay. Never
 * the last server: the button is off with the reason under the heading. */
@Composable
fun RemoveCard(vm: AppViewModel, setup: SetupPages, onAsk: (SetupAsk) -> Unit) {
    val colors = LocalColors.current
    val count = vm.servers.list.size
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Gap) {
        Text(RemoveServer.hint(vm.strings, count), color = colors.text2)
        OutlinedButton(
            onClick = { onAsk(SetupAsk.REMOVE) },
            enabled = setup.busy == null && RemoveServer.blocked(vm.strings, count) == null,
        ) { Text(t("serverset.remove_button"), color = colors.danger) }
    }
}

/**
 * A Technical mode text editor. "Check changes" lists what will change
 * (added, removed, changed, with old and new values) before anything is
 * saved; [changes] is computed from the saved text and the typed text.
 */
@Composable
fun RawEditor(
    vm: AppViewModel,
    title: String,
    hint: String,
    text: String,
    onText: (String) -> Unit,
    changes: () -> List<RawChange>,
    busy: Boolean,
    onSave: () -> Unit,
) {
    val colors = LocalColors.current
    var review by remember { mutableStateOf<List<RawChange>?>(null) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Gap) {
        Text(title, color = colors.text)
        Text(hint, color = colors.text2)
        OutlinedTextField(
            value = text,
            onValueChange = {
                review = null
                onText(it)
            },
            textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace),
            minLines = 6,
            modifier = Modifier.fillMaxWidth(),
        )
        val listed = review
        if (listed == null) {
            OutlinedButton(onClick = { review = changes() }, enabled = !busy) { Text(t("mobile.raw.check")) }
        } else if (listed.isEmpty()) {
            Text(t("mobile.raw.nothing"), color = colors.text2)
        } else {
            Text(t("mobile.raw.will_change"), color = colors.text)
            for (change in listed) Text(RawText.line(vm.strings, change), color = colors.text, fontFamily = FontFamily.Monospace)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    review = null
                    onSave()
                }, enabled = !busy) { Text(t("mobile.raw.save")) }
                OutlinedButton(onClick = { review = null }) { Text(t("mobile.raw.edit_more")) }
            }
        }
    }
}

