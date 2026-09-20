package com.udhyath.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

// ===========================================================================
// Chart data extraction (tolerant of the engine's several output shapes)
// ===========================================================================

val PLANET_KEYS = listOf("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu", "Lagna")
private val SIGN_EN = listOf("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces")
private val SIGN_SA = listOf("mesha", "vrishabha", "mithuna", "karka", "simha", "kanya", "tula", "vrishchika", "dhanu", "makara", "kumbha", "meena")

/** Sign index 0..11 from a name (English or Sanskrit, any case/prefix) or a 1-based number. */
fun signIndex(v: Any?): Int? {
    when (v) {
        is Int -> return if (v in 1..12) v - 1 else null
        is String -> {
            v.trim().toIntOrNull()?.let { return signIndex(it) }
            val s = v.trim().lowercase()
            SIGN_EN.indexOfFirst { s.startsWith(it.take(3)) }.takeIf { it >= 0 }?.let { return it }
            SIGN_SA.indexOfFirst { s.startsWith(it.take(4)) }.takeIf { it >= 0 }?.let { return it }
        }
    }
    return null
}

private fun planetKey(name: String): String? {
    val n = name.trim().lowercase()
    if (n in setOf("lagna", "ascendant", "asc", "la", "lg")) return "Lagna"
    return PLANET_KEYS.firstOrNull { it.lowercase() == n || it.lowercase().take(2) == n }
}

data class ChartData(val lagna: Int, val bySign: Map<Int, List<String>>, val retro: Set<String> = emptySet())

private fun signOfEntry(v: kotlinx.serialization.json.JsonElement): Int? = when (v) {
    is JsonPrimitive -> v.intOrNull?.let { signIndex(it) } ?: signIndex(v.content)
    is JsonObject -> v.str("sign", "rasi", "sign_name")?.let { signIndex(it) }
        ?: v.int("sign_num", "sign_index", "rasi_num")?.let { signIndex(it) }
    else -> null
}

fun extractChart(root: JsonObject): ChartData? {
    // Candidate containers, most specific first.
    val candidates = listOfNotNull(
        root.child("chart"), root.child("placements"), root.child("positions"), root.child("planets"),
        root.child("rasi"), root.child("navamsa"), root.child("varga"), root,
    )
    for (c in candidates) {
        val bySign = mutableMapOf<Int, MutableList<String>>()
        val retro = mutableSetOf<String>()
        var lagna: Int? = null
        c.forEach { (k, v) ->
            val pk = planetKey(k) ?: return@forEach
            val si = signOfEntry(v) ?: return@forEach
            if (pk == "Lagna") lagna = si
            bySign.getOrPut(si) { mutableListOf() }.add(pk)
            if ((v as? JsonObject)?.bool("retrograde", "retro") == true) retro += pk
        }
        // Planets as an array of {planet|name, sign}
        (c["planets"] as? JsonArray)?.forEach { el ->
            val o = el as? JsonObject ?: return@forEach
            val pk = o.str("planet", "name", "graha")?.let { planetKey(it) } ?: return@forEach
            val si = signOfEntry(o) ?: return@forEach
            if (pk == "Lagna") lagna = si
            bySign.getOrPut(si) { mutableListOf() }.add(pk)
            if (o.bool("retrograde", "retro") == true) retro += pk
        }
        if (lagna == null) {
            lagna = (root["ascendant"] ?: root["lagna"] ?: c["ascendant"] ?: c["lagna"])?.let { signOfEntry(it) }
            lagna?.let { l -> if (bySign.values.none { "Lagna" in it }) bySign.getOrPut(l) { mutableListOf() }.add("Lagna") }
        }
        if (bySign.values.sumOf { it.size } >= 5 && lagna != null) return ChartData(lagna!!, bySign, retro)
    }
    return null
}

// ===========================================================================
// Chart drawings — South Indian (fixed signs) and North Indian (fixed houses)
// ===========================================================================

