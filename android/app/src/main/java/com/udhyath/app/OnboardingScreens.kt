package com.udhyath.app

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FamilyRestroom
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.SelfImprovement
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.firebase.FirebaseException
import com.google.firebase.auth.AuthCredential
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.GoogleAuthProvider
import com.google.firebase.auth.PhoneAuthCredential
import com.google.firebase.auth.PhoneAuthOptions
import com.google.firebase.auth.PhoneAuthProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.booleanOrNull
import java.util.Calendar
import java.util.concurrent.TimeUnit

// ===========================================================================
// 1. Language picker — first thing on first launch; also Settings > Language
// ===========================================================================

@Composable
fun LanguagePickerScreen(firstRun: Boolean, current: AppLang?, onBack: (() -> Unit)? = null, onPick: (AppLang) -> Unit) {
    val body: @Composable ColumnScope.() -> Unit = {
        if (firstRun) {
            Spacer(Modifier.height(24.dp))
            Icon(painterResource(R.drawable.ic_diya), contentDescription = null, tint = Color.Unspecified,
                modifier = Modifier.size(88.dp).align(Alignment.CenterHorizontally))
            // Before a language is chosen we greet in all five scripts.
            Text(stringResource(R.string.lang_prompt_all), style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.secondary)
            Spacer(Modifier.height(8.dp))
        }
        AppLang.entries.forEachIndexed { i, lang ->
            val selected = lang == current
            OutlinedCard(
                modifier = Modifier.fillMaxWidth().heightIn(min = 76.dp)
                    .selectable(selected = selected, role = Role.RadioButton) { onPick(lang) }
                    .semantics { contentDescription = "${i + 1}. ${lang.nativeName}" },
                shape = RoundedCornerShape(20.dp),
                border = BorderStroke(if (selected) 2.dp else 1.dp,
                    if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline),
                colors = CardDefaults.outlinedCardColors(
                    containerColor = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface),
            ) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(40.dp).padding(2.dp), contentAlignment = Alignment.Center) {
                        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxSize()) {
                            Box(contentAlignment = Alignment.Center) { Text("${i + 1}", style = MaterialTheme.typography.titleMedium) }
                        }
                    }
                    Spacer(Modifier.width(16.dp))
                    Text(lang.nativeName, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f))
                    if (selected) Icon(Icons.Default.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
    if (firstRun) {
        Column(Modifier.fillMaxSize().systemBarsPadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp), content = body)
    } else {
        ScreenScaffold(stringResource(R.string.language_title), onBack = onBack) {
            Text(stringResource(R.string.language_hint), color = MaterialTheme.colorScheme.onSurfaceVariant)
            body()
        }
    }
}

// ===========================================================================
// 2. Sign in — Firebase phone OTP (+91 default) or Google → /api/auth/firebase
// ===========================================================================

class AuthVm(private val g: AppGraph) : ViewModel() {
    enum class Step { PHONE, CODE }
    val step = MutableStateFlow(Step.PHONE)
    val busy = MutableStateFlow(false)
    val error = MutableStateFlow<String?>(null)
    val errorKind = MutableStateFlow<Int?>(null) // string res for local errors
    private var verificationId: String? = null
    private var resendToken: PhoneAuthProvider.ForceResendingToken? = null
    var phoneShown = ""
        private set

    private val auth get() = FirebaseAuth.getInstance().apply { setLanguageCode(g.langCode ?: "hi") }

    fun sendCode(activity: android.app.Activity, countryCode: String, number: String, resend: Boolean = false) {
        val digits = number.filter { it.isDigit() }
        if (digits.length < 6) { errorKind.value = R.string.auth_bad_phone; return }
        phoneShown = "+${countryCode.filter { it.isDigit() }}$digits"
        busy.value = true; error.value = null; errorKind.value = null
        val opts = PhoneAuthOptions.newBuilder(auth)
            .setPhoneNumber(phoneShown)
            .setTimeout(60L, TimeUnit.SECONDS)
            .setActivity(activity)
            .setCallbacks(object : PhoneAuthProvider.OnVerificationStateChangedCallbacks() {
                override fun onVerificationCompleted(credential: PhoneAuthCredential) { signIn(credential) }
                override fun onVerificationFailed(e: FirebaseException) {
                    busy.value = false; errorKind.value = R.string.auth_otp_failed
                }
                override fun onCodeSent(id: String, token: PhoneAuthProvider.ForceResendingToken) {
                    verificationId = id; resendToken = token
                    busy.value = false; step.value = Step.CODE
                }
            })
        if (resend) resendToken?.let { opts.setForceResendingToken(it) }
        PhoneAuthProvider.verifyPhoneNumber(opts.build())
    }

