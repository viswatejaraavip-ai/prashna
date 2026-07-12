package com.udhyath.app

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

// Website palette
private val Saffron = Color(0xFFFF9933)
private val DeepSaffron = Color(0xFFE65100)
private val DeepPurple = Color(0xFF4A148C)
private val Maroon = Color(0xFF900C3F)
private val Cream = Color(0xFFFFF6E8)
private val CardBg = Color(0xFFFFFDF6)
private val Gold = Color(0xFFD4A017)

private val PLANET_ABBR = mapOf(
    "Sun" to "Su", "Moon" to "Mo", "Mars" to "Ma", "Mercury" to "Me",
    "Jupiter" to "Ju", "Venus" to "Ve", "Saturn" to "Sa",
    "Rahu" to "Ra", "Ketu" to "Ke", "Lagna" to "La")

// Classical South Indian fixed layout: sign -> (row, col) in a 4x4 frame
private val SOUTH_LAYOUT = mapOf(
    "Pisces" to (0 to 0), "Aries" to (0 to 1), "Taurus" to (0 to 2), "Gemini" to (0 to 3),
    "Aquarius" to (1 to 0), "Cancer" to (1 to 3),
    "Capricorn" to (2 to 0), "Leo" to (2 to 3),
    "Sagittarius" to (3 to 0), "Scorpio" to (3 to 1), "Libra" to (3 to 2), "Virgo" to (3 to 3))

private val TABS = listOf("Chart", "Navamsa", "Planets", "KP", "Dashas",
                          "Yogas", "Doshas", "Shadbala", "Gems")

