package io.github.peyoteheadlights.mcsc.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AddServer
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.Memory
import io.github.peyoteheadlights.mcsc.core.NewServerOptions

/**
 * The "+" on All servers (pages/add-server.js and panels/newserver.js):
 * a new server (Java or Bedrock, the kinds compared, a version, name,
 * color, memory and folder, then Minecraft's rules ticked by the person),
 * one from a modpack file on the phone, or one already on the PC. Nothing
 * is started; the new server opens once it's there.
 */
@Composable
fun AddServerScreen(vm: AppViewModel, onBack: () -> Unit, onOpen: (String) -> Unit) {
    val adding = vm.adding
    val colors = LocalColors.current
    var picking by remember { mutableStateOf(false) }
    val leave = {
        adding.leave()
        onBack()
    }
    BackHandler(onBack = leave)
    LaunchedEffect(Unit) {
        if (adding.options.value == null) adding.loadOptions() else adding.resume()
    }
    LaunchedEffect(adding.opened) {
        adding.opened?.let { id ->
            onOpen(id)
            adding.openedShown()
        }
    }
    if (picking) {
        FolderPickerDialog(vm, t("mobile.add.pick_folder"), adding.parent, onPick = {
            picking = false
            adding.parent = it
            adding.typedFolder = null
        }, onDismiss = { picking = false })
    }
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.add.title"), onBack = leave) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, verticalArrangement = Gap, modifier = Modifier.padding(padding).fillMaxSize()) {
            adding.task?.let { job ->
                item { Note(t("mobile.add.working", "step" to (job.step ?: job.title)), color = colors.text, modifier = Modifier.padding(top = 8.dp)) }
                item { Note(t("mobile.add.leave_ok"), color = colors.text3) }
            }
            adding.options.problem?.let { problem -> item { ProblemNote(problem, onRetry = adding::loadOptions) } }
            val options = adding.options.value
            if (options == null) {
                if (adding.options.problem == null) item { Note(t("mobile.common.loading")) }
                return@LazyColumn
            }
            val way = adding.way
            if (way == null) {
                item { SectionTitle(t("add.ways")) }
                item {
                    Card {
                        Item(t("add.way_new"), subtitle = t("mobile.add.way_new_hint"), onClick = { adding.begin(AddServer.NEW) })
                        Item(t("add.way_modpack"), subtitle = t("mobile.add.way_modpack_hint"), onClick = { adding.begin(AddServer.MODPACK) })
                        Item(t("add.way_have"), subtitle = t("mobile.add.way_have_hint"), onClick = { adding.begin(AddServer.HAVE) })
                    }
                }
                return@LazyColumn
            }
            item {
                TextButton(onClick = adding::startOver, modifier = Modifier.padding(horizontal = 8.dp)) { Text(t("mobile.add.start_over")) }
            }
            when (way) {
                AddServer.NEW -> newServer(vm, adding, options) { picking = true }
                AddServer.MODPACK -> fromModpack(vm, adding, options) { picking = true }
                else -> alreadyThere(vm, adding, options) { picking = true }
            }
            adding.addedLines.forEach { line -> item { Note(line, color = colors.text) } }
            adding.added?.let { added ->
                item { Button(onClick = adding::openAdded) { Text(t("mobile.add.open", "name" to added.server.name)) } }
            }
            item { SaidNote(adding.said) }
        }
    }
}

