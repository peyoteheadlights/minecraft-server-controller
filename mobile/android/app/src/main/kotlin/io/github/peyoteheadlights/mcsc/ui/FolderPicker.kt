package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.FolderListing
import io.github.peyoteheadlights.mcsc.core.FolderPicker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Reads the PC's folders for the picker. A refused folder keeps the last
 * listing on screen, with the agent's reason above it. */
class FolderBrowser(
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    var listing: Read<FolderListing> by mutableStateOf(Read())
        private set

    fun open(path: String?) {
        val c = client() ?: return
        listing = listing.copy(loading = true, problem = null)
        scope.launch {
            listing = try {
                Read(c.folders(path))
            } catch (e: AgentException) {
                noted(e)
                Read(listing.value, problem = Message.of(e))
            }
        }
    }
}

/**
 * Choose a folder on the PC (panels/folders.js): the drives and shortcuts
 * first, then tap into folders and press "Use this folder". Technical mode
 * can type a path, which the agent checks the same way. Owner only.
 */
@Composable
fun FolderPickerDialog(vm: AppViewModel, title: String, start: String?, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    val colors = LocalColors.current
    val browser = vm.folders
    var typed by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { browser.open(start?.takeIf { it.isNotBlank() }) }
    val read = browser.listing
    val listing = read.value
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState()), verticalArrangement = Gap) {
                read.problem?.let { Text(it.text(vm.strings), color = colors.danger) }
                if (listing == null) {
                    Text(t("mobile.common.loading"))
                } else {
                    Text(listing.path ?: t("folders.this_pc"), color = colors.text, fontWeight = FontWeight.Medium)
                    FolderPicker.up(listing)?.let { up -> Choice(t("folders.up")) { browser.open(up) } }
                    if (FolderPicker.atTop(listing)) {
                        for (drive in listing.drives) Choice(FolderPicker.driveName(vm.strings, drive)) { browser.open(drive.path) }
                        for (shortcut in listing.shortcuts) Choice(FolderPicker.shortcutName(vm.strings, shortcut)) { browser.open(shortcut.path) }
                    } else {
                        for (folder in listing.folders) {
                            Choice(folder.name, tag = t("folders.world").takeIf { folder.world }) { browser.open(folder.path) }
                        }
                    }
                    for (note in FolderPicker.notes(vm.strings, listing)) Text(note, color = colors.text2)
                }
                if (FolderPicker.canType(vm.technical)) {
                    OutlinedTextField(
                        value = typed,
                        onValueChange = { typed = it },
                        label = { Text(t("mobile.folders.type_path")) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    TextButton(onClick = { browser.open(typed.trim()) }, enabled = typed.isNotBlank()) { Text(t("mobile.folders.open")) }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { listing?.path?.let(onPick) },
                enabled = listing?.path != null && !read.loading,
            ) { Text(t("folders.choose")) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}

@Composable
private fun Choice(name: String, tag: String? = null, onClick: () -> Unit) {
    val colors = LocalColors.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp).clickable(onClick = onClick).padding(vertical = 6.dp),
    ) {
        Text(name, color = colors.accentInk, modifier = Modifier.weight(1f))
        tag?.let { Text(it, color = colors.text2) }
    }
}
