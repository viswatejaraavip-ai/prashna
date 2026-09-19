package com.udhyath.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    /** Deep link waiting for the nav graph (push tap, prashna:// link). */
    private val pendingLink = MutableStateFlow<Uri?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        Notifications.createChannels(this) // localized channel names after a language switch
        pendingLink.value = linkFrom(intent)
        // We route deep links ourselves (after onboarding); stop NavHost from also handling this intent.
        intent?.data = null
        syncLocale()
        setContent {
            val g = LocalContext.current.graph
            val settings by g.settings.settings.collectAsStateWithLifecycle(initialValue = null)
            val s = settings
            UdhyathTheme(largeText = s?.largeText == true, dark = isSystemInDarkTheme()) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    if (s != null) AppRoot(s, pendingLink)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        linkFrom(intent)?.let { pendingLink.value = it }
        intent.data = null
    }

    private fun linkFrom(i: Intent?): Uri? {
        if (i == null) return null
        i.data?.takeIf { it.scheme == "prashna" }?.let { return it }
        // FCM notification messages delivered in background: data keys arrive as extras.
        val extras = i.extras ?: return null
        val map = extras.keySet().associateWith { extras.get(it)?.toString() }
        return Notifications.deepLinkFor(map)
    }

    /**
     * Keep DataStore, AppCompat locale and the backend in agreement — e.g. if
     * the user changed the app language from Android's system settings (13+).
     */
    private fun syncLocale() {
        val g = graph
        g.scope.launch {
            val saved = g.settings.current().lang
            val active = LocaleController.current()
            when {
                saved != null && active == null -> LocaleController.apply(saved)
                active != null && active != saved -> {
                    g.settings.setLang(active)
                    g.langCode = active.code
                    if (g.account.signedIn) runCatching { g.api.patchMe(lang = active.code) }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Connectivity for the offline banner
// ---------------------------------------------------------------------------

@Composable
fun rememberOnline(): State<Boolean> {
    val ctx = LocalContext.current
    val online = remember { mutableStateOf(true) }
    DisposableEffect(Unit) {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        fun check() = cm?.getNetworkCapabilities(cm.activeNetwork)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        online.value = check()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { online.value = true }
            override fun onLost(network: Network) { online.value = check() }
        }
        runCatching { cm?.registerNetworkCallback(NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build(), cb) }
        onDispose { runCatching { cm?.unregisterNetworkCallback(cb) } }
    }
    return online
}

@Composable
fun OfflineBanner() {
    val online by rememberOnline()
    AnimatedVisibility(!online) {
        Text(stringResource(R.string.offline_banner),
            Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.secondary).statusBarsPadding().padding(8.dp),
            color = MaterialTheme.colorScheme.onSecondary, textAlign = TextAlign.Center,
            style = MaterialTheme.typography.labelLarge)
    }
}

// ---------------------------------------------------------------------------
// Root: onboarding gate → main app
// ---------------------------------------------------------------------------

@Composable
fun AppRoot(s: AppSettings, pendingLink: MutableStateFlow<Uri?>) {
    val g = LocalContext.current.graph
    val scope = rememberCoroutineScope()
    val maintenance by AppEvents.maintenance.collectAsStateWithLifecycle()
    val expired by AppEvents.sessionExpired.collectAsStateWithLifecycle()
    var signedIn by remember { mutableStateOf(g.account.signedIn) }
    val user by g.account.user.collectAsStateWithLifecycle()
    val profilesLoaded by g.account.loaded.collectAsStateWithLifecycle()
    val profiles by g.account.profiles.collectAsStateWithLifecycle()
    var bootError by remember { mutableStateOf<Throwable?>(null) }
    var bootTick by remember { mutableIntStateOf(0) }

    LaunchedEffect(expired) {
        if (expired) { g.account.signOut(); signedIn = false; AppEvents.sessionExpired.value = false }
    }

    // Load the signed-in user + profiles once per sign-in.
    LaunchedEffect(signedIn, bootTick) {
        if (!signedIn) return@LaunchedEffect
        bootError = null
        runCatching {
            val u = g.account.refreshMe()
            if (u.disclaimer_accepted_at != null) g.settings.setRoleChosen(true)
            // Terms changed since last acceptance -> the consent screen shows again.
            g.settings.setDisclaimerAccepted(u.terms_accepted)
            // Keep the server's language in step with the device choice.
            if (s.lang != null && u.lang != s.lang.code) runCatching { g.api.patchMe(lang = s.lang.code) }
            g.account.refreshProfiles()
            g.account.syncFcmToken()
            runCatching { g.billing.restore() }
        }.onFailure { bootError = it }
    }

    Column(Modifier.fillMaxSize()) {
        OfflineBanner()
        Box(Modifier.weight(1f)) {
            when {
                maintenance != null -> MaintenanceScreen(maintenance!!) {
                    scope.launch { runCatching { g.api.pricing() }.onSuccess { AppEvents.maintenance.value = null } }
                }
                s.lang == null -> LanguagePickerScreen(firstRun = true, current = null) { lang -> chooseLanguage(g, lang, scope) }
                !signedIn -> AuthScreen(onSignedIn = { signedIn = true })
                user == null || !profilesLoaded -> {
                    val err = bootError
                    if (err != null) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        ErrorBox(err, onRetry = { bootTick++ })
                    } else Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { SplashMark() }
                }
                !s.roleChosen -> RoleScreen()
                !s.disclaimerAccepted -> DisclaimerScreen()
                user?.isAstrologer != true && profiles.none { it.relation != "client" } ->
                    ProfileEditScreen(pid = null, onboarding = true, onDone = {}, onBack = null)
                user?.isAstrologer != true && !s.snapshotSeen -> {
                    val pid = s.activeProfileId ?: profiles.first().id
                    SnapshotScreen(pid, onContinue = { askFirst ->
                        if (askFirst) pendingLink.value = Uri.parse("prashna://chat?pid=$pid")
                        scope.launch { g.settings.setSnapshotSeen(true) }
                    })
                }
                else -> MainScaffold(s, user!!, pendingLink)
            }
        }
    }
}

fun chooseLanguage(g: AppGraph, lang: AppLang, scope: kotlinx.coroutines.CoroutineScope) {
    scope.launch {
        g.settings.setLang(lang)
        g.langCode = lang.code
        if (g.account.signedIn) runCatching { g.account.setUser(g.api.patchMe(lang = lang.code)) }
        LocaleController.apply(lang) // recreates the activity in the new language
    }
}

@Composable
fun SplashMark() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(painterResource(R.drawable.ic_diya), contentDescription = stringResource(R.string.app_name),
            tint = androidx.compose.ui.graphics.Color.Unspecified, modifier = Modifier.size(96.dp))
        Spacer(Modifier.height(16.dp))
        CircularProgressIndicator()
    }
}