@Composable
private fun planetLabels(): Map<String, String> {
    val abbr = stringArrayResource(R.array.planet_abbr)
    return PLANET_KEYS.mapIndexed { i, k -> k to abbr.getOrElse(i) { k.take(2) } }.toMap()
}

@Composable
private fun chartDescription(c: ChartData, title: String): String {
    val signs = stringArrayResource(R.array.sign_names)
    val names = stringArrayResource(R.array.planet_names)
    val parts = c.bySign.entries.sortedBy { it.key }.joinToString("; ") { (s, ps) ->
        signs[s] + ": " + ps.joinToString(", ") { p -> names.getOrNull(PLANET_KEYS.indexOf(p)) ?: p }
    }
    return stringResource(R.string.cd_chart, title, signs[c.lagna], parts)
}

@Composable
fun SouthChart(c: ChartData, title: String, modifier: Modifier = Modifier) {
    val labels = planetLabels()
    val signs = stringArrayResource(R.array.sign_names)
    val desc = chartDescription(c, title)
    // Sign index → (row, col) in the 4x4 frame (Pisces top-left, clockwise).
    val pos = mapOf(11 to (0 to 0), 0 to (0 to 1), 1 to (0 to 2), 2 to (0 to 3), 10 to (1 to 0), 3 to (1 to 3),
        9 to (2 to 0), 4 to (2 to 3), 8 to (3 to 0), 7 to (3 to 1), 6 to (3 to 2), 5 to (3 to 3))
    val line = MaterialTheme.colorScheme.outline
    Column(modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = desc }) {
        for (r in 0..3) Row(Modifier.fillMaxWidth().aspectRatio(4f)) {
            for (col in 0..3) {
                val sign = pos.entries.firstOrNull { it.value == (r to col) }?.key
                if (sign == null) {
                    if (r == 1 && col == 1) Box(Modifier.weight(2f).fillMaxHeight(), contentAlignment = Alignment.Center) {
                        Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.secondary, textAlign = TextAlign.Center)
                    } else if (r == 1 || r == 2) { if (col == 1) Spacer(Modifier.weight(2f)) }
                    continue
                }
                val isLagna = sign == c.lagna
                Column(Modifier.weight(1f).fillMaxHeight().padding(1.dp)
                    .background(if (isLagna) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface, RoundedCornerShape(4.dp))
                    .border(if (isLagna) 2.dp else 1.dp, if (isLagna) MaterialTheme.colorScheme.primary else line, RoundedCornerShape(4.dp))
                    .padding(3.dp)) {
                    Text(signs[sign], style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    Text(c.bySign[sign].orEmpty().joinToString(" ") { labels[it] + if (it in c.retro) "ᴿ" else "" },
                        style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.secondary)
                }
            }
        }
    }
}

