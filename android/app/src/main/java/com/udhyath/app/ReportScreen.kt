package com.udhyath.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Toc
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

class ReportsVm(private val g: AppGraph) : ViewModel() {
    val reports = MutableStateFlow<Load<List<Report>>>(Load.Loading)
    val teaser = MutableStateFlow<Load<JsonObject>?>(null)
    val buying = MutableStateFlow(false)
    val buyError = MutableStateFlow<Throwable?>(null)
    val needTopUp = MutableStateFlow(false)
    private var pendingBuy: Pair<String, Boolean>? = null

    init {
        refresh()
        // Poll while anything is generating (the screen is open).
        viewModelScope.launch {
            while (isActive) {
                delay(20_000)
                if (reports.value.dataOrNull?.any { it.status == "generating" } == true) refresh(quiet = true)
            }
        }
    }

    fun refresh(quiet: Boolean = false) {
        viewModelScope.launch {
            if (!quiet) reports.value = Load.Loading
            runCatching { g.api.reports() }.onSuccess { reports.value = Load.Ok(it) }.onFailure { if (!quiet) reports.value = Load.Err(it) }
        }
    }

    fun loadTeaser(pid: String) {
        teaser.value = Load.Loading
        viewModelScope.launch { teaser.value = runCatching { g.api.teaser(pid) }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    }

    fun buy(pid: String, brand: Boolean) {
        buying.value = true; buyError.value = null
        viewModelScope.launch {
            try {
                val r = g.api.createReport(pid, brand)
                if (r.id.isNotBlank()) ReportWatchWorker.watch(g.app, r.id)
                refresh()
            } catch (e: Exception) {
                if (e.errorKind() == ErrorKind.INSUFFICIENT_BALANCE) { pendingBuy = pid to brand; needTopUp.value = true }
                else buyError.value = e
            } finally { buying.value = false }
        }
    }

    fun resume(id: String) {
        buying.value = true; buyError.value = null
        viewModelScope.launch {
            try { g.api.resumeReport(id); ReportWatchWorker.watch(g.app, id); refresh() }
            catch (e: Exception) { if (e.errorKind() == ErrorKind.INSUFFICIENT_BALANCE) needTopUp.value = true else buyError.value = e }
            finally { buying.value = false }
        }
    }

    fun onToppedUp() { needTopUp.value = false; pendingBuy?.let { (p, b) -> pendingBuy = null; buy(p, b) } }
    fun dismissTopUp() { needTopUp.value = false; pendingBuy = null }
}

@Composable
fun ReportsScreen(nav: NavHostController, pid: String?) {
    val g = LocalContext.current.graph
    val vm = graphViewModel { ReportsVm(it) }
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val user by g.account.user.collectAsStateWithLifecycle()
    val pricing by g.account.pricing.collectAsStateWithLifecycle()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val astro = user?.isAstrologer == true
    var clients by remember { mutableStateOf<List<Profile>>(emptyList()) }
    LaunchedEffect(astro) { if (astro) clients = runCatching { g.api.clients() }.getOrDefault(emptyList()) }
    val options = if (astro) (clients + profiles).distinctBy { it.id } else profiles.filter { it.relation != "client" }
    var selected by remember(pid, options.size) {
        mutableStateOf(options.firstOrNull { it.id == (pid ?: settings.activeProfileId) } ?: options.firstOrNull())
    }
    val reports by vm.reports.collectAsStateWithLifecycle()
    val teaser by vm.teaser.collectAsStateWithLifecycle()
    val buying by vm.buying.collectAsStateWithLifecycle()
    val buyError by vm.buyError.collectAsStateWithLifecycle()
    val needTopUp by vm.needTopUp.collectAsStateWithLifecycle()
    var confirm by remember { mutableStateOf(false) }
    var branded by remember { mutableStateOf(astro) }

    if (needTopUp) TopUpSheet(reason = stringResource(R.string.topup_reason_report, rupees(pricing.report_price_units)),
        onDismiss = { vm.dismissTopUp() }, onCredited = { vm.onToppedUp() })

    if (confirm) selected?.let { p ->
        AlertDialog(onDismissRequest = { confirm = false },
            title = { Text(stringResource(R.string.report_confirm_title)) },
            text = { Text(stringResource(R.string.report_confirm_body, p.name, rupees(pricing.report_price_units))) },
            confirmButton = { TextButton(onClick = { confirm = false; vm.buy(p.id, astro && branded) }) { Text(stringResource(R.string.report_buy_short)) } },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text(stringResource(R.string.cancel)) } })
    }

    ScreenScaffold(stringResource(R.string.report_title), onBack = if (pid != null) ({ nav.popBackStack() }) else null) {
        SectionCard(accent = true) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.AutoStories, contentDescription = null, tint = MaterialTheme.colorScheme.secondary)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.report_headline), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            }
            Text(stringResource(R.string.report_pitch))
            ProfilePicker(stringResource(R.string.report_for), options, selected) { selected = it; vm.teaser.value = null }
        }

        // Free teaser chapter
        SectionCard(title = stringResource(R.string.report_teaser_title)) {
            when (val t = teaser) {
                null -> BigButton(stringResource(R.string.report_teaser_cta), secondary = true, enabled = selected != null,
                    onClick = { selected?.let { vm.loadTeaser(it.id) } })
                else -> LoadView(t, onRetry = { selected?.let { vm.loadTeaser(it.id) } }) { TeaserBody(it) }
            }
        }

        if (astro) Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(branded, { branded = it }); Spacer(Modifier.width(8.dp)); Text(stringResource(R.string.report_branded))
        }
        BigButton(stringResource(R.string.report_buy, rupees(pricing.report_price_units)), enabled = selected != null, busy = buying,
            onClick = { confirm = true })
        buyError?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }

        Text(stringResource(R.string.report_mine), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        LoadView(reports, onRetry = { vm.refresh() }) { list ->
            if (list.isEmpty()) EmptyBox(stringResource(R.string.report_none))
            list.forEach { r -> ReportRow(r, profiles + clients, onOpen = { nav.navigate("report/${r.id}") }, onResume = { vm.resume(r.id) },
                onRefund = { nav.navigate(Routes.refunds("report:${r.id}")) }) }
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun TeaserBody(t: JsonObject) {
    val chapter = t.child("chapter", "teaser_chapter")
    val title = chapter?.str("title") ?: t.str("title")
    val body = chapter?.str("content", "text") ?: t.str("teaser", "content", "text")
    if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    if (body != null) MarkdownText(body)
    t.child("full_report")?.let { fr ->
        val chapters = fr.list("chapters")
        if (chapters != null) {
            Text(stringResource(R.string.report_chapters_count, chapters.size), style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 8.dp))
            chapters.take(18).forEachIndexed { i, c -> Text("${i + 1}. ${c.displayText()}", style = MaterialTheme.typography.bodyMedium) }
        }
        fr.str("delivery")?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
private fun ReportRow(r: Report, people: List<Profile>, onOpen: () -> Unit, onResume: () -> Unit, onRefund: () -> Unit) {
    val who = people.firstOrNull { it.id == r.profile_id }?.name
    SectionCard(Modifier.clickable(enabled = r.status != "failed", onClick = onOpen)) {
        Text(listOfNotNull(who, formatDateTime(r.created_at)).joinToString(" · "), style = MaterialTheme.typography.labelLarge)
        when (r.status) {
            "generating", "queued", "pending" -> {
                Text(stringResource(R.string.report_generating, r.sections_done, r.sections_total))
                val total = r.sections_total.coerceAtLeast(1)
                LinearProgressIndicator(progress = { r.sections_done / total.toFloat() }, modifier = Modifier.fillMaxWidth())
                Text(stringResource(R.string.report_notify_note), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            "failed" -> {
                Text(stringResource(R.string.report_failed, r.sections_done, r.sections_total), color = MaterialTheme.colorScheme.error)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onResume) { Text(stringResource(R.string.report_resume)) }
                    OutlinedButton(onClick = onRefund) { Text(stringResource(R.string.refund_request)) }
                }
            }
            else -> Row(verticalAlignment = Alignment.CenterVertically) {
                Pill(stringResource(R.string.report_ready), MaterialTheme.colorScheme.primaryContainer)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onOpen) { Text(stringResource(R.string.report_read)) }
            }
        }
    }
}

// ===========================================================================
// Reader + PDF
// ===========================================================================

@Composable
fun ReportReaderScreen(id: String, onBack: () -> Unit) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf<Load<Report>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    var pdfBusy by remember { mutableStateOf(false) }
    var pdfErr by remember { mutableStateOf<Throwable?>(null) }
    var tocOpen by remember { mutableStateOf(false) }
    val list = rememberLazyListState()
    LaunchedEffect(id, tick) {
        state = runCatching { g.api.report(id) }.fold({ Load.Ok(it) }, { Load.Err(it) })
        while ((state as? Load.Ok)?.data?.status == "generating") {
            delay(20_000)
            runCatching { g.api.report(id) }.onSuccess { state = Load.Ok(it) }
        }
    }
    fun pdf(share: Boolean) {
        pdfBusy = true; pdfErr = null
        scope.launch {
            try {
                val bytes = g.api.download(g.api.reportPdf(id))
                if (share) shareFile(ctx, bytes, "prashna-report.pdf", "application/pdf") else viewFile(ctx, bytes, "prashna-report.pdf", "application/pdf")
            } catch (e: Exception) { pdfErr = e } finally { pdfBusy = false }
        }
    }
    val report = state.dataOrNull
    Scaffold(topBar = {
        AppTopBar(stringResource(R.string.report_title), onBack = onBack, actions = {
            if (report != null && report.sections.isNotEmpty()) IconButton(onClick = { tocOpen = true }) {
                Icon(Icons.Default.Toc, contentDescription = stringResource(R.string.report_toc))
            }
            if (report?.status == "ready") {
                IconButton(enabled = !pdfBusy, onClick = { pdf(false) }) { Icon(Icons.Default.PictureAsPdf, contentDescription = stringResource(R.string.report_pdf)) }
                IconButton(enabled = !pdfBusy, onClick = { pdf(true) }) { Icon(Icons.Default.Share, contentDescription = stringResource(R.string.report_share)) }
            }
        })
    }) { pad ->
        Box(Modifier.padding(pad).fillMaxSize()) {
            when (val s = state) {
                Load.Loading -> LoadingBox()
                is Load.Err -> ErrorBox(s.error, onRetry = { tick++ })
                is Load.Ok -> LazyColumn(state = list, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    if (pdfBusy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                    pdfErr?.let { e -> item { Text(errorText(e), color = MaterialTheme.colorScheme.error) } }
                    if (s.data.status == "generating") item {
                        SectionCard(accent = true) {
                            Text(stringResource(R.string.report_generating, s.data.sections_done, s.data.sections_total))
                            LinearProgressIndicator(progress = { s.data.sections_done / s.data.sections_total.coerceAtLeast(1).toFloat() },
                                modifier = Modifier.fillMaxWidth())
                        }
                    }
                    itemsIndexed(s.data.sections.sortedBy { it.idx }) { _, sec ->
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("${sec.idx}. ${sec.title}", style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.secondary,
                                fontWeight = FontWeight.Bold)
                            MarkdownText(sec.content)
                            HorizontalDivider(Modifier.padding(top = 8.dp))
                        }
                    }
                }
            }
        }
    }
    if (tocOpen && report != null) {
        AlertDialog(onDismissRequest = { tocOpen = false }, confirmButton = {},
            title = { Text(stringResource(R.string.report_toc)) },
            text = {
                LazyColumn {
                    val offset = listOfNotNull(pdfBusy.takeIf { it }, pdfErr, report.takeIf { it.status == "generating" }).size
                    itemsIndexed(report.sections.sortedBy { it.idx }) { i, sec ->
                        Text("${sec.idx}. ${sec.title}", Modifier.fillMaxWidth().clickable {
                            tocOpen = false; scope.launch { list.animateScrollToItem(i + offset) }
                        }.padding(vertical = 10.dp))
                    }
                }
            })
    }
}