@Composable
fun ChartsScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var dateText by remember { mutableStateOf(prefsGet(context, "bc_date")) }
    var timeText by remember { mutableStateOf(prefsGet(context, "bc_time")) }
    var placeQuery by remember { mutableStateOf(prefsGet(context, "bc_place")) }
    var suggestions by remember { mutableStateOf(listOf<JSONObject>()) }
    var picked by remember { mutableStateOf<JSONObject?>(null) }
    var chart by remember { mutableStateOf<JSONObject?>(null) }
    var birthBody by remember { mutableStateOf<JSONObject?>(null) }
    var dashaData by remember { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var tab by remember { mutableStateOf(0) }

    LaunchedEffect(placeQuery) {
        if (picked?.optString("name")?.let { placeQuery.startsWith(it) } == true) return@LaunchedEffect
        delay(250)
        if (placeQuery.length >= 2) {
            try {
                val arr = Api.searchPlaces(placeQuery)
                suggestions = (0 until arr.length()).map { arr.getJSONObject(it) }
            } catch (_: Exception) {}
        } else suggestions = emptyList()
    }

    fun compute() {
        val d = dateText.split("-").mapNotNull { it.toIntOrNull() }
        val t = timeText.split(":").mapNotNull { it.toIntOrNull() }
        val p = picked
        if (d.size != 3 || t.size < 2 || p == null) {
            error = "Pick date, time and a birth place from suggestions"; return
        }
        error = null; busy = true; chart = null; dashaData = null
        val body = JSONObject()
            .put("year", d[0]).put("month", d[1]).put("day", d[2])
            .put("hour", t[0]).put("minute", t[1])
            .put("latitude", p.getDouble("latitude"))
            .put("longitude", p.getDouble("longitude"))
            .put("tz_name", p.optString("tz_name", "Asia/Kolkata"))
        scope.launch {
            try {
                chart = Api.computeChart(body)
                birthBody = body
                tab = 0
                prefsPut(context, "bc_date", dateText); prefsPut(context, "bc_time", timeText)
                prefsPut(context, "bc_place", placeQuery)
            } catch (e: Exception) { error = e.message ?: "Network error" }
            finally { busy = false }
        }
    }

    LaunchedEffect(tab, chart) {
        if (TABS[tab] == "Dashas" && chart != null && dashaData == null) {
            try { dashaData = Api.dashas(birthBody!!, "vimshottari") } catch (_: Exception) {}
        }
    }

    Column(Modifier.fillMaxSize().background(Cream)) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp)) {
            // ---- birth form ----
            SectionCard {
                Text("🕉 Compute birth chart — FREE", fontWeight = FontWeight.Bold,
                     color = DeepSaffron, fontSize = 17.sp)
                Spacer(Modifier.height(8.dp))
                Row {
                    OutlinedButton(onClick = {
                        val now = java.util.Calendar.getInstance()
                        DatePickerDialog(context, { _, y, m, dd ->
                            dateText = "%04d-%02d-%02d".format(y, m + 1, dd)
                        }, now.get(1), now.get(2), now.get(5)).show()
                    }, modifier = Modifier.weight(1f)) {
                        Text(if (dateText.isBlank()) "📅 Date" else dateText, color = Maroon)
                    }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(onClick = {
                        TimePickerDialog(context, { _, h, m ->
                            timeText = "%02d:%02d".format(h, m)
                        }, 12, 0, true).show()
                    }, modifier = Modifier.weight(1f)) {
                        Text(if (timeText.isBlank()) "🕐 Time" else timeText, color = Maroon)
                    }
                }
                OutlinedTextField(placeQuery, {
                    placeQuery = it; picked = null
                }, label = { Text("Birth place — type to search") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())
                suggestions.takeIf { picked == null }?.forEach { s ->
                    Text("${s.getString("name")}, ${s.getString("region")}",
                        Modifier.fillMaxWidth().clickable {
                            picked = s
                            placeQuery = "${s.getString("name")}, ${s.getString("region")}"
                            suggestions = emptyList()
                        }.padding(vertical = 7.dp, horizontal = 6.dp),
                        color = DeepPurple)
                }
                Spacer(Modifier.height(10.dp))
                Button(onClick = { compute() }, enabled = !busy,
                    colors = ButtonDefaults.buttonColors(containerColor = DeepSaffron),
                    modifier = Modifier.fillMaxWidth()) {
                    Text(if (busy) "Computing…" else "Compute all charts")
                }
                error?.let { Text(it, color = Color(0xFFC62828), fontSize = 13.sp) }
            }

            chart?.let { c ->
                ScrollableTabRow(selectedTabIndex = tab, containerColor = CardBg,
                                 contentColor = Maroon, edgePadding = 4.dp) {
                    TABS.forEachIndexed { i, name ->
                        Tab(selected = tab == i, onClick = { tab = i },
                            text = { Text(name, fontSize = 13.sp,
                                fontWeight = if (tab == i) FontWeight.Bold else FontWeight.Normal) })
                    }
                }
                Spacer(Modifier.height(10.dp))
                when (TABS[tab]) {
                    "Chart" -> RasiTab(c)
                    "Navamsa" -> VargaTab(c, "D9", "Navamsa — marriage, inner strength")
                    "Planets" -> PlanetsTab(c)
                    "KP" -> KPTab(c)
                    "Dashas" -> DashasTab(dashaData)
                    "Yogas" -> YogasTab(c)
                    "Doshas" -> DoshasTab(c)
                    "Shadbala" -> ShadbalaTab(c)
                    "Gems" -> GemsTab(c)
                }
            }
        }
    }
}

private fun prefsGet(ctx: android.content.Context, k: String) =
    ctx.getSharedPreferences("udhyath", 0).getString(k, "") ?: ""

private fun prefsPut(ctx: android.content.Context, k: String, v: String) =
    ctx.getSharedPreferences("udhyath", 0).edit().putString(k, v).apply()

@Composable
private fun SectionCard(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp)
            .background(CardBg, RoundedCornerShape(14.dp))
            .border(1.dp, Color(0xFFE8C87E), RoundedCornerShape(14.dp))
            .padding(14.dp), content = content)
}

