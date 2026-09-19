package com.udhyath.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.filled.ViewModule
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

// ===========================================================================
// Client list with search + quick add
// ===========================================================================

@Composable
fun ClientsScreen(nav: NavHostController) {
    val g = LocalContext.current.graph
    val user by g.account.user.collectAsStateWithLifecycle()
    var state by remember { mutableStateOf<Load<List<Profile>>>(Load.Loading) }
    var q by remember { mutableStateOf("") }
    var tick by remember { mutableIntStateOf(0) }
    val localProfiles by g.account.profiles.collectAsStateWithLifecycle()
    LaunchedEffect(tick, localProfiles.size) { state = runCatching { g.api.clients() }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    Scaffold(
        topBar = {
            AppTopBar(stringResource(R.string.clients_title), actions = {
                AssistChip(onClick = { nav.navigate(Routes.PRO) }, leadingIcon = { Icon(Icons.Default.Verified, null) },
                    label = { Text(stringResource(if (user?.isPro == true) R.string.pro_active_short else R.string.pro_get_short)) })
                Spacer(Modifier.width(8.dp))
            })
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.profileEdit(relation = "client")) },
                icon = { Icon(Icons.Default.Add, null) }, text = { Text(stringResource(R.string.client_add)) })
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            OutlinedTextField(q, { q = it }, Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                placeholder = { Text(stringResource(R.string.clients_search)) }, singleLine = true,
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) })
            when (val s = state) {
                Load.Loading -> LoadingBox()
                is Load.Err -> ErrorBox(s.error, onRetry = { tick++ })
                is Load.Ok -> {
                    val needle = q.trim().lowercase()
                    val list = s.data.filter { needle.isEmpty() || it.name.lowercase().contains(needle) ||
                        it.birth.place.lowercase().contains(needle) || it.notes.orEmpty().lowercase().contains(needle) }
                        .sortedBy { it.name.lowercase() }
                    if (list.isEmpty()) EmptyBox(stringResource(if (s.data.isEmpty()) R.string.clients_empty else R.string.clients_no_match))
                    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(list, key = { it.id }) { c ->
                            SectionCard(Modifier.clickable { nav.navigate("client/${c.id}") }) {
                                Text(c.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                                Text("${formatDate(c.birth.date)} · ${if (c.time_known) formatTime(c.birth.time) else stringResource(R.string.time_unknown_short)} · ${c.birth.place}",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                c.notes?.takeIf { it.isNotBlank() }?.let { Text(it, maxLines = 2, style = MaterialTheme.typography.bodyMedium) }
                            }
                        }
                        item { Spacer(Modifier.height(72.dp)) }
                    }
                }
            }
        }
    }
}

// ===========================================================================
// Client detail: notes + tools
// ===========================================================================