@Composable
fun MaintenanceScreen(message: String, onRetry: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center) {
        Icon(painterResource(R.drawable.ic_diya), contentDescription = null,
            tint = androidx.compose.ui.graphics.Color.Unspecified, modifier = Modifier.size(96.dp))
        Spacer(Modifier.height(16.dp))
        Text(stringResource(R.string.maintenance_title), style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        Text(message.ifBlank { stringResource(R.string.maintenance_default) }, textAlign = TextAlign.Center)
        Spacer(Modifier.height(24.dp))
        OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
    }
}

// ---------------------------------------------------------------------------
// Main app with bottom navigation
// ---------------------------------------------------------------------------

object Routes {
    const val HOME = "home"
    const val ASK = "ask"
    const val CHAT = "chat?sid={sid}&pid={pid}&voice={voice}"
    fun chat(sid: String? = null, pid: String? = null, voice: Boolean = false) =
        "chat?sid=${sid.orEmpty()}&pid=${pid.orEmpty()}&voice=$voice"
    const val CHARTS = "charts?pid={pid}"
    fun charts(pid: String? = null) = "charts?pid=${pid.orEmpty()}"
    const val PROFILES = "profiles"
    const val PROFILE_EDIT = "profile_edit?pid={pid}&relation={relation}"
    fun profileEdit(pid: String? = null, relation: String? = null) = "profile_edit?pid=${pid.orEmpty()}&relation=${relation.orEmpty()}"
    const val ALERTS = "alerts/{pid}"
    const val MATCHING = "matching"
    const val MUHURTA = "muhurta"
    const val RECTIFY = "rectify/{pid}"
    const val REPORTS = "reports?pid={pid}"
    fun reports(pid: String? = null) = "reports?pid=${pid.orEmpty()}"
    const val REPORT = "report/{id}"
    const val WALLET = "wallet"
    const val MORE = "more"
    const val LANGUAGE = "language"
    const val NOTIF = "notif_prefs"
    const val LEGAL = "legal/{doc}"
    const val REFUNDS = "refunds?ref={ref}"
    fun refunds(ref: String? = null) = "refunds?ref=${ref.orEmpty()}"
    const val SUPPORT = "support"
    const val ACCOUNT = "account"
    const val CLIENTS = "clients"
    const val CLIENT = "client/{pid}"
    const val PRO_BUNDLE = "pro_bundle/{pid}"
    const val BRAND = "brand"
    const val PRO = "pro"
}

