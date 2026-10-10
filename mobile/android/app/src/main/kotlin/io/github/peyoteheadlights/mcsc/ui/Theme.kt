package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import io.github.peyoteheadlights.mcsc.core.ServerColors
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.Tone
import io.github.peyoteheadlights.mcsc.data.SharedData

/** The dashboard's color tokens (agent/web/styles.css), tinted with a
 * server's color on its screens exactly as the dashboard tints its pages. */
@Immutable
data class McscColors(
    val dark: Boolean,
    val desk: Color,
    val sheet: Color,
    val surface: Color,
    val sunken: Color,
    val float: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    val accent: Color,
    val accentText: Color,
    val accentInk: Color,
    val accentBand: Color,
    val success: Color,
    val warning: Color,
    val danger: Color,
    val neutral: Color,
    val border: Color,
) {
    fun tone(tone: Tone): Color = when (tone) {
        Tone.SUCCESS -> success
        Tone.WARNING -> warning
        Tone.DANGER -> danger
        Tone.NEUTRAL -> text2
    }
}

fun hexColor(hex: String?): Color? = ServerColors.rgb(hex)?.let { Color(it[0], it[1], it[2]) }

fun colorsFor(tokens: Map<String, String>, tint: Map<String, String>?): McscColors {
    fun c(name: String): Color = hexColor(tint?.get("--$name") ?: tokens[name]) ?: Color.Gray
    val sheet = c("sheet")
    val dark = ServerColors.luminance(ServerColors.rgb(tint?.get("--sheet") ?: tokens["sheet"]) ?: intArrayOf(255, 255, 255)) < 0.18
    val text = c("text-primary")
    return McscColors(
        dark = dark,
        desk = c("desk"),
        sheet = sheet,
        surface = c("surface"),
        sunken = c("surface-sunken"),
        float = c("surface-float"),
        text = text,
        text2 = c("text-secondary"),
        text3 = c("text-tertiary"),
        accent = c("accent"),
        accentText = c("accent-text"),
        accentInk = c("accent-ink"),
        accentBand = c("accent-band"),
        success = c("success"),
        warning = c("warning"),
        danger = c("danger"),
        neutral = c("neutral"),
        border = text.copy(alpha = if (dark) 0.14f else 0.12f),
    )
}

val LocalColors = staticCompositionLocalOf<McscColors> { error("McscTheme is missing") }
val LocalStrings = staticCompositionLocalOf<Strings> { error("McscTheme is missing") }

/** The dashboard's theme name for the person's choice ("system" follows the phone). */
@Composable
fun themeName(choice: String): String =
    if (choice == "system") (if (isSystemInDarkTheme()) "dark" else "light") else choice

@Composable
fun McscTheme(shared: SharedData, theme: String, serverColor: String? = null, content: @Composable () -> Unit) {
    val tokens = remember(shared, theme) { shared.theme(theme) }
    val colors = remember(tokens, theme, serverColor) {
        colorsFor(tokens, serverColor?.let { ServerColors.derive(it, tokens, theme) })
    }
    val scheme = if (colors.dark) {
        darkColorScheme(
            primary = colors.accent, onPrimary = colors.accentText,
            secondary = colors.accentInk, onSecondary = colors.sheet,
            background = colors.sheet, onBackground = colors.text,
            surface = colors.sheet, onSurface = colors.text,
            surfaceVariant = colors.sunken, onSurfaceVariant = colors.text2,
            surfaceContainer = colors.surface, surfaceContainerLow = colors.surface,
            surfaceContainerHigh = colors.float, surfaceContainerHighest = colors.float,
            surfaceContainerLowest = colors.sunken,
            outline = colors.border, outlineVariant = colors.border,
            error = colors.danger, onError = colors.sheet,
            secondaryContainer = colors.accentBand, onSecondaryContainer = colors.text,
        )
    } else {
        lightColorScheme(
            primary = colors.accent, onPrimary = colors.accentText,
            secondary = colors.accentInk, onSecondary = colors.surface,
            background = colors.sheet, onBackground = colors.text,
            surface = colors.sheet, onSurface = colors.text,
            surfaceVariant = colors.sunken, onSurfaceVariant = colors.text2,
            surfaceContainer = colors.surface, surfaceContainerLow = colors.surface,
            surfaceContainerHigh = colors.float, surfaceContainerHighest = colors.float,
            surfaceContainerLowest = colors.surface,
            outline = colors.border, outlineVariant = colors.border,
            error = colors.danger, onError = colors.surface,
            secondaryContainer = colors.accentBand, onSecondaryContainer = colors.text,
        )
    }
    CompositionLocalProvider(LocalColors provides colors) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}

/** A word from mobile/shared/strings.json, in Simple or Technical wording. */
@Composable
fun t(key: String, vararg values: Pair<String, Any?>): String = LocalStrings.current.t(key, *values)

@Composable
fun Message.text(): String = text(LocalStrings.current)
