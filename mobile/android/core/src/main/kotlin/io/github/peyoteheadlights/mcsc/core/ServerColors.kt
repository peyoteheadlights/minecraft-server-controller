package io.github.peyoteheadlights.mcsc.core

import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A server's color carried through its whole screen, the same sums as the
 * dashboard's agent/web/js/colors.js (deriveFrom): the screen, cards and
 * sunken areas take a little of the color, buttons are filled with it, and
 * every color people read is shaded until it passes WCAG AA (4.5:1 for
 * text, 3:1 for marks). ServerColorsTest checks every palette color in
 * every theme against what colors.js itself gives (mobile/shared/color-cases.json).
 */
object ServerColors {
    const val AA_TEXT = 4.5
    const val AA_MARK = 3.0

    private val BLACK = intArrayOf(0, 0, 0)
    private val WHITE = intArrayOf(255, 255, 255)

    fun rgb(hex: String?): IntArray? {
        val text = hex?.trim()?.removePrefix("#") ?: return null
        if (!Regex("^[0-9a-fA-F]{6}$").matches(text)) return null
        val n = text.toInt(16)
        return intArrayOf((n shr 16) and 255, (n shr 8) and 255, n and 255)
    }

    fun hex(color: IntArray): String =
        "#" + color.joinToString("") { "%02X".format(it.coerceIn(0, 255)) }

    private fun channel(c: Int): Double {
        val s = c / 255.0
        return if (s <= 0.04045) s / 12.92 else ((s + 0.055) / 1.055).pow(2.4)
    }

    fun luminance(color: IntArray): Double =
        0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])

    fun contrast(a: IntArray, b: IntArray): Double {
        val la = luminance(a)
        val lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }

    /** JavaScript's Math.round: halves go up. */
    private fun jsRound(x: Double): Int = kotlin.math.floor(x + 0.5).toInt()

    fun mix(a: IntArray, b: IntArray, amount: Double): IntArray =
        IntArray(3) { i -> jsRound(a[i] + (b[i] - a[i]) * amount) }

    fun readable(color: IntArray, backgrounds: List<IntArray>, minimum: Double = AA_TEXT): IntArray {
        val darkest = backgrounds.minOf { luminance(it) }
        val target = if (darkest > 0.18) BLACK else WHITE
        for (step in 0..20) {
            val candidate = mix(color, target, step / 20.0)
            if (backgrounds.all { contrast(candidate, it) >= minimum }) return candidate
        }
        return target
    }

    data class Fill(val fill: IntArray, val text: IntArray)

    fun fillWithText(color: IntArray): Fill {
        val dark = intArrayOf(17, 17, 17)
        val text = if (contrast(color, WHITE) >= contrast(color, dark)) WHITE else dark
        val away = if (text === WHITE) BLACK else WHITE
        for (step in 0..20) {
            val fill = mix(color, away, step / 20.0)
            if (contrast(fill, text) >= AA_TEXT) return Fill(fill, text)
        }
        return Fill(away, text)
    }

    private data class Amounts(val sheet: Double, val surface: Double, val sunken: Double, val band: Double)

    private fun tintAmounts(dark: Boolean, theme: String): Amounts = when {
        theme == "contrast" -> Amounts(0.1, 0.06, 0.1, 0.2)
        dark -> Amounts(0.18, 0.13, 0.16, 0.3)
        else -> Amounts(0.2, 0.07, 0.18, 0.32)
    }

    private fun keepReadable(color: IntArray?, before: List<IntArray>, after: List<IntArray>, floor: Double = AA_TEXT): IntArray? {
        if (color == null) return null
        val was = before.minOf { contrast(color, it) }
        return readable(color, after, min(floor, was))
    }

    /**
     * Every token a server's color sets, as "#RRGGBB" (and "--accent-soft" as
     * an rgba() string), for theme [k] ("sheet" -> "#F7F7F9", without the
     * leading dashes) named [theme] ("light", "dark", "graphite", "contrast").
     */
    fun derive(baseHex: String, k: Map<String, String>, theme: String): Map<String, String>? {
        val base = rgb(baseHex) ?: return null
        val tok = { name: String -> rgb(k[name]) }
        val sheet0 = tok("sheet") ?: WHITE
        val surface0 = tok("surface") ?: WHITE
        val sunken0 = tok("surface-sunken") ?: surface0
        val float0 = tok("surface-float") ?: surface0
        val desk = tok("desk") ?: WHITE
        val dark = luminance(sheet0) < 0.18
        val amount = tintAmounts(dark, theme)
        val sheet = mix(sheet0, base, amount.sheet)
        val surface = mix(surface0, base, amount.surface)
        val sunken = mix(sunken0, base, amount.sunken)
        val float = mix(float0, base, amount.surface)
        val band = mix(sheet0, base, amount.band)
        val before = listOf(sheet0, surface0, sunken0)
        val after = listOf(sheet, surface, sunken, band)
        val textOn = { name: String -> keepReadable(tok(name), before, after) }
        val fill = fillWithText(base)
        val hover = fillWithText(mix(fill.fill, if (dark) WHITE else BLACK, 0.12))
        val ink = readable(base, listOf(surface, sheet, band))
        val ring = readable(base, listOf(surface, sheet), AA_MARK)
        val tab = mix(desk, base, if (dark) 0.32 else 0.24)
        val tokens = linkedMapOf<String, IntArray?>(
            "--sheet" to sheet, "--surface" to surface, "--surface-sunken" to sunken, "--surface-float" to float,
            "--text-primary" to textOn("text-primary"),
            "--text-secondary" to textOn("text-secondary"),
            "--text-tertiary" to textOn("text-tertiary"),
            "--success" to textOn("success"),
            "--warning" to textOn("warning"),
            "--danger" to textOn("danger"),
            "--accent" to fill.fill,
            "--accent-text" to fill.text,
            "--accent-hover" to hover.fill,
            "--accent-hover-text" to hover.text,
            "--accent-ink" to ink,
            "--accent-band" to band,
            "--accent-edge" to base,
            "--accent-ring" to ring,
            "--tab-fill" to tab,
            "--tab-text" to readable(tok("text-primary") ?: BLACK, listOf(tab)),
        )
        val out = linkedMapOf<String, String>()
        for ((name, value) in tokens) if (value != null) out[name] = hex(value)
        out["--accent-soft"] = "rgba(${base.joinToString(", ")}, ${if (dark) "0.2" else "0.13"})"
        return out
    }

    /** A server's badge: its color as a fill, with text that reads on it. */
    fun badge(baseHex: String?): Pair<String, String>? {
        val base = rgb(baseHex) ?: return null
        val f = fillWithText(base)
        return hex(f.fill) to hex(f.text)
    }

    /** The themes in mobile/shared/theme.json: name -> token -> "#RRGGBB". */
    fun parseThemes(text: String): Map<String, Map<String, String>> {
        val root = Json.parseToJsonElement(text) as JsonObject
        return root.mapValues { (_, tokens) ->
            (tokens as JsonObject).mapNotNull { (name, value) ->
                val p = value as? JsonPrimitive
                if (p != null && p.isString) name to p.content else null
            }.toMap()
        }
    }
}
