package com.udhyath.app

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

// ===========================================================================
// Session history
// ===========================================================================

@Composable
fun SessionsScreen(nav: NavHostController) {
    val g = LocalContext.current.graph
    val pricing by g.account.pricing.collectAsStateWithLifecycle()
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    var state by remember { mutableStateOf<Load<List<SessionInfo>>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    LaunchedEffect(tick) { state = runCatching { g.api.sessions(30) }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    Scaffold(
        topBar = { AppTopBar(stringResource(R.string.ask_title)) },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.chat(pid = settings.activeProfileId)) },
                icon = { Icon(Icons.Default.Add, null) }, text = { Text(stringResource(R.string.ask_new)) })
        },
    ) { pad ->
        LazyColumn(Modifier.padding(pad).fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                SectionCard(accent = true) {
                    Text(stringResource(R.string.ask_intro), style = MaterialTheme.typography.bodyLarge)
                    Pill(stringResource(R.string.price_per_question, rupees(pricing.query_price_units)))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        BigButton(stringResource(R.string.ask_type), modifier = Modifier.weight(1f), onClick = { nav.navigate(Routes.chat(pid = settings.activeProfileId)) })
                        BigButton(stringResource(R.string.ask_speak), modifier = Modifier.weight(1f), icon = Icons.Default.Mic, secondary = true,
                            onClick = { nav.navigate(Routes.chat(pid = settings.activeProfileId, voice = true)) })
                    }
                }
            }
            item { Text(stringResource(R.string.ask_history), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            when (val s = state) {
                Load.Loading -> item { LoadingBox() }
                is Load.Err -> item { ErrorBox(s.error, onRetry = { tick++ }) }
                is Load.Ok -> {
                    if (s.data.isEmpty()) item { EmptyBox(stringResource(R.string.ask_history_empty)) }
                    items(s.data, key = { it.id }) { sess ->
                        val who = profiles.firstOrNull { it.id == sess.profile_id }?.name
                        SectionCard(Modifier.clickable { nav.navigate(Routes.chat(sid = sess.id, pid = sess.profile_id)) }) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(if (sess.mode == "voice") Icons.Default.Mic else Icons.Default.Keyboard, contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(8.dp))
                                Text(listOfNotNull(who, formatDateTime(sess.created_at)).joinToString(" · "),
                                    style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
                                Text(stringResource(R.string.questions_count, sess.query_count), style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(sess.title?.ifBlank { null } ?: stringResource(R.string.session_no_summary), maxLines = 3)
                        }
                    }
                }
            }
            item { Spacer(Modifier.height(72.dp)) }
        }
    }
}

// ===========================================================================
// Chat — streaming text + voice mode
// ===========================================================================

data class UiMsg(
    val role: String,
    val text: String,
    val charged: Long = 0,
    val streaming: Boolean = false,
    val status: String? = null,
    val failed: Boolean = false,
)

enum class VoiceRoute { UNKNOWN, ON_DEVICE, CLOUD }

class ChatVm(private val g: AppGraph, initialSid: String?, initialPid: String?) : ViewModel() {
    val sid = MutableStateFlow(initialSid)
    val profileId = MutableStateFlow(initialPid)
    val messages = MutableStateFlow<List<UiMsg>>(emptyList())
    val loading = MutableStateFlow(initialSid != null)
    val loadError = MutableStateFlow<Throwable?>(null)
    val sending = MutableStateFlow(false)
    val error = MutableStateFlow<Throwable?>(null)
    val needTopUp = MutableStateFlow(false)
    val hasHistory = MutableStateFlow<Boolean?>(null)

    // Voice
    val voiceMode = MutableStateFlow(false)
    val voiceState = MutableStateFlow(VoiceState.IDLE)
    val partial = MutableStateFlow("")
    val voiceRoute = MutableStateFlow(VoiceRoute.UNKNOWN)
    val handsFree = MutableStateFlow(true)
    private var engine: VoiceEngine? = null
    private val recorder = WavRecorder()
    private var pendingRetry: String? = null
    private var job: Job? = null

    init {
        attachEngine(VoiceEngine(g.app))
        if (initialSid != null) loadHistory()
        viewModelScope.launch { hasHistory.value = runCatching { g.api.sessions(1).isNotEmpty() }.getOrNull() }
    }

