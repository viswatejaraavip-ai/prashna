@file:OptIn(ExperimentalMaterial3Api::class)

package com.udhyath.app

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.text.NumberFormat
import java.util.Locale

// ------------------------------------------------------------------ state

sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ok<T>(val data: T) : Load<T>
    data class Err(val error: Throwable) : Load<Nothing>
}

val <T> Load<T>.dataOrNull: T? get() = (this as? Load.Ok<T>)?.data

@Composable
inline fun <reified VM : ViewModel> graphViewModel(key: String? = null, crossinline create: (AppGraph) -> VM): VM {
    val g = LocalContext.current.graph
    return viewModel(key = key) { create(g) }
}

// ------------------------------------------------------------------ money

/** Paise → "₹10" / "₹10.50" with Indian digit grouping. */
fun rupees(units: Long): String {
    val nf = NumberFormat.getNumberInstance(Locale("en", "IN"))
    nf.minimumFractionDigits = if (units % 100 == 0L) 0 else 2
    nf.maximumFractionDigits = 2
    return "₹" + nf.format(units / 100.0)
}

// ------------------------------------------------------------------ errors

@Composable
fun errorText(t: Throwable): String = when (t.errorKind()) {
    ErrorKind.OFFLINE -> stringResource(R.string.err_offline)
    ErrorKind.INSUFFICIENT_BALANCE -> stringResource(R.string.err_balance)
    ErrorKind.RATE_LIMITED -> stringResource(R.string.err_rate_limited)
    ErrorKind.NOT_FOUND -> stringResource(R.string.err_not_found)
    ErrorKind.FORBIDDEN -> (t as? ApiException)?.detail ?: stringResource(R.string.err_forbidden)
    ErrorKind.MAINTENANCE -> (t as? ApiException)?.detail?.takeIf { it.isNotBlank() } ?: stringResource(R.string.maintenance_default)
    ErrorKind.UNAUTHORIZED -> stringResource(R.string.err_session)
    ErrorKind.INVALID -> (t as? ApiException)?.detail ?: stringResource(R.string.err_invalid)
    ErrorKind.SERVER -> stringResource(R.string.err_server)
}

// ------------------------------------------------------------------ layout

@Composable
fun AppTopBar(title: String, onBack: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {}) {
    TopAppBar(
        title = { Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, maxLines = 1,
            modifier = Modifier.semantics { heading() }) },
        navigationIcon = {
            if (onBack != null) IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.cd_back))
            }
        },
        actions = actions,
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
    )
}

/** Standard screen: top bar + scrollable column body with comfortable padding. */
@Composable
fun ScreenScaffold(
    title: String,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
    scroll: Boolean = true,
    bottomBar: @Composable () -> Unit = {},
    content: @Composable ColumnScope.() -> Unit,
) {
    Scaffold(
        topBar = { AppTopBar(title, onBack, actions) },
        bottomBar = bottomBar,
        containerColor = MaterialTheme.colorScheme.background,
    ) { pad ->
        val m = Modifier.padding(pad).fillMaxSize().let { if (scroll) it.verticalScroll(rememberScrollState()) else it }
        Column(m.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
    }
}

@Composable
fun SectionCard(
    modifier: Modifier = Modifier,
    title: String? = null,
    accent: Boolean = false,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (accent) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.secondary, modifier = Modifier.semantics { heading() })
            content()
        }
    }
}

@Composable
fun BigButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
              icon: ImageVector? = null, secondary: Boolean = false, busy: Boolean = false) {
    val content: @Composable RowScope.() -> Unit = {
        if (busy) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = LocalContentColor.current)
            Spacer(Modifier.width(10.dp))
        } else if (icon != null) {
            Icon(icon, contentDescription = null); Spacer(Modifier.width(8.dp))
        }
        Text(text, style = MaterialTheme.typography.labelLarge, textAlign = TextAlign.Center)
    }
    val m = modifier.fillMaxWidth().heightIn(min = 56.dp)
    if (secondary) OutlinedButton(onClick, m, enabled = enabled && !busy, shape = RoundedCornerShape(16.dp), content = content)
    else Button(onClick, m, enabled = enabled && !busy, shape = RoundedCornerShape(16.dp), content = content)
}