private fun LazyListScope.newServer(vm: AppViewModel, adding: AddServerPages, options: NewServerOptions, onPickFolder: () -> Unit) {
    item { SectionTitle(t("new.step_edition")) }
    item {
        Card {
            for ((edition, key) in listOf("java" to "new.java", "bedrock" to "new.bedrock")) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = adding.edition == edition, onClick = { adding.pickEdition(edition) })
                    Column {
                        Text(t(key), color = LocalColors.current.text)
                        Text(t("${key}_hint"), color = LocalColors.current.text2)
                    }
                }
            }
        }
    }
    if (adding.edition == "java") {
        item { SectionTitle(t("new.step_kind")) }
        item { Note(t("new.kind_hint")) }
        for (kind in AddServer.kinds(options)) {
            item {
                Card {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(kind.name, color = LocalColors.current.text, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                            if (kind.id == options.recommended) Text(t("new.recommended"), color = LocalColors.current.success)
                        }
                        for ((label, value) in AddServer.rows(vm.strings, kind, vm.technical)) {
                            Text("$label: $value", color = LocalColors.current.text2)
                        }
                        val chosen = adding.type?.id == kind.id
                        OutlinedButton(onClick = { adding.pickType(kind) }, enabled = !chosen) { Text(t(if (chosen) "new.chosen" else "new.choose")) }
                    }
                }
            }
        }
        if (options.recommended.isNotEmpty()) {
            options.types.firstOrNull { it.id == options.recommended }?.let { item { Note(t("new.rec_why", "name" to it.name), color = LocalColors.current.text3) } }
        }
    } else {
        item { Note(t("new.bedrock_versions"), color = LocalColors.current.text3) }
    }
    val kind = adding.type ?: return
    versionStep(vm, adding)
    detailsStep(vm, adding, options, memory = AddServer.memoryShown(kind), onPickFolder = onPickFolder)
    rulesStep(vm, adding, options, kind.edition)
    item {
        val ready = AddServer.ready(adding.name, adding.folder, adding.version?.minecraft, adding.ruled)
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Gap) {
            Button(onClick = { adding.create(vm.strings) }, enabled = ready && adding.busy == null && adding.task == null) {
                Text(t(if (adding.busy == "create") "new.creating" else "new.create"))
            }
            Text(t("new.create_hint"), color = LocalColors.current.text2)
        }
    }
}

private fun LazyListScope.versionStep(vm: AppViewModel, adding: AddServerPages) {
    item { SectionTitle(t("new.step_version")) }
    item {
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                val read = adding.versions
                read.problem?.let { Text(it.text(vm.strings), color = LocalColors.current.danger) }
                val versions = read.value
                if (versions == null) {
                    if (read.problem == null) Text(t("mobile.common.loading"), color = LocalColors.current.text2)
                    return@Column
                }
                versions.source?.let { Text(t("new.version_hint", "source" to it), color = LocalColors.current.text2) }
                if (versions.snapshots) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(t("new.show_snapshots"), color = LocalColors.current.text, modifier = Modifier.weight(1f))
                        Switch(checked = adding.snapshots, onCheckedChange = adding::showSnapshots)
                    }
                }
                val choices = adding.choices()
                Picker(
                    t("new.version"),
                    adding.version?.minecraft ?: t("mobile.version.pick"),
                    choices.map { it.minecraft to if (it.stable) it.minecraft else vm.strings.t("new.snapshot_option", "version" to it.minecraft) },
                    adding::pickVersion,
                )
                val loaders = adding.version?.loaders.orEmpty()
                if (adding.type?.picksLoader == true && loaders.isNotEmpty()) {
                    Picker(t("new.loader_choice"), adding.loader ?: loaders.first(), loaders.map { it to it }, adding::pickLoader)
                    Text(t("new.loader_hint"), color = LocalColors.current.text2)
                }
            }
        }
    }
}

private fun LazyListScope.detailsStep(vm: AppViewModel, adding: AddServerPages, options: NewServerOptions, memory: Boolean, onPickFolder: () -> Unit) {
    item { SectionTitle(t("new.step_details")) }
    item {
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                OutlinedTextField(
                    value = adding.name,
                    onValueChange = { adding.name = it.take(60) },
                    label = { Text(t("add.name")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                folderField(vm, adding, t("new.folder"), t("new.folder_hint"), onPickFolder)
                if (memory) adding.memoryMb?.let { mb ->
                    Text(t("new.memory"), color = LocalColors.current.text)
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { adding.nudgeMemory(-512) }) { Text(t("mobile.add.less")) }
                        Text(Memory.gb(mb), color = LocalColors.current.text)
                        OutlinedButton(onClick = { adding.nudgeMemory(512) }) { Text(t("mobile.add.more")) }
                    }
                }
            }
            ColorPicker(options.palette.map { it.id to it.hex }, adding.color, locked = false) { adding.color = it }
        }
    }
}

