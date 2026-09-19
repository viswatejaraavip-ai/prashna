# ---- kotlinx.serialization (library ships rules; these cover our DTOs) ----
-keepattributes *Annotation*, InnerClasses, Signature, EnclosingMethod
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class com.udhyath.app.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers class com.udhyath.app.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.udhyath.app.**$$serializer { *; }

# ---- OkHttp / Okio ----
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# ---- Firebase Messaging service is referenced from the manifest (kept by AAPT) ----
-keep class com.udhyath.app.UdhyathMessagingService { *; }

# ---- Play Billing ----
-keep class com.android.vending.billing.** { *; }

# ---- Credential Manager / Google ID ----
-if class androidx.credentials.CredentialManager
-keep class androidx.credentials.playservices.** { *; }

# ---- WorkManager workers are instantiated reflectively ----
-keep class * extends androidx.work.ListenableWorker { <init>(...); }
