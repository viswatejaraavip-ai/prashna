@file:OptIn(ExperimentalSerializationApi::class)

package com.udhyath.app

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNames
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/**
 * DTOs for docs/launch/CONTRACT.md. Every field has a default and unknown keys
 * are ignored, so the app keeps working while the backend adds fields. Where
 * the contract names a document without fixing its id key we accept the
 * usual spellings via @JsonNames.
 */
val AppJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    isLenient = true
    encodeDefaults = true
}

@Serializable
data class NotifPrefs(val daily: Boolean = true, val transits: Boolean = true, val promos: Boolean = false)

@Serializable
data class User(
    val uid: String = "",
    val phone: String? = null,
    val email: String? = null,
    val name: String? = null,
    val lang: String? = null,
    val role: String? = null,
    val balance_units: Long = 0,
    val plan: String = "free",
    val plan_expires_at: String? = null,
    val trial_claimed: Boolean = false,
    val disclaimer_accepted_at: String? = null,
    val notif_prefs: NotifPrefs = NotifPrefs(),
) {
    val isAstrologer get() = role == "astrologer"
    /** Pro needs plan == "pro" and an unexpired plan_expires_at (server enforces the same). */
    val isPro: Boolean get() {
        if (plan != "pro") return false
        val exp = plan_expires_at ?: return true
        return runCatching {
            java.time.Instant.parse(if (exp.endsWith("Z") || exp.contains('+')) exp else exp + "Z").isAfter(java.time.Instant.now())
        }.getOrDefault(true)
    }
}

@Serializable
data class Pricing(
    val query_price_units: Long = 1000,
    val report_price_units: Long = 105000,
    val pro_plan_units: Long = 49900,
    val pro_plan_days: Int = 30,
    val topup_options: List<JsonElement> = emptyList(),
    val play_products: List<JsonElement> = emptyList(),
) {
    /** Play product ids; the contract doesn't fix the element shape, so accept strings or {product_id}. */
    val playProductIds: List<String>
        get() = play_products.mapNotNull { el ->
            when (el) {
                is JsonPrimitive -> el.content
                is JsonObject -> el.str("product_id") ?: el.str("id") ?: el.str("sku")
                else -> null
            }
        }.ifEmpty { listOf("wallet_100", "wallet_200", "wallet_500", "wallet_1000") }
}

@Serializable
data class AuthResponse(val token: String, val user: User = User())

@Serializable
data class MeResponse(val user: User = User(), val pricing: Pricing = Pricing())

@Serializable
data class Birth(
    val date: String = "",          // YYYY-MM-DD
    val time: String = "12:00",     // HH:MM (24h)
    val tz: String = "Asia/Kolkata",
    val lat: Double = 0.0,
    val lon: Double = 0.0,
    val place: String = "",
)

@Serializable
data class Profile(
    @JsonNames("profile_id", "pid") val id: String = "",
    val name: String = "",
    val relation: String = "self",
    val birth: Birth = Birth(),
    val time_known: Boolean = true,
    val gender: String? = null,
    val notes: String? = null,
    val created_at: String? = null,
)

@Serializable
data class ProfileInput(
    val name: String,
    val relation: String,
    val birth: Birth,
    val time_known: Boolean,
    val gender: String? = null,
    val notes: String? = null,
)

@Serializable
data class Place(
    val name: String = "",
    val region: String = "",
    @JsonNames("lat") val latitude: Double = 0.0,
    @JsonNames("lon", "lng") val longitude: Double = 0.0,
    @JsonNames("tz") val tz_name: String = "Asia/Kolkata",
    @kotlinx.serialization.SerialName("label") val serverLabel: String? = null,
) {
    val label: String get() = serverLabel?.takeIf { it.isNotBlank() } ?: if (region.isBlank()) name else "$name, $region"
}

@Serializable
data class LedgerEntry(
    val type: String = "",
    val delta_units: Long = 0,
    val balance_after: Long = 0,
    val ref: String? = null,
    val created_at: String = "",
)

@Serializable
data class SessionInfo(
    @JsonNames("session_id", "sid") val id: String = "",
    val profile_id: String? = null,
    val lang: String? = null,
    val mode: String = "text",
    val created_at: String = "",
    val summary: String? = null,
    val query_count: Int = 0,
)

@Serializable
data class ChatMsg(
    val role: String = "assistant",
    val text: String = "",
    val charged_units: Long = 0,
    val trace_id: String? = null,
    val created_at: String? = null,
)

@Serializable
data class AskResult(
    val reply: String = "",
    val charged_units: Long = 0,
    val balance_units: Long? = null,
    val status: String = "ok",
    val trace_id: String? = null,
)

