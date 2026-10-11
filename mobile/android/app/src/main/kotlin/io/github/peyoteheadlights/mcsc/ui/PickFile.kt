package io.github.peyoteheadlights.mcsc.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import io.github.peyoteheadlights.mcsc.core.PickedFile
import java.io.FileNotFoundException

/**
 * Picks a file with the phone's own picker (its storage, Downloads or a
 * cloud app). [onPicked] gets it with its name and size, read only while
 * it's sent; nothing happens when the person cancels. Any kind of file can
 * be picked, since phones rarely know a .jar or .mcpack, so the screen
 * checks the name and the agent checks the file.
 */
@Composable
fun rememberFilePicker(onPicked: (PickedFile) -> Unit): () -> Unit {
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        var name = uri.lastPathSegment ?: "file"
        var size: Long? = null
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { row ->
            if (row.moveToFirst()) {
                row.getString(0)?.let { name = it }
                if (!row.isNull(1)) size = row.getLong(1)
            }
        }
        onPicked(PickedFile(name, size) { context.contentResolver.openInputStream(uri) ?: throw FileNotFoundException(name) })
    }
    return { launcher.launch(arrayOf("*/*")) }
}