@Composable
fun NorthChart(c: ChartData, title: String, modifier: Modifier = Modifier) {
    val labels = planetLabels()
    val desc = chartDescription(c, title)
    val measurer = rememberTextMeasurer()
    val lineColor = MaterialTheme.colorScheme.secondary
    val textColor = MaterialTheme.colorScheme.onSurface
    val numColor = MaterialTheme.colorScheme.primary
    val scale = LocalTextScale.current
    // House centres (unit square), house 1 = top diamond, anticlockwise.
    val centres = listOf(0.5f to 0.27f, 0.25f to 0.11f, 0.11f to 0.25f, 0.27f to 0.5f, 0.11f to 0.75f, 0.25f to 0.89f,
        0.5f to 0.73f, 0.75f to 0.89f, 0.89f to 0.75f, 0.73f to 0.5f, 0.89f to 0.25f, 0.75f to 0.11f)
    val numPos = listOf(0.5f to 0.43f, 0.25f to 0.2f, 0.2f to 0.25f, 0.43f to 0.5f, 0.2f to 0.75f, 0.25f to 0.8f,
        0.5f to 0.57f, 0.75f to 0.8f, 0.8f to 0.75f, 0.57f to 0.5f, 0.8f to 0.25f, 0.75f to 0.2f)
    Column(modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.secondary,
            modifier = Modifier.align(Alignment.CenterHorizontally))
        Canvas(Modifier.fillMaxWidth().aspectRatio(1f).semantics { contentDescription = desc }) {
            val w = size.width; val h = size.height
            val st = Stroke(width = 2.dp.toPx())
            drawRect(lineColor, style = st)
            drawLine(lineColor, Offset(0f, 0f), Offset(w, h), 2.dp.toPx())
            drawLine(lineColor, Offset(w, 0f), Offset(0f, h), 2.dp.toPx())
            drawLine(lineColor, Offset(w / 2, 0f), Offset(w, h / 2), 2.dp.toPx())
            drawLine(lineColor, Offset(w, h / 2), Offset(w / 2, h), 2.dp.toPx())
            drawLine(lineColor, Offset(w / 2, h), Offset(0f, h / 2), 2.dp.toPx())
            drawLine(lineColor, Offset(0f, h / 2), Offset(w / 2, 0f), 2.dp.toPx())
            for (house in 0 until 12) {
                val sign = (c.lagna + house) % 12
                val (nx, ny) = numPos[house]
                val num = measurer.measure("${sign + 1}", TextStyle(fontSize = (11 * scale).sp, color = numColor))
                drawText(num, topLeft = Offset(nx * w - num.size.width / 2f, ny * h - num.size.height / 2f))
                val planets = c.bySign[sign].orEmpty().filter { it != "Lagna" }
                    .joinToString(" ") { labels[it] + if (it in c.retro) "ᴿ" else "" }
                val txt = if (house == 0) (labels["Lagna"] + if (planets.isNotEmpty()) " $planets" else "") else planets
                if (txt.isBlank()) continue
                val (cx, cy) = centres[house]
                val m = measurer.measure(txt, TextStyle(fontSize = (13 * scale).sp, fontWeight = FontWeight.SemiBold, color = textColor,
                    textAlign = TextAlign.Center), constraints = androidx.compose.ui.unit.Constraints(maxWidth = (w * 0.22f).toInt()))
                drawText(m, topLeft = Offset(cx * w - m.size.width / 2f, cy * h - m.size.height / 2f))
            }
        }
    }
}

@Composable
fun ChartDrawing(c: ChartData, title: String, style: String) {
    if (style == "north") NorthChart(c, title) else SouthChart(c, title)
}

// ===========================================================================
// Charts screen
// ===========================================================================

/** One tab: API kind (+division) and whether it's a Pro (astrologer) view. */
data class ChartTab(val kind: String, val division: String? = null, val label: Int, val pro: Boolean = false)

val BASIC_TABS = listOf(
    ChartTab("rasi", label = R.string.tab_rasi),
    ChartTab("navamsa", label = R.string.tab_navamsa),
    ChartTab("dashas", label = R.string.tab_dashas),
    ChartTab("yogas", label = R.string.tab_yogas),
    ChartTab("doshas", label = R.string.tab_doshas),
    ChartTab("panchanga", label = R.string.tab_panchanga),
    ChartTab("bhava", label = R.string.tab_bhava),
    ChartTab("gemstones", label = R.string.tab_gemstones),
)
val PRO_TABS = listOf(
    ChartTab("varga", "all", R.string.tab_vargas, pro = true),
    ChartTab("kp", label = R.string.tab_kp, pro = true),
    ChartTab("shadbala", label = R.string.tab_shadbala, pro = true),
    ChartTab("ashtakavarga", label = R.string.tab_ashtakavarga, pro = true),
    ChartTab("nadi", label = R.string.tab_nadi, pro = true),
    ChartTab("varshphal", label = R.string.tab_varshphal, pro = true),
    ChartTab("lalkitab", label = R.string.tab_lalkitab, pro = true),
)

