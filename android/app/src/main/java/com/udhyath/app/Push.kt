package com.udhyath.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import java.util.concurrent.TimeUnit

/**
 * Push handling. FCM data payload (our assumption; the contract only fixes the
 * cron endpoints): `type` = daily | transit | report | wallet | support, plus
 * optional `profile_id`, `report_id`, `title`, `body`, or a ready `deeplink`
 * (`prashna://...`). Notification-type messages delivered while the app is in
 * the background put the same keys in the launch intent's extras.
 */
object Notifications {
    const val CH_DAILY = "daily"
    const val CH_TRANSITS = "transits"
    const val CH_REPORTS = "reports"
    const val CH_ACCOUNT = "account"

    /** (Re)create channels; called at startup and after a language change so names are localized. */
    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
        listOf(
            Triple(CH_DAILY, R.string.channel_daily, NotificationManager.IMPORTANCE_DEFAULT),
            Triple(CH_TRANSITS, R.string.channel_transits, NotificationManager.IMPORTANCE_DEFAULT),
            Triple(CH_REPORTS, R.string.channel_reports, NotificationManager.IMPORTANCE_HIGH),
            Triple(CH_ACCOUNT, R.string.channel_account, NotificationManager.IMPORTANCE_DEFAULT),
        ).forEach { (id, name, importance) ->
            nm.createNotificationChannel(NotificationChannel(id, ctx.getString(name), importance))
        }
    }

    fun deepLinkFor(data: Map<String, String?>): Uri? {
        data["deeplink"]?.takeIf { it.startsWith("prashna://") }?.let { return Uri.parse(it) }
        return when (data["type"]) {
            "daily" -> Uri.parse("prashna://home")
            "transit", "transit_alert" -> data["profile_id"]?.let { Uri.parse("prashna://alerts/$it") } ?: Uri.parse("prashna://home")
            "report" -> data["report_id"]?.let { Uri.parse("prashna://report/$it") } ?: Uri.parse("prashna://reports")
            "wallet" -> Uri.parse("prashna://wallet")
            "support" -> Uri.parse("prashna://support")
            else -> null
        }
    }

    fun channelFor(type: String?) = when (type) {
        "transit", "transit_alert" -> CH_TRANSITS
        "report" -> CH_REPORTS
        "wallet", "support" -> CH_ACCOUNT
        else -> CH_DAILY
    }

    fun canPost(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun show(ctx: Context, channel: String, title: String, body: String, link: Uri?, id: Int = (System.currentTimeMillis() % Int.MAX_VALUE).toInt()) {
        if (!canPost(ctx)) return
        val intent = Intent(ctx, MainActivity::class.java).apply {
            action = Intent.ACTION_VIEW
            data = link
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pi = PendingIntent.getActivity(ctx, id, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(ctx, R.color.saffron))
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        try { NotificationManagerCompat.from(ctx).notify(id, n) } catch (_: SecurityException) {}
    }
}

class UdhyathMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val g = applicationContext.graph
        g.account.launch { g.account.syncFcmToken(token) }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val title = message.notification?.title ?: data["title"] ?: getString(R.string.app_name)
        val body = message.notification?.body ?: data["body"] ?: return
        Notifications.show(this, Notifications.channelFor(data["type"]), title, body, Notifications.deepLinkFor(data))
    }
}

/**
 * Backup for the "report ready" push: while a purchased report is generating
 * we poll every 15 minutes and post a local notification when it completes.
 */
class ReportWatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val g = applicationContext.graph
        if (!g.account.signedIn) return Result.success()
        val watched = g.settings.watchedReports()
        if (watched.isEmpty()) { WorkManager.getInstance(applicationContext).cancelUniqueWork(NAME); return Result.success() }
        val still = mutableSetOf<String>()
        for (id in watched) {
            val r = runCatching { g.api.report(id) }.getOrNull()
            when (r?.status) {
                null, "generating", "queued", "pending" -> still += id
                "done", "completed", "ready" -> Notifications.show(
                    applicationContext, Notifications.CH_REPORTS,
                    applicationContext.getString(R.string.notif_report_ready_title),
                    applicationContext.getString(R.string.notif_report_ready_body),
                    Uri.parse("prashna://report/$id"),
                )
                else -> {} // failed: the reports screen offers resume
            }
        }
        g.settings.setWatchedReports(still)
        return Result.success()
    }

    companion object {
        private const val NAME = "report-watch"
        fun watch(ctx: Context, reportId: String) {
            val g = ctx.graph
            g.account.launch {
                g.settings.setWatchedReports(g.settings.watchedReports() + reportId)
                val req = PeriodicWorkRequestBuilder<ReportWatchWorker>(15, TimeUnit.MINUTES)
                    .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setInitialDelay(15, TimeUnit.MINUTES)
                    .build()
                WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, req)
            }
        }
    }
}
