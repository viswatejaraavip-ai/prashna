package com.udhyath.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Error codes from the contract: `{"detail": "...", "code": "..."}`. */
enum class ErrorKind { OFFLINE, UNAUTHORIZED, INSUFFICIENT_BALANCE, RATE_LIMITED, NOT_FOUND, FORBIDDEN, INVALID, MAINTENANCE, SERVER }

class ApiException(val kind: ErrorKind, val http: Int, val detail: String?) : IOException(detail ?: kind.name)

fun Throwable.errorKind(): ErrorKind = when (this) {
    is ApiException -> kind
    is java.net.SocketTimeoutException -> ErrorKind.SERVER // reachable but slow: not "offline"
    is IOException -> ErrorKind.OFFLINE
    else -> ErrorKind.SERVER
}

/** App-wide signals raised by the HTTP layer. */
object AppEvents {
    /** Non-null while the backend reports maintenance (config_flags.maintenance_message). */
    val maintenance = MutableStateFlow<String?>(null)
    /** Flipped when the server rejects our JWT; the app returns to sign-in. */
    val sessionExpired = MutableStateFlow(false)
    /** Latest known balance (paise), updated from any response that carries it. */
    val balance = MutableStateFlow<Long?>(null)
}

sealed interface StreamEvent {
    data class Delta(val text: String) : StreamEvent
    data class Done(val result: AskResult) : StreamEvent
}