private data class Tab(val route: String, val label: Int, val icon: ImageVector)

@Composable
fun MainScaffold(s: AppSettings, user: User, pendingLink: MutableStateFlow<Uri?>) {
    val nav = rememberNavController()
    val g = LocalContext.current.graph
    val astro = user.isAstrologer
    val tabs = if (astro) listOf(
        Tab(Routes.CLIENTS, R.string.tab_clients, Icons.Default.Groups),
        Tab(Routes.ASK, R.string.tab_ask, Icons.AutoMirrored.Filled.Chat),
        Tab(Routes.reports(), R.string.tab_reports, Icons.Default.AutoStories),
        Tab(Routes.MORE, R.string.tab_more, Icons.Default.Menu),
    ) else listOf(
        Tab(Routes.HOME, R.string.tab_home, Icons.Default.Home),
        Tab(Routes.ASK, R.string.tab_ask, Icons.AutoMirrored.Filled.Chat),
        Tab(Routes.charts(), R.string.tab_charts, Icons.Default.WbSunny),
        Tab(Routes.reports(), R.string.tab_reports, Icons.Default.AutoStories),
        Tab(Routes.MORE, R.string.tab_more, Icons.Default.Menu),
    )
    val backStack by nav.currentBackStackEntryAsState()
    val current = backStack?.destination?.route
    val showBar = tabs.any { it.route.substringBefore('?') == current?.substringBefore('?') }

    // Deep links from pushes / prashna:// URIs.
    val link by pendingLink.collectAsStateWithLifecycle()
    LaunchedEffect(link, nav) {
        val l = link ?: return@LaunchedEffect
        pendingLink.value = null
        // Debug builds only: prashna://nav/<route>?<args> opens any screen (UI testing).
        if (BuildConfig.DEBUG && l.host == "nav") {
            val route = l.path.orEmpty().trimStart('/') + (l.query?.let { "?$it" } ?: "")
            runCatching { nav.navigate(route) }
            return@LaunchedEffect
        }
        runCatching { nav.navigate(l) }
    }

    NotificationPermissionAsk(s)

    Scaffold(
        bottomBar = {
            if (showBar) NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                tabs.forEach { t ->
                    val selected = current?.substringBefore('?') == t.route.substringBefore('?')
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            nav.navigate(t.route) {
                                popUpTo(nav.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true; restoreState = true
                            }
                        },
                        icon = { Icon(t.icon, contentDescription = null) },
                        label = { Text(stringResource(t.label), maxLines = 1) },
                    )
                }
            }
        },
        contentWindowInsets = WindowInsets(0),
    ) { pad ->
        Box(Modifier.padding(pad)) {
            AppNavHost(nav, if (astro) Routes.CLIENTS else Routes.HOME, s, user)
        }
    }
}

@Composable
fun NotificationPermissionAsk(s: AppSettings) {
    if (Build.VERSION.SDK_INT < 33 || s.notifAsked) return
    val ctx = LocalContext.current
    val g = ctx.graph
    val scope = rememberCoroutineScope()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        scope.launch { g.settings.setNotifAsked(true) }
    }
    var show by remember { mutableStateOf(ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) }
    if (!show) { LaunchedEffect(Unit) { g.settings.setNotifAsked(true) }; return }
    AlertDialog(
        onDismissRequest = { show = false; scope.launch { g.settings.setNotifAsked(true) } },
        title = { Text(stringResource(R.string.notif_perm_title)) },
        text = { Text(stringResource(R.string.notif_perm_body)) },
        confirmButton = { TextButton(onClick = { show = false; launcher.launch(Manifest.permission.POST_NOTIFICATIONS) }) { Text(stringResource(R.string.allow)) } },
        dismissButton = { TextButton(onClick = { show = false; scope.launch { g.settings.setNotifAsked(true) } }) { Text(stringResource(R.string.not_now)) } },
    )
}

