package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.FolderPicker
import io.github.peyoteheadlights.mcsc.core.WorldImport
import io.github.peyoteheadlights.mcsc.core.WorldRead
import io.github.peyoteheadlights.mcsc.core.WorldTimeline

/** What the World page's import and download cards need from the screen. */
class WorldImportActions(
    val pickZip: () -> Unit,
    val pickFolder: () -> Unit,
    val stop: () -> Unit,
    val takeHome: () -> Unit,
)

/**
 * "Bring a world in" (a zip from the phone, a folder on the PC or one of
 * single-player's saves) and "Take the world home" (world.js). Each card
 * shows only to someone allowed to use it.
 */
fun LazyListScope.worldImportCards(
    vm: AppViewModel,
    world: WorldPages,
    timeline: WorldTimeline?,
    bedrock: Boolean,
    actions: WorldImportActions,
) {
    val strings = vm.strings
    if (WorldImport.canImport(vm.me) && timeline != null) {
        item { SectionTitle(t("import.title")) }
        item {
            val colors = LocalColors.current
            val blocked = WorldImport.blocked(strings, timeline)
            val free = blocked == null && world.busy == null
            Card {
                Note(t(if (bedrock) "import.lead_bedrock" else "import.lead"), color = colors.text, modifier = Modifier.padding(top = 10.dp))
                if (blocked != null) Note(blocked, color = colors.warning)
                world.sending?.let { (name, done, size) ->
                    val part = if (size != null && size > 0) " ${done * 100 / size}%" else " " + Display.bytes(strings, done)
                    Note(t("mobile.import.sending", "name" to name) + part)
                }
                if (world.busy == "import" && world.sending == null) Note(t("import.reading"))
                Presses(
                    when {
                        world.sending != null -> listOf(Press(t("action.cancel"), world::cancelSending))
                        timeline.serverRunning && vm.canControl() -> listOf(Press(t("mobile.import.stop_ask"), actions.stop, danger = true))
                        else -> listOfNotNull(
                            Press(t(if (bedrock) "import.choose_mcworld" else "import.choose_zip"), actions.pickZip, enabled = free),
                            Press(t("import.choose_folder"), actions.pickFolder, enabled = free).takeIf { FolderPicker.allowed(vm.me) },
                        )
                    },
                )
            }
        }
        // Single-player's saves folder holds Java worlds; Bedrock keeps its own.
        val saves = world.saves?.worlds.orEmpty()
        if (!bedrock && saves.isNotEmpty()) {
            item { SectionTitle(t("import.from_saves")) }
            item {
                val now = rememberNow()
                val free = WorldImport.blocked(strings, timeline) == null && world.busy == null
                Card {
                    for (save in saves) {
                        Item(save.folder, subtitle = Display.ago(strings, save.modified, now))
                        Presses(listOf(Press(t("import.use"), { world.pickWorldFolder(save.path, strings) }, enabled = free)))
                    }
                }
            }
        }
    }
    if (WorldImport.canDownload(vm.me)) {
        item { SectionTitle(t("download.title")) }
        item {
            val colors = LocalColors.current
            Card {
                Note(t(if (bedrock) "download.lead_bedrock" else "download.lead"), color = colors.text, modifier = Modifier.padding(top = 10.dp))
                world.downloading?.let { (name, done, size) ->
                    val part = if (size != null && size > 0) " ${done * 100 / size}%" else " " + Display.bytes(strings, done)
                    Note(t("mobile.backups.downloading", "name" to name) + part)
                }
                Presses(
                    listOf(
                        Press(
                            t(if (world.busy == "take_home" && world.downloading == null) "download.packing" else "download.button"),
                            actions.takeHome,
                            enabled = world.busy == null,
                        ),
                    ),
                )
            }
        }
    }
}

/** The world read, shown before it replaces anything; Cancel forgets it on the agent. */
@Composable
fun WorldReadDialog(vm: AppViewModel, read: WorldRead, onReplace: () -> Unit, onCancel: () -> Unit) {
    val colors = LocalColors.current
    val strings = vm.strings
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(t("import.confirm_title", "name" to WorldImport.title(read))) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Gap) {
                for ((label, value) in WorldImport.facts(strings, read.world)) Text("$label: $value", color = colors.text)
                for (line in WorldImport.lines(strings, read)) Text(line.text, color = colors.tone(line.tone))
                Text(t("import.confirm_body"), color = colors.text2)
            }
        },
        confirmButton = {
            TextButton(
                onClick = onReplace,
                enabled = WorldImport.canUse(read),
                colors = ButtonDefaults.textButtonColors(contentColor = colors.danger),
            ) { Text(t("import.confirm_action")) }
        },
        dismissButton = { TextButton(onClick = onCancel) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}
