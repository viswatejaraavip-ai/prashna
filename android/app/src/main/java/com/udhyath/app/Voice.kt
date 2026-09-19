package com.udhyath.app

import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Base64
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.coroutines.coroutineContext
import kotlin.math.sqrt

enum class VoiceState { IDLE, LISTENING, THINKING, SPEAKING }

/** What the device can do on-device for a language. Cloud is used for whatever is missing. */
data class VoiceCapability(val sttOnDevice: Boolean, val ttsOnDevice: Boolean) {
    /** The server `/voice` endpoint does STT + answer (+ optional TTS) in one call, so any gap means the cloud path. */
    val useCloud get() = !sttOnDevice || !ttsOnDevice
}

/**
 * On-device speech in the user's language: SpeechRecognizer (hi-IN, te-IN,
 * ta-IN, kn-IN, ml-IN) and TextToSpeech. Detects missing language packs so
 * the chat can fall back to the server `/voice` endpoint. Main thread only.
 */
class VoiceEngine(private val context: Context) {
    private var tts: TextToSpeech? = null
    private val ttsReady = CompletableDeferred<Boolean>()
    private var recognizer: SpeechRecognizer? = null
    private var player: MediaPlayer? = null
    var onSpeakingDone: (() -> Unit)? = null

    init {
        tts = TextToSpeech(context.applicationContext) { status -> ttsReady.complete(status == TextToSpeech.SUCCESS) }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) { if (id == LAST) ContextCompat.getMainExecutor(context).execute { onSpeakingDone?.invoke() } }
            @Deprecated("Deprecated in Java")
            override fun onError(id: String?) { if (id == LAST) ContextCompat.getMainExecutor(context).execute { onSpeakingDone?.invoke() } }
            override fun onStop(utteranceId: String?, interrupted: Boolean) {}
        })
    }

    // ------------------------------------------------------------ detection

    suspend fun capability(lang: AppLang): VoiceCapability =
        VoiceCapability(sttOnDevice = sttAvailable(lang), ttsOnDevice = ttsAvailable(lang))

    private suspend fun ttsAvailable(lang: AppLang): Boolean {
        val ok = withTimeoutOrNull(4000) { ttsReady.await() } ?: false
        val engine = tts ?: return false
        if (!ok) return false
        val r = engine.isLanguageAvailable(lang.locale)
        if (r < TextToSpeech.LANG_AVAILABLE) return false // LANG_MISSING_DATA / LANG_NOT_SUPPORTED
        // Some engines report the language but have no installed voice for it.
        val voices = runCatching { engine.voices }.getOrNull() ?: return true
        val forLang = voices.filter { it.locale.language == lang.code }
        if (forLang.isEmpty()) return true
        return forLang.any { v -> !v.features.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) }
    }

    private suspend fun sttAvailable(lang: AppLang): Boolean {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) return false
        if (Build.VERSION.SDK_INT >= 33) {
            val rec = SpeechRecognizer.createSpeechRecognizer(context)
            val result = CompletableDeferred<Boolean?>()
            try {
                rec.checkRecognitionSupport(recognizeIntent(lang), ContextCompat.getMainExecutor(context),
                    object : RecognitionSupportCallback {
                        override fun onSupportResult(s: RecognitionSupport) {
                            val langs = s.installedOnDeviceLanguages + s.onlineLanguages
                            result.complete(langs.any { it.startsWith(lang.code, ignoreCase = true) })
                        }
                        override fun onError(error: Int) { result.complete(null) }
                    })
                val r = withTimeoutOrNull(3000) { result.await() }
                if (r != null) return r
            } catch (_: Exception) {
            } finally { rec.destroy() }
        } else {
            legacySupportedLanguages()?.let { list -> return list.any { it.startsWith(lang.code, ignoreCase = true) } }
        }
        // Unknown: try on-device; a LANGUAGE_* error at runtime flips us to cloud.
        return true
    }

    /** API < 33: ask the recognizer for its language list via the voice-details broadcast. */
    private suspend fun legacySupportedLanguages(): List<String>? {
        val done = CompletableDeferred<List<String>?>()
        val detailsIntent = RecognizerIntent.getVoiceDetailsIntent(context) ?: return null
        context.sendOrderedBroadcast(detailsIntent, null, object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                val extras = getResultExtras(true)
                done.complete(extras?.getStringArrayList(RecognizerIntent.EXTRA_SUPPORTED_LANGUAGES))
            }
        }, null, android.app.Activity.RESULT_OK, null, null)
        return withTimeoutOrNull(2500) { done.await() }
    }

    // ------------------------------------------------------ on-device STT

    private fun recognizeIntent(lang: AppLang) = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang.voiceTag)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, lang.voiceTag)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
    }

    /**
     * Listen once. [onPartial] streams the live transcript; [onFinal] gets
     * the recognized text (or null for silence); [onLanguageMissing] fires
     * if the recognizer says the language pack isn't available.
     */
    fun listen(
        lang: AppLang,
        onReady: () -> Unit,
        onPartial: (String) -> Unit,
        onFinal: (String?) -> Unit,
        onLanguageMissing: () -> Unit,
        onError: (Int) -> Unit,
    ) {
        stopSpeaking()
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) = onReady()
                override fun onResults(results: Bundle) {
                    onFinal(results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() })
                }
                override fun onPartialResults(partial: Bundle?) {
                    partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(onPartial)
                }
                override fun onError(error: Int) {
                    when (error) {
                        // ERROR_LANGUAGE_NOT_SUPPORTED (12) / ERROR_LANGUAGE_UNAVAILABLE (13), API 31+
                        12, 13 -> onLanguageMissing()
                        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> onFinal(null)
                        SpeechRecognizer.ERROR_CLIENT -> onFinal(null)
                        else -> onError(error)
                    }
                }
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            startListening(recognizeIntent(lang))
        }
    }

    fun stopListening() { recognizer?.stopListening() }
    fun cancelListening() { recognizer?.cancel() }

    // ------------------------------------------------------ on-device TTS

    fun speak(text: String, lang: AppLang) {
        val engine = tts ?: return
        engine.language = lang.locale
        engine.setSpeechRate(0.95f)
        val spoken = text
            .replace(Regex("\\[(.*?)\\]\\(.*?\\)"), "$1")
            .replace(Regex("[*_#`>|]+"), " ")
            .replace(Regex("\\s{2,}"), " ")
        val cap = (TextToSpeech.getMaxSpeechInputLength() - 100).coerceAtLeast(500)
        val chunks = spoken.split(Regex("(?<=[.!?।॥])\\s+")).filter { it.isNotBlank() }.flatMap { it.chunked(cap) }
        if (chunks.isEmpty()) { onSpeakingDone?.invoke(); return }
        chunks.forEachIndexed { i, c ->
            engine.speak(c, if (i == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD, null,
                if (i == chunks.lastIndex) LAST else "u$i")
        }
    }

    /** Interrupt: stops on-device TTS and any cloud audio playback. */
    fun stopSpeaking() {
        tts?.stop()
        player?.let { runCatching { it.stop() }; it.release() }
        player = null
    }

    // ------------------------------------------------------ cloud path

    /** Play the server's `audio_b64` reply (format decided by the server; MediaPlayer sniffs it). */
    fun playBase64(b64: String) {
        stopSpeaking()
        val bytes = Base64.decode(b64, Base64.DEFAULT)
        val f = File(context.cacheDir, "reply_audio").apply { writeBytes(bytes) }
        player = MediaPlayer().apply {
            setDataSource(f.absolutePath)
            setOnCompletionListener { onSpeakingDone?.invoke(); release(); if (player === it) player = null }
            setOnErrorListener { _, _, _ -> onSpeakingDone?.invoke(); true }
            prepare(); start()
        }
    }

    fun destroy() {
        recognizer?.destroy(); recognizer = null
        stopSpeaking()
        tts?.shutdown(); tts = null
    }

    companion object { private const val LAST = "udhyath-last" }
}