    fun loadHistory() {
        val s = sid.value ?: return
        loading.value = true; loadError.value = null
        viewModelScope.launch {
            runCatching { g.api.messages(s) }
                .onSuccess { list -> messages.value = list.map { UiMsg(if (it.role == "user") "user" else "assistant", it.text, it.charged_units) } }
                .onFailure { loadError.value = it }
            loading.value = false
        }
    }

    fun setProfile(pid: String) { if (sid.value == null) profileId.value = pid }

    private suspend fun ensureSession(mode: String): String {
        sid.value?.let { return it }
        val pid = profileId.value ?: g.settings.current().activeProfileId ?: g.account.profiles.value.firstOrNull()?.id
            ?: throw ApiException(ErrorKind.INVALID, 400, null)
        profileId.value = pid
        return g.api.createSession(pid, mode).also { sid.value = it }
    }

    /** Text question, streamed. In voice mode the reply is spoken when complete. */
    fun ask(text: String, speakReply: Boolean = false) {
        val q = text.trim()
        if (q.isEmpty() || sending.value) return
        error.value = null
        sending.value = true
        messages.update { it + UiMsg("user", q) + UiMsg("assistant", "", streaming = true) }
        job = viewModelScope.launch {
            try {
                val s = ensureSession(if (voiceMode.value) "voice" else "text")
                if (speakReply) voiceState.value = VoiceState.THINKING
                val buf = StringBuilder()
                var done: AskResult? = null
                g.api.askStream(s, q).collect { ev ->
                    when (ev) {
                        is StreamEvent.Delta -> { buf.append(ev.text); updateLast { it.copy(text = buf.toString()) } }
                        is StreamEvent.Done -> done = ev.result
                    }
                }
                val r = done ?: AskResult(reply = buf.toString())
                val finalText = buf.toString().ifBlank { r.reply }
                updateLast { it.copy(text = finalText, streaming = false, charged = r.charged_units, status = r.status) }
                hasHistory.value = true
                if (speakReply) speak(finalText)
            } catch (e: Exception) {
                onAskError(e, q)
            } finally {
                sending.value = false
            }
        }
    }

    private fun onAskError(e: Exception, q: String) {
        // Drop the empty assistant bubble; mark the question as not sent.
        messages.update { list ->
            val trimmed = if (list.lastOrNull()?.role == "assistant" && list.last().text.isBlank()) list.dropLast(1) else list.map { if (it.streaming) it.copy(streaming = false) else it }
            trimmed.mapIndexed { i, m -> if (i == trimmed.lastIndex && m.role == "user") m.copy(failed = true) else m }
        }
        voiceState.value = VoiceState.IDLE
        if (e.errorKind() == ErrorKind.INSUFFICIENT_BALANCE) { pendingRetry = q; needTopUp.value = true } else error.value = e
    }

    fun retryLast() {
        val last = messages.value.lastOrNull { it.role == "user" && it.failed } ?: return
        messages.update { it.filterNot { m -> m === last } }
        ask(last.text, speakReply = voiceMode.value)
    }

    fun onToppedUp() {
        needTopUp.value = false
        val q = pendingRetry ?: return
        pendingRetry = null
        messages.update { it.filterNot { m -> m.role == "user" && m.failed && m.text == q } }
        ask(q, speakReply = voiceMode.value)
    }

    fun dismissTopUp() { needTopUp.value = false }

    private fun updateLast(f: (UiMsg) -> UiMsg) {
        messages.update { list -> if (list.isEmpty()) list else list.dropLast(1) + f(list.last()) }
    }

    // ------------------------------------------------------------- voice

    private fun attachEngine(e: VoiceEngine) {
        engine = e
        e.onSpeakingDone = {
            voiceState.value = VoiceState.IDLE
            if (voiceMode.value && handsFree.value) startListening()
        }
    }

    fun enterVoice(lang: AppLang) {
        voiceMode.value = true
        viewModelScope.launch {
            val cap = engine?.capability(lang) ?: VoiceCapability(false, false)
            voiceRoute.value = if (cap.useCloud) VoiceRoute.CLOUD else VoiceRoute.ON_DEVICE
            ttsOnDevice = cap.ttsOnDevice
            startListening()
        }
    }

    private var ttsOnDevice = true
    private var lang: AppLang = AppLang.HI
    fun setLang(l: AppLang) { lang = l }