@Composable
fun ClientDetailScreen(nav: NavHostController, pid: String) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    var client by remember { mutableStateOf<Load<Profile>>(Load.Loading) }
    var notes by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(pid, tick) {
        client = runCatching { g.api.profile(pid) }.fold({ Load.Ok(it.copy(id = it.id.ifBlank { pid })).also { r -> notes = r.data.notes.orEmpty(); g.account.upsertLocal(r.data) } }, { Load.Err(it) })
    }
    ScreenScaffold(client.dataOrNull?.name ?: stringResource(R.string.client_title), onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = { nav.navigate(Routes.profileEdit(pid)) }) { Icon(Icons.Default.Edit, contentDescription = stringResource(R.string.profile_edit_title)) }
    }) {
        LoadView(client, onRetry = { tick++ }) { c ->
            SectionCard {
                KeyValue(stringResource(R.string.k_date), formatDate(c.birth.date))
                KeyValue(stringResource(R.string.k_time), if (c.time_known) formatTime(c.birth.time) else stringResource(R.string.time_unknown_short))
                KeyValue(stringResource(R.string.field_birth_place), c.birth.place)
            }
            val tools = listOf(
                Triple(Icons.Default.WbSunny, R.string.qa_charts) { nav.navigate(Routes.charts(c.id)) },
                Triple(Icons.Default.ViewModule, R.string.pro_bundle) { nav.navigate("pro_bundle/${c.id}") },
                Triple(Icons.AutoMirrored.Filled.Chat, R.string.qa_ask) { nav.navigate(Routes.chat(pid = c.id)) },
                Triple(Icons.Default.AutoStories, R.string.qa_report) { nav.navigate(Routes.reports(c.id)) },
                Triple(Icons.Default.Favorite, R.string.qa_matching) { nav.navigate(Routes.MATCHING) },
            )
            tools.forEach { (icon, label, go) ->
                OutlinedCard(onClick = go, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Text(stringResource(label), style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
            SectionCard(title = stringResource(R.string.field_notes)) {
                OutlinedTextField(notes, { notes = it; saved = false }, modifier = Modifier.fillMaxWidth(), minLines = 4)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Button(enabled = !saving, onClick = {
                        saving = true; err = null
                        scope.launch {
                            runCatching { g.api.updateClientNotes(pid, notes) }.onSuccess { saved = true }.onFailure { err = it }
                            saving = false
                        }
                    }) { Text(stringResource(R.string.save)) }
                    Spacer(Modifier.width(12.dp))
                    if (saved) Text(stringResource(R.string.saved), color = BrandColors.Good)
                }
                err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

// ===========================================================================
// Pro bundle: all vargas, KP, Shadbala, Ashtakavarga, dashas — dense layouts
// ===========================================================================

@Composable
fun ProBundleScreen(nav: NavHostController, pid: String) {
    val g = LocalContext.current.graph
    val user by g.account.user.collectAsStateWithLifecycle()
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    var state by remember { mutableStateOf<Load<JsonObject>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(pid, tick, user?.isPro) {
        if (user?.isPro == true) state = runCatching { g.api.proBundle(pid) }.fold({ Load.Ok(it) }, { Load.Err(it) })
    }
    ScreenScaffold(stringResource(R.string.pro_bundle), onBack = { nav.popBackStack() }) {
        if (user?.isPro != true) { ProLockedCard { nav.navigate(Routes.PRO) }; return@ScreenScaffold }
        LoadView(state, onRetry = { tick++ }) { bundle ->
            bundle.forEach { (k, v) ->
                var open by remember(k) { mutableStateOf(k.contains("varga") || k == "kp") }
                SectionCard {
                    Row(Modifier.fillMaxWidth().clickable { open = !open }, verticalAlignment = Alignment.CenterVertically) {
                        Text(proSectionLabel(k), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.secondary, modifier = Modifier.weight(1f))
                        Icon(if (open) Icons.Default.ExpandLess else Icons.Default.ExpandMore, contentDescription = null)
                    }
                    if (open) {
                        val vo = v as? JsonObject
                        if (k.contains("varga") && vo != null) {
                            // Two-up grid of divisional charts.
                            vo.entries.chunked(2).forEach { row ->
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    row.forEach { (name, chart) ->
                                        Box(Modifier.weight(1f)) {
                                            val c = (chart as? JsonObject)?.let { extractChart(JsonObject(mapOf("chart" to it))) ?: extractChart(it) }
                                            if (c != null) ChartDrawing(c, name, settings.chartStyle) else Column { Text(name); JsonView(chart, dense = true) }
                                        }
                                    }
                                    if (row.size == 1) Spacer(Modifier.weight(1f))
                                }
                            }
                        } else JsonView(v, dense = true)
                    }
                }
            }
        }
    }
}

@Composable
private fun proSectionLabel(k: String): String = when {
    k.contains("varga") -> stringResource(R.string.tab_vargas)
    k == "kp" -> stringResource(R.string.tab_kp)
    k.contains("shadbala") -> stringResource(R.string.tab_shadbala)
    k.contains("ashtaka") -> stringResource(R.string.tab_ashtakavarga)
    k.contains("dasha") -> stringResource(R.string.tab_dashas)
    else -> keyLabel(k)
}

// ===========================================================================
// Brand settings (white-label PDFs)
// ===========================================================================

@Composable
fun BrandScreen(onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf<Load<Brand>>(Load.Loading) }
    var b by remember { mutableStateOf(Brand()) }
    var busy by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf<String?>(null) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    val savedMsg = stringResource(R.string.saved)
    LaunchedEffect(tick) {
        state = runCatching { g.api.brand() }.recoverCatching { if (it.errorKind() == ErrorKind.NOT_FOUND) Brand() else throw it }
            .fold({ b = it; Load.Ok(it) }, { Load.Err(it) })
    }
    ScreenScaffold(stringResource(R.string.brand_title), onBack = onBack) {
        Text(stringResource(R.string.brand_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        LoadView(state, onRetry = { tick++ }) {
            OutlinedTextField(b.display_name, { b = b.copy(display_name = it) }, label = { Text(stringResource(R.string.brand_name)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(b.phone, { b = b.copy(phone = it) }, label = { Text(stringResource(R.string.brand_phone)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(b.logo_url, { b = b.copy(logo_url = it) }, label = { Text(stringResource(R.string.brand_logo)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(b.footer, { b = b.copy(footer = it) }, label = { Text(stringResource(R.string.brand_footer)) }, modifier = Modifier.fillMaxWidth(), minLines = 2)
            BigButton(stringResource(R.string.save), busy = busy, icon = Icons.Default.Badge, onClick = {
                busy = true; err = null; msg = null
                scope.launch { runCatching { g.api.saveBrand(b) }.onSuccess { msg = savedMsg }.onFailure { err = it }; busy = false }
            })
            msg?.let { Text(it, color = BrandColors.Good) }
            err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        }
    }
}

// ===========================================================================
// Pro plan purchase (debits the wallet)
// ===========================================================================

@Composable
fun ProPlanScreen(nav: NavHostController, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    val user by g.account.user.collectAsStateWithLifecycle()
    val pricing by g.account.pricing.collectAsStateWithLifecycle()
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var topUp by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    fun buy() {
        busy = true; err = null
        scope.launch {
            try { g.api.buyPro(); g.account.refreshMe() }
            catch (e: Exception) { if (e.errorKind() == ErrorKind.INSUFFICIENT_BALANCE) topUp = true else err = e }
            finally { busy = false }
        }
    }
    if (topUp) TopUpSheet(stringResource(R.string.topup_reason_pro, rupees(pricing.pro_plan_units)), onDismiss = { topUp = false },
        onCredited = { topUp = false; buy() })
    if (confirm) AlertDialog(onDismissRequest = { confirm = false },
        title = { Text(stringResource(R.string.pro_title)) },
        text = { Text(stringResource(R.string.pro_confirm, rupees(pricing.pro_plan_units), pricing.pro_plan_days)) },
        confirmButton = { TextButton(onClick = { confirm = false; buy() }) { Text(stringResource(R.string.pro_buy_short)) } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text(stringResource(R.string.cancel)) } })

    ScreenScaffold(stringResource(R.string.pro_title), onBack = onBack) {
        SectionCard(accent = true) {
            Text(stringResource(R.string.pro_price, rupees(pricing.pro_plan_units), pricing.pro_plan_days),
                style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            listOf(R.string.pro_feat_vargas, R.string.pro_feat_kp, R.string.pro_feat_strength, R.string.pro_feat_bundle, R.string.pro_feat_brand)
                .forEach { Row { Text("✓  ", color = BrandColors.Good); Text(stringResource(it)) } }
        }
        if (user?.isPro == true) {
            SectionCard { Text(stringResource(R.string.pro_active_until, formatDateTime(user?.plan_expires_at))) }
            BigButton(stringResource(R.string.pro_extend), onClick = { confirm = true }, busy = busy, secondary = true)
        } else BigButton(stringResource(R.string.pro_buy, rupees(pricing.pro_plan_units)), onClick = { confirm = true }, busy = busy)
        err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        OutlinedButton(onClick = { nav.navigate(Routes.BRAND) }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.brand_title)) }
    }
}
