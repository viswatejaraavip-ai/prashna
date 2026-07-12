package com.udhyath.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch

// Udhyath palette — matches the website's vibrant Indian styling.
private val Saffron = Color(0xFFFF9933)
private val DeepPurple = Color(0xFF4A148C)
private val Maroon = Color(0xFF900C3F)
private val Cream = Color(0xFFFFF8E7)

data class ChatMessage(val role: String, val content: String, val charge: Double = 0.0)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = DeepPurple, secondary = Saffron,
                    background = Cream, surface = Color.White,
                )
            ) { UdhyathApp() }
        }
    }
}

private fun prefs(context: Context) =
    context.getSharedPreferences("udhyath", Context.MODE_PRIVATE)

@Composable
fun UdhyathApp() {
    val context = LocalContext.current
    var token by remember { mutableStateOf(prefs(context).getString("token", null)) }
    Api.token = token

    if (token == null) {
        AuthScreen(onAuthed = { newToken ->
            prefs(context).edit().putString("token", newToken).apply()
            Api.token = newToken
            token = newToken
        })
    } else {
        ChatScreen(onLogout = {
            prefs(context).edit().remove("token").apply()
            Api.token = null
            token = null
        })
    }
}

@Composable
fun AuthScreen(onAuthed: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var otp by remember { mutableStateOf("") }
    var otpPending by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun run(block: suspend () -> Unit) {
        error = null; info = null; busy = true
        scope.launch {
            try { block() } catch (e: ApiException) {
                if (e.detail.startsWith("verify_email")) {
                    otpPending = true
                    info = "Enter the 6-digit code we emailed you."
                } else error = e.detail
            } catch (e: Exception) {
                error = e.message ?: "Network error"
            } finally { busy = false }
        }
    }

    Column(
        Modifier.fillMaxSize().background(Cream).imePadding()
            .verticalScroll(androidx.compose.foundation.rememberScrollState())
            .padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("🪔", fontSize = 56.sp)
        Text("Udhyath", fontSize = 34.sp, fontWeight = FontWeight.Bold, color = Maroon)
        Text("Vedic astrology, spoken in your language",
             color = DeepPurple, textAlign = TextAlign.Center)
        Spacer(Modifier.height(28.dp))

        if (!otpPending) {
            OutlinedTextField(email, { email = it.trim() }, label = { Text("Email") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(password, { password = it }, label = { Text("Password (8+ chars)") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(18.dp))
            Button(
                onClick = { run { onAuthed(Api.login(email, password).getString("token")) } },
                enabled = !busy && email.isNotBlank() && password.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Maroon),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) { Text(if (busy) "Please wait…" else "Sign in") }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = { run {
                    val r = Api.register(email, password)
                    if (r.optBoolean("pending_verification")) {
                        otpPending = true
                        info = "Enter the 6-digit code we emailed you."
                    }
                } },
                enabled = !busy && email.isNotBlank() && password.length >= 8,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) { Text("Create account") }
        } else {
            Text("Verifying $email", fontWeight = FontWeight.SemiBold, color = DeepPurple)
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(otp, { otp = it.filter(Char::isDigit).take(6) },
                label = { Text("6-digit code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(18.dp))
            Button(
                onClick = { run { onAuthed(Api.verifyOtp(email, otp).getString("token")) } },
                enabled = !busy && otp.length == 6,
                colors = ButtonDefaults.buttonColors(containerColor = Maroon),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) { Text(if (busy) "Please wait…" else "Verify") }
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = { run { Api.resendOtp(email); info = "Code re-sent." } }) {
                Text("Resend code")
            }
            TextButton(onClick = { otpPending = false; otp = "" }) { Text("Back") }
        }

        info?.let { Spacer(Modifier.height(12.dp)); Text(it, color = DeepPurple) }
        error?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(onLogout: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    var language by remember {
        mutableStateOf(LANGUAGES.first {
            it.tag == (prefs(context).getString("lang", "te-IN") ?: "te-IN")
        })
    }
    var langMenu by remember { mutableStateOf(false) }
    var balance by remember { mutableStateOf<Double?>(null) }
    var sessionId by remember { mutableStateOf<String?>(null) }
    val messages = remember { mutableStateListOf<ChatMessage>() }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var topupNeeded by remember { mutableStateOf(false) }
    var voiceState by remember { mutableStateOf(VoiceState.IDLE) }
    var liveMode by remember { mutableStateOf(false) }
    var speakReplies by remember { mutableStateOf(true) }
    var trialBanner by remember { mutableStateOf<String?>(null) }

    // Set after VoiceManager exists — recognizer results must reach sendText.
    var onRecognized by remember { mutableStateOf<(String) -> Unit>({}) }
    val voice = remember {
        VoiceManager(context,
            onResult = { text -> onRecognized(text) },
            onState = { voiceState = it },
            onError = { error = it })
    }
    DisposableEffect(Unit) { onDispose { voice.destroy() } }

    val micPermission = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) voice.startListening(language.tag) }

    fun listen() {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED) voice.startListening(language.tag)
        else micPermission.launch(Manifest.permission.RECORD_AUDIO)
    }

    voice.onSpeechDone = { if (liveMode) listen() }

    LaunchedEffect(Unit) {
        try { balance = Api.me().getDouble("balance") }
        catch (e: ApiException) { if (e.code == 401) onLogout() }
        catch (_: Exception) {}
        // First launch on this install: try to claim the one-per-device trial.
        if (!prefs(context).getBoolean("trial_checked", false)) {
            try {
                val deviceId = android.provider.Settings.Secure.getString(
                    context.contentResolver,
                    android.provider.Settings.Secure.ANDROID_ID) ?: return@LaunchedEffect
                val r = Api.claimTrial(deviceId)
                prefs(context).edit().putBoolean("trial_checked", true).apply()
                if (r.optBoolean("granted")) {
                    balance = r.optDouble("balance", balance ?: 0.0)
                    trialBanner = "🎁 Welcome! Your first question is free — " +
                                  "just share your birth details and ask."
                }
            } catch (_: Exception) { /* retry next launch */ }
        }
    }
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.size - 1)
    }

    fun sendText(text: String) {
        if (text.isBlank() || busy) return
        error = null; busy = true
        messages.add(ChatMessage("user", text))
        scope.launch {
            try {
                val sid = sessionId ?: Api.createSession().getString("session_id")
                    .also { sessionId = it }
                val r = Api.sendMessage(sid, text)
                val reply = r.getString("reply")
                messages.add(ChatMessage("assistant", reply, r.optDouble("charge", 0.0)))
                balance = r.optDouble("balance", balance ?: 0.0)
                if (speakReplies || liveMode) voice.speak(reply, language.tag)
            } catch (e: ApiException) {
                if (e.code == 402) topupNeeded = true else error = e.detail
                liveMode = false
            } catch (e: Exception) {
                error = e.message ?: "Network error"; liveMode = false
            } finally { busy = false }
        }
    }
    onRecognized = { text -> input = ""; sendText(text) }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = DeepPurple, titleContentColor = Color.White),
                title = {
                    Column {
                        Text("🪔 Udhyath", fontWeight = FontWeight.Bold)
                        Text(balance?.let { "₹%.2f".format(it) } ?: "…",
                             fontSize = 13.sp, color = Saffron)
                    }
                },
                actions = {
                    TextButton(onClick = { langMenu = true }) {
                        Text(language.label, color = Saffron, fontWeight = FontWeight.Bold)
                    }
                    DropdownMenu(expanded = langMenu, onDismissRequest = { langMenu = false }) {
                        LANGUAGES.forEach { lang ->
                            DropdownMenuItem(text = { Text(lang.label) }, onClick = {
                                language = lang; langMenu = false
                                prefs(context).edit().putString("lang", lang.tag).apply()
                            })
                        }
                    }
                    TextButton(onClick = onLogout) { Text("Logout", color = Color.White) }
                },
            )
        },
        containerColor = Cream,
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().imePadding()) {
            trialBanner?.let {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Saffron),
                    modifier = Modifier.fillMaxWidth().padding(10.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(it, Modifier.weight(1f).padding(12.dp),
                             color = Color(0xFF4A148C), fontWeight = FontWeight.SemiBold)
                        TextButton(onClick = { trialBanner = null }) { Text("✕") }
                    }
                }
            }
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(12.dp),
            ) {
                if (messages.isEmpty()) item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color.White),
                        modifier = Modifier.fillMaxWidth().padding(top = 24.dp),
                    ) {
                        Text(
                            "Namaste! 🙏 Share your birth date, exact time and place, " +
                            "and ask anything — career, marriage, health, timing. " +
                            "I read your KP, Nadi, bhava, Ashtakavarga and all four " +
                            "dasha systems together before answering.\n\n" +
                            "Tap the mic and speak in ${language.label} — I will " +
                            "reply in your language, with voice.",
                            Modifier.padding(16.dp), color = DeepPurple)
                    }
                }
                items(messages) { msg -> MessageBubble(msg) }
                if (busy) item {
                    Text("The astrologer is consulting your charts…",
                         Modifier.padding(12.dp), color = Maroon, fontSize = 13.sp)
                }
            }

            error?.let {
                Text(it, Modifier.fillMaxWidth().padding(horizontal = 14.dp),
                     color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
            }
            if (voiceState == VoiceState.LISTENING)
                Text("🎙 Listening (${language.label})…",
                     Modifier.fillMaxWidth().padding(4.dp),
                     textAlign = TextAlign.Center, color = Maroon)

            Row(
                Modifier.fillMaxWidth().padding(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    input, { input = it },
                    placeholder = { Text("Ask in ${language.label}…") },
                    modifier = Modifier.weight(1f),
                    maxLines = 3,
                )
                Spacer(Modifier.width(6.dp))
                FilledIconButton(
                    onClick = {
                        if (voiceState == VoiceState.SPEAKING) voice.stopSpeaking() else listen()
                    },
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = if (voiceState == VoiceState.LISTENING) Maroon else Saffron),
                    modifier = Modifier.size(48.dp),
                ) { Text(if (voiceState == VoiceState.SPEAKING) "⏹" else "🎙", fontSize = 20.sp) }
                Spacer(Modifier.width(6.dp))
                FilledIconButton(
                    onClick = { val t = input; input = ""; sendText(t) },
                    enabled = !busy && input.isNotBlank(),
                    colors = IconButtonDefaults.filledIconButtonColors(containerColor = DeepPurple),
                    modifier = Modifier.size(48.dp),
                ) { Text("➤", color = Color.White, fontSize = 18.sp) }
            }
            Row(
                Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Switch(checked = liveMode, onCheckedChange = { liveMode = it; if (it) listen() })
                Text("  Live conversation", fontSize = 13.sp, color = DeepPurple)
                Spacer(Modifier.weight(1f))
                Switch(checked = speakReplies, onCheckedChange = { speakReplies = it })
                Text("  Speak replies", fontSize = 13.sp, color = DeepPurple)
            }
        }
    }

    if (topupNeeded) AlertDialog(
        onDismissRequest = { topupNeeded = false },
        title = { Text("Balance too low") },
        text = { Text("Add funds to your Udhyath wallet on the website, " +
                      "then come back — your balance is shared across web, " +
                      "API and this app.") },
        confirmButton = {
            Button(onClick = {
                topupNeeded = false
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(Api.BASE)))
            }) { Text("Open website") }
        },
        dismissButton = {
            TextButton(onClick = { topupNeeded = false }) { Text("Later") }
        },
    )
}

@Composable
fun MessageBubble(msg: ChatMessage) {
    val isUser = msg.role == "user"
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            Modifier
                .widthIn(max = 300.dp)
                .background(
                    if (isUser) DeepPurple else Color.White,
                    RoundedCornerShape(
                        topStart = 14.dp, topEnd = 14.dp,
                        bottomStart = if (isUser) 14.dp else 2.dp,
                        bottomEnd = if (isUser) 2.dp else 14.dp))
                .padding(12.dp)
        ) {
            Text(msg.content, color = if (isUser) Color.White else Color(0xFF2D2D2D))
            if (!isUser && msg.charge > 0)
                Text("₹%.2f".format(msg.charge), fontSize = 11.sp, color = Maroon)
        }
    }
}
