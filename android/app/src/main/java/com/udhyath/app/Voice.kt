package com.udhyath.app

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

/** Languages the app speaks and listens in. */
data class AppLanguage(val label: String, val tag: String)

val LANGUAGES = listOf(
    AppLanguage("తెలుగు", "te-IN"),
    AppLanguage("हिन्दी", "hi-IN"),
    AppLanguage("தமிழ்", "ta-IN"),
    AppLanguage("ಕನ್ನಡ", "kn-IN"),
    AppLanguage("മലയാളം", "ml-IN"),
    AppLanguage("বাংলা", "bn-IN"),
    AppLanguage("मराठी", "mr-IN"),
    AppLanguage("ગુજરાતી", "gu-IN"),
    AppLanguage("ਪੰਜਾਬੀ", "pa-IN"),
    AppLanguage("English", "en-IN"),
)

enum class VoiceState { IDLE, LISTENING, SPEAKING }

/**
 * Wraps Android SpeechRecognizer (speech -> text) and TextToSpeech
 * (text -> speech) for one conversational loop. All calls on the main thread.
 */
class VoiceManager(
    private val context: Context,
    private val onResult: (String) -> Unit,
    private val onState: (VoiceState) -> Unit,
    private val onError: (String) -> Unit,
) {
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pendingSpeech: Pair<String, String>? = null
    var onSpeechDone: (() -> Unit)? = null

    init {
        tts = TextToSpeech(context) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            pendingSpeech?.let { (text, tag) -> speak(text, tag) }
            pendingSpeech = null
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onError(id: String?) { onState(VoiceState.IDLE) }
            override fun onDone(id: String?) {
                onState(VoiceState.IDLE)
                onSpeechDone?.invoke()
            }
        })
    }

    fun startListening(langTag: String) {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            onError("Speech recognition is not available on this device")
            return
        }
        stopSpeaking()
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle) {
                    onState(VoiceState.IDLE)
                    val texts = results.getStringArrayList(
                        SpeechRecognizer.RESULTS_RECOGNITION)
                    texts?.firstOrNull()?.takeIf { it.isNotBlank() }?.let(onResult)
                }
                override fun onError(error: Int) {
                    onState(VoiceState.IDLE)
                    if (error != SpeechRecognizer.ERROR_NO_MATCH &&
                        error != SpeechRecognizer.ERROR_SPEECH_TIMEOUT &&
                        error != SpeechRecognizer.ERROR_CLIENT)
                        onError("Voice input error ($error) — try again")
                }
                override fun onReadyForSpeech(params: Bundle?) { onState(VoiceState.LISTENING) }
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onPartialResults(partialResults: Bundle?) {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                         RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, langTag)
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
            })
        }
    }

    fun speak(text: String, langTag: String) {
        val engine = tts ?: return
        if (!ttsReady) { pendingSpeech = text to langTag; return }
        engine.language = Locale.forLanguageTag(langTag)
        onState(VoiceState.SPEAKING)
        // Long agent replies exceed the TTS per-utterance limit; chunk on sentences.
        val chunks = text.split(Regex("(?<=[.!?।॥])\\s+")).filter { it.isNotBlank() }
        chunks.forEachIndexed { i, chunk ->
            engine.speak(chunk,
                if (i == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD,
                null, if (i == chunks.lastIndex) "udhyath-done" else "udhyath-$i")
        }
        if (chunks.isEmpty()) onState(VoiceState.IDLE)
    }

    fun stopSpeaking() {
        tts?.stop()
    }

    fun destroy() {
        recognizer?.destroy()
        tts?.shutdown()
    }
}
