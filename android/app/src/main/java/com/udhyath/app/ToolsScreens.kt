package com.udhyath.app

import android.app.DatePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.time.LocalDate

// ===========================================================================
// Matching (guna milan) + share PDF
// ===========================================================================

@Composable
fun ProfilePicker(label: String, options: List<Profile>, selected: Profile?, onPick: (Profile) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column {
        Text(label, style = MaterialTheme.typography.labelLarge)
        Box {
            OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) {
                Text(selected?.let { "${it.name} · ${relationLabel(it.relation)}" } ?: stringResource(R.string.pick_person),
                    modifier = Modifier.weight(1f))
                Icon(Icons.Default.ArrowDropDown, contentDescription = null)
            }
            DropdownMenu(open, onDismissRequest = { open = false }) {
                options.forEach { p ->
                    DropdownMenuItem(text = { Text("${p.name} · ${relationLabel(p.relation)}") }, onClick = { open = false; onPick(p) })
                }
            }
        }
    }
}

@Composable
fun MatchingScreen(nav: NavHostController, onBack: () -> Unit, presetA: String? = null) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val user by g.account.user.collectAsStateWithLifecycle()
    var clients by remember { mutableStateOf<List<Profile>>(emptyList()) }
    LaunchedEffect(user?.isAstrologer) { if (user?.isAstrologer == true) clients = runCatching { g.api.clients() }.getOrDefault(emptyList()) }
    val options = (profiles + clients).distinctBy { it.id }
    var a by remember { mutableStateOf(options.firstOrNull { it.id == presetA } ?: options.firstOrNull { it.relation == "self" }) }
    var b by remember { mutableStateOf<Profile?>(null) }
    var result by remember { mutableStateOf<Load<JsonObject>?>(null) }
    var pdfBusy by remember { mutableStateOf(false) }
    var pdfErr by remember { mutableStateOf<Throwable?>(null) }

    fun run() {
        val pa = a ?: return; val pb = b ?: return
        result = Load.Loading
        scope.launch { result = runCatching { g.api.matching(pa.id, pb.id) }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    }

    ScreenScaffold(stringResource(R.string.matching_title), onBack = onBack) {
        Text(stringResource(R.string.matching_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        ProfilePicker(stringResource(R.string.matching_person_a), options, a) { a = it; result = null }
        ProfilePicker(stringResource(R.string.matching_person_b), options.filter { it.id != a?.id }, b) { b = it; result = null }
        TextButton(onClick = { nav.navigate(Routes.profileEdit(relation = "other")) }) {
            Icon(Icons.Default.Add, null); Spacer(Modifier.width(6.dp)); Text(stringResource(R.string.matching_add_person))
        }
        BigButton(stringResource(R.string.matching_run), onClick = { run() }, enabled = a != null && b != null, busy = result == Load.Loading)
        result?.let { r ->
            LoadView(r, onRetry = { run() }) { data ->
                val score = data.num("total", "score", "guna_score", "points")
                val max = data.num("max", "out_of", "max_score") ?: 36.0
                val verdict = data.str("verdict", "summary", "result")
                SectionCard(accent = true) {
                    if (score != null) Text(stringResource(R.string.matching_score, score.toInt(), max.toInt()),
                        style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.secondary)
                    if (verdict != null) Text(verdict, style = MaterialTheme.typography.bodyLarge)
                }
                val rest = JsonObject(data.filterKeys { it !in setOf("total", "score", "guna_score", "points", "max", "out_of", "max_score", "verdict", "summary", "result") })
                if (rest.isNotEmpty()) SectionCard { JsonView(rest) }
                BigButton(stringResource(R.string.matching_pdf), icon = Icons.Default.PictureAsPdf, secondary = true, busy = pdfBusy, onClick = {
                    val pa = a ?: return@BigButton; val pb = b ?: return@BigButton
                    pdfBusy = true; pdfErr = null
                    scope.launch {
                        try {
                            val bytes = g.api.download(g.api.matchingPdf(pa.id, pb.id, brand = user?.isAstrologer == true))
                            shareFile(ctx, bytes, "udhyath-matching.pdf", "application/pdf", ctx.getString(R.string.share_matching_text))
                        } catch (e: Exception) { pdfErr = e } finally { pdfBusy = false }
                    }
                })
                pdfErr?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

// ===========================================================================
// Muhurta finder
// ===========================================================================

val MUHURTA_EVENTS = listOf("marriage", "griha_pravesam", "vehicle", "business", "travel", "naming")

@Composable
fun muhurtaEventLabel(e: String) = stringResource(when (e) {
    "marriage" -> R.string.ev_marriage; "griha_pravesam" -> R.string.ev_griha_pravesam; "vehicle" -> R.string.ev_vehicle
    "business" -> R.string.ev_business; "travel" -> R.string.ev_travel; else -> R.string.ev_naming
})

@Composable
fun DateButton(label: String, value: String, modifier: Modifier = Modifier, onPick: (String) -> Unit) {
    val ctx = LocalContext.current
    OutlinedButton(onClick = {
        val d = runCatching { LocalDate.parse(value) }.getOrDefault(LocalDate.now())
        DatePickerDialog(ctx, { _, y, m, dd -> onPick("%04d-%02d-%02d".format(y, m + 1, dd)) }, d.year, d.monthValue - 1, d.dayOfMonth).show()
    }, modifier = modifier.heightIn(min = 56.dp)) {
        Icon(Icons.Default.CalendarMonth, contentDescription = null); Spacer(Modifier.width(6.dp))
        Column {
            Text(label, style = MaterialTheme.typography.labelSmall)
            Text(if (value.isBlank()) "—" else formatDate(value))
        }
    }
}

@Composable
fun MuhurtaScreen(onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val active = profiles.firstOrNull { it.id == settings.activeProfileId }
    var event by remember { mutableStateOf("marriage") }
    var from by remember { mutableStateOf(LocalDate.now().toString()) }
    var to by remember { mutableStateOf(LocalDate.now().plusDays(60).toString()) }
    var place by remember(active?.id) { mutableStateOf(active?.birth?.let { Place(it.place, "", it.lat, it.lon, it.tz) }) }
    var personal by remember { mutableStateOf(true) }
    var result by remember { mutableStateOf<Load<List<JsonElement>>?>(null) }

    fun run() {
        val p = place ?: return
        result = Load.Loading
        scope.launch {
            result = runCatching {
                g.api.muhurta(event, from, to, if (personal) active?.id else null, p.latitude, p.longitude, p.tz_name).itemsList("windows", "muhurtas")
            }.fold({ Load.Ok(it) }, { Load.Err(it) })
        }
    }

    ScreenScaffold(stringResource(R.string.muhurta_title), onBack = onBack) {
        Text(stringResource(R.string.muhurta_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.muhurta_event), style = MaterialTheme.typography.labelLarge)
        ChipRow(MUHURTA_EVENTS, event, label = { muhurtaEventLabel(it) }) { event = it }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DateButton(stringResource(R.string.from), from, Modifier.weight(1f)) { from = it }
            DateButton(stringResource(R.string.to), to, Modifier.weight(1f)) { to = it }
        }
        PlaceSearchField(place, label = stringResource(R.string.muhurta_place)) { place = it }
        if (active != null) Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(personal, { personal = it }); Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.muhurta_personal, active.name))
        }
        BigButton(stringResource(R.string.muhurta_find), onClick = { run() }, enabled = place != null && from <= to, busy = result == Load.Loading)
        result?.let { r ->
            LoadView(r, onRetry = { run() }) { list ->
                if (list.isEmpty()) EmptyBox(stringResource(R.string.muhurta_none))
                list.forEachIndexed { i, w ->
                    val o = w.obj()
                    SectionCard(accent = i == 0) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Pill("#${i + 1}")
                            Spacer(Modifier.width(8.dp))
                            val start = o?.str("start", "from", "date")
                            val end = o?.str("end", "to")
                            Text(listOfNotNull(start?.let { formatDateTime(it) }, end?.let { formatDateTime(it) }).joinToString(" – "),
                                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        }
                        o?.str("quality", "reason", "description", "summary")?.let { Text(it) }
                        o?.num("score")?.let { Text(stringResource(R.string.score_value, it.toInt()), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        if (o == null) JsonView(w)
                    }
                }
            }
        }
    }
}

// ===========================================================================
// Birth-time helper (rectification from life events; engine heuristics)
// ===========================================================================

val LIFE_EVENTS = listOf("marriage", "child_birth", "job_start", "relocation", "parent_death", "accident", "graduation")

@Composable
fun lifeEventLabel(e: String) = stringResource(when (e) {
    "marriage" -> R.string.le_marriage; "child_birth" -> R.string.le_child_birth; "job_start" -> R.string.le_job_start
    "relocation" -> R.string.le_relocation; "parent_death" -> R.string.le_parent_death; "accident" -> R.string.le_accident
    else -> R.string.le_graduation
})

@Composable
fun RectifyScreen(pid: String, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val profile = profiles.firstOrNull { it.id == pid }
    val events = remember { mutableStateListOf<Pair<String, String>>() }
    var newType by remember { mutableStateOf("marriage") }
    var newDate by remember { mutableStateOf("") }
    var result by remember { mutableStateOf<Load<List<JsonElement>>?>(null) }
    var applied by remember { mutableStateOf<String?>(null) }
    var applyErr by remember { mutableStateOf<Throwable?>(null) }

    fun run() {
        result = Load.Loading
        scope.launch { result = runCatching { g.api.rectify(pid, events.toList()).itemsList("candidates") }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    }

    ScreenScaffold(stringResource(R.string.rectify_title), onBack = onBack) {
        Text(stringResource(R.string.rectify_subtitle, profile?.name ?: ""), color = MaterialTheme.colorScheme.onSurfaceVariant)
        SectionCard(title = stringResource(R.string.rectify_add_event)) {
            ChipRow(LIFE_EVENTS, newType, label = { lifeEventLabel(it) }) { newType = it }
            DateButton(stringResource(R.string.k_date), newDate, Modifier.fillMaxWidth()) { newDate = it }
            BigButton(stringResource(R.string.add), secondary = true, enabled = newDate.isNotBlank() && events.size < 8, onClick = {
                events += newDate to newType; newDate = ""
            })
        }
        events.forEachIndexed { i, (d, t) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${lifeEventLabel(t)} · ${formatDate(d)}", Modifier.weight(1f))
                IconButton(onClick = { events.removeAt(i) }) { Icon(Icons.Default.Close, contentDescription = stringResource(R.string.remove)) }
            }
        }
        Text(stringResource(R.string.rectify_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        BigButton(stringResource(R.string.rectify_run), enabled = events.size >= 2, busy = result == Load.Loading, onClick = { run() })
        result?.let { r ->
            LoadView(r, onRetry = { run() }) { list ->
                if (list.isEmpty()) EmptyBox(stringResource(R.string.rectify_none))
                list.forEach { c ->
                    val o = c.obj()
                    val time = o?.str("time", "birth_time", "candidate")
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(time?.let { formatTime(it.take(5)) } ?: c.displayText(), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                                o?.num("score")?.let { Text(stringResource(R.string.score_value, it.toInt())) }
                                o?.str("lagna", "ascendant")?.let { Text("${stringResource(R.string.k_lagna)}: $it") }
                                o?.str("reason", "notes", "description")?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                            }
                            if (time != null && profile != null) TextButton(onClick = {
                                scope.launch {
                                    runCatching {
                                        g.api.updateProfile(pid, ProfileInput(profile.name, profile.relation,
                                            profile.birth.copy(time = time.take(5)), true, profile.gender, profile.notes))
                                    }.onSuccess { g.account.upsertLocal(it.copy(id = it.id.ifBlank { pid })); applied = time }
                                        .onFailure { applyErr = it }
                                }
                            }) { Text(stringResource(R.string.rectify_use)) }
                        }
                    }
                }
            }
        }
        applied?.let { Text(stringResource(R.string.rectify_applied, formatTime(it.take(5))), color = BrandColors.Good, textAlign = TextAlign.Center) }
        applyErr?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
    }
}