/**
 * 16 kHz mono LINEAR16 recorder for the cloud `/voice` path. Stops on
 * [stop], after ~1.4 s of silence following speech, or at [maxMs]. Returns a
 * WAV file (LINEAR16 with a RIFF header — Google STT reads the header).
 */
class WavRecorder {
    @Volatile private var stopRequested = false
    fun stop() { stopRequested = true }

    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO
    suspend fun record(maxMs: Long = 30_000, onLevel: (Float) -> Unit = {}): ByteArray? = withContext(Dispatchers.IO) {
        stopRequested = false
        val rate = 16_000
        val minBuf = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuf <= 0) return@withContext null
        val rec = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, rate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, minBuf * 2)
        } catch (_: Exception) { return@withContext null }
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); return@withContext null }
        val pcm = ByteArrayOutputStream()
        val buf = ShortArray(minBuf / 2)
        val bb = ByteBuffer.allocate(buf.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        var heardSpeech = false
        var silentMs = 0L
        val started = System.currentTimeMillis()
        try {
            rec.startRecording()
            while (coroutineContext.isActive && !stopRequested && System.currentTimeMillis() - started < maxMs) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                var sum = 0.0
                bb.clear()
                for (i in 0 until n) { sum += buf[i] * buf[i].toDouble(); bb.putShort(buf[i]) }
                pcm.write(bb.array(), 0, n * 2)
                val rms = sqrt(sum / n).toFloat()
                onLevel((rms / 3000f).coerceIn(0f, 1f))
                val chunkMs = n * 1000L / rate
                if (rms > 900) { heardSpeech = true; silentMs = 0 } else silentMs += chunkMs
                if (heardSpeech && silentMs > 1400) break
                if (!heardSpeech && System.currentTimeMillis() - started > 8000) break
            }
        } finally {
            runCatching { rec.stop() }; rec.release()
        }
        if (!heardSpeech) return@withContext null
        wav(pcm.toByteArray(), rate)
    }

    private fun wav(pcm: ByteArray, rate: Int): ByteArray {
        val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()); h.putInt(36 + pcm.size); h.put("WAVE".toByteArray())
        h.put("fmt ".toByteArray()); h.putInt(16); h.putShort(1); h.putShort(1)
        h.putInt(rate); h.putInt(rate * 2); h.putShort(2); h.putShort(16)
        h.put("data".toByteArray()); h.putInt(pcm.size)
        return h.array() + pcm
    }
}
