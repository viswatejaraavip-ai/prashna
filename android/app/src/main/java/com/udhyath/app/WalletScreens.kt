@file:OptIn(ExperimentalMaterial3Api::class)

package com.udhyath.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalanceWallet
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

/** Play top-up packs; shows the price of each pack as Play formats it. */
@Composable
fun TopUpPacks(onCredited: () -> Unit) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val pricing by g.account.pricing.collectAsStateWithLifecycle()
    var packs by remember { mutableStateOf<Load<List<TopUpPack>>>(Load.Loading) }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val msgPending = stringResource(R.string.topup_pending)
    val msgFailed = stringResource(R.string.topup_failed)
    val msgDone = stringResource(R.string.topup_done)

    LaunchedEffect(pricing.playProductIds, tick) {
        packs = Load.Loading
        packs = runCatching { g.billing.packs(pricing.playProductIds) }.fold({ Load.Ok(it) }, { Load.Err(it) })
    }
    LaunchedEffect(Unit) {
        g.billing.events.collect { e ->
            busy = false
            when (e) {
                is PurchaseEvent.Credited -> { status = msgDone; runCatching { g.account.refreshMe() }; onCredited() }
                PurchaseEvent.Pending -> status = msgPending
                PurchaseEvent.Cancelled -> status = null
                is PurchaseEvent.Failed -> status = msgFailed
            }
        }
    }
    LoadView(packs, onRetry = { tick++ }) { list ->
        if (list.isEmpty()) Text(stringResource(R.string.topup_unavailable), textAlign = TextAlign.Center)
        list.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                row.forEach { p ->
                    OutlinedCard(onClick = {
                        val act = ctx.findActivity() ?: return@OutlinedCard
                        val uid = g.account.user.value?.uid ?: return@OutlinedCard
                        status = null; busy = g.billing.buy(act, p, uid)
                    }, enabled = !busy, modifier = Modifier.weight(1f), shape = RoundedCornerShape(16.dp)) {
                        Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(p.price, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.secondary)
                            Text(stringResource(R.string.topup_questions, (p.rupees * 100L / pricing.query_price_units.coerceAtLeast(1)).toInt()),
                                style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
                        }
                    }
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    status?.let { Text(it, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth()) }
    TextButton(onClick = { scope.launch { runCatching { g.billing.restore() } } }) { Text(stringResource(R.string.topup_restore)) }
}

/** Inline top-up (insufficient balance while asking / buying). */
@Composable
fun TopUpSheet(reason: String, onDismiss: () -> Unit, onCredited: () -> Unit) {
    val balance by AppEvents.balance.collectAsStateWithLifecycle()
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.topup_title), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(reason)
            Text(stringResource(R.string.wallet_balance_is, balance?.let { rupees(it) } ?: "—"), color = MaterialTheme.colorScheme.onSurfaceVariant)
            TopUpPacks(onCredited = onCredited)
        }
    }
}

@Composable
fun ledgerTypeLabel(t: String) = stringResource(when (t) {
    "topup" -> R.string.lt_topup; "query" -> R.string.lt_query; "report" -> R.string.lt_report; "refund" -> R.string.lt_refund
    "trial" -> R.string.lt_trial; "subscription" -> R.string.lt_subscription; else -> R.string.lt_adjust
})

@Composable
fun WalletScreen(nav: NavHostController, onBack: () -> Unit) {
    val g = LocalContext.current.graph
    val balance by AppEvents.balance.collectAsStateWithLifecycle()
    var ledger by remember { mutableStateOf<Load<List<LedgerEntry>>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(tick) {
        runCatching { g.account.refreshMe() }
        ledger = runCatching { g.api.ledger(50) }.fold({ Load.Ok(it) }, { Load.Err(it) })
    }
    ScreenScaffold(stringResource(R.string.wallet_title), onBack = onBack) {
        SectionCard(accent = true) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.AccountBalanceWallet, contentDescription = null, tint = MaterialTheme.colorScheme.secondary)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.wallet_balance), style = MaterialTheme.typography.titleMedium)
            }
            Text(balance?.let { rupees(it) } ?: "—", style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold)
        }
        SectionCard(title = stringResource(R.string.topup_title)) { TopUpPacks(onCredited = { tick++ }) }
        Text(stringResource(R.string.wallet_history), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        LoadView(ledger, onRetry = { tick++ }) { list ->
            if (list.isEmpty()) EmptyBox(stringResource(R.string.wallet_history_empty))
            list.forEach { e ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(ledgerTypeLabel(e.type), fontWeight = FontWeight.SemiBold)
                        Text(formatDateTime(e.created_at), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text((if (e.delta_units >= 0) "+" else "−") + rupees(kotlin.math.abs(e.delta_units)),
                            color = if (e.delta_units >= 0) BrandColors.Good else MaterialTheme.colorScheme.onSurface, fontWeight = FontWeight.Bold)
                        if (e.delta_units < 0 && e.type in setOf("query", "report", "subscription")) TextButton(
                            onClick = { nav.navigate(Routes.refunds(e.ref ?: "${e.type}:${e.created_at}")) },
                            contentPadding = PaddingValues(0.dp)) { Text(stringResource(R.string.refund_request), style = MaterialTheme.typography.labelSmall) }
                    }
                }
                HorizontalDivider()
            }
        }
    }
}