class ChartsVm(private val g: AppGraph) : ViewModel() {
    val state = MutableStateFlow<Load<JsonObject>>(Load.Loading)
    private val cache = mutableMapOf<String, JsonObject>()
    fun load(pid: String, tab: ChartTab, force: Boolean = false) {
        val key = "$pid/${tab.kind}/${tab.division}"
        if (!force) cache[key]?.let { state.value = Load.Ok(it); return }
        viewModelScope.launch {
            state.value = Load.Loading
            val year = if (tab.kind == "varshphal") java.time.LocalDate.now().year else null
            state.value = runCatching { g.api.chart(pid, tab.kind, tab.division, year) }
                .onSuccess { cache[key] = it }.fold({ Load.Ok(it) }, { Load.Err(it) })
        }
    }
}

@Composable
fun ChartsScreen(nav: NavHostController, pid: String?, showBack: Boolean) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val vm = graphViewModel(key = "charts-$pid") { ChartsVm(it) }
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val user by g.account.user.collectAsStateWithLifecycle()
    val astro = user?.isAstrologer == true
    // Clients are not in the family list (/api/profiles hides them), so when an
    // astrologer opens a client's charts by id we fetch that one profile rather
    // than silently falling back to somebody else's chart.
    var fetchFailed by remember(pid) { mutableStateOf<Throwable?>(null) }
    var fetchTick by remember(pid) { mutableIntStateOf(0) }
    LaunchedEffect(pid, profiles, fetchTick) {
        if (pid != null && profiles.none { it.id == pid }) {
            runCatching { g.api.profile(pid) }
                .onSuccess { g.account.upsertLocal(it.copy(id = it.id.ifBlank { pid })) }
                .onFailure { fetchFailed = it }
        }
    }
    val profile = if (pid != null) profiles.firstOrNull { it.id == pid }
    else profiles.firstOrNull { it.id == settings.activeProfileId } ?: profiles.firstOrNull { it.relation != "client" }
    val tabs = if (astro) BASIC_TABS + PRO_TABS else BASIC_TABS
    // Always open on Rasi (and again when switching person): a restored index
    // would be off-screen in the scrollable tab row with no visible selection.
    var tabIdx by remember(profile?.id) { mutableStateOf(0) }
    val tab = tabs[tabIdx.coerceIn(0, tabs.lastIndex)]
    val state by vm.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var sharing by remember { mutableStateOf(false) }
    val locked = tab.pro && user?.isPro != true

    LaunchedEffect(profile?.id, tab) { if (profile != null && !locked) vm.load(profile.id, tab) }

    Scaffold(topBar = {
        AppTopBar(profile?.name ?: stringResource(R.string.tab_charts), onBack = if (showBack || pid != null) ({ nav.popBackStack() }) else null, actions = {
            if (profile != null) IconButton(enabled = !sharing, onClick = {
                sharing = true
                scope.launch {
                    runCatching { g.api.download(g.api.shareCard(profile.id, "chart")) }
                        .onSuccess { shareFile(ctx, it, "prashna-chart.png", "image/png", ctx.getString(R.string.share_chart_text)) }
                    sharing = false
                }
            }) { Icon(Icons.Default.Share, contentDescription = stringResource(R.string.cd_share_chart)) }
        })
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (profile == null) {
                val err = fetchFailed
                when {
                    err != null -> ErrorBox(err, onRetry = { fetchFailed = null; fetchTick++ })
                    pid != null -> LoadingBox()
                    else -> EmptyBox(stringResource(R.string.profile_none))
                }
                return@Column
            }
            if (pid == null && !astro) {
                val family = profiles.filter { it.relation != "client" }
                Box(Modifier.padding(horizontal = 16.dp)) {
                    ProfileSwitcher(family, profile, onPick = { p -> scope.launch { g.settings.setActiveProfile(p.id) } },
                        onManage = { nav.navigate(Routes.PROFILES) })
                }
            }
            ScrollableTabRow(selectedTabIndex = tabIdx, edgePadding = 12.dp, containerColor = MaterialTheme.colorScheme.background) {
                tabs.forEachIndexed { i, t ->
                    Tab(selected = i == tabIdx, onClick = { tabIdx = i }, text = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (t.pro && user?.isPro != true) Icon(Icons.Default.Lock, contentDescription = null, modifier = Modifier.size(14.dp))
                            Text(stringResource(t.label))
                        }
                    })
                }
            }
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (!profile.time_known && tab.kind in setOf("rasi", "bhava", "navamsa")) {
                    Text(stringResource(R.string.time_unknown_chart_note), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (locked) {
                    ProLockedCard { nav.navigate(Routes.PRO) }
                } else {
                    val st = state
                    // Server enforces Pro for deep kinds for every role: 403 → upsell.
                    if (st is Load.Err && st.error.errorKind() == ErrorKind.FORBIDDEN) ProLockedCard { nav.navigate(Routes.PRO) }
                    else LoadView(st, onRetry = { vm.load(profile.id, tab, force = true) }) { data ->
                        ChartTabBody(tab, data, settings.chartStyle, dense = astro) { style ->
                            scope.launch { g.settings.setChartStyle(style) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun rememberSaveableInt(initial: Int): MutableState<Int> =
    androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(initial) }

@Composable
fun ProLockedCard(onGetPro: () -> Unit) {
    SectionCard(accent = true) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Lock, contentDescription = null, tint = MaterialTheme.colorScheme.secondary)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.pro_locked), style = MaterialTheme.typography.titleMedium)
        }
        Text(stringResource(R.string.pro_locked_desc))
        BigButton(stringResource(R.string.pro_get), onClick = onGetPro)
    }
}

