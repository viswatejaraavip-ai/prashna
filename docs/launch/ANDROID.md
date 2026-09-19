# Udhyath Android: setup, build and release

The app lives in `android/` (Kotlin, Jetpack Compose, Material 3). Package id: `com.udhyath.app`.

## 1. Toolchain

- JDK 17 and Android SDK platform 36 (`compileSdk = 36`, `minSdk = 26`).
- AGP 8.11.1, Kotlin 2.1.20, Gradle 8.13 (the wrapper downloads it).
- `android/local.properties` points at your SDK (`sdk.dir=...`). It is gitignored.

```bash
cd android
./gradlew assembleDebug testDebugUnitTest   # debug APK + unit tests
./gradlew assembleRelease                   # R8-minified release build (signing: section 5)
```

Base URL comes from `BuildConfig.API_BASE`:

| Build type | API_BASE |
|---|---|
| debug | `http://10.0.2.2:8000` (the emulator's view of the host; cleartext is allowed only for this host, and only in debug) |
| release | `https://api.udhyath.com` (placeholder; change it in `app/build.gradle.kts`) |

The WhatsApp support number is `BuildConfig.SUPPORT_WHATSAPP` (placeholder `919000000000`) in `app/build.gradle.kts`.

## 2. Firebase (required for the build)

`android/app/google-services.json` is **not committed**. It is gitignored. If it is missing, the build stops with instructions.

1. Create a Firebase project, or use the one the backend uses (it must be the same project, because the backend verifies the Firebase ID tokens).
2. Add an Android app with package **`com.udhyath.app`**.
3. Add the **SHA-1 and SHA-256** fingerprints of every signing key. Phone auth and Google sign-in both depend on them:
   - Debug key: `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android`
   - Upload key: run the same command against your release keystore.
   - **Play App Signing key**: Play Console → *Test and release → App integrity → App signing*. Copy the SHA-1 and SHA-256. Without this, OTP and Google sign-in fail on builds installed from Play.
4. Authentication → Sign-in method: enable **Phone** and **Google**. For Phone, also:
   - Enable the **Play Integrity API** for the Google Cloud project. Otherwise OTP falls back to a reCAPTCHA browser flow.
   - Add test phone numbers for QA if you want. India (+91) is the default country code in the app.
5. Download `google-services.json` and save it at `android/app/google-services.json`.
6. Google sign-in uses Credential Manager with the **Web client ID**. The google-services plugin generates `default_web_client_id` from the JSON when a Web OAuth client exists (Firebase creates one when you enable Google sign-in; download the JSON *after* enabling it). If that client is missing, the Google button shows "not available in this build" and phone OTP still works.
7. Cloud Messaging: nothing to configure in the app. The backend sends pushes with the Admin SDK.

**UI-only build without Firebase:** `cp android/app/google-services.example.json android/app/google-services.json`. The app compiles and runs, but sign-in and push will not work.

### Push payloads the app understands

Pushes with a `notification` block are shown by the system. `data`-only pushes are shown by the app. Both use these `data` keys:

| key | values |
|---|---|
| `type` | `daily` → Home, `transit` → Transit alerts (needs `profile_id`), `report` → report reader (needs `report_id`), `wallet`, `support` |
| `deeplink` | optional; a ready `udhyath://…` link takes precedence |
| `title`, `body` | used for data-only messages |

Deep links: `udhyath://home`, `udhyath://alerts/{pid}`, `udhyath://report/{id}`, `udhyath://reports`, `udhyath://wallet`, `udhyath://support`, `udhyath://chat?pid={pid}`.

Notification channels: `daily`, `transits`, `reports`, `account`. The default channel for system-displayed pushes is `daily`. Set `android.notification.channel_id` in the FCM message to pick another.

## 3. Play Console

1. Create the app with package `com.udhyath.app`, default language Hindi. Add listings in te-IN, ta-IN, kn-IN and ml-IN.
2. **In-app products** (Monetize → Products → In-app products). All of them are **consumable**, and the server consumes them after verifying:

   | Product id | Price |
   |---|---|
   | `wallet_100` | ₹100 |
   | `wallet_200` | ₹200 |
   | `wallet_500` | ₹500 |
   | `wallet_1000` | ₹1000 |

   The app reads the list from `GET /api/pricing` → `play_products`. It falls back to these four ids if that list is empty.
3. Link a Google Cloud service account with the **Android Publisher API** and give it *View financial data* and *Manage orders* in Play Console. The backend uses it for `POST /api/wallet/play/verify`.
4. Every purchase is bound to the account with `obfuscatedAccountId = sha256_hex(firebase uid)`. The server rejects tokens bound to another account.
5. Add license testers (Setup → License testing) so QA can buy without being charged.
6. Privacy policy URL for the listing: `https://<api host>/legal/privacy`. Also link `/legal/terms` and `/legal/refund`. The backend serves these as public HTML.
7. Data safety form: phone number/email (auth), birth details (app functionality), purchase history, audio (voice questions; processed on-device by default, sent to the server only when the device has no language pack), device ids (FCM token and install id, used for the one-time free trial). Account deletion is in-app under More → Privacy and data. For the web deletion URL Play requires, point to a support page.

## 4. Languages

- On first launch the user picks one of exactly five languages: हिन्दी, తెలుగు, தமிழ், ಕನ್ನಡ, മലയാളം. The choice is applied with `AppCompatDelegate.setApplicationLocales` (per-app language). On Android 13+ it also shows in system settings via `res/xml/locales_config.xml`. On older versions AppCompat stores it (`autoStoreLocales`).
- The choice is sent to the backend as `lang` on `POST /api/auth/firebase`, via `PATCH /api/me {lang}`, and as `Accept-Language` on every request. That makes AI answers, the daily forecast and legal pages come back in that language.
- Voice uses `hi-IN`, `te-IN`, `ta-IN`, `kn-IN`, `ml-IN` for SpeechRecognizer and TextToSpeech. If the phone lacks the recognizer or TTS voice for the language, the chat switches to the server `/voice` endpoint (16 kHz mono LINEAR16 WAV upload, server TTS when needed).
- UI strings are in `res/values-{hi,te,ta,kn,ml}/strings.xml`. `values/strings.xml` holds the English base and is only a fallback. `StringsCompletenessTest` fails the build's unit tests if any key is missing, has different `%1$s` placeholders, or was left in English.

## 5. Release signing and publishing

1. Create an upload key once: `keytool -genkeypair -v -keystore udhyath-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000`
2. Create `android/keystore.properties`. It is gitignored:
   ```properties
   storeFile=../udhyath-upload.jks
   storePassword=...
   keyAlias=upload
   keyPassword=...
   ```
   The path is relative to `android/`.
3. Set `API_BASE` for release in `app/build.gradle.kts`. Bump `versionCode` and `versionName`.
4. `./gradlew bundleRelease` → `app/build/outputs/bundle/release/app-release.aab`. Upload it to the internal testing track first.
5. Enrol in Play App Signing, then add the Play signing key's SHA-1/SHA-256 to Firebase (section 2.3).
6. R8 is on for release (`isMinifyEnabled` and `isShrinkResources`). Keep rules are in `app/proguard-rules.pro`. Smoke-test a release build on a device before promoting it: sign-in, one paid question, a Play test purchase, and a push.

## 6. QA checklist

- Fresh install: the language picker appears first. Pick Telugu and confirm the whole UI switches.
- Sign in with a +91 test number, choose a role, accept the disclaimer, enter birth details (try "I don't know my exact time"), and check that the free snapshot appears.
- Ask a question. The price should show before sending, and the reply should stream in the chosen language.
- Voice: test on a device with the Google speech pack, and on one without it (the cloud path, which shows a notice).
- Top up with a license-tester account. The balance should update and the ledger should show the entry.
- Buy the life report. Check the progress bar, the "ready" notification, the reader, and PDF open/share.
- Astrologer role: add a client, open the Pro bundle (it should be locked until Pro), buy Pro, edit the brand, and share a branded matching PDF.
- More: switch the language, turn on large text, change notification toggles, request a refund, send a support ticket, open WhatsApp, export data, delete the account.
- Airplane mode: the offline banner appears, and errors offer a retry.
