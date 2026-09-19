package com.udhyath.app

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class ChartExtractTest {
    private fun parse(s: String): JsonObject = AppJson.parseToJsonElement(s).jsonObject

    @Test
    fun compactPlanetToSignMap() {
        val c = extractChart(parse("""{"chart":{"Lagna":"Leo","Sun":"Aries","Moon":"Taurus","Mars":"Leo","Mercury":"Aries","Jupiter":"Pisces","Venus":"Pisces","Saturn":"Aquarius","Rahu":"Virgo","Ketu":"Pisces"}}"""))
        assertNotNull(c); c!!
        assertEquals(4, c.lagna)
        assertEquals(listOf("Lagna", "Mars"), c.bySign[4])
    }

    @Test
    fun planetsObjectWithAscendantAndNumbers() {
        val c = extractChart(parse("""{"ascendant":{"sign":"Mesha"},"planets":{"Sun":{"sign_num":2},"Moon":{"sign":"Cancer","retrograde":false},"Mars":{"sign":"Scorpio"},"Saturn":{"sign":"Capricorn","retrograde":true},"Jupiter":{"sign":"Sagittarius"}}}"""))
        assertNotNull(c); c!!
        assertEquals(0, c.lagna)
        assertEquals(listOf("Sun"), c.bySign[1])
        assertEquals(setOf("Saturn"), c.retro)
    }

    @Test
    fun rupeesFormatting() {
        assertEquals("₹10", rupees(1000))
        assertEquals("₹1,050", rupees(105000))
        assertEquals("₹10.50", rupees(1050))
    }

    @Test
    fun obfuscatedAccountIdIsLowercaseSha256() {
        assertEquals("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", sha256Hex("test"))
    }
}