@Composable
fun SouthChart(placements: Map<String, List<String>>, lagnaSign: String, title: String) {
    Column(Modifier.fillMaxWidth()) {
        Text(title, color = Maroon, fontWeight = FontWeight.Bold,
             modifier = Modifier.align(Alignment.CenterHorizontally))
        Spacer(Modifier.height(6.dp))
        @Composable
        fun RowScope.signCell(sign: String) {
            val isLagna = sign == lagnaSign
            Column(
                Modifier.weight(1f).fillMaxHeight().padding(1.dp)
                    .background(if (isLagna) Color(0xFFFFE9CC) else Color.White,
                                RoundedCornerShape(6.dp))
                    .border(if (isLagna) 2.dp else 1.dp,
                            if (isLagna) DeepSaffron else Color(0xFFE8C87E),
                            RoundedCornerShape(6.dp))
                    .padding(3.dp)
            ) {
                Text(sign.take(3), fontSize = 9.sp, color = Color(0xFF8D6E63))
                Text((placements[sign] ?: emptyList()).joinToString(" "),
                     fontSize = 11.5.sp, color = DeepPurple,
                     fontWeight = FontWeight.SemiBold, lineHeight = 14.sp)
            }
        }
        val signAt = { r: Int, col: Int ->
            SOUTH_LAYOUT.entries.first { it.value == (r to col) }.key }
        for (r in 0..3) {
            Row(Modifier.fillMaxWidth().height(78.dp)) {
                if (r == 0 || r == 3) {
                    for (col in 0..3) signCell(signAt(r, col))
                } else {
                    signCell(signAt(r, 0))
                    Box(Modifier.weight(2f).fillMaxHeight(),
                        contentAlignment = Alignment.Center) {
                        if (r == 1) Text("ॐ", fontSize = 36.sp, color = Saffron,
                                         textAlign = TextAlign.Center)
                    }
                    signCell(signAt(r, 3))
                }
            }
        }
    }
}

private fun compactToPlacements(compact: JSONObject): Pair<Map<String, List<String>>, String> {
    val out = mutableMapOf<String, MutableList<String>>()
    var lagna = ""
    compact.keys().forEach { planet ->
        val sign = compact.getString(planet)
        if (planet == "Lagna") lagna = sign
        out.getOrPut(sign) { mutableListOf() }.add(PLANET_ABBR[planet] ?: planet.take(2))
    }
    return out to lagna
}

@Composable
private fun RasiTab(c: JSONObject) {
    val d1 = c.getJSONObject("all_vargas").getJSONObject("D1")
    val (pl, lagna) = compactToPlacements(d1)
    SectionCard {
        SouthChart(pl, lagna, "Rasi (D-1)")
        Spacer(Modifier.height(8.dp))
        val pan = c.getJSONObject("panchanga")
        Text("Birth panchanga: ${pan.getJSONObject("tithi").getString("paksha")} " +
             "${pan.getJSONObject("tithi").getString("name")} · ${pan.getString("vara")} · " +
             "${pan.getJSONObject("nakshatra").getString("name")} · " +
             "${pan.getJSONObject("yoga").getString("name")}",
             fontSize = 13.sp, color = Color(0xFF8D6E63))
    }
}

@Composable
private fun VargaTab(c: JSONObject, key: String, caption: String) {
    val v = c.getJSONObject("all_vargas").getJSONObject(key)
    val (pl, lagna) = compactToPlacements(v)
    SectionCard {
        SouthChart(pl, lagna, "$key chart")
        Text(caption, fontSize = 13.sp, color = Color(0xFF8D6E63))
    }
}

@Composable
private fun TableRow(vararg cells: String, bold: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        cells.forEachIndexed { i, cell ->
            Text(cell, Modifier.weight(if (i == 0) 1.1f else 1f), fontSize = 12.5.sp,
                 fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
                 color = if (bold) Maroon else Color(0xFF3E2723))
        }
    }
}

