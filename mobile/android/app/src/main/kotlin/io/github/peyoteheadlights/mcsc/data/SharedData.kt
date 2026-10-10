package io.github.peyoteheadlights.mcsc.data

import android.content.res.AssetManager
import io.github.peyoteheadlights.mcsc.core.AgentJson
import io.github.peyoteheadlights.mcsc.core.ApiRange
import io.github.peyoteheadlights.mcsc.core.ServerColors
import io.github.peyoteheadlights.mcsc.core.Strings
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** mobile/shared, bundled as the app's assets: the dashboard's words,
 * themes and alert names, and which agent API versions this app speaks. */
class SharedData(
    val english: Map<String, List<String>>,
    val themes: Map<String, Map<String, String>>,
    val feed: Map<String, String>,
    val apiRange: ApiRange,
    val appVersion: String,
) {
    /** A theme's tokens without the leading dashes ("sheet" -> "#F7F7F9"). */
    fun theme(name: String): Map<String, String> =
        (themes[name] ?: themes.getValue("light")).mapKeys { it.key.removePrefix("--") }

    companion object {
        fun load(assets: AssetManager): SharedData {
            fun read(name: String) = assets.open(name).bufferedReader().use { it.readText() }
            val version = AgentJson.parseToJsonElement(read("version.json")).jsonObject
            val api = version.getValue("agent_api").jsonObject
            val feed = AgentJson.parseToJsonElement(read("feed.json")).jsonObject
                .mapValues { it.value.jsonPrimitive.content }
            return SharedData(
                english = Strings.parse(read("strings.json")),
                themes = ServerColors.parseThemes(read("theme.json")),
                feed = feed,
                apiRange = ApiRange(api.getValue("min").jsonPrimitive.int, api.getValue("max").jsonPrimitive.int),
                appVersion = version.getValue("app_version").jsonPrimitive.content,
            )
        }
    }
}
