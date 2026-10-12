package io.github.peyoteheadlights.mcsc.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File

/**
 * Where a file waits for the share menu (res/xml/shared_files.xml): one
 * folder per [kind] ("world", "help"), so clearing out the last world never
 * deletes a help file another app is still reading, or the other way round.
 */
fun sharedFolder(context: Context, kind: String): File = File(File(context.cacheDir, "shared"), kind)

/**
 * Opens the phone's share menu for [file] (a world's zip, or the help file): save it to
 * Files or Drive, or send it to another app. Only the app that is picked
 * can read it, and only that once.
 */
fun shareFile(context: Context, file: File, title: String) {
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val send = Intent(Intent.ACTION_SEND)
        .setType("application/zip")
        .putExtra(Intent.EXTRA_STREAM, uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try {
        context.startActivity(Intent.createChooser(send, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (ignored: ActivityNotFoundException) {
        // No app takes a file at all: nothing to share it with.
    }
}