    fun exitVoice() {
        voiceMode.value = false
        engine?.stopSpeaking(); engine?.cancelListening(); recorder.stop()
        voiceState.value = VoiceState.IDLE
        partial.value = ""
    }

    fun startListening() {
        if (!voiceMode.value || sending.value) return
        engine?.stopSpeaking()
        partial.value = ""
        when (voiceRoute.value) {
            VoiceRoute.CLOUD -> cloudTurn()
            else -> engine?.listen(lang,
                onReady = { voiceState.value = VoiceState.LISTENING },
                onPartial = { partial.value = it },
                onFinal = { text ->
                    voiceState.value = VoiceState.IDLE
                    if (text != null) { partial.value = ""; ask(text, speakReply = true) }
                },
                onLanguageMissing = {
                    // Device lacks the pack after all → switch to the cloud path for this session.
                    voiceRoute.value = VoiceRoute.CLOUD; cloudTurn()
                },
                onError = { voiceState.value = VoiceState.IDLE; error.value = ApiException(ErrorKind.SERVER, 0, null) },
            )
        }
    }

    /** Stop talking now (interrupt). Listening resumes only on the user's tap. */
    fun stopSpeaking() {
        engine?.stopSpeaking()
        voiceState.value = VoiceState.IDLE
    }

    fun stopListening() {
        if (voiceRoute.value == VoiceRoute.CLOUD) recorder.stop() else engine?.stopListening()
    }

    private fun speak(text: String) {
        val e = engine ?: return
        if (!ttsOnDevice) { voiceState.value = VoiceState.IDLE; return }
        voiceState.value = VoiceState.SPEAKING
        e.speak(text, lang)
    }

    private fun cloudTurn() {
        if (sending.value) return
        viewModelScope.launch {
            voiceState.value = VoiceState.LISTENING
            val wav = recorder.record()
            if (wav == null || !voiceMode.value) { voiceState.value = VoiceState.IDLE; return@launch }
            voiceState.value = VoiceState.THINKING
            sending.value = true
            messages.update { it + UiMsg("user", "…") + UiMsg("assistant", "", streaming = true) }
            try {
                val s = ensureSession("voice")
                val r = g.api.voice(s, wav, "audio/wav", "question.wav", tts = !ttsOnDevice)
                messages.update { list ->
                    val base = list.dropLast(2)
                    base + UiMsg("user", r.transcript.ifBlank { "🎤" }) + UiMsg("assistant", r.reply, r.charged_units, status = r.status)
                }
                hasHistory.value = true
                val audio = r.audio_b64
                if (audio != null) { voiceState.value = VoiceState.SPEAKING; engine?.playBase64(audio) }
                else if (ttsOnDevice) speak(r.reply) else voiceState.value = VoiceState.IDLE
            } catch (e: Exception) {
                messages.update { list -> list.dropLast(2) }
                voiceState.value = VoiceState.IDLE
                if (e.errorKind() == ErrorKind.INSUFFICIENT_BALANCE) needTopUp.value = true else error.value = e
            } finally { sending.value = false }
        }
    }

    fun readAloud(text: String) {
        engine?.let { voiceState.value = VoiceState.SPEAKING; it.speak(text, lang) }
    }

    override fun onCleared() {
        engine?.destroy(); recorder.stop()
    }
}

