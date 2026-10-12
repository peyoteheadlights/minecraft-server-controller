package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.VersionChange

/** What Server settings asks to confirm. */
enum class SetupAsk { CHANGE, ROLL_BACK, CROSSPLAY_ON, REMOVE }

/**
 * The server's kind and version as its console said them, the EULA when
 * the server needs it, and changing the version or kind: checked first,
 * one confirmation, then a task the phone can leave and come back to.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun VersionCard(vm: AppViewModel, setup: SetupPages, canEdit: Boolean, ask: (SetupAsk) -> Unit) {
    val colors = LocalColors.current
    val strings = vm.strings
    val context = LocalContext.current
    val read = setup.version
    var open by remember { mutableStateOf(false) }
    var eulaTicked by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Gap) {
        read.problem?.let { Text(it.text(strings), color = colors.danger) }
        val version = read.value ?: return@Column
        Text(t("version.kind") + ": " + version.capabilities.name.ifBlank { version.type }, color = colors.text)
        Text(t("version.minecraft") + ": " + (version.minecraftVersion ?: t("value.unknown")), color = colors.text)
        if (version.loaderName != null) Text(version.loaderName + ": " + (version.loaderVersion ?: t("value.unknown")), color = colors.text2)
        if (vm.technical) version.minecraftVersionSource?.let { Text(t("version.seen_in") + ": " + it, color = colors.text2) }
        if (version.minecraftVersion == null) Text(t("version.not_seen_yet"), color = colors.text2)
        if (version.detectedType != null && version.detectedType != version.type) {
            Text(t("version.type_disagrees", "console" to version.detectedType, "set" to version.capabilities.name), color = colors.warning)
        }
        VersionChange.pending(version)?.let { pending ->
            Text(t("version.pending", "version" to pending) + " " + t("version.pending_note"), color = colors.text2)
        }

        if (VersionChange.eulaNeeded(version)) {
            Text(t("version.eula_needed"), color = colors.warning)
            if (canEdit) {
                TextButton(onClick = { openLink(context, version.eulaUrl) }) { Text(t("new.eula_link")) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = eulaTicked, onCheckedChange = { eulaTicked = it })
                    Text(t("new.eula_tick"), color = colors.text)
                }
                Button(onClick = { setup.acceptEula(strings) }, enabled = eulaTicked && setup.busy == null) {
                    Text(t(if (setup.busy == "eula") "version.accepting" else "version.eula_accept"))
                }
            }
        }

        val task = setup.task
        if (task != null || setup.busy == "version" || setup.busy == "roll_back") {
            Text(task?.step?.let { t("mobile.version.working", "step" to it) } ?: t("mobile.version.working_plain"), color = colors.text)
            Text(t("mobile.version.leave_ok"), color = colors.text2)
        }

        version.lastChange?.let { last ->
            val at = last.at ?: return@let
            Text(
                t("version.last_change", "what" to listOfNotNull(last.type, last.minecraftVersion).joinToString(" "),
                    "when" to Display.dateTime(strings, at)),
                color = colors.text2,
            )
        }
        if (canEdit && VersionChange.canRollBack(version)) {
            OutlinedButton(onClick = { ask(SetupAsk.ROLL_BACK) }, enabled = setup.busy == null && task == null) { Text(t("version.back")) }
        }

        if (!canEdit) return@Column
        TextButton(onClick = {
            open = !open
            if (open) setup.openChanger()
        }) { Text(t("version.change_opener")) }
        if (!open) return@Column

        Text(t("version.change_kind"), color = colors.text)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (type in setup.types) {
                FilterChip(selected = type.id == setup.pickedType, onClick = { setup.pickType(type.id) }, label = { Text(type.name) })
            }
        }
        Text(t(if (version.capabilities.edition == "bedrock") "version.only_bedrock" else "version.only_java"), color = colors.text2)
        val offered = setup.versions
        offered.problem?.let { Text(it.text(strings), color = colors.danger) }
        val list = offered.value
        if (offered.loading) Text(t("mobile.common.loading"), color = colors.text2)
        if (list != null) {
            list.sourceProblem?.let { Text(it, color = colors.warning) }
            if (list.latestOnly) Text(t("new.bedrock_versions"), color = colors.text2)
            if (list.snapshots) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(t("new.show_snapshots"), color = colors.text, modifier = Modifier.weight(1f))
                    Switch(checked = setup.snapshots, onCheckedChange = setup::showSnapshots)
                }
            }
            val choices = VersionChange.choices(list, setup.snapshots)
            Picker(
                label = t("version.change_to"),
                shown = setup.pickedVersion?.let { picked ->
                    if (choices.firstOrNull { it.minecraft == picked }?.stable == false) t("new.snapshot_option", "version" to picked) else picked
                } ?: t("mobile.version.pick"),
                options = choices.map { it.minecraft to if (it.stable) it.minecraft else t("new.snapshot_option", "version" to it.minecraft) },
                onPick = setup::pickVersion,
            )
            val loaders = list.versions.firstOrNull { it.minecraft == setup.pickedVersion }?.loaders.orEmpty()
            if (vm.technical && loaders.isNotEmpty()) {
                Picker(t("version.loader_pick"), setup.pickedLoader ?: loaders.first(), loaders.map { it to it }, setup::pickLoader)
            }
        }
        val report = setup.report
        report?.problem?.let { Text(it.text(strings), color = colors.danger) }
        report?.value?.let { checked ->
            Text(t("version.after") + ": " + VersionChange.target(checked), color = colors.text)
            checked.javaRequired?.let { Text(t("version.java_needed") + ": Java $it", color = colors.text2) }
            if (vm.technical) checked.java.detail?.let { Text(t("version.java_here") + ": " + it, color = colors.text2) }
            for (line in VersionChange.lines(strings, checked)) Text(line.text, color = colors.tone(line.tone))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = setup::check, enabled = setup.pickedVersion != null && report?.loading != true && setup.busy == null) {
                Text(t(if (report?.loading == true) "version.checking" else "version.check"))
            }
            Button(onClick = { ask(SetupAsk.CHANGE) }, enabled = report?.value != null && setup.busy == null && task == null) {
                Text(t(if (setup.busy == "version") "version.changing" else "version.change"))
            }
        }
    }
}

/** A button showing the pick, opening the list to choose from. */
@Composable
internal fun Picker(label: String, shown: String, options: List<Pair<String, String>>, onPick: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(label, color = LocalColors.current.text)
        Box {
            OutlinedButton(onClick = { expanded = true }) { Text(shown) }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                for ((value, words) in options) {
                    DropdownMenuItem(text = { Text(words) }, onClick = {
                        expanded = false
                        onPick(value)
                    })
                }
            }
        }
    }
}
