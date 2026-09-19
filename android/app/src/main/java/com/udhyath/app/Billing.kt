package com.udhyath.app

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.android.billingclient.api.queryProductDetails
import com.android.billingclient.api.queryPurchasesAsync
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/** Lowercase hex SHA-256, used for Play's obfuscatedAccountId. */
fun sha256Hex(s: String): String =
    java.security.MessageDigest.getInstance("SHA-256").digest(s.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

/** A wallet top-up pack from Play (consumable). */
data class TopUpPack(val productId: String, val price: String, val rupees: Int, val details: ProductDetails?)

sealed interface PurchaseEvent {
    data class Credited(val balanceUnits: Long?) : PurchaseEvent
    data object Pending : PurchaseEvent
    data object Cancelled : PurchaseEvent
    data class Failed(val message: String?) : PurchaseEvent
}

/**
 * Google Play Billing for the consumable wallet packs `wallet_100/200/500/1000`.
 * Every purchase is sent to `POST /api/wallet/play/verify`, which verifies with
 * the Android Publisher API, credits the wallet idempotently and consumes the
 * product server-side — so the app never consumes locally.
 */
class BillingManager(context: Context, private val api: UdhyathApi) : PurchasesUpdatedListener {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val _events = MutableSharedFlow<PurchaseEvent>(extraBufferCapacity = 4)
    val events: SharedFlow<PurchaseEvent> = _events

    private val client: BillingClient = BillingClient.newBuilder(context.applicationContext)
        .setListener(this)
        .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
        .enableAutoServiceReconnection()
        .build()

    private suspend fun connect(): Boolean {
        if (client.isReady) return true
        return suspendCancellableCoroutine { cont ->
            client.startConnection(object : BillingClientStateListener {
                override fun onBillingSetupFinished(result: BillingResult) {
                    if (cont.isActive) cont.resume(result.responseCode == BillingClient.BillingResponseCode.OK)
                }
                override fun onBillingServiceDisconnected() {
                    if (cont.isActive) cont.resume(false)
                }
            })
        }
    }

    /** Rupee value encoded in the product id (`wallet_500` → 500). */
    private fun rupeesOf(id: String) = id.substringAfterLast('_').toIntOrNull() ?: 0

    suspend fun packs(productIds: List<String>): List<TopUpPack> {
        if (!connect()) return emptyList()
        val params = QueryProductDetailsParams.newBuilder().setProductList(
            productIds.map {
                QueryProductDetailsParams.Product.newBuilder()
                    .setProductId(it).setProductType(BillingClient.ProductType.INAPP).build()
            }
        ).build()
        val result = client.queryProductDetails(params)
        return result.productDetailsList.orEmpty()
            .map { TopUpPack(it.productId, it.oneTimePurchaseOfferDetails?.formattedPrice ?: "₹${rupeesOf(it.productId)}", rupeesOf(it.productId), it) }
            .sortedBy { it.rupees }
    }

    /**
     * Launch the Play purchase sheet. [uid] is bound to the purchase as
     * `obfuscatedAccountId = sha256_hex(uid)`; the server rejects tokens bound
     * to another account.
     */
    fun buy(activity: Activity, pack: TopUpPack, uid: String): Boolean {
        val details = pack.details ?: return false
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(
                BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(details).build()
            ))
            .setObfuscatedAccountId(sha256Hex(uid))
            .build()
        return client.launchBillingFlow(activity, params).responseCode == BillingClient.BillingResponseCode.OK
    }

    override fun onPurchasesUpdated(result: BillingResult, purchases: MutableList<Purchase>?) {
        when (result.responseCode) {
            BillingClient.BillingResponseCode.OK -> purchases?.forEach { handle(it) }
            BillingClient.BillingResponseCode.USER_CANCELED -> _events.tryEmit(PurchaseEvent.Cancelled)
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> scope.launch { restore() }
            else -> _events.tryEmit(PurchaseEvent.Failed(result.debugMessage))
        }
    }

    private fun handle(p: Purchase) {
        when (p.purchaseState) {
            Purchase.PurchaseState.PENDING -> _events.tryEmit(PurchaseEvent.Pending)
            Purchase.PurchaseState.PURCHASED -> scope.launch {
                val productId = p.products.firstOrNull() ?: return@launch
                runCatching { api.playVerify(productId, p.purchaseToken) }
                    .onSuccess { _events.emit(PurchaseEvent.Credited(it.long("balance_units"))) }
                    .onFailure { _events.emit(PurchaseEvent.Failed(it.message)) }
            }
            else -> {}
        }
    }

    /**
     * Re-send any purchased-but-unconsumed packs (app killed mid-verify,
     * pending payments that later completed). The server is idempotent.
     */
    suspend fun restore() {
        if (!connect()) return
        val res = client.queryPurchasesAsync(
            QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.INAPP).build()
        )
        res.purchasesList.filter { it.purchaseState == Purchase.PurchaseState.PURCHASED }.forEach { handle(it) }
    }
}
