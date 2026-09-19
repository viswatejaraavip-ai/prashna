package com.udhyath.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.booleanOrNull

/*
 * Renders the server's display-ready `view` (backend app/features/views.py):
 * an optional chart, optional list of divisional charts, and sections of
 * rows / tables / item cards / text. All strings arrive localized, so this
 * file never shows engine field names.
 */

/** `{"lagna": 0-11, "planets": [{"key", "sign", "retro"}]}` -> drawable chart. */
fun chartFromView(o: JsonObject?): ChartData? {
    if (o == null) return null
    val lagna = (o["lagna"] as? JsonPrimitive)?.intOrNull ?: return null
    val bySign = mutableMapOf<Int, MutableList<String>>()
    val retro = mutableSetOf<String>()
    bySign.getOrPut(lagna) { mutableListOf() }.add("Lagna")
    (o["planets"] as? JsonArray)?.forEach { el ->
        val p = el as? JsonObject ?: return@forEach
        val key = p.str("key") ?: return@forEach
        val sign = (p["sign"] as? JsonPrimitive)?.intOrNull ?: return@forEach
        bySign.getOrPut(sign) { mutableListOf() }.add(key)
        if ((p["retro"] as? JsonPrimitive)?.booleanOrNull == true) retro += key
    }
    return ChartData(lagna, bySign, retro)
}

private fun JsonArray?.strings(): List<String> =
    this?.map { (it as? JsonPrimitive)?.content ?: "" } ?: emptyList()

@Composable
fun ViewSections(view: JsonObject, dense: Boolean) {
    (view["sections"] as? JsonArray)?.forEach { el ->
        val s = el as? JsonObject ?: return@forEach
        SectionCard(title = s.str("title")) {
            (s["rows"] as? JsonArray)?.forEach { r ->
                val cells = (r as? JsonArray).strings()
                if (cells.size >= 2) KeyValue(cells[0], cells[1])
            }
            (s["table"] as? JsonObject)?.let { t ->
                TextTable((t["columns"] as? JsonArray).strings(),
                    (t["rows"] as? JsonArray)?.map { (it as? JsonArray).strings() } ?: emptyList(), dense)
            }
            (s["items"] as? JsonArray)?.forEachIndexed { i, it ->
                val o = it as? JsonObject ?: return@forEachIndexed
                if (i > 0) HorizontalDivider(Modifier.padding(vertical = 6.dp))
                o.str("title")?.let { Text(it, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
                o.str("badge")?.let { badge ->
                    val color = when (o.str("tone")) {
                        "good" -> MaterialTheme.colorScheme.tertiaryContainer
                        "bad" -> MaterialTheme.colorScheme.errorContainer
                        "warn" -> MaterialTheme.colorScheme.secondaryContainer
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    }
                    Spacer(Modifier.height(4.dp)); Pill(badge, color)
                }
                o.str("text")?.let { Spacer(Modifier.height(4.dp)); Text(it, style = MaterialTheme.typography.bodyLarge) }
            }
            s.str("text")?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
        }
    }
}

@Composable
fun TextTable(columns: List<String>, rows: List<List<String>>, dense: Boolean) {
    val cellW = if (dense) 96.dp else 112.dp
    Column(Modifier.horizontalScroll(rememberScrollState())
        .border(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.5f), RoundedCornerShape(8.dp))) {
        if (columns.any { it.isNotBlank() }) {
            Row(Modifier.background(MaterialTheme.colorScheme.secondaryContainer).padding(vertical = 6.dp)) {
                columns.forEach { c ->
                    Text(c, Modifier.width(cellW).padding(horizontal = 6.dp), style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.Bold)
                }
            }
        }
        rows.forEachIndexed { i, r ->
            Row(Modifier.background(if (i % 2 == 1) MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f) else MaterialTheme.colorScheme.surface)
                .padding(vertical = 5.dp), horizontalArrangement = Arrangement.Start) {
                r.forEach { cell ->
                    Text(cell.ifBlank { "—" }, Modifier.width(cellW).padding(horizontal = 6.dp),
                        style = if (dense) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}
