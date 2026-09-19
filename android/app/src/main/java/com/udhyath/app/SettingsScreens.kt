package com.udhyath.app

import android.content.Intent
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Gavel
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PersonRemove
import androidx.compose.material.icons.filled.Policy
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material.icons.filled.TextIncrease
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
private fun NavRow(icon: ImageVector, title: String, subtitle: String? = null, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title, style = MaterialTheme.typography.bodyLarge) },
        supportingContent = subtitle?.let { { Text(it) } },
        leadingContent = { Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
        trailingContent = { Icon(Icons.Default.ChevronRight, contentDescription = null) },
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(onClick = onClick),
        colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
    )
}

@Composable
private fun SwitchRow(icon: ImageVector, title: String, subtitle: String? = null, checked: Boolean, onChange: (Boolean) -> Unit) {
    ListItem(
        headlineContent = { Text(title, style = MaterialTheme.typography.bodyLarge) },
        supportingContent = subtitle?.let { { Text(it) } },
        leadingContent = { Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
        trailingContent = { Switch(checked, onCheckedChange = null) },
        modifier = Modifier.fillMaxWidth().toggleable(checked, role = Role.Switch, onValueChange = onChange),
        colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
    )
}

@Composable
fun MoreScreen(nav: NavHostController) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val user by g.account.user.collectAsStateWithLifecycle()
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val balance by AppEvents.balance.collectAsStateWithLifecycle()
    val astro = user?.isAstrologer == true
    var confirmLogout by remember { mutableStateOf(false) }

    if (confirmLogout) AlertDialog(onDismissRequest = { confirmLogout = false },
        title = { Text(stringResource(R.string.logout)) }, text = { Text(stringResource(R.string.logout_confirm)) },
        confirmButton = { TextButton(onClick = { confirmLogout = false; AppEvents.sessionExpired.value = true }) { Text(stringResource(R.string.logout)) } },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) } })

    ScreenScaffold(stringResource(R.string.tab_more)) {
        SectionCard {
            Text(user?.name?.ifBlank { null } ?: user?.phone ?: user?.email ?: "", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(listOfNotNull(user?.phone, user?.email).joinToString(" · "), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Pill(stringResource(if (astro) R.string.role_astrologer else R.string.role_personal))
        }
        SectionCard {
            NavRow(Icons.Default.AccountBalanceWallet, stringResource(R.string.wallet_title), balance?.let { rupees(it) }) { nav.navigate(Routes.WALLET) }
            if (astro) {
                NavRow(Icons.Default.Verified, stringResource(R.string.pro_title)) { nav.navigate(Routes.PRO) }
                NavRow(Icons.Default.Badge, stringResource(R.string.brand_title)) { nav.navigate(Routes.BRAND) }
            }
            NavRow(Icons.Default.Groups, stringResource(R.string.family_title)) { nav.navigate(Routes.PROFILES) }
        }
        SectionCard(title = stringResource(R.string.settings_prefs)) {
            NavRow(Icons.Default.Language, stringResource(R.string.language_title), settings.lang?.nativeName) { nav.navigate(Routes.LANGUAGE) }
            SwitchRow(Icons.Default.TextIncrease, stringResource(R.string.settings_large_text), stringResource(R.string.settings_large_text_desc),
                settings.largeText) { v -> scope.launch { g.settings.setLargeText(v) } }
            NavRow(Icons.Default.Notifications, stringResource(R.string.notif_title)) { nav.navigate(Routes.NOTIF) }
        }
        SectionCard(title = stringResource(R.string.settings_help)) {
            NavRow(Icons.Default.SupportAgent, stringResource(R.string.support_title)) { nav.navigate(Routes.SUPPORT) }
            NavRow(Icons.Default.Receipt, stringResource(R.string.refunds_title)) { nav.navigate(Routes.refunds()) }
        }
        SectionCard(title = stringResource(R.string.settings_legal)) {
            NavRow(Icons.Default.Gavel, stringResource(R.string.legal_terms)) { nav.navigate("legal/terms") }
            NavRow(Icons.Default.Policy, stringResource(R.string.legal_privacy)) { nav.navigate("legal/privacy") }
            NavRow(Icons.Default.Receipt, stringResource(R.string.legal_refund)) { nav.navigate("legal/refund") }
            NavRow(Icons.Default.Policy, stringResource(R.string.disclaimer_title)) { nav.navigate("legal/disclaimer") }
        }
        SectionCard(title = stringResource(R.string.settings_privacy)) {
            NavRow(Icons.Default.Download, stringResource(R.string.account_export)) { nav.navigate(Routes.ACCOUNT) }
            NavRow(Icons.Default.PersonRemove, stringResource(R.string.account_delete)) { nav.navigate(Routes.ACCOUNT) }
        }
        OutlinedButton(onClick = { confirmLogout = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
            Icon(Icons.AutoMirrored.Filled.Logout, null); Spacer(Modifier.width(8.dp)); Text(stringResource(R.string.logout))
        }
        Text(stringResource(R.string.version, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(16.dp))
    }
}

// ===========================================================================
// Notification preferences (daily / transits / promos) + OS permission
// ===========================================================================

@Composable
fun NotificationPrefsScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val user by g.account.user.collectAsStateWithLifecycle()
    var prefs by remember(user) { mutableStateOf(user?.notif_prefs ?: NotifPrefs()) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    val allowed = Notifications.canPost(ctx)
    fun save(p: NotifPrefs) {
        val old = prefs; prefs = p; err = null
        scope.launch { runCatching { g.account.setUser(g.api.patchMe(notif = p)) }.onFailure { prefs = old; err = it } }
    }
    ScreenScaffold(stringResource(R.string.notif_title), onBack = onBack) {
        if (!allowed) SectionCard(accent = true) {
            Text(stringResource(R.string.notif_blocked))
            Button(onClick = {
                ctx.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName))
            }) { Text(stringResource(R.string.notif_open_settings)) }
        }
        SectionCard {
            SwitchRow(Icons.Default.Notifications, stringResource(R.string.notif_daily), stringResource(R.string.notif_daily_desc), prefs.daily) { save(prefs.copy(daily = it)) }
            SwitchRow(Icons.Default.Notifications, stringResource(R.string.notif_transits), stringResource(R.string.notif_transits_desc), prefs.transits) { save(prefs.copy(transits = it)) }
            SwitchRow(Icons.Default.Notifications, stringResource(R.string.notif_promos), stringResource(R.string.notif_promos_desc), prefs.promos) { save(prefs.copy(promos = it)) }
        }
        err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
    }
}

// ===========================================================================
// Legal pages (/api/legal/{doc}, localized by the server)
// ===========================================================================

@Composable
fun LegalScreen(doc: String, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    var state by remember { mutableStateOf<Load<LegalDoc>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(doc, tick) { state = runCatching { g.api.legal(doc) }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    val fallbackTitle = stringResource(when (doc) {
        "privacy" -> R.string.legal_privacy; "refund" -> R.string.legal_refund; "disclaimer" -> R.string.disclaimer_title; else -> R.string.legal_terms
    })
    ScreenScaffold(state.dataOrNull?.title?.ifBlank { null } ?: fallbackTitle, onBack = onBack) {
        LoadView(state, onRetry = { tick++ }) { MarkdownText(it.body_markdown) }
    }
}

// ===========================================================================
// Refunds
// ===========================================================================

@Composable
fun refundStatusLabel(s: String) = stringResource(when (s) {
    "approved" -> R.string.refund_approved; "rejected" -> R.string.refund_rejected; else -> R.string.refund_requested
})

@Composable
fun RefundsScreen(ref: String?, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<Load<List<Refund>>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    var reference by remember { mutableStateOf(ref ?: "") }
    var reason by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var sent by remember { mutableStateOf(false) }
    LaunchedEffect(tick) { list = runCatching { g.api.refunds() }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    ScreenScaffold(stringResource(R.string.refunds_title), onBack = onBack) {
        SectionCard(title = stringResource(R.string.refund_request)) {
            Text(stringResource(R.string.refund_intro), style = MaterialTheme.typography.bodyMedium)
            OutlinedTextField(reference, { reference = it }, label = { Text(stringResource(R.string.refund_ref)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(reason, { reason = it }, label = { Text(stringResource(R.string.refund_reason)) }, minLines = 3, modifier = Modifier.fillMaxWidth())
            BigButton(stringResource(R.string.submit), enabled = reason.trim().length >= 10 && reference.isNotBlank(), busy = busy, onClick = {
                busy = true; err = null
                scope.launch {
                    runCatching { g.api.requestRefund(reference.trim(), reason.trim()) }
                        .onSuccess { sent = true; reason = ""; tick++ }.onFailure { err = it }
                    busy = false
                }
            })
            if (sent) Text(stringResource(R.string.refund_sent), color = BrandColors.Good)
            err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        }
        Text(stringResource(R.string.refunds_mine), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        LoadView(list, onRetry = { tick++ }) { items ->
            if (items.isEmpty()) EmptyBox(stringResource(R.string.refunds_none))
            items.forEach { r ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(r.ref ?: "", Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                        Pill(refundStatusLabel(r.status))
                    }
                    if (r.amount_units > 0) Text(rupees(r.amount_units))
                    Text(r.reason, style = MaterialTheme.typography.bodySmall)
                    Text(formatDateTime(r.created_at), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

// ===========================================================================
// Support: in-app ticket + WhatsApp
// ===========================================================================

val SUPPORT_CATEGORIES = listOf("payment", "report", "answer", "app", "account", "other")

@Composable
fun supportCategoryLabel(c: String) = stringResource(when (c) {
    "payment" -> R.string.sc_payment; "report" -> R.string.sc_report; "answer" -> R.string.sc_answer
    "app" -> R.string.sc_app; "account" -> R.string.sc_account; else -> R.string.sc_other
})

@Composable
fun SupportScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val user by g.account.user.collectAsStateWithLifecycle()
    var cat by remember { mutableStateOf("payment") }
    var msg by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var sent by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var tickets by remember { mutableStateOf<Load<List<SupportTicket>>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(tick) { tickets = runCatching { g.api.tickets() }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    val waText = stringResource(R.string.support_whatsapp_text, user?.uid ?: "")
    ScreenScaffold(stringResource(R.string.support_title), onBack = onBack) {
        SectionCard(title = stringResource(R.string.support_new)) {
            ChipRow(SUPPORT_CATEGORIES, cat, label = { supportCategoryLabel(it) }) { cat = it }
            OutlinedTextField(msg, { msg = it }, label = { Text(stringResource(R.string.support_message)) }, minLines = 4, modifier = Modifier.fillMaxWidth())
            BigButton(stringResource(R.string.submit), enabled = msg.trim().length >= 10, busy = busy, onClick = {
                busy = true; err = null
                scope.launch {
                    runCatching { g.api.createTicket(cat, msg.trim()) }.onSuccess { sent = true; msg = ""; tick++ }.onFailure { err = it }
                    busy = false
                }
            })
            if (sent) Text(stringResource(R.string.support_sent), color = BrandColors.Good)
            err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        }
        BigButton(stringResource(R.string.support_whatsapp), secondary = true, onClick = { openWhatsAppSupport(ctx, waText) })
        Text(stringResource(R.string.support_mine), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        LoadView(tickets, onRetry = { tick++ }) { list ->
            if (list.isEmpty()) EmptyBox(stringResource(R.string.support_none))
            list.forEach { t ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(supportCategoryLabel(t.category), Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                        Pill(stringResource(if (t.status == "resolved") R.string.support_resolved else R.string.support_open))
                    }
                    Text(t.message)
                    t.replies.forEach { r ->
                        val text = r.obj()?.str("text", "message", "body") ?: r.displayText()
                        Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium) {
                            Text(text, Modifier.padding(10.dp))
                        }
                    }
                    Text(formatDateTime(t.created_at), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

// ===========================================================================
// Data export (DPDP) + account deletion
// ===========================================================================

@Composable
fun AccountScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    var exporting by remember { mutableStateOf(false) }
    var exportMsg by remember { mutableStateOf<String?>(null) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var pendingJson by remember { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }
    var understood by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    val savedMsg = stringResource(R.string.export_saved)

    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val json = pendingJson ?: return@rememberLauncherForActivityResult
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { ctx.contentResolver.openOutputStream(uri)?.use { it.write(json.toByteArray()) } } }
                .onSuccess { exportMsg = savedMsg }.onFailure { err = it }
            pendingJson = null
        }
    }

    if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false },
        title = { Text(stringResource(R.string.account_delete)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(stringResource(R.string.account_delete_body))
                Row(Modifier.toggleable(understood, role = Role.Checkbox) { understood = it }, verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(understood, null); Spacer(Modifier.width(8.dp)); Text(stringResource(R.string.account_delete_understand))
                }
            }
        },
        confirmButton = {
            TextButton(enabled = understood && !deleting, onClick = {
                deleting = true
                scope.launch {
                    runCatching { g.api.deleteAccount() }
                        .onSuccess { confirmDelete = false; AppEvents.sessionExpired.value = true }
                        .onFailure { err = it; confirmDelete = false }
                    deleting = false
                }
            }) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } })

    ScreenScaffold(stringResource(R.string.settings_privacy), onBack = onBack) {
        SectionCard(title = stringResource(R.string.account_export)) {
            Text(stringResource(R.string.account_export_desc))
            BigButton(stringResource(R.string.account_export_cta), icon = Icons.Default.Download, busy = exporting, onClick = {
                exporting = true; err = null; exportMsg = null
                scope.launch {
                    runCatching { g.api.exportData() }.onSuccess { pendingJson = it; saver.launch("prashna-my-data.json") }.onFailure { err = it }
                    exporting = false
                }
            })
            exportMsg?.let { Text(it, color = BrandColors.Good) }
        }
        SectionCard(title = stringResource(R.string.account_delete)) {
            Text(stringResource(R.string.account_delete_desc))
            OutlinedButton(onClick = { understood = false; confirmDelete = true }, modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                Text(stringResource(R.string.account_delete))
            }
        }
        err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
    }
}
