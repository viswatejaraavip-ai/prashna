package com.udhyath.app

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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

private val Saffron = Color(0xFFFF9933)
private val DeepSaffron = Color(0xFFE65100)
private val DeepPurple = Color(0xFF4A148C)
private val Maroon = Color(0xFF900C3F)
private val Cream = Color(0xFFFFF6E8)
private val CardBg = Color(0xFFFFFDF6)

@Composable
fun ReportScreen(loggedIn: Boolean, onNeedLogin: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val birthJson = remember {
        context.getSharedPreferences("udhyath", 0).getString("birth_json", "") ?: ""
    }
    var teaser by remember { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirm by remember { mutableStateOf(false) }
    var reports by remember { mutableStateOf(listOf<JSONObject>()) }
    var openReport by remember { mutableStateOf<JSONObject?>(null) }
    var activeId by remember { mutableStateOf<String?>(null) }

    suspend fun refreshList() {
        try {
            val arr = Api.listReports()
            reports = (0 until arr.length()).map { arr.getJSONObject(it) }
        } catch (_: Exception) {}
    }
    LaunchedEffect(loggedIn) { if (loggedIn) refreshList() }
    // poll while a report is generating
    LaunchedEffect(activeId) {
        while (activeId != null) {
            delay(20_000)
            refreshList()
            val cur = reports.find { it.optString("report_id") == activeId }
            if (cur != null && cur.optString("status") != "generating") activeId = null
        }
    }

    val report = openReport
    if (report != null) {
        ReportReader(report) { openReport = null }
        return
    }

    Column(Modifier.fillMaxSize().background(Cream)
               .verticalScroll(rememberScrollState()).padding(12.dp)) {
        Text("📜 సంపూర్ణ జీవిత నివేదిక", fontSize = 21.sp,
             fontWeight = FontWeight.Bold, color = Maroon)
        Text("Mega Life Report — ≈1,00,000 words · 18 chapters",
             fontSize = 13.sp, color = Color(0xFF8D6E63))
        Spacer(Modifier.height(10.dp))

        if (!loggedIn) {
            Card(colors = CardDefaults.cardColors(containerColor = CardBg)) {
                Column(Modifier.padding(16.dp)) {
                    Text("రిపోర్ట్ కోసం లాగిన్ అవ్వండి — Astrologer ట్యాబ్‌లో.",
                         color = DeepPurple)
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = onNeedLogin,
                        colors = ButtonDefaults.buttonColors(containerColor = Maroon)) {
                        Text("లాగిన్ / ఖాతా")
                    }
                }
            }
            return
        }
        if (birthJson.isBlank()) {
            Card(colors = CardDefaults.cardColors(containerColor = CardBg)) {
                Text("ముందుగా 🕉 Free Charts ట్యాబ్‌లో మీ జాతకం లెక్కించండి.",
                     Modifier.padding(16.dp), color = DeepPurple)
            }
            return
        }

        // teaser
        Card(colors = CardDefaults.cardColors(containerColor = CardBg)) {
            Column(Modifier.padding(16.dp)) {
                Text("🔮 ఉచిత ప్రివ్యూ", fontWeight = FontWeight.Bold, color = DeepSaffron)
                val t = teaser
                if (t == null) {
                    Text("మీ జాతకం నుంచి 100 పదాల రుచి — పూర్తి నివేదికలో ఏముందో చూడండి.",
                         fontSize = 13.sp, color = Color(0xFF5D4037))
                    Spacer(Modifier.height(8.dp))
                    Button(enabled = !busy, onClick = {
                        busy = true; error = null
                        scope.launch {
                            try { teaser = Api.reportTeaser(JSONObject(birthJson)) }
                            catch (e: Exception) { error = e.message }
                            finally { busy = false }
                        }
                    }, colors = ButtonDefaults.buttonColors(containerColor = Saffron)) {
                        Text(if (busy) "సిద్ధమవుతోంది…" else "ఉచిత ప్రివ్యూ చూడండి",
                             color = Color(0xFF4E342E))
                    }
                } else {
                    Spacer(Modifier.height(6.dp))
                    Text(t.getString("teaser"), fontSize = 15.sp, lineHeight = 23.sp,
                         color = Color(0xFF3E2723))
                    val fr = t.getJSONObject("full_report")
                    Spacer(Modifier.height(10.dp))
                    Text("పూర్తి నివేదికలో ${fr.getJSONArray("chapters").length()} అధ్యాయాలు · " +
                         "${fr.getString("words")} పదాలు",
                         fontSize = 12.5.sp, color = Color(0xFF8D6E63))
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = { confirm = true },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Maroon)) {
                        Text("పూర్తి నివేదిక పొందండి — ₹%.0f".format(fr.getDouble("price")))
                    }
                }
                error?.let { Text(it, color = Color(0xFFC62828), fontSize = 13.sp) }
            }
        }

        Spacer(Modifier.height(14.dp))
        if (reports.isNotEmpty()) {
            Text("మీ నివేదికలు", fontWeight = FontWeight.Bold, color = Maroon)
            reports.forEach { r ->
                val status = r.optString("status")
                val done = r.optInt("sections_done"); val total = r.optInt("sections_total")
                Card(
                    colors = CardDefaults.cardColors(containerColor = CardBg),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp)
                        .clickable(enabled = status != "failed") {
                            scope.launch {
                                try { openReport = Api.getReport(r.getString("report_id")) }
                                catch (e: Exception) { error = e.message }
                            }
                        },
                ) {
                    Column(Modifier.padding(14.dp)) {
                        Text(when (status) {
                            "ready" -> "✅ నివేదిక సిద్ధం — చదవడానికి నొక్కండి"
                            "generating" -> "⏳ తయారవుతోంది… $done/$total అధ్యాయాలు"
                            else -> "❌ విఫలమైంది (డబ్బు వాపసు అయింది)"
                        }, fontWeight = FontWeight.SemiBold, color = DeepPurple)
                        if (status == "generating")
                            LinearProgressIndicator(
                                progress = { if (total > 0) done.toFloat() / total else 0f },
                                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                                color = Saffron, trackColor = Color(0xFFF2E3C2))
                        Text(r.optString("created_at").take(16).replace("T", " "),
                             fontSize = 11.5.sp, color = Color(0xFF8D6E63))
                    }
                }
            }
        }
    }

    if (confirm) AlertDialog(
        onDismissRequest = { confirm = false },
        title = { Text("పూర్తి జీవిత నివేదిక") },
        text = { Text("≈1,00,000 పదాలు, 18 అధ్యాయాలు — గతం, భవిష్యత్తు, ఉద్యోగం, " +
                      "వివాహం, సంతానం, ధనం, కుటుంబం, ఆధ్యాత్మికం. ₹1,050 మీ వాలెట్ " +
                      "నుంచి తీసుకుంటాం. సుమారు 30–45 నిమిషాల్లో సిద్ధమవుతుంది.") },
        confirmButton = {
            Button(onClick = {
                confirm = false; busy = true
                scope.launch {
                    try {
                        val r = Api.buyReport(JSONObject(birthJson))
                        activeId = r.getString("report_id")
                        refreshList()
                    } catch (e: Exception) { error = e.message }
                    finally { busy = false }
                }
            }, colors = ButtonDefaults.buttonColors(containerColor = Maroon)) {
                Text("₹1,050 చెల్లించి కొనండి")
            }
        },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("తర్వాత") } },
    )
}

