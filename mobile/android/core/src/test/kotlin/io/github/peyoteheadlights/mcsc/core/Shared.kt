package io.github.peyoteheadlights.mcsc.core

import java.io.File

/** The files mobile/tools/generate.py writes, which both apps bundle. */
object Shared {
    private val dir = File(System.getProperty("mcsc.shared") ?: "../../shared")

    fun text(name: String): String = File(dir, name).readText()

    val strings: Map<String, List<String>> by lazy { Strings.parse(text("strings.json")) }
}