class UdhyathApi(
    private val baseUrl: String,
    private val tokenProvider: () -> String?,
    private val langProvider: () -> String?,
) {
    private val jsonType = "application/json; charset=utf-8".toMediaType()

    private val headers = Interceptor { chain ->
        val b = chain.request().newBuilder()
            .header("Accept", chain.request().header("Accept") ?: "application/json")
            .header("X-Client", "android/${BuildConfig.VERSION_NAME}")
        tokenProvider()?.let { b.header("Authorization", "Bearer $it") }
        // Contract: Accept-Language selects the language of every response, including AI replies.
        langProvider()?.let { b.header("Accept-Language", it) }
        chain.proceed(b.build())
    }

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .addInterceptor(headers)
        .build()

    /** Long-lived reads for SSE and the cloud voice path (Opus can take a while). */
    private val slowClient: OkHttpClient = client.newBuilder()
        .readTimeout(180, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.SECONDS)
        .build()

    // ------------------------------------------------------------------ core

    private fun url(path: String, query: Map<String, Any?> = emptyMap()): okhttp3.HttpUrl {
        val b = (baseUrl.trimEnd('/') + path).toHttpUrl().newBuilder()
        query.forEach { (k, v) -> if (v != null) b.addQueryParameter(k, v.toString()) }
        return b.build()
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { if (cont.isActive) cont.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) { cont.resume(response) }
        })
        cont.invokeOnCancellation { runCatching { cancel() } }
    }

    private fun raise(code: Int, text: String): Nothing {
        val obj = runCatching { AppJson.parseToJsonElement(text) as? JsonObject }.getOrNull()
        val detail = obj?.let { o ->
            o.str("detail") ?: o["detail"]?.let { d ->
                // FastAPI 422 validation arrays
                d.itemsList().mapNotNull { it.obj()?.str("msg") }.joinToString("; ").ifBlank { null }
            }
        }
        val kind = when (obj?.str("code")) {
            "insufficient_balance" -> ErrorKind.INSUFFICIENT_BALANCE
            "rate_limited" -> ErrorKind.RATE_LIMITED
            "not_found" -> ErrorKind.NOT_FOUND
            "forbidden" -> ErrorKind.FORBIDDEN
            "invalid" -> ErrorKind.INVALID
            "maintenance" -> ErrorKind.MAINTENANCE
            "unavailable" -> ErrorKind.SERVER // storage outage (503), not a maintenance window
            else -> when (code) {
                401 -> ErrorKind.UNAUTHORIZED
                402 -> ErrorKind.INSUFFICIENT_BALANCE
                403 -> ErrorKind.FORBIDDEN
                404 -> ErrorKind.NOT_FOUND
                400, 409, 422 -> ErrorKind.INVALID
                429 -> ErrorKind.RATE_LIMITED
                else -> ErrorKind.SERVER
            }
        }
        if (kind == ErrorKind.MAINTENANCE) AppEvents.maintenance.value = detail ?: ""
        if (kind == ErrorKind.UNAUTHORIZED && tokenProvider() != null) AppEvents.sessionExpired.value = true
        throw ApiException(kind, code, detail)
    }

    private suspend fun exec(req: Request, slow: Boolean = false): String = withContext(Dispatchers.IO) {
        val resp = (if (slow) slowClient else client).newCall(req).await()
        resp.use {
            val text = it.body?.string().orEmpty()
            if (!it.isSuccessful) raise(it.code, text)
            if (AppEvents.maintenance.value != null) AppEvents.maintenance.value = null
            text
        }
    }

    private suspend fun call(
        method: String, path: String, body: JsonElement? = null,
        query: Map<String, Any?> = emptyMap(), slow: Boolean = false,
    ): JsonElement {
        val rb: RequestBody? = when {
            body != null -> AppJson.encodeToString(body).toRequestBody(jsonType)
            method == "POST" || method == "PUT" || method == "PATCH" -> "{}".toRequestBody(jsonType)
            else -> null
        }
        val text = exec(Request.Builder().url(url(path, query)).method(method, rb).build(), slow)
        val el = if (text.isBlank()) JsonObject(emptyMap()) else AppJson.parseToJsonElement(text)
        el.obj()?.long("balance_units")?.let { AppEvents.balance.value = it }
        return el
    }

    private suspend fun get(path: String, query: Map<String, Any?> = emptyMap()) = call("GET", path, query = query)
    private suspend fun post(path: String, body: JsonElement? = null, slow: Boolean = false) = call("POST", path, body, slow = slow)
    private suspend fun patch(path: String, body: JsonElement) = call("PATCH", path, body)
    private suspend fun httpPut(path: String, body: JsonElement) = call("PUT", path, body)
    private suspend fun delete(path: String) = call("DELETE", path)

    private inline fun <reified T> toJson(v: T): JsonElement = AppJson.encodeToJsonElement(v)

    /** Signed-URL responses: accept `{url}`, `{signed_url}`, `{pdf_url}` or a bare string. */
    private fun signedUrl(el: JsonElement): String =
        el.obj()?.str("url", "signed_url", "pdf_url", "png_url", "download_url")
            ?: (el as? kotlinx.serialization.json.JsonPrimitive)?.content
            ?: throw ApiException(ErrorKind.SERVER, 200, null)

    private fun userOf(el: JsonElement): User =
        (el.obj()?.get("user") ?: el).decodeAs()

    // ------------------------------------------------------------ platform

    suspend fun authFirebase(idToken: String, deviceId: String, lang: String): AuthResponse =
        post("/api/auth/firebase", buildJsonObject {
            put("id_token", idToken); put("device_id", deviceId); put("lang", lang)
        }).decodeAs()

    suspend fun me(): MeResponse = get("/api/me").decodeAs<MeResponse>().also {
        AppEvents.balance.value = it.user.balance_units
    }

    suspend fun patchMe(name: String? = null, lang: String? = null, notif: NotifPrefs? = null, role: String? = null): User =
        userOf(patch("/api/me", buildJsonObject {
            name?.let { put("name", it) }
            lang?.let { put("lang", it) }
            role?.let { put("role", it) }
            notif?.let { n -> putJsonObject("notif_prefs") { put("daily", n.daily); put("transits", n.transits); put("promos", n.promos) } }
        }))

    suspend fun registerFcm(token: String) { post("/api/me/fcm-token", buildJsonObject { put("token", token) }) }
    suspend fun acceptDisclaimer() { post("/api/me/disclaimer") }
    suspend fun pricing(): Pricing = get("/api/pricing").decodeAs()

    suspend fun playVerify(productId: String, purchaseToken: String): JsonObject =
        post("/api/wallet/play/verify", buildJsonObject {
            put("product_id", productId); put("purchase_token", purchaseToken)
        }).obj() ?: JsonObject(emptyMap())

    suspend fun ledger(limit: Int = 50): List<LedgerEntry> =
        get("/api/wallet/ledger", mapOf("limit" to limit)).decodeItems("ledger", "entries")

    suspend fun requestRefund(ref: String, reason: String) {
        post("/api/refunds", buildJsonObject { put("ref", ref); put("reason", reason) })
    }
    suspend fun refunds(): List<Refund> = get("/api/refunds").decodeItems("refunds")

    suspend fun createTicket(category: String, message: String) {
        post("/api/support", buildJsonObject { put("category", category); put("message", message) })
    }
    suspend fun tickets(): List<SupportTicket> = get("/api/support").decodeItems("tickets")

    /** Raw export JSON text, saved verbatim by the user. */
    suspend fun exportData(): String =
        exec(Request.Builder().url(url("/api/me/export")).get().build())

    suspend fun deleteAccount() { delete("/api/me") }
    suspend fun buyPro(): JsonObject = post("/api/plan/pro/purchase").obj() ?: JsonObject(emptyMap())
    suspend fun legal(doc: String): LegalDoc = get("/api/legal/$doc", mapOf("lang" to langProvider())).decodeAs()

    /** Public HTML policy page (for Play listing / opening in a browser). */
    fun publicLegalUrl(doc: String): String = baseUrl.trimEnd('/') + "/legal/$doc" + (langProvider()?.let { "?lang=$it" } ?: "")

    // ------------------------------------------------------------------ AI

    suspend fun createSession(profileId: String, mode: String): String =
        post("/api/sessions", buildJsonObject { put("profile_id", profileId); put("mode", mode) })
            .obj()?.str("session_id", "id") ?: throw ApiException(ErrorKind.SERVER, 200, null)

    suspend fun sessions(limit: Int = 20): List<SessionInfo> =
        get("/api/sessions", mapOf("limit" to limit)).decodeItems("sessions")

    suspend fun messages(sid: String): List<ChatMsg> =
        get("/api/sessions/$sid/messages").decodeItems("messages")

    suspend fun ask(sid: String, text: String): AskResult =
        post("/api/sessions/$sid/ask", buildJsonObject { put("text", text) }, slow = true).decodeAs()

    /**
     * `POST /ask/stream` as Server-Sent Events: `event: delta {text}` … then
     * `event: done {charged_units, balance_units, status, trace_id}`. An
     * `event: error {detail, code}` (if the server sends one mid-stream) is
     * raised as [ApiException]. Cancelling the collector cancels the HTTP call.
     */
    fun askStream(sid: String, text: String): Flow<StreamEvent> = callbackFlow {
        val req = Request.Builder()
            .url(url("/api/sessions/$sid/ask/stream"))
            .header("Accept", "text/event-stream")
            .post(AppJson.encodeToString(buildJsonObject { put("text", text) } as JsonElement).toRequestBody(jsonType))
            .build()
        val call = slowClient.newCall(req)
        val job = launch(Dispatchers.IO) {
            try {
                call.execute().use { resp ->
                    if (!resp.isSuccessful) raise(resp.code, resp.body?.string().orEmpty())
                    val source = resp.body!!.source()
                    var event = "message"
                    val data = StringBuilder()
                    fun dispatch() {
                        if (data.isEmpty()) { event = "message"; return }
                        val payload = data.toString(); data.clear()
                        val obj = runCatching { AppJson.parseToJsonElement(payload).obj() }.getOrNull()
                        when (event) {
                            "delta", "message" -> {
                                val t = obj?.str("text", "delta") ?: if (obj == null) payload else null
                                if (t != null) trySend(StreamEvent.Delta(t))
                            }
                            "done" -> {
                                val r = obj?.let { runCatching { it.decodeAs<AskResult>() }.getOrNull() } ?: AskResult()
                                r.balance_units?.let { AppEvents.balance.value = it }
                                trySend(StreamEvent.Done(r))
                            }
                            "error" -> {
                                raise(obj?.int("status_code") ?: 500, payload)
                            }
                        }
                        event = "message"
                    }
                    while (true) {
                        val line = source.readUtf8Line() ?: break
                        when {
                            line.isEmpty() -> dispatch()
                            line.startsWith(":") -> Unit // comment / keep-alive
                            line.startsWith("event:") -> event = line.substringAfter(':').trim()
                            line.startsWith("data:") -> {
                                if (data.isNotEmpty()) data.append('\n')
                                data.append(line.substringAfter(':').removePrefix(" "))
                            }
                        }
                    }
                    dispatch()
                }
                close()
            } catch (e: Throwable) {
                close(e)
            }
        }
        awaitClose { call.cancel(); job.cancel() }
    }

    /** Cloud speech path for devices without the language pack. */
    suspend fun voice(sid: String, audio: ByteArray, mime: String, fileName: String, tts: Boolean): VoiceResult {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", fileName, audio.toRequestBody(mime.toMediaType()))
            .addFormDataPart("tts", tts.toString())
            .build()
        val text = exec(Request.Builder().url(url("/api/sessions/$sid/voice")).post(body).build(), slow = true)
        return AppJson.parseToJsonElement(text).decodeAs<VoiceResult>().also {
            it.balance_units?.let { b -> AppEvents.balance.value = b }
        }
    }

    // ------------------------------------------------------------- reports

    suspend fun teaser(profileId: String): JsonObject =
        post("/api/reports/teaser", buildJsonObject { put("profile_id", profileId) }, slow = true).obj() ?: JsonObject(emptyMap())

    suspend fun createReport(profileId: String, brand: Boolean = false): Report =
        post("/api/reports", buildJsonObject { put("profile_id", profileId); put("brand", brand) }).decodeAs()

    suspend fun reports(): List<Report> = get("/api/reports").decodeItems("reports")
    suspend fun report(id: String): Report = get("/api/reports/$id").decodeAs()
    suspend fun resumeReport(id: String): Report = post("/api/reports/$id/resume").decodeAs()
    suspend fun reportPdf(id: String): String = signedUrl(get("/api/reports/$id/pdf"))

    // ------------------------------------------------------------ features

    suspend fun profiles(): List<Profile> = get("/api/profiles").decodeItems("profiles")
    suspend fun profile(pid: String): Profile = (get("/api/profiles/$pid").let { it.obj()?.get("profile") ?: it }).decodeAs()
    suspend fun createProfile(p: ProfileInput): Profile =
        post("/api/profiles", toJson(p)).let { it.obj()?.get("profile") ?: it }.decodeAs()
    suspend fun updateProfile(pid: String, p: ProfileInput): Profile =
        patch("/api/profiles/$pid", toJson(p)).let { it.obj()?.get("profile") ?: it }.decodeAs()
    suspend fun deleteProfile(pid: String) { delete("/api/profiles/$pid") }

    suspend fun chart(pid: String, kind: String, division: String? = null, year: Int? = null): JsonObject =
        get("/api/profiles/$pid/chart", mapOf("kind" to kind, "division" to division, "year" to year)).obj() ?: JsonObject(emptyMap())

    suspend fun snapshot(pid: String): JsonObject = get("/api/profiles/$pid/snapshot").obj() ?: JsonObject(emptyMap())
    suspend fun daily(pid: String?): JsonObject = get("/api/daily", mapOf("profile_id" to pid)).obj() ?: JsonObject(emptyMap())
    suspend fun alerts(pid: String): JsonElement = get("/api/profiles/$pid/alerts")

    suspend fun matching(a: String, b: String): JsonObject =
        post("/api/matching", buildJsonObject { put("profile_a", a); put("profile_b", b) }).obj() ?: JsonObject(emptyMap())
    /** [brand] = astrologer white-label PDF. */
    suspend fun matchingPdf(a: String, b: String, brand: Boolean = false): String =
        signedUrl(post("/api/matching/pdf", buildJsonObject { put("profile_a", a); put("profile_b", b); put("brand", brand) }, slow = true))

    suspend fun muhurta(event: String, from: String, to: String, profileId: String?, lat: Double, lon: Double, tz: String? = null): JsonElement =
        post("/api/muhurta", buildJsonObject {
            put("event", event); put("from", from); put("to", to)
            profileId?.let { put("profile_id", it) }
            put("lat", lat); put("lon", lon)
            tz?.let { put("tz", it) }
        }, slow = true)

    suspend fun rectify(pid: String, events: List<Pair<String, String>>): JsonElement =
        post("/api/profiles/$pid/rectify", buildJsonObject {
            put("events", buildJsonArray {
                events.forEach { (date, type) -> add(buildJsonObject { put("date", date); put("type", type) }) }
            })
        }, slow = true)

    suspend fun shareCard(pid: String, kind: String): String =
        signedUrl(post("/api/share-card", buildJsonObject { put("profile_id", pid); put("kind", kind) }))

    suspend fun places(q: String): List<Place> = get("/api/places", mapOf("q" to q)).decodeItems("places")

    // ----------------------------------------------------------- astrologer

    suspend fun clients(): List<Profile> = get("/api/astro/clients").decodeItems("clients", "profiles")
    suspend fun addClient(p: ProfileInput): Profile =
        post("/api/astro/clients", toJson(p)).let { it.obj()?.get("client") ?: it.obj()?.get("profile") ?: it }.decodeAs()
    suspend fun updateClientNotes(pid: String, notes: String) {
        patch("/api/astro/clients/$pid", buildJsonObject { put("notes", notes) })
    }
    suspend fun brand(): Brand = get("/api/astro/brand").let { it.obj()?.get("brand") ?: it }.decodeAs()
    suspend fun saveBrand(b: Brand) { httpPut("/api/astro/brand", toJson(b)) }
    suspend fun proBundle(pid: String): JsonObject = get("/api/astro/clients/$pid/pro-bundle").obj() ?: JsonObject(emptyMap())

    /** Download a signed URL (PDF / PNG) — no auth header needed but harmless. */
    suspend fun download(url: String): ByteArray = withContext(Dispatchers.IO) {
        val plain = OkHttpClient.Builder().readTimeout(120, TimeUnit.SECONDS).build()
        val abs = if (url.startsWith("/")) baseUrl.trimEnd('/') + url else url
        val rb = Request.Builder().url(abs)
        // Relative URLs are served by our API and need the bearer token.
        if (url.startsWith("/")) tokenProvider()?.let { rb.header("Authorization", "Bearer $it") }
        plain.newCall(rb.build()).await().use { r ->
            if (!r.isSuccessful) throw ApiException(ErrorKind.SERVER, r.code, null)
            r.body!!.bytes()
        }
    }
}