@Composable
private fun ReportReader(report: JSONObject, onBack: () -> Unit) {
    val sections = report.getJSONArray("sections")
    var open by remember { mutableStateOf(0) }
    Column(Modifier.fillMaxSize().background(Cream)
               .verticalScroll(rememberScrollState()).padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("← వెనక్కి", color = Maroon) }
            Text("📜 మీ జీవిత నివేదిక", fontWeight = FontWeight.Bold,
                 color = Maroon, fontSize = 17.sp)
        }
        if (report.getString("status") == "generating")
            Text("⏳ ఇంకా తయారవుతోంది — ${report.optInt("sections_done")}/" +
                 "${report.optInt("sections_total")} అధ్యాయాలు సిద్ధం.",
                 fontSize = 13.sp, color = Color(0xFF8D6E63))
        for (i in 0 until sections.length()) {
            val s = sections.getJSONObject(i)
            Column(Modifier.fillMaxWidth().padding(vertical = 5.dp)
                       .background(CardBg, RoundedCornerShape(12.dp))
                       .border(1.dp, Color(0xFFE8C87E), RoundedCornerShape(12.dp))
                       .clickable { open = if (open == i) -1 else i }
                       .padding(14.dp)) {
                Text("${s.getInt("idx")}. ${s.getString("title")}",
                     fontWeight = FontWeight.Bold, color = DeepPurple)
                if (open == i) {
                    Spacer(Modifier.height(8.dp))
                    Text(s.getString("content"), fontSize = 14.5.sp,
                         lineHeight = 23.sp, color = Color(0xFF3E2723))
                }
            }
        }
    }
}