    fun verifyCode(code: String) {
        val id = verificationId ?: return
        if (code.length != 6) { errorKind.value = R.string.auth_bad_code; return }
        signIn(PhoneAuthProvider.getCredential(id, code))
    }

    fun back() { step.value = Step.PHONE; error.value = null; errorKind.value = null }

    fun google(activity: android.app.Activity) {
        val resId = activity.resources.getIdentifier("default_web_client_id", "string", activity.packageName)
        if (resId == 0) { errorKind.value = R.string.auth_google_unconfigured; return }
        busy.value = true; error.value = null; errorKind.value = null
        viewModelScope.launch {
            try {
                val option = GetGoogleIdOption.Builder()
                    .setServerClientId(activity.getString(resId))
                    .setFilterByAuthorizedAccounts(false)
                    .build()
                val result = CredentialManager.create(activity)
                    .getCredential(activity, GetCredentialRequest.Builder().addCredentialOption(option).build())
                val cred = result.credential
                if (cred is CustomCredential && cred.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                    val idToken = GoogleIdTokenCredential.createFrom(cred.data).idToken
                    signIn(GoogleAuthProvider.getCredential(idToken, null))
                } else { busy.value = false; errorKind.value = R.string.auth_google_failed }
            } catch (_: GetCredentialCancellationException) {
                busy.value = false
            } catch (_: androidx.credentials.exceptions.NoCredentialException) {
                // No Google account on this phone: phone OTP remains available.
                busy.value = false; errorKind.value = R.string.auth_google_failed
            } catch (e: Exception) {
                busy.value = false; errorKind.value = R.string.auth_google_failed
            }
        }
    }

    private fun signIn(credential: AuthCredential) {
        busy.value = true; error.value = null; errorKind.value = null
        viewModelScope.launch {
            try {
                val fbUser = auth.signInWithCredential(credential).await().user ?: error("no user")
                val idToken = fbUser.getIdToken(true).await().token ?: error("no token")
                val res = g.api.authFirebase(idToken, g.settings.deviceId(), g.langCode ?: "hi")
                g.account.onSignedIn(res)
                signedIn.value = true
            } catch (e: ApiException) {
                error.value = e.detail; if (e.detail == null) errorKind.value = R.string.err_server
            } catch (e: java.io.IOException) {
                errorKind.value = R.string.err_offline
            } catch (e: Exception) {
                errorKind.value = if (step.value == Step.CODE) R.string.auth_bad_code else R.string.auth_otp_failed
            } finally { busy.value = false }
        }
    }

    val signedIn = MutableStateFlow(false)
}