@Composable
private fun PlanetsTab(c: JSONObject) {
    SectionCard {
        TableRow("Planet", "Sign", "Position", "Nakshatra", "House", bold = true)
        HorizontalDivider(color = Color(0xFFE8C87E))
        val asc = c.getJSONObject("ascendant")
        TableRow("Lagna", asc.getString("sign"), asc.getString("dms"), "—", "1")
        val planets = c.getJSONObject("planets")
        planets.keys().forEach { name ->
            val p = planets.getJSONObject(name)
            TableRow(name + (if (p.optBoolean("retrograde")) " ℞" else ""),
                     p.getString("sign"), p.getString("dms"),
                     p.getJSONObject("nakshatra").getString("name") +
                     " (" + p.getJSONObject("nakshatra").getInt("pada") + ")",
                     p.getInt("house_whole_sign").toString())
        }
    }
}

@Composable
private fun KPTab(c: JSONObject) {
    val kp = c.getJSONObject("kp")
    SectionCard {
        Text("KP sub lords (Krishnamurti ayanamsa)", fontWeight = FontWeight.Bold, color = Maroon)
        Spacer(Modifier.height(6.dp))
        TableRow("Planet", "Sign lord", "Star lord", "Sub lord", bold = true)
        HorizontalDivider(color = Color(0xFFE8C87E))
        val planets = kp.getJSONObject("planets")
        planets.keys().forEach { name ->
            val p = planets.getJSONObject(name)
            TableRow(name, p.getString("sign_lord"), p.getString("star_lord"),
                     p.getString("sub_lord"))
        }
    }
}

@Composable
private fun DashasTab(d: JSONObject?) {
    if (d == null) { SectionCard { Text("Loading dashas…", color = Color(0xFF8D6E63)) }; return }
    var open by remember { mutableStateOf(-1) }
    SectionCard {
        Text("Vimshottari mahadashas (tap for antardashas)",
             fontWeight = FontWeight.Bold, color = Maroon)
        val mahas = d.getJSONArray("mahadashas")
        for (i in 0 until mahas.length()) {
            val m = mahas.getJSONObject(i)
            Column(Modifier.fillMaxWidth().clickable { open = if (open == i) -1 else i }
                       .padding(vertical = 6.dp)) {
                Text("${m.getString("lord")}  ·  ${m.getString("start").take(10)} → " +
                     m.getString("end").take(10),
                     fontWeight = FontWeight.SemiBold, color = DeepPurple, fontSize = 14.sp)
                if (open == i) {
                    val antars = m.getJSONArray("antardashas")
                    for (j in 0 until antars.length()) {
                        val a = antars.getJSONObject(j)
                        Text("   ${a.getString("lord")}: ${a.getString("start").take(10)} → " +
                             a.getString("end").take(10),
                             fontSize = 12.5.sp, color = Color(0xFF5D4037))
                    }
                }
            }
            HorizontalDivider(color = Color(0xFFF2E3C2))
        }
    }
}

@Composable
private fun YogasTab(c: JSONObject) {
    val y = c.getJSONObject("yogas")
    SectionCard {
        Text("✨ ${y.getInt("count")} yogas found", fontWeight = FontWeight.Bold, color = Maroon)
        val arr = y.getJSONArray("yogas")
        for (i in 0 until arr.length()) {
            val item = arr.getJSONObject(i)
            Spacer(Modifier.height(8.dp))
            Text(item.getString("yoga"), fontWeight = FontWeight.Bold, color = DeepPurple)
            Text(item.getString("description"), fontSize = 13.sp, color = Color(0xFF5D4037))
            Text("📍 " + item.getString("factors"), fontSize = 12.sp, color = Color(0xFF8D6E63))
        }
        if (arr.length() == 0) Text("No classical yogas from the detected set.",
                                    color = Color(0xFF8D6E63))
    }
}