@Composable
private fun folderField(vm: AppViewModel, adding: AddServerPages, label: String, hint: String, onPickFolder: () -> Unit) {
    val colors = LocalColors.current
    Text(label, color = colors.text)
    if (vm.technical) {
        OutlinedTextField(
            value = adding.typedFolder ?: adding.folder,
            onValueChange = { adding.typedFolder = it },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
    } else {
        Text(
            adding.folder.ifEmpty { vm.strings.t("mobile.add.no_folder") },
            color = if (adding.folder.isEmpty()) colors.text2 else colors.text,
        )
    }
    OutlinedButton(onClick = onPickFolder) { Text(t("mobile.add.pick_folder")) }
    Text(hint, color = colors.text2)
}

private fun LazyListScope.rulesStep(vm: AppViewModel, adding: AddServerPages, options: NewServerOptions, edition: String) {
    item { SectionTitle(t("new.step_rules")) }
    item {
        val context = LocalContext.current
        val bedrock = edition == "bedrock"
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                Text(t(if (bedrock) "new.bedrock_terms_intro" else "new.eula_intro"), color = LocalColors.current.text)
                TextButton(onClick = { openLink(context, if (bedrock) options.bedrock.eulaUrl else options.eulaUrl) }) { Text(t("new.eula_link")) }
                if (bedrock) TextButton(onClick = { openLink(context, options.bedrock.privacyUrl) }) { Text(t("new.privacy_link")) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = adding.ruled, onCheckedChange = { adding.ruled = it })
                    Text(t(AddServer.ruleKey(edition)), color = LocalColors.current.text)
                }
            }
        }
    }
}

private fun LazyListScope.fromModpack(vm: AppViewModel, adding: AddServerPages, options: NewServerOptions, onPickFolder: () -> Unit) {
    item {
        val strings = vm.strings
        val pick = rememberFilePicker { adding.inspect(it, strings) }
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                if (adding.busy == "inspect") Text(t("mobile.content.reading"), color = LocalColors.current.text2)
                OutlinedButton(onClick = pick, enabled = adding.busy == null) { Text(t("mobile.content.modpack_choose")) }
            }
        }
    }
    val inspected = adding.pack ?: return
    val pack = inspected.pack
    item {
        val strings = vm.strings
        val unknown = strings.t("value.unknown")
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                Text(t("mobile.add.pack_name", "name" to pack.name.ifBlank { unknown }), color = LocalColors.current.text, fontWeight = FontWeight.Medium)
                Text(t("pack.minecraft") + ": " + (pack.minecraftVersion ?: unknown), color = LocalColors.current.text2)
                Text(t("pack.loader") + ": " + listOfNotNull(pack.typeName, pack.loaderVersion).joinToString(" ").ifBlank { unknown }, color = LocalColors.current.text2)
                Text(t("pack.files") + ": " + t("pack.files_value", "count" to pack.downloadCount, "size" to Display.bytes(strings, pack.downloadBytes)), color = LocalColors.current.text2)
                for (problem in pack.problems) Text("• $problem", color = LocalColors.current.danger)
                if (pack.clientOnly.isNotEmpty()) Text(t("pack.client_only", "names" to pack.clientOnly.joinToString(", ")), color = LocalColors.current.text2)
            }
        }
    }
    if (!pack.canImport) return
    detailsStep(vm, adding, options, memory = true, onPickFolder = onPickFolder)
    rulesStep(vm, adding, options, "java")
    item {
        val ready = AddServer.ready(adding.name, adding.folder, pack.minecraftVersion, adding.ruled)
        Button(
            onClick = { adding.createFromPack(vm.strings) },
            enabled = ready && adding.busy == null && adding.task == null,
            modifier = Modifier.padding(horizontal = 16.dp),
        ) { Text(t(if (adding.busy == "create") "new.creating" else "new.create")) }
    }
}

private fun LazyListScope.alreadyThere(vm: AppViewModel, adding: AddServerPages, options: NewServerOptions, onPickFolder: () -> Unit) {
    item { SectionTitle(t("add.existing")) }
    item {
        Card {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Gap) {
                Text(t("add.existing_hint"), color = LocalColors.current.text2)
                OutlinedTextField(
                    value = adding.name,
                    onValueChange = { adding.name = it.take(60) },
                    label = { Text(t("add.name")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Picker(
                    t("add.kind"),
                    adding.type?.name ?: t("mobile.version.pick"),
                    options.types.map { it.id to it.name },
                ) { id -> options.types.firstOrNull { it.id == id }?.let(adding::pickType) }
                Text(t("add.kind_hint"), color = LocalColors.current.text2)
                folderField(vm, adding, t("add.folder"), t("add.existing_hint"), onPickFolder)
                if (vm.technical) {
                    OutlinedTextField(
                        value = adding.jar,
                        onValueChange = { adding.jar = it.take(180) },
                        label = { Text(t("add.jar")) },
                        supportingText = { Text(t("add.jar_hint")) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Button(
                    onClick = { adding.add(vm.strings) },
                    enabled = adding.busy == null && adding.type != null && adding.name.isNotBlank() && adding.folder.isNotBlank(),
                ) { Text(t(if (adding.busy == "add") "add.adding" else "add.submit")) }
            }
        }
    }
}
