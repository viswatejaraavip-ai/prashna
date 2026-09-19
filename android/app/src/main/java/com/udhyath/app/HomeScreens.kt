package com.udhyath.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.AccessTime
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

// ===========================================================================
// Home — daily card, transit alerts preview, quick actions
// ===========================================================================

class HomeVm(private val g: AppGraph) : ViewModel() {
    val daily = MutableStateFlow<Load<JsonObject>>(Load.Loading)
    val alerts = MutableStateFlow<Load<List<JsonElement>>>(Load.Loading)
    private var loadedFor: String? = null

    fun load(pid: String?, force: Boolean = false) {
        if (!force && pid == loadedFor) return
        loadedFor = pid
        viewModelScope.launch {
            daily.value = Load.Loading
            daily.value = runCatching { g.api.daily(pid) }.fold({ Load.Ok(it) }, { Load.Err(it) })
        }
        if (pid != null) viewModelScope.launch {
            alerts.value = Load.Loading
            alerts.value = runCatching { g.api.alerts(pid).itemsList("alerts") }.fold({ Load.Ok(it) }, { Load.Err(it) })
        }
    }
}

@Composable
fun HomeScreen(nav: NavHostController) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val vm = graphViewModel { HomeVm(it) }
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val family = profiles.filter { it.relation != "client" }
    val active = family.firstOrNull { it.id == settings.activeProfileId } ?: family.firstOrNull()
    val daily by vm.daily.collectAsStateWithLifecycle()
    val alerts by vm.alerts.collectAsStateWithLifecycle()
    val balance by AppEvents.balance.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var sharing by remember { mutableStateOf(false) }
    var shareErr by remember { mutableStateOf<Throwable?>(null) }

    LaunchedEffect(active?.id) { vm.load(active?.id) }

    Scaffold(
        topBar = {
            AppTopBar(stringResource(R.string.app_name), actions = {
                AssistChip(onClick = { nav.navigate(Routes.WALLET) },
                    label = { Text(balance?.let { rupees(it) } ?: "—") },
                    leadingIcon = { Icon(Icons.Default.AccountBalanceWallet, contentDescription = null) },
                    modifier = Modifier.semantics { contentDescription = ctx.getString(R.string.cd_wallet_balance, balance?.let { rupees(it) } ?: "") })
                Spacer(Modifier.width(8.dp))
            })
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            ProfileSwitcher(family, active, onPick = { scope.launch { g.settings.setActiveProfile(it.id) } },
                onManage = { nav.navigate(Routes.PROFILES) })

            // --- Daily card
            SectionCard(title = stringResource(R.string.home_today), accent = true) {
                LoadView(daily, onRetry = { vm.load(active?.id, force = true) }) { d -> DailyCard(d) }
                if (active != null) Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                    TextButton(enabled = !sharing, onClick = {
                        sharing = true; shareErr = null
                        scope.launch {
                            try {
                                val url = g.api.shareCard(active.id, "daily")
                                val bytes = g.api.download(url)
                                shareFile(ctx, bytes, "prashna-daily.png", "image/png", ctx.getString(R.string.share_daily_text))
                            } catch (e: Exception) { shareErr = e } finally { sharing = false }
                        }
                    }) {
                        Icon(Icons.Default.Share, contentDescription = null); Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.share_whatsapp))
                    }
                }
                shareErr?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
            }

            // --- Quick actions
            val actions = listOf(
                QuickAction(Icons.AutoMirrored.Filled.Chat, R.string.qa_ask) { nav.navigate(Routes.chat(pid = active?.id)) },
                QuickAction(Icons.Default.Mic, R.string.qa_talk) { nav.navigate(Routes.chat(pid = active?.id, voice = true)) },
                QuickAction(Icons.Default.WbSunny, R.string.qa_charts) { nav.navigate(Routes.charts(active?.id)) },
                QuickAction(Icons.Default.Favorite, R.string.qa_matching) { nav.navigate(Routes.MATCHING) },
                QuickAction(Icons.Default.Event, R.string.qa_muhurta) { nav.navigate(Routes.MUHURTA) },
                QuickAction(Icons.Default.AutoStories, R.string.qa_report) { nav.navigate(Routes.reports(active?.id)) },
                QuickAction(Icons.Default.AccessTime, R.string.qa_rectify) { active?.let { nav.navigate("rectify/${it.id}") } },
                QuickAction(Icons.Default.Groups, R.string.qa_family) { nav.navigate(Routes.PROFILES) },
            )
            QuickGrid(actions)

            // --- Transit alerts
            SectionCard(title = stringResource(R.string.home_alerts)) {
                when (val a = alerts) {
                    Load.Loading -> LoadingBox()
                    is Load.Err -> ErrorBox(a.error, onRetry = { vm.load(active?.id, force = true) })
                    is Load.Ok -> if (a.data.isEmpty()) Text(stringResource(R.string.alerts_none), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else {
                        a.data.take(2).forEach { AlertRow(it) }
                        if (active != null) TextButton(onClick = { nav.navigate("alerts/${active.id}") }) {
                            Text(stringResource(R.string.see_all))
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

/**
 * Today's personal forecast, panchanga and day timings, laid out from the
 * /api/daily shape. Row labels come localized from the server (`labels`),
 * so no engine field names ever reach the screen.
 */
@Composable
fun DailyCard(d: JsonObject) {
    val labels = d.child("labels")
    fun label(key: String) = labels?.str(key) ?: ""
    d.child("forecast")?.let { f ->
        f.str("title")?.let { Text(it, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
        f.str("rating_text")?.let { rt ->
            val color = when (f.str("rating")) {
                "good" -> MaterialTheme.colorScheme.tertiaryContainer
                "careful" -> MaterialTheme.colorScheme.errorContainer
                else -> MaterialTheme.colorScheme.secondaryContainer
            }
            Pill(rt, color)
        }
        f["lines"].arr()?.mapNotNull { (it as? JsonPrimitive)?.content }?.forEach {
            Text(it, style = MaterialTheme.typography.bodyLarge)
        }
        Spacer(Modifier.height(4.dp))
    }
    val pan = d.child("panchanga") ?: return
    val timings = pan.child("timings")
    timings?.child("rahu_kalam")?.let { rk ->
        Row(verticalAlignment = Alignment.CenterVertically) {
            Pill(label("rahu_kalam").ifBlank { stringResource(R.string.k_rahu_kalam) }, MaterialTheme.colorScheme.errorContainer)
            Spacer(Modifier.width(8.dp))
            Text(span(rk), fontWeight = FontWeight.SemiBold)
        }
    }
    HorizontalDivider()
    val tithi = pan.child("tithi")
    val rows = listOfNotNull(
        tithi?.let { label("tithi") to listOfNotNull(it.str("paksha_local"), it.str("local")).joinToString(" ") },
        pan.child("vara")?.str("local")?.let { label("vara") to it },
        pan.child("nakshatra")?.let { n -> label("nakshatra_short") to (n.str("local") ?: "") },
        pan.child("yoga")?.str("local")?.let { label("yoga") to it },
        pan.child("karana")?.str("local")?.let { label("karana") to it },
        pan.child("moon_sign")?.str("local")?.let { label("moon_sign") to it },
        timings?.str("sunrise")?.let { label("sunrise") to it },
        timings?.str("sunset")?.let { label("sunset") to it },
        timings?.child("yamagandam")?.let { label("yamagandam") to span(it) },
        timings?.child("gulika")?.let { label("gulika") to span(it) },
        timings?.child("abhijit")?.let { label("abhijit") to span(it) },
    ).filter { it.first.isNotBlank() && it.second.isNotBlank() }
    rows.forEach { (k, v) -> KeyValue(k, v) }
}

private fun span(o: JsonObject): String = listOfNotNull(o.str("start"), o.str("end")).joinToString(" – ")

private data class QuickAction(val icon: ImageVector, val label: Int, val onClick: () -> Unit)

@Composable
private fun QuickGrid(items: List<QuickAction>) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.chunked(4).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { a ->
                    val label = stringResource(a.label)
                    Card(onClick = a.onClick, modifier = Modifier.weight(1f).heightIn(min = 92.dp)
                        .semantics(mergeDescendants = true) { contentDescription = label },
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                        Column(Modifier.fillMaxWidth().padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center) {
                            Icon(a.icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(30.dp))
                            Spacer(Modifier.height(6.dp))
                            Text(label, style = MaterialTheme.typography.labelMedium, textAlign = TextAlign.Center, maxLines = 2)
                        }
                    }
                }
                repeat(4 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
fun AlertRow(el: JsonElement) {
    val o = el.obj()
    if (o == null) { Text(el.displayText()); return }
    val title = o.str("title", "kind", "type", "name") ?: ""
    val when_ = listOfNotNull(o.str("date", "start", "from"), o.str("end", "to")).joinToString(" – ")
    val desc = o.str("description", "text", "summary", "line")
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.Top) {
        Icon(Icons.Default.NotificationsActive, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            if (when_.isNotBlank()) Text(when_.let { formatMaybeDate(it) }, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (desc != null) Text(desc, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private fun formatMaybeDate(s: String): String =
    s.split(" – ").joinToString(" – ") { if (Regex("^\\d{4}-\\d{2}-\\d{2}").containsMatchIn(it)) formatDate(it) else it }

// ===========================================================================
// Family switcher + profile list
// ===========================================================================

@Composable
fun ProfileSwitcher(profiles: List<Profile>, active: Profile?, onPick: (Profile) -> Unit, onManage: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        val desc = stringResource(R.string.cd_switch_profile, active?.name ?: "")
        Surface(onClick = { open = true }, shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.secondaryContainer,
            modifier = Modifier.semantics { contentDescription = desc; this.role = Role.DropdownList }) {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(active?.name ?: stringResource(R.string.profile_none), style = MaterialTheme.typography.titleMedium)
                if (active != null) { Spacer(Modifier.width(6.dp)); Text("· " + relationLabel(active.relation), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                Icon(Icons.Default.ArrowDropDown, contentDescription = null)
            }
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            profiles.forEach { p ->
                DropdownMenuItem(text = { Text("${p.name} · ${relationLabel(p.relation)}") }, onClick = { open = false; onPick(p) })
            }
            HorizontalDivider()
            DropdownMenuItem(text = { Text(stringResource(R.string.family_manage)) }, leadingIcon = { Icon(Icons.Default.Groups, null) },
                onClick = { open = false; onManage() })
        }
    }
}

@Composable
fun ProfilesScreen(nav: NavHostController) {
    val g = LocalContext.current.graph
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val scope = rememberCoroutineScope()
    val family = profiles.filter { it.relation != "client" }
    LaunchedEffect(Unit) { runCatching { g.account.refreshProfiles() } }
    Scaffold(
        topBar = { AppTopBar(stringResource(R.string.family_title), onBack = { nav.popBackStack() }) },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.profileEdit()) },
                icon = { Icon(Icons.Default.Add, null) }, text = { Text(stringResource(R.string.family_add)) })
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (family.isEmpty()) EmptyBox(stringResource(R.string.family_empty))
            family.forEach { p ->
                val isActive = p.id == settings.activeProfileId
                SectionCard(accent = isActive, modifier = Modifier.clickable {
                    scope.launch { g.settings.setActiveProfile(p.id) }
                }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(p.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            Text("${relationLabel(p.relation)} · ${formatDate(p.birth.date)}" +
                                (if (p.time_known) " · " + formatTime(p.birth.time) else ""), color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(p.birth.place_local.ifBlank { p.birth.place }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            if (isActive) Pill(stringResource(R.string.profile_active))
                        }
                        IconButton(onClick = { nav.navigate(Routes.profileEdit(p.id)) }) {
                            Icon(Icons.Default.Edit, contentDescription = stringResource(R.string.cd_edit_profile, p.name))
                        }
                    }
                }
            }
            Spacer(Modifier.height(80.dp))
        }
    }
}

// ===========================================================================
// Transit alerts (next 180 days)
// ===========================================================================

@Composable
fun AlertsScreen(pid: String, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    var state by remember { mutableStateOf<Load<List<JsonElement>>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(pid, tick) {
        state = Load.Loading
        state = runCatching { g.api.alerts(pid).itemsList("alerts") }.fold({ Load.Ok(it) }, { Load.Err(it) })
    }
    ScreenScaffold(stringResource(R.string.alerts_title), onBack = onBack) {
        Text(stringResource(R.string.alerts_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        LoadView(state, onRetry = { tick++ }) { list ->
            if (list.isEmpty()) EmptyBox(stringResource(R.string.alerts_none))
            list.forEach { SectionCard { AlertRow(it) } }
        }
    }
}