@Composable
fun AuthScreen(onSignedIn: () -> Unit) {
    val vm = graphViewModel { AuthVm(it) }
    val ctx = LocalContext.current
    val activity = ctx.findActivity()
    val step by vm.step.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    val error by vm.error.collectAsStateWithLifecycle()
    val errorRes by vm.errorKind.collectAsStateWithLifecycle()
    val done by vm.signedIn.collectAsStateWithLifecycle()
    LaunchedEffect(done) {
        // The VM outlives sign-out (activity scope), so consume the flag.
        if (done) { vm.signedIn.value = false; vm.back(); onSignedIn() }
    }

    var cc by rememberSaveable { mutableStateOf("91") }
    var phone by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var resendIn by remember { mutableIntStateOf(0) }
    LaunchedEffect(step) {
        if (step == AuthVm.Step.CODE) { resendIn = 30; while (resendIn > 0) { delay(1000); resendIn-- } }
    }

    Column(Modifier.fillMaxSize().systemBarsPadding().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Spacer(Modifier.height(24.dp))
        Icon(painterResource(R.drawable.ic_diya), contentDescription = null, tint = Color.Unspecified, modifier = Modifier.size(84.dp))
        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.displaySmall, color = MaterialTheme.colorScheme.secondary,
            fontWeight = FontWeight.Bold)
        Text(stringResource(R.string.tagline), textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(12.dp))

        if (step == AuthVm.Step.PHONE) {
            Text(stringResource(R.string.auth_phone_title), style = MaterialTheme.typography.titleMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(cc, { cc = it.filter(Char::isDigit).take(3) }, prefix = { Text("+") },
                    label = { Text(stringResource(R.string.auth_country)) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.width(96.dp))
                Spacer(Modifier.width(8.dp))
                OutlinedTextField(phone, { phone = it.filter(Char::isDigit).take(12) },
                    label = { Text(stringResource(R.string.auth_phone_label)) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.weight(1f))
            }
            BigButton(stringResource(R.string.auth_send_code), onClick = { activity?.let { vm.sendCode(it, cc, phone) } },
                enabled = phone.length >= 6, busy = busy)
        } else {
            Text(stringResource(R.string.auth_code_sent, vm.phoneShown), textAlign = TextAlign.Center)
            OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6); if (code.length == 6) vm.verifyCode(code) },
                label = { Text(stringResource(R.string.auth_code_label)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
            BigButton(stringResource(R.string.auth_verify), onClick = { vm.verifyCode(code) }, enabled = code.length == 6, busy = busy)
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                TextButton(onClick = { vm.back() }) { Text(stringResource(R.string.auth_change_number)) }
                TextButton(onClick = { activity?.let { vm.sendCode(it, cc, phone, resend = true) } }, enabled = resendIn == 0 && !busy) {
                    Text(if (resendIn > 0) stringResource(R.string.auth_resend_in, resendIn) else stringResource(R.string.auth_resend))
                }
            }
        }

        (error ?: errorRes?.let { stringResource(it) })?.let {
            Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
        }

        if (step == AuthVm.Step.PHONE) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                HorizontalDivider(Modifier.weight(1f))
                Text(stringResource(R.string.or), Modifier.padding(horizontal = 12.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                HorizontalDivider(Modifier.weight(1f))
            }
            BigButton(stringResource(R.string.auth_google), onClick = { activity?.let { vm.google(it) } }, secondary = true, enabled = !busy)
        }
        Spacer(Modifier.height(8.dp))
        Text(stringResource(R.string.auth_terms_note), style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ===========================================================================
// 3. Role — "for myself / my family" vs "I'm an astrologer"
// ===========================================================================

@Composable
fun RoleScreen() {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf<String?>(null) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    fun pick(role: String) {
        busy = role; err = null
        scope.launch {
            try {
                g.account.setUser(g.api.patchMe(role = role))
                g.settings.setRoleChosen(true)
            } catch (e: Exception) { err = e } finally { busy = null }
        }
    }
    Column(Modifier.fillMaxSize().systemBarsPadding().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Spacer(Modifier.height(16.dp))
        Text(stringResource(R.string.role_title), style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.secondary)
        RoleCard(Icons.Default.FamilyRestroom, stringResource(R.string.role_personal), stringResource(R.string.role_personal_desc), busy == "user") { pick("user") }
        RoleCard(Icons.Default.SelfImprovement, stringResource(R.string.role_astrologer), stringResource(R.string.role_astrologer_desc), busy == "astrologer") { pick("astrologer") }
        err?.let { ErrorBox(it, onRetry = null) }
    }
}

@Composable
private fun RoleCard(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, desc: String, busy: Boolean, onClick: () -> Unit) {
    OutlinedCard(onClick = onClick, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp)) {
        Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(44.dp))
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                Text(desc, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (busy) CircularProgressIndicator(Modifier.size(24.dp))
        }
    }
}

// ===========================================================================
// 4. Disclaimer acceptance
// ===========================================================================

@Composable
fun DisclaimerScreen() {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    var doc by remember { mutableStateOf<LegalDoc?>(null) }
    var agreed by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var legalOpen by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { doc = runCatching { g.api.legal("disclaimer") }.getOrNull() }

    legalOpen?.let { LegalDialog(it) { legalOpen = null } }

    Column(Modifier.fillMaxSize().systemBarsPadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(doc?.title?.ifBlank { null } ?: stringResource(R.string.disclaimer_title),
            style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.secondary)
        SectionCard(Modifier.weight(1f)) {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                val body = doc?.body_markdown
                if (body.isNullOrBlank()) Text(stringResource(R.string.disclaimer_fallback), style = MaterialTheme.typography.bodyLarge)
                else MarkdownText(body)
            }
        }
        Row(Modifier.fillMaxWidth().toggleable(agreed, role = Role.Checkbox) { agreed = it }, verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = agreed, onCheckedChange = null)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.disclaimer_agree))
        }
        Row {
            TextButton(onClick = { legalOpen = "terms" }) { Text(stringResource(R.string.legal_terms)) }
            TextButton(onClick = { legalOpen = "privacy" }) { Text(stringResource(R.string.legal_privacy)) }
        }
        err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        BigButton(stringResource(R.string.continue_), enabled = agreed, busy = busy, onClick = {
            busy = true; err = null
            scope.launch {
                try { g.api.acceptDisclaimer(); g.settings.setDisclaimerAccepted(true) }
                catch (e: Exception) { err = e } finally { busy = false }
            }
        })
    }
}

