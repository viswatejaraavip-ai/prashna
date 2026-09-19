package com.udhyath.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

// Brand: saffron flame, maroon diya bowl, warm cream paper, temple gold.
object BrandColors {
    val Saffron = Color(0xFFE8770E)
    val SaffronLight = Color(0xFFFFE3C4)
    val Maroon = Color(0xFF7A1F2B)
    val MaroonDark = Color(0xFF4E1219)
    val Cream = Color(0xFFFFF8EC)
    val Paper = Color(0xFFFFFDF7)
    val Gold = Color(0xFFC8962E)
    val GoldLight = Color(0xFFF1DFB5)
    val Ink = Color(0xFF2B1B17)
    val Muted = Color(0xFF6D5A50)
    val Good = Color(0xFF2E7D32)
    val Warn = Color(0xFFB26A00)
    val Bad = Color(0xFFB3261E)
}

private val Light = lightColorScheme(
    primary = BrandColors.Saffron,
    onPrimary = Color.White,
    primaryContainer = BrandColors.SaffronLight,
    onPrimaryContainer = BrandColors.MaroonDark,
    secondary = BrandColors.Maroon,
    onSecondary = Color.White,
    secondaryContainer = BrandColors.GoldLight,
    onSecondaryContainer = BrandColors.MaroonDark,
    tertiary = BrandColors.Gold,
    background = BrandColors.Cream,
    onBackground = BrandColors.Ink,
    surface = BrandColors.Paper,
    onSurface = BrandColors.Ink,
    surfaceVariant = Color(0xFFF6EBD9),
    onSurfaceVariant = BrandColors.Muted,
    outline = Color(0xFFD9C3A0),
    error = BrandColors.Bad,
)

private val Dark = darkColorScheme(
    primary = Color(0xFFFFB067),
    onPrimary = Color(0xFF4A2300),
    primaryContainer = Color(0xFF6B3500),
    onPrimaryContainer = Color(0xFFFFDCBE),
    secondary = Color(0xFFFFB3B6),
    onSecondary = Color(0xFF5B1320),
    secondaryContainer = Color(0xFF5A3A12),
    onSecondaryContainer = Color(0xFFF7DFB0),
    tertiary = BrandColors.Gold,
    background = Color(0xFF1C1411),
    onBackground = Color(0xFFF1E4DA),
    surface = Color(0xFF261C18),
    onSurface = Color(0xFFF1E4DA),
    surfaceVariant = Color(0xFF3A2D26),
    onSurfaceVariant = Color(0xFFD8C2B4),
    outline = Color(0xFF7D6758),
)

/** Current text-size multiplier (1.0 or the "large text" setting) for hand-sized text. */
val LocalTextScale = staticCompositionLocalOf { 1f }

private fun TextStyle.scaled(f: Float, size: TextUnit, line: TextUnit) =
    copy(fontSize = (size.value * f).sp, lineHeight = (line.value * f).sp)

/**
 * Indic scripts need more line height than Latin; sizes start a notch above
 * Material defaults so older family members can read comfortably, and the
 * "large text" setting multiplies everything by 1.2 on top of system font scale.
 */
private fun typography(f: Float): Typography {
    val t = Typography()
    return Typography(
        displaySmall = t.displaySmall.scaled(f, 34.sp, 46.sp),
        headlineLarge = t.headlineLarge.scaled(f, 30.sp, 42.sp),
        headlineMedium = t.headlineMedium.scaled(f, 26.sp, 36.sp),
        headlineSmall = t.headlineSmall.scaled(f, 23.sp, 33.sp),
        titleLarge = t.titleLarge.scaled(f, 21.sp, 30.sp),
        titleMedium = t.titleMedium.scaled(f, 18.sp, 27.sp),
        titleSmall = t.titleSmall.scaled(f, 16.sp, 24.sp),
        // letterSpacing must stay in sp like every other style: text fields lerp
        // bodyLarge <-> bodySmall for their label, and Em/Sp can't be mixed.
        bodyLarge = t.bodyLarge.scaled(f, 17.sp, 27.sp).copy(letterSpacing = (0.17f * f).sp),
        bodyMedium = t.bodyMedium.scaled(f, 15.sp, 24.sp),
        bodySmall = t.bodySmall.scaled(f, 13.sp, 20.sp),
        labelLarge = t.labelLarge.scaled(f, 16.sp, 22.sp),
        labelMedium = t.labelMedium.scaled(f, 14.sp, 20.sp),
        labelSmall = t.labelSmall.scaled(f, 12.sp, 17.sp),
    )
}

@Composable
fun UdhyathTheme(largeText: Boolean, dark: Boolean, content: @Composable () -> Unit) {
    val f = if (largeText) 1.2f else 1f
    androidx.compose.runtime.CompositionLocalProvider(LocalTextScale provides f) {
        MaterialTheme(colorScheme = if (dark) Dark else Light, typography = typography(f), content = content)
    }
}