@Composable
fun ChatScreen(nav: NavHostController, sid: String?, pid: String?, startVoice: Boolean) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val vm = graphViewModel(key = "chat-$sid-$pid") { ChatVm(it, sid, pid) }
    val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = AppSettings())
    val lang = settings.lang ?: AppLang.HI
    val pricing by g.account.pricing.collectAsStateWithLifecycle()
    val balance by AppEvents.balance.collectAsStateWithLifecycle()
    val user by g.account.user.collectAsStateWithLifecycle()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val messages by vm.messages.collectAsStateWithLifecycle()
    val sending by vm.sending.collectAsStateWithLifecycle()
    val loading by vm.loading.collectAsStateWithLifecycle()
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    val error by vm.error.collectAsStateWithLifecycle()
    val needTopUp by vm.needTopUp.collectAsStateWithLifecycle()
    val voiceMode by vm.voiceMode.collectAsStateWithLifecycle()
    val sessionId by vm.sid.collectAsStateWithLifecycle()
    val boundPid by vm.profileId.collectAsStateWithLifecycle()
    val hasHistory by vm.hasHistory.collectAsStateWithLifecycle()
    var input by remember { mutableStateOf("") }
    val list = rememberLazyListState()

    LaunchedEffect(lang) { vm.setLang(lang) }

    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) vm.enterVoice(lang)
    }
    fun enterVoice() {
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) vm.enterVoice(lang)
        else micPermission.launch(Manifest.permission.RECORD_AUDIO)
    }
    LaunchedEffect(startVoice) { if (startVoice && !voiceMode) enterVoice() }
    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) { if (messages.isNotEmpty()) list.animateScrollToItem(messages.lastIndex) }

    var clients by remember { mutableStateOf<List<Profile>>(emptyList()) }
    LaunchedEffect(user?.isAstrologer) { if (user?.isAstrologer == true) clients = runCatching { g.api.clients() }.getOrDefault(emptyList()) }
    val candidates = if (user?.isAstrologer == true) (clients + profiles).distinctBy { it.id } else profiles.filter { it.relation != "client" }
    val bound = candidates.firstOrNull { it.id == (boundPid ?: settings.activeProfileId) }
        ?: if (user?.isAstrologer == true && boundPid == null) candidates.firstOrNull() else null
    LaunchedEffect(bound?.id) { bound?.let { vm.setProfile(it.id) } }

    if (needTopUp) TopUpSheet(reason = stringResource(R.string.topup_reason_question), onDismiss = { vm.dismissTopUp() }, onCredited = { vm.onToppedUp() })

    Scaffold(topBar = {
        AppTopBar(stringResource(R.string.chat_title), onBack = { nav.popBackStack() }, actions = {
            AssistChip(onClick = { nav.navigate(Routes.WALLET) }, label = { Text(balance?.let { rupees(it) } ?: "—") })
            Spacer(Modifier.width(8.dp))
        })
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().imePadding()) {
            // Who the chat is about — switchable until the first question.
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.chat_about), style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.width(8.dp))
                if (sessionId == null) ProfileSwitcher(candidates, bound, onPick = { vm.setProfile(it.id) },
                    onManage = { nav.navigate(if (user?.isAstrologer == true) Routes.CLIENTS else Routes.PROFILES) })
                else Text(bound?.name ?: "", style = MaterialTheme.typography.titleMedium)
            }
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = list, contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (loading) item { LoadingBox() }
                loadError?.let { e -> item { ErrorBox(e, onRetry = { vm.loadHistory() }) } }
                if (messages.isEmpty() && !loading) item {
                    SectionCard(accent = true) {
                        Text(stringResource(R.string.chat_empty_title), style = MaterialTheme.typography.titleMedium)
                        Text(stringResource(R.string.chat_empty_body))
                        if (hasHistory == false && user?.trial_claimed == true) Pill(stringResource(R.string.chat_first_free))
                        SuggestionChips { input = it }
                    }
                }
                itemsIndexed(messages) { _, m -> Bubble(m, onRetry = { vm.retryLast() }, onRead = { vm.readAloud(m.text) }) }
                error?.let { e -> item { ErrorBox(e, onRetry = null) } }
            }

            if (voiceMode) VoicePanel(vm)
            else {
                // Price shown before asking.
                Text(stringResource(R.string.chat_price_line, rupees(pricing.query_price_units), balance?.let { rupees(it) } ?: "—"),
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp))
                Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.Bottom) {
                    IconButton(onClick = { enterVoice() }, modifier = Modifier.size(52.dp)) {
                        Icon(Icons.Default.Mic, contentDescription = stringResource(R.string.cd_voice_mode), tint = MaterialTheme.colorScheme.primary)
                    }
                    OutlinedTextField(input, { input = it }, modifier = Modifier.weight(1f), placeholder = { Text(stringResource(R.string.chat_hint)) },
                        maxLines = 5, shape = RoundedCornerShape(20.dp))
                    Spacer(Modifier.width(6.dp))
                    FilledIconButton(onClick = { vm.ask(input); input = "" }, enabled = input.isNotBlank() && !sending, modifier = Modifier.size(52.dp)) {
                        if (sending) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        else Icon(Icons.AutoMirrored.Filled.Send, contentDescription = stringResource(R.string.cd_send))
                    }
                }
            }
        }
    }
}

