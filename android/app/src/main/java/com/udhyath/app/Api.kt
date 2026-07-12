package com.udhyath.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Raised for non-2xx responses; `detail` is the API's human-readable message. */
class ApiException(val code: Int, val detail: String) : IOException(detail)

/**
 * Minimal HTTP client over the Udhyath backend (same /api layer the website
 * uses). Platform HttpURLConnection + org.json only — no third-party deps.
 */
object Api {
    const val BASE = "https://astrology.example.com"
    var token: String? = null

    private suspend fun request(method: String, path: String,
                                body: JSONObject? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val conn = URL(BASE + path).openConnection() as HttpURLConnection
            conn.requestMethod = method
            conn.connectTimeout = 20_000
            conn.readTimeout = 180_000  // agent replies can take a while
            conn.setRequestProperty("Accept", "application/json")
            token?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val status = conn.responseCode
            val text = (if (status < 400) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.readText() ?: ""
            conn.disconnect()
            val json = when {
                text.trimStart().startsWith("[") ->
                    JSONObject().put("items", JSONArray(text))
                text.isNotBlank() -> JSONObject(text)
                else -> JSONObject()
            }
            if (status >= 400) throw ApiException(status, extractDetail(json))
            json
        }

    /** FastAPI errors carry either a string detail or a 422 validation array. */
    private fun extractDetail(json: JSONObject): String {
        val detail = json.opt("detail") ?: return "Request failed"
        if (detail is JSONArray) {
            val parts = (0 until detail.length()).mapNotNull { i ->
                (detail.opt(i) as? JSONObject)?.optString("msg")
            }
            if (parts.isNotEmpty()) return parts.joinToString("; ")
        }
        return detail.toString()
    }

    suspend fun login(email: String, password: String): JSONObject =
        request("POST", "/api/auth/login",
                JSONObject().put("email", email).put("password", password))

    suspend fun register(email: String, password: String): JSONObject =
        request("POST", "/api/auth/register",
                JSONObject().put("email", email).put("password", password))

    suspend fun verifyOtp(email: String, otp: String): JSONObject =
        request("POST", "/api/auth/verify-otp",
                JSONObject().put("email", email).put("otp", otp))

    suspend fun resendOtp(email: String): JSONObject =
        request("POST", "/api/auth/resend-otp", JSONObject().put("email", email))

    suspend fun me(): JSONObject = request("GET", "/api/me")

    suspend fun claimTrial(deviceId: String): JSONObject =
        request("POST", "/api/trial/claim", JSONObject().put("device_id", deviceId))

    suspend fun createSession(): JSONObject = request("POST", "/api/sessions", JSONObject())

    suspend fun sendMessage(sessionId: String, content: String): JSONObject =
        request("POST", "/api/sessions/$sessionId/messages",
                JSONObject().put("content", content))

    // ---- free chart endpoints (no login needed) ----

    suspend fun searchPlaces(q: String): JSONArray =
        request("GET", "/api/places/search?q=" +
                java.net.URLEncoder.encode(q, "UTF-8")).getJSONArray("items")

    suspend fun computeChart(birth: JSONObject): JSONObject =
        request("POST", "/api/astrology/chart", birth)

    suspend fun dashas(birth: JSONObject, system: String): JSONObject {
        val body = JSONObject(birth.toString())
            .put("system", system).put("levels", 2)
        return request("POST", "/api/astrology/dashas", body)
    }
}
