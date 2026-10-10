package io.github.peyoteheadlights.mcsc.ui

import android.provider.DocumentsContract
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import java.io.OutputStream

/**
 * Asks where to save a .zip with the phone's own file picker (it can be
 * Downloads, a USB drive or a cloud app). [onPicked] gets the file to
 * write and a way to remove it again if the download doesn't finish;
 * nothing happens when the person cancels. The result starts the picker
 * with a suggested file name.
 */
@Composable
fun rememberZipSaver(onPicked: (open: () -> OutputStream?, discard: () -> Unit) -> Unit): (String) -> Unit {
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        onPicked(
            { context.contentResolver.openOutputStream(uri, "w") },
            { runCatching { DocumentsContract.deleteDocument(context.contentResolver, uri) } },
        )
    }
    return { name -> launcher.launch(name) }
}
