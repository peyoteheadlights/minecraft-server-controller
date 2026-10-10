package io.github.peyoteheadlights.mcsc.data

import io.github.peyoteheadlights.mcsc.core.AgentJson
import java.io.File
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException

/** One value kept in a file in the app's private storage, written whole
 * and replaced in one step, so a crash never leaves half a file. */
class JsonFile<T>(
    private val file: File,
    private val serializer: KSerializer<T>,
    private val empty: () -> T,
) {
    @Synchronized
    fun read(): T {
        if (!file.exists()) return empty()
        return try {
            AgentJson.decodeFromString(serializer, file.readText())
        } catch (e: SerializationException) {
            empty()
        } catch (e: IllegalArgumentException) {
            empty()
        }
    }

    @Synchronized
    fun write(value: T) {
        val part = File(file.parentFile, file.name + ".part")
        part.writeText(AgentJson.encodeToString(serializer, value))
        if (!part.renameTo(file)) {
            file.delete()
            part.renameTo(file)
        }
    }

    @Synchronized
    fun update(change: (T) -> T): T = change(read()).also(::write)
}