@Composable
fun LegalDialog(docName: String, onClose: () -> Unit) {
    val g = LocalContext.current.graph
    var state by remember { mutableStateOf<Load<LegalDoc>>(Load.Loading) }
    LaunchedEffect(docName) { state = runCatching { g.api.legal(docName) }.fold({ Load.Ok(it) }, { Load.Err(it) }) }
    AlertDialog(onDismissRequest = onClose,
        confirmButton = { TextButton(onClick = onClose) { Text(stringResource(R.string.close)) } },
        title = { Text(state.dataOrNull?.title ?: "") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                LoadView(state, onRetry = {}) { MarkdownText(it.body_markdown) }
            }
        })
}

// ===========================================================================
// 5. Birth details / profile editor (family member or astrologer client)
// ===========================================================================

val RELATIONS = listOf("self", "spouse", "child", "parent", "other")

@Composable
fun relationLabel(r: String): String = stringResource(when (r) {
    "self" -> R.string.rel_self; "spouse" -> R.string.rel_spouse; "child" -> R.string.rel_child
    "parent" -> R.string.rel_parent; "client" -> R.string.rel_client; else -> R.string.rel_other
})

@Composable
fun ProfileEditScreen(
    pid: String?,
    onboarding: Boolean,
    presetRelation: String? = null,
    asClient: Boolean = false,
    onDone: (Profile) -> Unit,
    onBack: (() -> Unit)?,
) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    val existing = remember(pid) { profiles.firstOrNull { it.id == pid } }

    var name by rememberSaveable { mutableStateOf(existing?.name ?: "") }
    var relation by rememberSaveable { mutableStateOf(existing?.relation ?: presetRelation ?: if (asClient) "client" else if (onboarding) "self" else "spouse") }
    var gender by rememberSaveable { mutableStateOf(existing?.gender) }
    var date by rememberSaveable { mutableStateOf(existing?.birth?.date ?: "") }
    var time by rememberSaveable { mutableStateOf(existing?.birth?.time?.takeIf { existing.time_known } ?: "") }
    var timeUnknown by rememberSaveable { mutableStateOf(existing?.let { !it.time_known } ?: false) }
    var place by remember { mutableStateOf(existing?.birth?.let { Place(it.place, "", it.lat, it.lon, it.tz, label_local = it.place_local) }) }
    var notes by rememberSaveable { mutableStateOf(existing?.notes ?: "") }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<Throwable?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }

    val valid = name.isNotBlank() && date.isNotBlank() && (timeUnknown || time.isNotBlank()) && place != null

    fun save() {
        val p = place ?: return
        busy = true; err = null
        val input = ProfileInput(
            name = name.trim(), relation = relation,
            birth = Birth(date = date, time = if (timeUnknown) "12:00" else time, tz = p.tz_name, lat = p.latitude, lon = p.longitude, place = p.label),
            time_known = !timeUnknown, gender = gender, notes = notes.ifBlank { null },
        )
        scope.launch {
            try {
                val saved = when {
                    pid != null -> g.api.updateProfile(pid, input)
                    asClient || relation == "client" -> g.api.addClient(input)
                    else -> g.api.createProfile(input)
                }.let { if (it.id.isBlank() && pid != null) it.copy(id = pid) else it }
                g.account.upsertLocal(saved)
                // Only onboarding (the first, "self" profile) changes whose chart the app shows.
                if (onboarding) g.settings.setActiveProfile(saved.id)
                onDone(saved)
            } catch (e: Exception) { err = e } finally { busy = false }
        }
    }

    val title = when {
        onboarding -> stringResource(R.string.birth_title_onboarding)
        pid != null -> stringResource(R.string.profile_edit_title)
        asClient -> stringResource(R.string.client_add_title)
        else -> stringResource(R.string.profile_add_title)
    }

    if (confirmDelete && pid != null) AlertDialog(
        onDismissRequest = { confirmDelete = false },
        title = { Text(stringResource(R.string.profile_delete_title)) },
        text = { Text(stringResource(R.string.profile_delete_body, name)) },
        confirmButton = { TextButton(onClick = {
            confirmDelete = false
            scope.launch {
                runCatching { g.api.deleteProfile(pid) }.onSuccess { g.account.removeLocal(pid); onBack?.invoke() }.onFailure { err = it }
            }
        }) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } },
    )

    ScreenScaffold(title, onBack = onBack, actions = {
        if (pid != null && existing?.relation != "self") IconButton(onClick = { confirmDelete = true }) {
            Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.delete))
        }
    }) {
        if (onboarding) Text(stringResource(R.string.birth_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.field_name)) }, singleLine = true,
            modifier = Modifier.fillMaxWidth())

        if (!onboarding && !asClient && relation != "client") {
            Text(stringResource(R.string.field_relation), style = MaterialTheme.typography.labelLarge)
            ChipRow(RELATIONS.filter { it != "self" || existing?.relation == "self" || profiles.none { p -> p.relation == "self" } }, relation,
                label = { relationLabel(it) }) { relation = it }
        }
        Text(stringResource(R.string.field_gender), style = MaterialTheme.typography.labelLarge)
        ChipRow(listOf("male", "female", "other"), gender, label = {
            stringResource(when (it) { "male" -> R.string.gender_male; "female" -> R.string.gender_female; else -> R.string.gender_other })
        }) { gender = if (gender == it) null else it }

        // Date
        OutlinedButton(onClick = {
            val c = Calendar.getInstance()
            val parts = date.split("-").mapNotNull { it.toIntOrNull() }
            val (y, m, d) = if (parts.size == 3) Triple(parts[0], parts[1] - 1, parts[2]) else Triple(1990, 0, 1)
            DatePickerDialog(ctx, { _, yy, mm, dd -> date = "%04d-%02d-%02d".format(yy, mm + 1, dd) }, y, m, d).apply {
                datePicker.maxDate = c.timeInMillis
            }.show()
        }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) {
            Icon(Icons.Default.CalendarMonth, contentDescription = null); Spacer(Modifier.width(8.dp))
            Text(if (date.isBlank()) stringResource(R.string.field_birth_date) else formatDate(date))
        }
        // Time
        OutlinedButton(onClick = {
            val parts = time.split(":").mapNotNull { it.toIntOrNull() }
            TimePickerDialog(ctx, { _, h, m -> time = "%02d:%02d".format(h, m); timeUnknown = false },
                parts.getOrElse(0) { 6 }, parts.getOrElse(1) { 0 }, false).show()
        }, enabled = !timeUnknown, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) {
            Icon(Icons.Default.Schedule, contentDescription = null); Spacer(Modifier.width(8.dp))
            Text(if (time.isBlank() || timeUnknown) stringResource(R.string.field_birth_time) else formatTime(time))
        }
        Row(Modifier.fillMaxWidth().toggleable(timeUnknown, role = Role.Checkbox) { timeUnknown = it },
            verticalAlignment = Alignment.CenterVertically) {
            Checkbox(timeUnknown, onCheckedChange = null); Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.field_time_unknown))
        }
        if (timeUnknown) Text(stringResource(R.string.time_unknown_note), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)

        PlaceSearchField(place) { place = it }

        if (asClient || relation == "client" || existing?.relation == "client") {
            OutlinedTextField(notes, { notes = it }, label = { Text(stringResource(R.string.field_notes)) },
                modifier = Modifier.fillMaxWidth(), minLines = 2)
        }

        err?.let { Text(errorText(it), color = MaterialTheme.colorScheme.error) }
        BigButton(stringResource(if (onboarding) R.string.birth_cta else R.string.save), onClick = { save() }, enabled = valid, busy = busy)
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
fun <T> ChipRow(options: List<T>, selected: T?, label: @Composable (T) -> String, onSelect: (T) -> Unit) {
    @OptIn(ExperimentalLayoutApi::class)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        options.forEach { o ->
            FilterChip(selected = o == selected, onClick = { onSelect(o) }, label = { Text(label(o)) })
        }
    }
}