@Composable
fun LoadingBox(modifier: Modifier = Modifier, label: String? = null) {
    val desc = label ?: stringResource(R.string.loading)
    Column(modifier.fillMaxWidth().padding(32.dp).semantics { contentDescription = desc },
        horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        if (label != null) { Spacer(Modifier.height(12.dp)); Text(label, textAlign = TextAlign.Center) }
    }
}

@Composable
fun ErrorBox(error: Throwable, onRetry: (() -> Unit)?, modifier: Modifier = Modifier) {
    val offline = error.errorKind() == ErrorKind.OFFLINE
    Column(modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(if (offline) Icons.Default.CloudOff else Icons.Default.ErrorOutline, contentDescription = null,
            tint = MaterialTheme.colorScheme.secondary, modifier = Modifier.size(40.dp))
        Text(errorText(error), textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
        if (onRetry != null) OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
    }
}

@Composable
fun EmptyBox(text: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Column(modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(Icons.Default.Inbox, contentDescription = null, tint = MaterialTheme.colorScheme.outline, modifier = Modifier.size(40.dp))
        Text(text, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
        action?.invoke()
    }
}

/** Renders a Load<T>: spinner, error with retry, or [content]. */
@Composable
fun <T> LoadView(state: Load<T>, onRetry: () -> Unit, content: @Composable (T) -> Unit) {
    when (state) {
        Load.Loading -> LoadingBox()
        is Load.Err -> ErrorBox(state.error, onRetry)
        is Load.Ok -> content(state.data)
    }
}

@Composable
fun KeyValue(label: String, value: String, strong: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.Top) {
        Text(label, Modifier.weight(0.45f), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        Text(value, Modifier.weight(0.55f), style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (strong) FontWeight.Bold else FontWeight.Medium)
    }
}

@Composable
fun Pill(text: String, color: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.secondaryContainer) {
    Text(text, Modifier.background(color, RoundedCornerShape(50)).padding(horizontal = 12.dp, vertical = 4.dp),
        style = MaterialTheme.typography.labelMedium)
}

// --------------------------------------------------------- JSON rendering

/**
 * Known response keys → localized labels. The backend localizes values; keys
 * are stable identifiers, so labels live here. Unknown keys fall back to a
 * humanized form of the key.
 */
private val KEY_LABELS: Map<String, Int> = mapOf(
    "tithi" to R.string.k_tithi, "nakshatra" to R.string.k_nakshatra, "yoga" to R.string.k_yoga,
    "karana" to R.string.k_karana, "vara" to R.string.k_vara, "weekday" to R.string.k_vara,
    "sunrise" to R.string.k_sunrise, "sunset" to R.string.k_sunset, "moonrise" to R.string.k_moonrise,
    "rahu_kalam" to R.string.k_rahu_kalam, "rahu_kaal" to R.string.k_rahu_kalam, "gulika" to R.string.k_gulika,
    "gulika_kalam" to R.string.k_gulika, "yamaganda" to R.string.k_yamaganda, "abhijit" to R.string.k_abhijit,
    "lagna" to R.string.k_lagna, "ascendant" to R.string.k_lagna, "moon_sign" to R.string.k_moon_sign,
    "sun_sign" to R.string.k_sun_sign, "dasha" to R.string.k_dasha, "mahadasha" to R.string.k_dasha,
    "antardasha" to R.string.k_antardasha, "current_dasha" to R.string.k_dasha, "score" to R.string.k_score,
    "total" to R.string.k_total, "verdict" to R.string.k_verdict, "start" to R.string.k_start,
    "end" to R.string.k_end, "from" to R.string.k_start, "to" to R.string.k_end, "date" to R.string.k_date,
    "time" to R.string.k_time, "planet" to R.string.k_planet, "sign" to R.string.k_sign, "house" to R.string.k_house,
    "degree" to R.string.k_degree, "dms" to R.string.k_degree, "lord" to R.string.k_lord, "strength" to R.string.k_strength,
    "description" to R.string.k_description, "summary" to R.string.k_summary, "forecast" to R.string.k_forecast,
    "paksha" to R.string.k_paksha, "masa" to R.string.k_masa, "samvatsara" to R.string.k_samvatsara,
    "kind" to R.string.k_kind, "type" to R.string.k_kind, "name" to R.string.k_name, "reason" to R.string.k_reason,
    "quality" to R.string.k_quality, "rank" to R.string.k_rank, "retrograde" to R.string.k_retrograde,
    "sign_lord" to R.string.k_sign_lord, "star_lord" to R.string.k_star_lord, "sub_lord" to R.string.k_sub_lord,
    "rupas" to R.string.k_rupas, "ratio" to R.string.k_ratio, "bindus" to R.string.k_bindus,
    "manglik" to R.string.k_manglik, "doshas" to R.string.k_doshas, "yogas" to R.string.k_yogas,
    "remedies" to R.string.k_remedies, "remedy" to R.string.k_remedies, "gunas" to R.string.k_gunas,
    "koota" to R.string.k_koota, "max" to R.string.k_max, "obtained" to R.string.k_obtained, "points" to R.string.k_obtained,
)

@Composable
fun keyLabel(key: String): String {
    KEY_LABELS[key.lowercase()]?.let { return stringResource(it) }
    return key.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

/**
 * Generic, readable rendering of any JSON the engine returns: objects become
 * label/value rows (nested objects become sub-sections), arrays of objects
 * become dense horizontally-scrollable tables. Used for professional views
 * whose shape the contract leaves to the engine.
 */
@Composable
fun JsonView(el: JsonElement, depth: Int = 0, dense: Boolean = false) {
    when (el) {
        is JsonPrimitive -> Text(el.displayText(), style = MaterialTheme.typography.bodyMedium)
        is JsonArray -> {
            val objs = el.filterIsInstance<JsonObject>()
            if (objs.size == el.size && objs.isNotEmpty() && objs.all { o -> o.values.all { it is JsonPrimitive || it is JsonArray && it.all { x -> x is JsonPrimitive } } }) {
                DenseTable(objs, dense)
            } else {
                el.forEach { item ->
                    if (item is JsonPrimitive) Text("• " + item.displayText(), style = MaterialTheme.typography.bodyMedium)
                    else Column(Modifier.padding(start = (depth * 8).dp, bottom = 6.dp)) { JsonView(item, depth + 1, dense) }
                }
            }
        }
        is JsonObject -> Column(verticalArrangement = Arrangement.spacedBy(if (dense) 2.dp else 4.dp)) {
            el.forEach { (k, v) ->
                when {
                    v is JsonPrimitive || (v is JsonArray && v.all { it is JsonPrimitive }) -> KeyValue(keyLabel(k), v.displayText())
                    else -> {
                        Text(keyLabel(k), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.secondary, modifier = Modifier.padding(top = 6.dp))
                        Column(Modifier.padding(start = if (depth < 3) 8.dp else 0.dp)) { JsonView(v, depth + 1, dense) }
                    }
                }
            }
        }
    }
}

@Composable
fun DenseTable(rows: List<JsonObject>, dense: Boolean = true) {
    val cols = rows.flatMap { it.keys }.distinct()
    val cellW = if (dense) 92.dp else 110.dp
    Column(Modifier.horizontalScroll(rememberScrollState())
        .border(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.5f), RoundedCornerShape(8.dp))) {
        Row(Modifier.background(MaterialTheme.colorScheme.secondaryContainer).padding(vertical = 6.dp)) {
            cols.forEach { c ->
                Text(keyLabel(c), Modifier.width(cellW).padding(horizontal = 6.dp), style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold)
            }
        }
        rows.forEachIndexed { i, r ->
            Row(Modifier.background(if (i % 2 == 1) MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f) else MaterialTheme.colorScheme.surface)
                .padding(vertical = 5.dp)) {
                cols.forEach { c ->
                    Text(r[c]?.displayText() ?: "—", Modifier.width(cellW).padding(horizontal = 6.dp),
                        style = if (dense) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

// --------------------------------------------------------- markdown-lite

private fun inline(s: String): AnnotatedString = buildAnnotatedString {
    var i = 0
    val parts = Regex("\\*\\*(.+?)\\*\\*").findAll(s)
    for (m in parts) {
        append(s.substring(i, m.range.first))
        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(m.groupValues[1]) }
        i = m.range.last + 1
    }
    append(s.substring(i))
}

/** Headings (#), bullets (-, *), bold (**x**) and paragraphs — enough for AI replies, legal pages, reports. */
@Composable
fun MarkdownText(md: String, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        md.replace("\r", "").split("\n").forEach { raw ->
            val line = raw.trimEnd()
            when {
                line.isBlank() -> Spacer(Modifier.height(2.dp))
                line.startsWith("#") -> Text(inline(line.trimStart('#').trim()),
                    style = if (line.startsWith("##")) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.secondary, modifier = Modifier.semantics { heading() })
                line.trimStart().startsWith("- ") || line.trimStart().startsWith("* ") ->
                    Row { Text("•  "); Text(inline(line.trimStart().drop(2)), style = MaterialTheme.typography.bodyLarge) }
                else -> Text(inline(line), style = MaterialTheme.typography.bodyLarge)
            }
        }
    }
}

// --------------------------------------------------------- sharing

fun shareText(ctx: Context, text: String, whatsappOnly: Boolean = false) {
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"; putExtra(Intent.EXTRA_TEXT, text)
        if (whatsappOnly) setPackage("com.whatsapp")
    }
    try { ctx.startActivity(if (whatsappOnly) send else Intent.createChooser(send, null)) }
    catch (_: ActivityNotFoundException) { ctx.startActivity(Intent.createChooser(send.setPackage(null), null)) }
}

/** Write bytes to cache/shared and open the Android share sheet (WhatsApp appears there). */
fun shareFile(ctx: Context, bytes: ByteArray, fileName: String, mime: String, text: String? = null) {
    val dir = File(ctx.cacheDir, "shared").apply { mkdirs() }
    val f = File(dir, fileName).apply { writeBytes(bytes) }
    val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = mime
        putExtra(Intent.EXTRA_STREAM, uri)
        text?.let { putExtra(Intent.EXTRA_TEXT, it) }
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    ctx.startActivity(Intent.createChooser(send, null))
}

/** Open a downloaded PDF in the user's viewer. */
fun viewFile(ctx: Context, bytes: ByteArray, fileName: String, mime: String) {
    val dir = File(ctx.cacheDir, "shared").apply { mkdirs() }
    val f = File(dir, fileName).apply { writeBytes(bytes) }
    val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
    val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try { ctx.startActivity(view) } catch (_: ActivityNotFoundException) { shareFile(ctx, bytes, fileName, mime) }
}

fun openUrl(ctx: Context, url: String) {
    try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: ActivityNotFoundException) {}
}

fun openWhatsAppSupport(ctx: Context, message: String) {
    openUrl(ctx, "https://wa.me/${BuildConfig.SUPPORT_WHATSAPP}?text=" + Uri.encode(message))
}

@Composable
fun str(@StringRes id: Int, vararg args: Any): String = stringResource(id, *args)

tailrec fun Context.findActivity(): android.app.Activity? = when (this) {
    is android.app.Activity -> this
    is android.content.ContextWrapper -> baseContext.findActivity()
    else -> null
}
