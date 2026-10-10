package io.github.peyoteheadlights.mcsc.core

import java.io.File
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StringsTest {
    @Test
    fun `every key the app uses is in the table`() {
        val keys = Regex("\"((?:mobile|state|time|value|servers|hero|action|confirm|error|feed|theme|mode|login|page)\\.[a-z0-9_.]+)\"")
        val roots = listOf(File("src/main"), File("../app/src/main")).filter { it.exists() }
        val used = roots.flatMap { root ->
            root.walk().filter { it.extension == "kt" }.flatMap { file -> keys.findAll(file.readText()).map { it.groupValues[1] } }
        }.filterNot { it.endsWith(".json") }.toSet()
        assertTrue(used.size > 20)
        val missing = used.filterNot { it in Shared.strings }
        assertEquals("missing from strings.json", emptyList<String>(), missing.sorted())
    }

    @Test
    fun `keys the app builds from parts are in the table`() {
        val built = listOf("start", "stop", "restart").flatMap { listOf("action.$it", "mobile.server.done_$it") } +
            listOf("stop", "restart").flatMap { listOf("confirm.${it}_title", "confirm.${it}_body") } +
            listOf("pairing", "unreachable", "certificate", "alerts", "signout")
                .flatMap { listOf("mobile.help.${it}_title", "mobile.help.${it}_body") } +
            listOf("system", "light", "dark", "graphite", "contrast").map { "theme.$it" }
        assertEquals(emptyList<String>(), built.filterNot { it in Shared.strings })
    }

    @Test
    fun `both wordings exist and the app's keys are its own`() {
        val app = AgentJson.parseToJsonElement(File("../../app-strings.json").readText()).jsonObject
        for (key in app.keys) {
            assertTrue(key, key.startsWith("mobile."))
            assertEquals(key, 2, Shared.strings.getValue(key).size)
        }
        val s = Strings(Shared.strings)
        assertEquals("Players not known", s.t("overview.players_unknown"))
        s.technical = true
        assertEquals("Player list not read", s.t("overview.players_unknown"))
    }

    @Test
    fun `values fill in, translations fall back to English`() {
        val s = Strings(
            mapOf("a" to listOf("Up for {duration}", "Up {duration}"), "b" to listOf("Hi", "Hi")),
            mapOf("a" to listOf("Seit {duration}", "Seit {duration}"), "b" to listOf("", "")),
        )
        assertEquals("Seit 5m", s.t("a", "duration" to "5m"))
        assertEquals("Hi", s.t("b"))
        assertEquals("nope", s.t("nope"))
        assertEquals("1 player online", Strings(Shared.strings).tn("head.players", 1))
    }

    @Test
    fun `every alert kind has its words`() {
        val feed = AgentJson.parseToJsonElement(Shared.text("feed.json")).jsonObject
        assertTrue(feed.size > 10)
        for ((event, key) in feed) {
            val k = (key as kotlinx.serialization.json.JsonPrimitive).content
            assertTrue("$event -> $k", k in Shared.strings)
        }
    }
}