/**
 * Debounced `/api/places?q=` search with a result list; the picked place
 * carries lat/lon/tz. Once picked, the place is shown read-only with a
 * "change" button: Indic transliterating keyboards (e.g. Gboard Telugu)
 * commit their own script over the text on selection, which would otherwise
 * overwrite the label and re-trigger a search that finds nothing.
 */
@Composable
fun PlaceSearchField(selected: Place?, label: String = stringResource(R.string.field_birth_place), onPick: (Place) -> Unit) {
    val g = LocalContext.current.graph
    val focus = androidx.compose.ui.platform.LocalFocusManager.current
    var editing by remember(selected) { mutableStateOf(selected == null) }
    var q by remember(selected) { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Place>>(emptyList()) }
    var searching by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    LaunchedEffect(q, editing) {
        if (!editing || q.trim().length < 2) { results = emptyList(); return@LaunchedEffect }
        delay(300)
        searching = true; failed = false
        runCatching { g.api.places(q.trim()) }.onSuccess { results = it }.onFailure { failed = true }
        searching = false
    }
    Column {
        if (!editing && selected != null) {
            OutlinedTextField(selected.shown, {}, readOnly = true, label = { Text(label) }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                leadingIcon = { Icon(Icons.Default.Place, contentDescription = null) },
                trailingIcon = {
                    TextButton(onClick = { q = ""; results = emptyList(); editing = true }) {
                        Text(stringResource(R.string.action_change))
                    }
                })
            return@Column
        }
        OutlinedTextField(q, { q = it }, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            leadingIcon = { Icon(Icons.Default.Place, contentDescription = null) },
            trailingIcon = { if (searching) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) })
        if (failed) Text(stringResource(R.string.err_offline), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        results.take(8).forEach { p ->
            Text(p.shown, Modifier.fillMaxWidth().clickable {
                focus.clearFocus(); results = emptyList(); editing = false; onPick(p)
            }.padding(vertical = 12.dp, horizontal = 8.dp), style = MaterialTheme.typography.bodyLarge)
            HorizontalDivider()
        }
        if (!searching && !failed && results.isEmpty() && q.trim().length >= 2)
            Text(stringResource(R.string.place_no_results), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

fun formatDate(iso: String): String = runCatching {
    val p = iso.take(10).split("-").map { it.toInt() }
    val c = Calendar.getInstance().apply { set(p[0], p[1] - 1, p[2]) }
    java.text.DateFormat.getDateInstance(java.text.DateFormat.MEDIUM).format(c.time)
}.getOrDefault(iso)

fun formatTime(hhmm: String): String = runCatching {
    val p = hhmm.split(":").map { it.toInt() }
    val c = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, p[0]); set(Calendar.MINUTE, p[1]) }
    java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(c.time)
}.getOrDefault(hhmm)

fun formatDateTime(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    return runCatching {
        val inst = java.time.Instant.parse(if (iso.endsWith("Z") || iso.contains('+')) iso else iso + "Z")
        val z = inst.atZone(java.time.ZoneId.systemDefault())
        java.time.format.DateTimeFormatter.ofLocalizedDateTime(java.time.format.FormatStyle.MEDIUM, java.time.format.FormatStyle.SHORT).format(z)
    }.getOrElse { formatDate(iso) }
}

// ===========================================================================
// 6. Free snapshot — the first reading, right after onboarding
// ===========================================================================

@Composable
fun SnapshotScreen(pid: String, onContinue: (askFirst: Boolean) -> Unit) {
    val g = LocalContext.current.graph
    val user by g.account.user.collectAsStateWithLifecycle()
    var state by remember { mutableStateOf<Load<JsonObject>>(Load.Loading) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(pid, tick) {
        state = Load.Loading
        state = runCatching { g.api.snapshot(pid) }.fold({ Load.Ok(it) }, { Load.Err(it) })
    }
    Column(Modifier.fillMaxSize().systemBarsPadding().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(stringResource(R.string.snapshot_title), style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.secondary)
        Text(stringResource(R.string.snapshot_subtitle), color = MaterialTheme.colorScheme.onSurfaceVariant)
        LoadView(state, onRetry = { tick++ }) { SnapshotCards(it) }
        if (state is Load.Ok || state is Load.Err) {
            SectionCard(accent = true) {
                Text(stringResource(if (user?.trial_claimed == true) R.string.snapshot_cta_ask else R.string.snapshot_cta_free),
                    style = MaterialTheme.typography.titleMedium)
                BigButton(stringResource(R.string.ask_astrologer), onClick = { onContinue(true) })
            }
            BigButton(stringResource(R.string.snapshot_continue), onClick = { onContinue(false) }, secondary = true)
        }
    }
}

/** The first reading, laid out from the known /snapshot shape (all text is already localized). */
@Composable
fun SnapshotCards(s: JsonObject) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (key in listOf("lagna", "moon_sign", "nakshatra")) {
            val o = s[key].obj() ?: continue
            SectionCard(title = o.str("title")) {
                o.str("name")?.let { Text(it, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold) }
                o.str("text")?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
            }
        }
        s["dasha"].obj()?.let { d ->
            SectionCard(title = d.str("title")) {
                for (part in listOf("maha", "antar")) {
                    val o = d[part].obj() ?: continue
                    o.str("name")?.let { Text(it, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
                    o.str("text")?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
                    Spacer(Modifier.height(6.dp))
                }
            }
        }
        s["notes"].arr()?.mapNotNull { (it as? JsonPrimitive)?.content }?.filter { it.isNotBlank() }?.takeIf { it.isNotEmpty() }?.let { notes ->
            SectionCard { notes.forEach { Row { Text("•  "); Text(it, style = MaterialTheme.typography.bodyMedium) } } }
        }
        s.str("disclaimer")?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Internal flags the server sends alongside readings; never shown as rows. */
private val HIDDEN_KEYS = setOf("profile_id", "lang", "id", "cached", "generated_at", "date_key",
    "approximate", "time_known")

/**
 * Presents a reading-like object (snapshot, daily forecast) as friendly cards:
 * each top-level entry becomes a card with its localized title, headline value
 * and plain-language line(s).
 */
@Composable
fun ReadingCards(obj: JsonObject) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        obj.forEach { (k, v) ->
            if (k in HIDDEN_KEYS) return@forEach
            if (v is JsonPrimitive && (v.booleanOrNull != null || v is JsonNull)) return@forEach
            when (v) {
                is JsonPrimitive -> if (v.content.length > 60) SectionCard(title = keyLabel(k)) { Text(v.content, style = MaterialTheme.typography.bodyLarge) }
                    else SectionCard { KeyValue(keyLabel(k), v.displayText(), strong = true) }
                is JsonObject -> SectionCard(title = keyLabel(k)) {
                    val head = v.str("name", "sign", "value", "lord", "title")
                    val line = v.str("line", "text", "meaning", "description", "summary", "plain")
                    if (head != null) Text(head, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                    if (line != null) Text(line, style = MaterialTheme.typography.bodyLarge)
                    val rest = JsonObject(v.filter { (key, value) -> key !in setOf("name", "sign", "value", "lord", "title", "line", "text", "meaning", "description", "summary", "plain") &&
                        key !in HIDDEN_KEYS && !(value is JsonPrimitive && value.booleanOrNull != null) })
                    if (rest.isNotEmpty()) JsonView(rest)
                }
                is JsonArray -> SectionCard(title = keyLabel(k)) {
                    v.forEach { item ->
                        when (item) {
                            is JsonPrimitive -> Row { Text("•  "); Text(item.content, style = MaterialTheme.typography.bodyLarge) }
                            is JsonObject -> {
                                val t = item.str("title", "name", "kind", "type")
                                val d = item.str("line", "text", "description", "summary")
                                if (t != null) Text(t, fontWeight = FontWeight.SemiBold)
                                if (d != null) Text(d)
                                if (t == null && d == null) JsonView(item)
                                Spacer(Modifier.height(4.dp))
                            }
                            else -> JsonView(item)
                        }
                    }
                }
            }
        }
    }
}