@Composable
fun AppNavHost(nav: NavHostController, start: String, s: AppSettings, user: User) {
    val back: () -> Unit = { nav.popBackStack() }
    val optStr = { name: String -> navArgument(name) { type = NavType.StringType; nullable = true; defaultValue = null } }
    fun String?.orNullIfBlank() = this?.takeIf { it.isNotBlank() }

    NavHost(nav, startDestination = start) {
        composable(Routes.HOME, deepLinks = listOf(navDeepLink { uriPattern = "prashna://home" })) {
            HomeScreen(nav)
        }
        composable(Routes.ASK) { SessionsScreen(nav) }
        composable(Routes.CHAT, arguments = listOf(optStr("sid"), optStr("pid"),
            navArgument("voice") { type = NavType.BoolType; defaultValue = false }),
            deepLinks = listOf(navDeepLink { uriPattern = "prashna://chat?pid={pid}" })) { e ->
            ChatScreen(nav, sid = e.arguments?.getString("sid").orNullIfBlank(),
                pid = e.arguments?.getString("pid").orNullIfBlank(), startVoice = e.arguments?.getBoolean("voice") == true)
        }
        composable(Routes.CHARTS, arguments = listOf(optStr("pid"))) { e ->
            ChartsScreen(nav, e.arguments?.getString("pid").orNullIfBlank(), showBack = nav.previousBackStackEntry != null && user.isAstrologer)
        }
        composable(Routes.PROFILES) { ProfilesScreen(nav) }
        composable(Routes.PROFILE_EDIT, arguments = listOf(optStr("pid"), optStr("relation"))) { e ->
            ProfileEditScreen(pid = e.arguments?.getString("pid").orNullIfBlank(), onboarding = false,
                presetRelation = e.arguments?.getString("relation").orNullIfBlank(),
                onDone = { back() }, onBack = back)
        }
        composable(Routes.ALERTS, deepLinks = listOf(navDeepLink { uriPattern = "prashna://alerts/{pid}" })) { e ->
            AlertsScreen(e.arguments?.getString("pid") ?: "", onBack = back)
        }
        composable(Routes.MATCHING) { MatchingScreen(nav, onBack = back) }
        composable(Routes.MUHURTA) { MuhurtaScreen(onBack = back) }
        composable(Routes.RECTIFY) { e -> RectifyScreen(e.arguments?.getString("pid") ?: "", onBack = back) }
        composable(Routes.REPORTS, arguments = listOf(optStr("pid")),
            deepLinks = listOf(navDeepLink { uriPattern = "prashna://reports" })) { e ->
            ReportsScreen(nav, e.arguments?.getString("pid").orNullIfBlank())
        }
        composable(Routes.REPORT, deepLinks = listOf(navDeepLink { uriPattern = "prashna://report/{id}" })) { e ->
            ReportReaderScreen(e.arguments?.getString("id") ?: "", onBack = back)
        }
        composable(Routes.WALLET, deepLinks = listOf(navDeepLink { uriPattern = "prashna://wallet" })) {
            WalletScreen(nav, onBack = back)
        }
        composable(Routes.MORE) { MoreScreen(nav) }
        composable(Routes.LANGUAGE) {
            val g = LocalContext.current.graph
            val scope = rememberCoroutineScope()
            LanguagePickerScreen(firstRun = false, current = s.lang, onBack = back) { lang -> chooseLanguage(g, lang, scope) }
        }
        composable(Routes.NOTIF) { NotificationPrefsScreen(onBack = back) }
        composable(Routes.LEGAL) { e -> LegalScreen(e.arguments?.getString("doc") ?: "terms", onBack = back) }
        composable(Routes.REFUNDS, arguments = listOf(optStr("ref"))) { e ->
            RefundsScreen(e.arguments?.getString("ref").orNullIfBlank(), onBack = back)
        }
        composable(Routes.SUPPORT, deepLinks = listOf(navDeepLink { uriPattern = "prashna://support" })) { SupportScreen(onBack = back) }
        composable(Routes.ACCOUNT) { AccountScreen(onBack = back) }
        composable(Routes.CLIENTS) { ClientsScreen(nav) }
        composable(Routes.CLIENT) { e -> ClientDetailScreen(nav, e.arguments?.getString("pid") ?: "") }
        composable(Routes.PRO_BUNDLE) { e -> ProBundleScreen(nav, e.arguments?.getString("pid") ?: "") }
        composable(Routes.BRAND) { BrandScreen(onBack = back) }
        composable(Routes.PRO) { ProPlanScreen(nav, onBack = back) }
    }
}
