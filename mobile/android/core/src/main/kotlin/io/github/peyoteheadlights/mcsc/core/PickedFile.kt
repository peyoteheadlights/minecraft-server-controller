package io.github.peyoteheadlights.mcsc.core

import java.io.InputStream
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source

/**
 * A file picked on the phone (a .jar, a pack or a modpack), read only while
 * it is sent, so a big one is never held in memory whole. [size] is null
 * when the phone doesn't say.
 */
class PickedFile(val name: String, val size: Long?, private val open: () -> InputStream) {
    /** [progress] gets the bytes sent so far and the size, when known. */
    internal fun body(progress: ((Long, Long?) -> Unit)? = null): RequestBody = object : RequestBody() {
        override fun contentType(): MediaType = OCTET_STREAM
        override fun contentLength(): Long = size ?: -1L
        override fun writeTo(sink: BufferedSink) {
            open().use { input ->
                if (progress == null) {
                    sink.writeAll(input.source())
                    return
                }
                val buffer = ByteArray(64 * 1024)
                var sent = 0L
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    sink.write(buffer, 0, n)
                    sent += n
                    progress(sent, size)
                }
            }
        }
    }

    companion object {
        private val OCTET_STREAM = "application/octet-stream".toMediaType()

        fun of(name: String, bytes: ByteArray): PickedFile = PickedFile(name, bytes.size.toLong()) { bytes.inputStream() }
    }
}
