package com.udhyath.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "udhyath_settings")

/** Non-secret app settings (DataStore). */
data class AppSettings(
    val lang: AppLang? = null,
    val largeText: Boolean = false,
    val chartStyle: String = "south",
    val activeProfileId: String? = null,
    val disclaimerAccepted: Boolean = false,
    val roleChosen: Boolean = false,
    val snapshotSeen: Boolean = false,
    val notifAsked: Boolean = false,
)

class SettingsStore(private val context: Context) {
    private object K {
        val lang = stringPreferencesKey("lang")
        val largeText = booleanPreferencesKey("large_text")
        val chartStyle = stringPreferencesKey("chart_style")
        val activeProfile = stringPreferencesKey("active_profile")
        val disclaimer = booleanPreferencesKey("disclaimer_accepted")
        val roleChosen = booleanPreferencesKey("role_chosen")
        val snapshotSeen = booleanPreferencesKey("snapshot_seen")
        val notifAsked = booleanPreferencesKey("notif_asked")
        val deviceId = stringPreferencesKey("device_id")
        val fcmToken = stringPreferencesKey("fcm_token_pending")
        val watchedReports = stringPreferencesKey("watched_reports")
    }

    val settings: Flow<AppSettings> = context.dataStore.data.map { p ->
        AppSettings(
            lang = AppLang.fromCode(p[K.lang]),
            largeText = p[K.largeText] ?: false,
            chartStyle = p[K.chartStyle] ?: "south",
            activeProfileId = p[K.activeProfile],
            disclaimerAccepted = p[K.disclaimer] ?: false,
            roleChosen = p[K.roleChosen] ?: false,
            snapshotSeen = p[K.snapshotSeen] ?: false,
            notifAsked = p[K.notifAsked] ?: false,
        )
    }

    suspend fun current(): AppSettings = settings.first()

    suspend fun setLang(lang: AppLang) = context.dataStore.edit { it[K.lang] = lang.code }
    suspend fun setLargeText(v: Boolean) = context.dataStore.edit { it[K.largeText] = v }
    suspend fun setChartStyle(v: String) = context.dataStore.edit { it[K.chartStyle] = v }
    suspend fun setActiveProfile(id: String?) = context.dataStore.edit {
        if (id == null) it.remove(K.activeProfile) else it[K.activeProfile] = id
    }
    suspend fun setDisclaimerAccepted(v: Boolean) = context.dataStore.edit { it[K.disclaimer] = v }
    suspend fun setRoleChosen(v: Boolean) = context.dataStore.edit { it[K.roleChosen] = v }
    suspend fun setSnapshotSeen(v: Boolean) = context.dataStore.edit { it[K.snapshotSeen] = v }
    suspend fun setNotifAsked(v: Boolean) = context.dataStore.edit { it[K.notifAsked] = v }

    /** Stable per-install id sent with auth so the free trial is granted once per device. */
    suspend fun deviceId(): String {
        val existing = context.dataStore.data.first()[K.deviceId]
        if (existing != null) return existing
        val fresh = UUID.randomUUID().toString()
        context.dataStore.edit { it[K.deviceId] = fresh }
        return fresh
    }

    suspend fun pendingFcmToken(): String? = context.dataStore.data.first()[K.fcmToken]
    suspend fun setPendingFcmToken(t: String?) = context.dataStore.edit {
        if (t == null) it.remove(K.fcmToken) else it[K.fcmToken] = t
    }

    suspend fun watchedReports(): Set<String> =
        context.dataStore.data.first()[K.watchedReports]?.split(',')?.filter { it.isNotBlank() }?.toSet()
            ?: emptySet()

    suspend fun setWatchedReports(ids: Set<String>) =
        context.dataStore.edit { it[K.watchedReports] = ids.joinToString(",") }

    /** Sign-out / account deletion: forget everything except language and text size. */
    suspend fun clearAccountState() = context.dataStore.edit {
        it.remove(K.activeProfile); it.remove(K.disclaimer); it.remove(K.roleChosen)
        it.remove(K.snapshotSeen); it.remove(K.watchedReports)
    }
}

/**
 * The app JWT, encrypted with an AES-GCM key that never leaves the Android
 * Keystore. Stored ciphertext lives in a private SharedPreferences file that
 * is excluded from backup (see data_extraction_rules.xml).
 */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("udhyath_secure", Context.MODE_PRIVATE)
    private val alias = "udhyath_token_key"

    @Volatile private var cached: String? = null

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    fun get(): String? {
        cached?.let { return it }
        val blob = prefs.getString("jwt", null) ?: return null
        return try {
            val raw = Base64.decode(blob, Base64.NO_WRAP)
            val iv = raw.copyOfRange(0, 12)
            val ct = raw.copyOfRange(12, raw.size)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(c.doFinal(ct), Charsets.UTF_8).also { cached = it }
        } catch (_: Exception) {
            // Key invalidated (e.g. restored to another device): force re-login.
            prefs.edit().remove("jwt").apply(); null
        }
    }

    fun set(token: String?) {
        cached = token
        if (token == null) { prefs.edit().remove("jwt").apply(); return }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val out = c.iv + c.doFinal(token.toByteArray(Charsets.UTF_8))
        prefs.edit().putString("jwt", Base64.encodeToString(out, Base64.NO_WRAP)).apply()
    }
}