@Composable
private fun DoshasTab(c: JSONObject) {
    val d = c.getJSONObject("doshas")
    val m = d.getJSONObject("manglik")
    val k = d.getJSONObject("kaal_sarpa")
    val ss = d.getJSONObject("sadhe_sati")
    SectionCard {
        Text(if (m.getBoolean("is_manglik")) "🔥 Manglik — ${m.getString("severity")}"
             else "✅ Not Manglik", fontWeight = FontWeight.Bold, color = Maroon)
        Text("Mars in ${m.getString("mars_sign")}", fontSize = 13.sp, color = Color(0xFF5D4037))
    }
    SectionCard {
        Text(if (k.getBoolean("present")) "🐍 Kaal Sarpa — ${k.optString("type")}"
             else if (k.getBoolean("partial")) "🟡 Partial Kaal Sarpa — ${k.optString("type")}"
             else "✅ No Kaal Sarpa dosha", fontWeight = FontWeight.Bold, color = Maroon)
    }
    SectionCard {
        Text("🪐 Sadhe Sati (Moon: ${ss.getString("natal_moon_sign")})",
             fontWeight = FontWeight.Bold, color = Maroon)
        val cur = ss.optJSONObject("currently_active")
        Text(if (cur != null) "Active now: ${cur.getString("phase")} until ${cur.getString("end")}"
             else "Not running today.", fontSize = 13.sp, color = Color(0xFF5D4037))
        val w = ss.getJSONArray("windows")
        for (i in 0 until minOf(w.length(), 12)) {
            val x = w.getJSONObject(i)
            Text("${x.getString("start")} → ${x.getString("end")}  ·  " +
                 "${if (x.getString("kind") == "sadhe_sati") "Sadhe Sati" else "Dhaiya"} " +
                 "(${x.getString("saturn_sign")})", fontSize = 12.sp, color = Color(0xFF8D6E63))
        }
    }
}

@Composable
private fun ShadbalaTab(c: JSONObject) {
    val sb = c.getJSONObject("shadbala")
    val ranking = sb.getJSONArray("ranking")
    SectionCard {
        Text("💪 Shadbala strength (rupas vs required)",
             fontWeight = FontWeight.Bold, color = Maroon)
        Spacer(Modifier.height(6.dp))
        for (i in 0 until ranking.length()) {
            val name = ranking.getString(i)
            val p = sb.getJSONObject("planets").getJSONObject(name)
            val ratio = p.getDouble("ratio").toFloat().coerceAtMost(1.6f)
            Row(verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(vertical = 4.dp)) {
                Text(name, Modifier.width(72.dp), fontSize = 13.sp, color = DeepPurple,
                     fontWeight = FontWeight.SemiBold)
                LinearProgressIndicator(
                    progress = { ratio / 1.6f },
                    modifier = Modifier.weight(1f).height(9.dp),
                    color = if (p.getBoolean("strong")) Color(0xFF2E7D32) else Saffron,
                    trackColor = Color(0xFFF2E3C2))
                Text(" ${p.getDouble("rupas")}", fontSize = 12.sp, color = Color(0xFF5D4037))
                Text(if (p.getBoolean("strong")) " ✓" else "", color = Color(0xFF2E7D32))
            }
        }
    }
}

@Composable
private fun GemsTab(c: JSONObject) {
    val g = c.getJSONObject("gemstones")
    val recs = g.getJSONArray("recommended")
    for (i in 0 until recs.length()) {
        val r = recs.getJSONObject(i)
        SectionCard {
            Text(r.getString("role"), fontSize = 12.sp, color = Color(0xFF8D6E63))
            Text("💎 ${r.getString("gem")} (${r.getString("hindi")})",
                 fontWeight = FontWeight.Bold, color = Maroon, fontSize = 17.sp)
            Text("Planet: ${r.getString("planet")} · ${r.getString("finger")} · " +
                 "${r.getString("metal")} · ${r.getString("day")}",
                 fontSize = 13.sp, color = Color(0xFF5D4037))
            Text("🕉 ${r.getString("mantra")}", fontSize = 13.sp, color = DeepPurple)
        }
    }
    SectionCard {
        Text(g.getString("note"), fontSize = 12.sp, color = Color(0xFF8D6E63))
    }
}
