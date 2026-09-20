package com.udhyath.app

import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Regression for "adding the brand in settings throws an API error": an
 * astrologer with no brand saved yet gets `{"brand": null}` from the older
 * server, and decoding that JSON null into [Brand] threw before the form was
 * ever drawn. Every shape the endpoint can answer with must yield a form.
 */
class BrandResponseTest {
    private fun parse(s: String) = AppJson.parseToJsonElement(s)

    private val full = Brand("Sri Sai Jyotisham", "+91 90000 00000",
        "https://example.com/logo.png", "By appointment")

    @Test
    fun nullBrandIsAnEmptyFormNotACrash() {
        assertEquals(Brand(), brandFromResponse(parse("""{"brand":null}""")))
    }

    @Test
    fun emptyBrandObjectIsAnEmptyForm() {
        assertEquals(Brand(), brandFromResponse(
            parse("""{"brand":{"display_name":"","phone":"","logo_url":"","footer":""}}""")))
    }

    @Test
    fun savedBrandIsDecodedFromTheWrapper() {
        val el = parse("""{"brand":{"display_name":"Sri Sai Jyotisham","phone":"+91 90000 00000",
            "logo_url":"https://example.com/logo.png","footer":"By appointment",
            "updated_at":"2026-09-20T00:00:00+00:00"}}""")
        assertEquals(full, brandFromResponse(el))
    }

    @Test
    fun bareBrandObjectWithoutTheWrapperIsAccepted() {
        val el = parse("""{"display_name":"Sri Sai Jyotisham","phone":"+91 90000 00000",
            "logo_url":"https://example.com/logo.png","footer":"By appointment"}""")
        assertEquals(full, brandFromResponse(el))
    }

    @Test
    fun anUnexpectedBodyKeepsWhatTheUserTyped() {
        assertEquals(full, brandFromResponse(JsonObject(emptyMap()), fallback = full))
        assertEquals(full, brandFromResponse(parse("""{"ok":true}"""), fallback = full))
        assertEquals(full, brandFromResponse(parse("\"oops\""), fallback = full))
    }

    @Test
    fun partialBrandFillsTheMissingFields() {
        assertEquals(Brand(display_name = "Only Name"),
            brandFromResponse(parse("""{"brand":{"display_name":"Only Name"}}""")))
    }
}
