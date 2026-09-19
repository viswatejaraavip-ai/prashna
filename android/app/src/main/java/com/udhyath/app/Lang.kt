package com.udhyath.app

import android.os.Build
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import java.util.Locale

/**
 * The six app languages, in the exact order shown on the first-launch
 * picker. [code] goes to the backend (`lang`, `Accept-Language`); [voiceTag]
 * drives SpeechRecognizer / TextToSpeech.
 */
enum class AppLang(val code: String, val nativeName: String, val englishName: String, val voiceTag: String) {
    HI("hi", "हिन्दी", "Hindi", "hi-IN"),
    TE("te", "తెలుగు", "Telugu", "te-IN"),
    TA("ta", "தமிழ்", "Tamil", "ta-IN"),
    KN("kn", "ಕನ್ನಡ", "Kannada", "kn-IN"),
    ML("ml", "മലയാളം", "Malayalam", "ml-IN"),
    // English uses the base values/ resources.
    EN("en", "English", "English", "en-IN");

    val locale: Locale get() = Locale.forLanguageTag(voiceTag)

    companion object {
        fun fromCode(code: String?): AppLang? =
            entries.firstOrNull { it.code.equals(code?.substringBefore('-'), ignoreCase = true) }
    }
}

object LocaleController {
    /**
     * Switch the whole app UI to [lang]. AppCompat persists the choice
     * (autoStoreLocales on API < 33; the system LocaleManager on 33+) and
     * recreates activities so every stringResource() re-resolves.
     */
    fun apply(lang: AppLang) {
        val current = AppCompatDelegate.getApplicationLocales()
        if (current.toLanguageTags() == lang.code) return
        AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(lang.code))
    }

    /** Language the UI is currently running in, if it is one of ours. */
    fun current(): AppLang? {
        val tags = AppCompatDelegate.getApplicationLocales()
        if (tags.isEmpty) return null
        return AppLang.fromCode(tags[0]?.language)
    }

    val supportsSystemPicker: Boolean get() = Build.VERSION.SDK_INT >= 33
}