@Serializable
data class VoiceResult(
    val transcript: String = "",
    val reply: String = "",
    val audio_b64: String? = null,
    val charged_units: Long = 0,
    val balance_units: Long? = null,
    val status: String = "ok",
    val trace_id: String? = null,
)

@Serializable
data class ReportSection(val idx: Int = 0, val title: String = "", val content: String = "")

@Serializable
data class Report(
    @JsonNames("report_id") val id: String = "",
    val status: String = "generating",
    val profile_id: String? = null,
    val sections_done: Int = 0,
    val sections_total: Int = 0,
    val created_at: String? = null,
    val completed_at: String? = null,
    val error: String? = null,
    val sections: List<ReportSection> = emptyList(),
)

@Serializable
data class LegalDoc(val title: String = "", val body_markdown: String = "")

@Serializable
data class Refund(
    @JsonNames("refund_id") val id: String = "",
    val ref: String? = null,
    val amount_units: Long = 0,
    val reason: String = "",
    val status: String = "requested",
    val created_at: String = "",
)

@Serializable
data class SupportTicket(
    @JsonNames("ticket_id") val id: String = "",
    val category: String = "",
    val message: String = "",
    val status: String = "open",
    val replies: List<JsonElement> = emptyList(),
    val created_at: String = "",
)

@Serializable
data class Brand(
    val display_name: String = "",
    val phone: String = "",
    val logo_url: String = "",
    val footer: String = "",
)

// ---------------------------------------------------------------------------
// Tolerant JSON helpers for responses whose inner shape the contract leaves
// open (charts, daily, snapshot, alerts, matching, muhurta, rectify...).
// ---------------------------------------------------------------------------

fun JsonElement?.obj(): JsonObject? = this as? JsonObject
fun JsonElement?.arr(): JsonArray? = this as? JsonArray

fun JsonObject.str(vararg keys: String): String? {
    for (k in keys) {
        val v = this[k]
        if (v is JsonPrimitive && v !is JsonNull && v.content.isNotBlank()) return v.content
    }
    return null
}

fun JsonObject.num(vararg keys: String): Double? {
    for (k in keys) (this[k] as? JsonPrimitive)?.doubleOrNull?.let { return it }
    return null
}

fun JsonObject.int(vararg keys: String): Int? {
    for (k in keys) (this[k] as? JsonPrimitive)?.let { p -> p.intOrNull ?: p.doubleOrNull?.toInt() }?.let { return it }
    return null
}

fun JsonObject.long(vararg keys: String): Long? {
    for (k in keys) (this[k] as? JsonPrimitive)?.longOrNull?.let { return it }
    return null
}

fun JsonObject.bool(vararg keys: String): Boolean? {
    for (k in keys) (this[k] as? JsonPrimitive)?.booleanOrNull?.let { return it }
    return null
}

fun JsonObject.child(vararg keys: String): JsonObject? {
    for (k in keys) (this[k] as? JsonObject)?.let { return it }
    return null
}

fun JsonObject.list(vararg keys: String): JsonArray? {
    for (k in keys) (this[k] as? JsonArray)?.let { return it }
    return null
}

/**
 * List endpoints may return a bare array or wrap it (`{items:[...]}`,
 * `{profiles:[...]}`...). Accept both.
 */
fun JsonElement.itemsList(vararg wrapperKeys: String): List<JsonElement> = when (this) {
    is JsonArray -> this
    is JsonObject -> {
        val keys = wrapperKeys.toList() + listOf("items", "data", "results")
        keys.firstNotNullOfOrNull { this[it] as? JsonArray }
            ?: this.values.firstOrNull { it is JsonArray } as? JsonArray
            ?: emptyList()
    }
    else -> emptyList()
}

inline fun <reified T> JsonElement.decodeItems(vararg wrapperKeys: String): List<T> =
    itemsList(*wrapperKeys).mapNotNull { runCatching { AppJson.decodeFromJsonElement<T>(it) }.getOrNull() }

inline fun <reified T> JsonElement.decodeAs(): T = AppJson.decodeFromJsonElement(this)

/** Primitive display text (numbers without trailing ".0"). */
fun JsonElement.displayText(): String = when (this) {
    is JsonPrimitive -> {
        val d = doubleOrNull
        when {
            isString -> content
            d != null && d == Math.floor(d) && !d.isInfinite() && kotlin.math.abs(d) < 1e15 -> d.toLong().toString()
            d != null -> "%.2f".format(d)
            else -> content
        }
    }
    is JsonArray -> joinToString(", ") { it.displayText() }
    is JsonObject -> entries.joinToString(" · ") { "${it.key}: ${it.value.displayText()}" }
}