@Composable
private fun SuggestionChips(onPick: (String) -> Unit) {
    val s = listOf(R.string.suggest_career, R.string.suggest_marriage, R.string.suggest_health, R.string.suggest_year)
    @OptIn(ExperimentalLayoutApi::class)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        s.forEach { id -> val t = stringResource(id); SuggestionChip(onClick = { onPick(t) }, label = { Text(t) }) }
    }
}

@Composable
private fun Bubble(m: UiMsg, onRetry: () -> Unit, onRead: () -> Unit) {
    val mine = m.role == "user"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Surface(
            shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = if (mine) 18.dp else 4.dp, bottomEnd = if (mine) 4.dp else 18.dp),
            color = if (mine) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
            tonalElevation = if (mine) 0.dp else 1.dp,
            modifier = Modifier.widthIn(max = 340.dp),
        ) {
            Column(Modifier.padding(12.dp).semantics { if (m.streaming) liveRegion = LiveRegionMode.Polite }) {
                if (mine) Text(m.text, style = MaterialTheme.typography.bodyLarge)
                else if (m.text.isBlank() && m.streaming) Text(stringResource(R.string.chat_thinking), color = MaterialTheme.colorScheme.onSurfaceVariant)
                else MarkdownText(m.text + if (m.streaming) " ▍" else "")
                if (!mine && !m.streaming) Row(verticalAlignment = Alignment.CenterVertically) {
                    val note = when {
                        m.charged > 0 -> stringResource(R.string.chat_charged, rupees(m.charged))
                        m.status == "clarify" || m.status == "refused" -> stringResource(R.string.chat_no_charge)
                        else -> null
                    }
                    if (note != null) Text(note, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f)) else Spacer(Modifier.weight(1f))
                    IconButton(onClick = onRead, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = stringResource(R.string.cd_read_aloud))
                    }
                }
                if (m.failed) TextButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
            }
        }
    }
}

@Composable
private fun VoicePanel(vm: ChatVm) {
    val state by vm.voiceState.collectAsStateWithLifecycle()
    val partial by vm.partial.collectAsStateWithLifecycle()
    val route by vm.voiceRoute.collectAsStateWithLifecycle()
    val handsFree by vm.handsFree.collectAsStateWithLifecycle()
    val pulse = rememberInfiniteTransition(label = "pulse")
    val s by pulse.animateFloat(1f, 1.12f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "s")
    val label = when (state) {
        VoiceState.LISTENING -> stringResource(R.string.voice_listening)
        VoiceState.THINKING -> stringResource(R.string.voice_thinking)
        VoiceState.SPEAKING -> stringResource(R.string.voice_speaking)
        VoiceState.IDLE -> stringResource(R.string.voice_tap_to_speak)
    }
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp).navigationBarsPadding(), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(label, style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            if (partial.isNotBlank()) Text(partial, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (route == VoiceRoute.CLOUD) Text(stringResource(R.string.voice_cloud_note), style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                IconButton(onClick = { vm.exitVoice() }, modifier = Modifier.size(52.dp)) {
                    Icon(Icons.Default.Close, contentDescription = stringResource(R.string.cd_exit_voice))
                }
                val big = Modifier.size(84.dp).let { if (state == VoiceState.LISTENING) it.scale(s) else it }
                when (state) {
                    VoiceState.SPEAKING -> FilledIconButton(onClick = { vm.stopSpeaking() }, modifier = big,
                        colors = IconButtonDefaults.filledIconButtonColors(containerColor = MaterialTheme.colorScheme.secondary)) {
                        Icon(Icons.Default.Stop, contentDescription = stringResource(R.string.cd_stop_speaking), modifier = Modifier.size(40.dp))
                    }
                    VoiceState.LISTENING -> FilledIconButton(onClick = { vm.stopListening() }, modifier = big) {
                        Icon(Icons.Default.Mic, contentDescription = stringResource(R.string.cd_stop_listening), modifier = Modifier.size(40.dp))
                    }
                    VoiceState.THINKING -> Box(big, contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(56.dp)) }
                    VoiceState.IDLE -> FilledIconButton(onClick = { vm.startListening() }, modifier = big) {
                        Icon(Icons.Default.Mic, contentDescription = stringResource(R.string.cd_start_listening), modifier = Modifier.size(40.dp))
                    }
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Switch(handsFree, { vm.handsFree.value = it })
                    Text(stringResource(R.string.voice_hands_free), style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
