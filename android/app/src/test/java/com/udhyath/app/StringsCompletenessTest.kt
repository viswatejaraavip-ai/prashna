package com.udhyath.app

import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Every user-visible string must exist in all five UI languages. Fails if a
 * key (or string-array) from values/ is missing from any of
 * values-{hi,te,ta,kn,ml}, if format placeholders differ, if an array has a
 * different number of items, or if a multi-word string was left in English.
 */
class StringsCompletenessTest {
    private val langs = listOf("hi", "te", "ta", "kn", "ml")

    private fun resDir(): File {
        // Gradle runs unit tests from the module dir; IDEs sometimes from the root.
        return listOf(File("src/main/res"), File("app/src/main/res"), File("android/app/src/main/res"))
            .firstOrNull { it.isDirectory } ?: error("res dir not found from ${File(".").absolutePath}")
    }

    private data class Res(val strings: Map<String, String>, val arrays: Map<String, List<String>>)

    private fun load(dir: File): Res {
        val strings = mutableMapOf<String, String>()
        val arrays = mutableMapOf<String, List<String>>()
        dir.listFiles { f -> f.extension == "xml" }?.forEach { f ->
            val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(f)
            val nodes = doc.documentElement.childNodes
            for (i in 0 until nodes.length) {
                val e = nodes.item(i) as? Element ?: continue
                if (e.getAttribute("translatable") == "false") continue
                val name = e.getAttribute("name")
                when (e.tagName) {
                    "string" -> strings[name] = e.textContent
                    "string-array" -> {
                        val items = e.getElementsByTagName("item")
                        arrays[name] = (0 until items.length).map { items.item(it).textContent }
                    }
                }
            }
        }
        return Res(strings, arrays)
    }

    private val placeholder = Regex("%(\\d+\\$)?[sdf]")
    private fun placeholders(s: String) = placeholder.findAll(s).map { it.value }.sorted().toList()

    @Test
    fun allFiveLanguagesHaveEveryKey() {
        val res = resDir()
        val base = load(File(res, "values"))
        assertTrue("base strings missing", base.strings.size > 100)
        val problems = mutableListOf<String>()
        for (lang in langs) {
            val dir = File(res, "values-$lang")
            if (!dir.isDirectory) { problems += "values-$lang/ is missing"; continue }
            val t = load(dir)
            for ((k, v) in base.strings) {
                val tv = t.strings[k]
                when {
                    tv == null -> problems += "[$lang] missing string '$k'"
                    tv.isBlank() -> problems += "[$lang] empty string '$k'"
                    placeholders(tv) != placeholders(v) -> problems += "[$lang] placeholders differ in '$k': ${placeholders(v)} vs ${placeholders(tv)}"
                    tv.trim() == v.trim() && v.trim().split(Regex("\\s+")).size >= 2 -> problems += "[$lang] '$k' is still in English"
                }
            }
            for ((k, items) in base.arrays) {
                val ti = t.arrays[k]
                if (ti == null) problems += "[$lang] missing string-array '$k'"
                else if (ti.size != items.size) problems += "[$lang] string-array '$k' has ${ti.size} items, expected ${items.size}"
            }
            (t.strings.keys - base.strings.keys).forEach { problems += "[$lang] stale key '$it' not in base" }
        }
        assertTrue("Translation problems (${problems.size}):\n" + problems.joinToString("\n"), problems.isEmpty())
    }

    @Test
    fun localeConfigListsExactlyTheFiveLanguages() {
        val xml = File(resDir(), "xml/locales_config.xml").readText()
        val found = Regex("android:name=\"([a-z-]+)\"").findAll(xml).map { it.groupValues[1] }.toList()
        assertTrue("locales_config.xml lists $found", found == langs + "en")
    }

    @Test
    fun appLanguagesAreInPickerOrder() {
        val codes = AppLang.entries.map { it.code }
        assertTrue("picker order $codes", codes == langs + "en")
        assertTrue(AppLang.entries.map { it.voiceTag } == listOf("hi-IN", "te-IN", "ta-IN", "kn-IN", "ml-IN", "en-IN"))
    }
}
