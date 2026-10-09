package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The app tints a server's screens with exactly the colors the dashboard
 * does: every palette color in every theme, against colors.js's own output. */
class ServerColorsTest {
    private val themes = ServerColors.parseThemes(Shared.text("theme.json"))

    @Test
    fun `every color in every theme matches the dashboard`() {
        val cases = AgentJson.parseToJsonElement(Shared.text("color-cases.json")) as JsonArray
        assertTrue(cases.size >= 40)
        for (case in cases) {
            val o = case.jsonObject
            val theme = o.getValue("theme").jsonPrimitive.content
            val base = o.getValue("base").jsonPrimitive.content
            val expected = o.getValue("tokens").jsonObject.mapValues { it.value.jsonPrimitive.content }
            val tokens = themes.getValue(theme).mapKeys { it.key.removePrefix("--") }
            assertEquals("$theme $base", expected, ServerColors.derive(base, tokens, theme))
        }
    }

    @Test
    fun `colors people read pass WCAG AA`() {
        for ((theme, raw) in themes) {
            val tokens = raw.mapKeys { it.key.removePrefix("--") }
            for (base in listOf("#FFFF00", "#000000", "#FFFFFF", "#7F7F7F", "#1967D4")) {
                val out = ServerColors.derive(base, tokens, theme)!!
                val c = { name: String -> ServerColors.rgb(out.getValue(name))!! }
                for (bg in listOf("--surface", "--sheet")) {
                    assertTrue("$theme $base text on $bg", ServerColors.contrast(c("--accent-ink"), c(bg)) >= 4.5)
                }
                assertTrue("$theme $base button", ServerColors.contrast(c("--accent"), c("--accent-text")) >= 4.5)
            }
        }
    }

    @Test
    fun `a color that isn't one is ignored`() {
        assertNull(ServerColors.derive("red", emptyMap(), "light"))
        assertNull(ServerColors.badge(null))
        assertEquals("#FFFFFF" to "#111111", ServerColors.badge("#ffffff"))
    }
}