@Composable
fun ChartTabBody(tab: ChartTab, data: JsonObject, style: String, dense: Boolean, onStyle: (String) -> Unit) {
    // Current server: a display-ready, localized `view`.
    data.child("view")?.let { view ->
        val main = chartFromView(view.child("chart"))
        val many = (view["charts"] as? JsonArray)?.mapNotNull { el ->
            val o = el as? JsonObject ?: return@mapNotNull null
            chartFromView(o.child("chart"))?.let { (o.str("title") ?: "") to it }
        }.orEmpty()
        if (main != null || many.isNotEmpty()) {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                listOf("south" to R.string.chart_south, "north" to R.string.chart_north).forEachIndexed { i, (k, l) ->
                    SegmentedButton(selected = style == k, onClick = { onStyle(k) }, shape = SegmentedButtonDefaults.itemShape(i, 2)) {
                        Text(stringResource(l))
                    }
                }
            }
        }
        if (main != null) SectionCard { ChartDrawing(main, stringResource(tab.label), style) }
        many.forEach { (title, c) -> SectionCard(title = title) { ChartDrawing(c, title, style) } }
        ViewSections(view, dense)
        return
    }
    val chart = if (tab.kind in setOf("rasi", "navamsa", "bhava")) extractChart(data) else null
    if (chart != null) {
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            listOf("south" to R.string.chart_south, "north" to R.string.chart_north).forEachIndexed { i, (k, l) ->
                SegmentedButton(selected = style == k, onClick = { onStyle(k) }, shape = SegmentedButtonDefaults.itemShape(i, 2)) {
                    Text(stringResource(l))
                }
            }
        }
        SectionCard { ChartDrawing(chart, stringResource(tab.label), style) }
    }
    // Multi-varga responses: draw each division's chart when we can read it.
    if (tab.kind == "varga") {
        val vargas = data.child("vargas", "all_vargas", "charts") ?: data
        vargas.forEach { (name, v) ->
            val vo = v as? JsonObject ?: return@forEach
            val c = extractChart(JsonObject(mapOf("chart" to vo))) ?: extractChart(vo)
            SectionCard(title = name) {
                if (c != null) ChartDrawing(c, name, style)
            }
        }
        return
    }
    val rest = if (chart != null) JsonObject(data.filterKeys { it !in setOf("chart", "placements", "positions") }) else data
}
