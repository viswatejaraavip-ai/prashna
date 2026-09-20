package com.udhyath.app

import android.app.Application
import android.content.Context
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await

class UdhyathApplication : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        // Four binder calls to system_server; nothing before the first frame
        // needs them, so they don't belong on the main thread at start-up.
        graph.scope.launch(Dispatchers.Default) { Notifications.createChannels(this@UdhyathApplication) }
    }
}

val Context.graph: AppGraph get() = (applicationContext as UdhyathApplication).graph

/** Manual dependency container: one instance per process. */
class AppGraph(val app: Application) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val settings = SettingsStore(app)
    val tokens = TokenStore(app)
    val cache = AccountCache(app)

    /**
     * Language code for Accept-Language; kept in memory so the HTTP layer
     * never blocks. Read synchronously from the SharedPreferences mirror (and
     * the AppCompat locale as a second source), then confirmed from DataStore
     * off the main thread — this used to be a `runBlocking` DataStore read in
     * Application.onCreate, i.e. disk I/O before the first frame.
     */
    @Volatile var langCode: String? = settings.langCodeNow ?: LocaleController.current()?.code

    val api = UdhyathApi(BuildConfig.API_BASE, tokenProvider = { tokens.get() }, langProvider = { langCode })
    val account = AccountRepo(this)
    val billing by lazy { BillingManager(app, api) }

    init {
        scope.launch {
            settings.current().lang?.code?.let { langCode = it }
        }
        // Open the connection to the API (DNS + TCP + TLS) and wake a Cloud
        // Run instance now, in the background, so the first request the user
        // actually waits for - usually POST /api/auth/firebase right after
        // they type the OTP - lands on a warm instance over a pooled socket.
        scope.launch { api.warm() }
    }
}

/**
 * Signed-in state shared by every screen: the user document, pricing, and the
 * profile list with the active profile (family switcher / astrologer client).
 */
class AccountRepo(private val g: AppGraph) {
    private val _user = MutableStateFlow<User?>(null)
    val user: StateFlow<User?> = _user.asStateFlow()
    private val _pricing = MutableStateFlow(Pricing())
    val pricing: StateFlow<Pricing> = _pricing.asStateFlow()
    private val _profiles = MutableStateFlow<List<Profile>>(emptyList())
    val profiles: StateFlow<List<Profile>> = _profiles.asStateFlow()
    private val _loaded = MutableStateFlow(false)
    /** True once profiles are available - from the cache or from the server. */
    val loaded: StateFlow<Boolean> = _loaded.asStateFlow()

    val signedIn: Boolean get() = g.tokens.get() != null

    init {
        // Paint the real home screen from the last known payload instead of a
        // splash spinner; the refresh below replaces it a moment later.
        if (signedIn) g.cache.read()?.let { snap ->
            snap.user?.let {
                _user.value = it
                AppEvents.balance.value = it.balance_units
            }
            _pricing.value = snap.pricing
            if (snap.profiles.isNotEmpty()) {
                _profiles.value = snap.profiles
                _loaded.value = true
            }
        }
    }

    private fun persist() {
        g.cache.write(AccountSnapshot(_user.value, _pricing.value, _profiles.value))
    }

    suspend fun onSignedIn(auth: AuthResponse) {
        g.tokens.set(auth.token)
        AppEvents.sessionExpired.value = false
        _user.value = auth.user
        AppEvents.balance.value = auth.user.balance_units
        // An account that already finished onboarding elsewhere skips role + disclaimer.
        if (auth.user.disclaimer_accepted_at != null) g.settings.setRoleChosen(true)
        // Re-ask for consent whenever the terms version changes.
        g.settings.setDisclaimerAccepted(auth.user.terms_accepted)
        // Not awaited: registering the push token is housekeeping and used to
        // add an FCM round trip plus a request before sign-in could finish.
        this.launch { syncFcmToken() }
    }

    suspend fun refreshMe(): User {
        val me = g.api.me()
        _user.value = me.user
        _pricing.value = me.pricing
        persist()
        return me.user
    }

    fun setUser(u: User) { _user.value = u; persist() }

    suspend fun refreshPricing() { runCatching { _pricing.value = g.api.pricing(); persist() } }

    suspend fun refreshProfiles(): List<Profile> {
        val list = g.api.profiles()
        _profiles.value = list
        _loaded.value = true
        persist()
        val active = g.settings.current().activeProfileId
        if (list.isNotEmpty() && list.none { it.id == active }) {
            g.settings.setActiveProfile((list.firstOrNull { it.relation == "self" } ?: list.first()).id)
        }
        return list
    }

    fun upsertLocal(p: Profile) {
        _profiles.value = _profiles.value.filterNot { it.id == p.id } + p
        persist()
    }

    fun removeLocal(pid: String) {
        _profiles.value = _profiles.value.filterNot { it.id == pid }
        persist()
    }

    /** Send the FCM token to the backend (retried on next launch if offline). */
    suspend fun syncFcmToken(explicit: String? = null) {
        if (!signedIn) { explicit?.let { g.settings.setPendingFcmToken(it) }; return }
        val token = explicit ?: g.settings.pendingFcmToken()
            ?: runCatching { FirebaseMessaging.getInstance().token.await() }.getOrNull()
            ?: return
        runCatching { g.api.registerFcm(token) }
            .onSuccess { g.settings.setPendingFcmToken(null) }
            .onFailure { g.settings.setPendingFcmToken(token) }
    }

    suspend fun signOut() {
        g.tokens.set(null)
        runCatching { com.google.firebase.auth.FirebaseAuth.getInstance().signOut() }
        _user.value = null
        _profiles.value = emptyList()
        _loaded.value = false
        AppEvents.balance.value = null
        g.cache.clear()
        g.settings.clearAccountState()
    }

    fun launch(block: suspend () -> Unit) = g.scope.launch { runCatching { block() } }
}
