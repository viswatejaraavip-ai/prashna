resource "google_firestore_database" "main" {
  name                              = "(default)"
  location_id                       = var.firestore_location
  type                              = "FIRESTORE_NATIVE"
  concurrency_mode                  = "OPTIMISTIC"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state           = var.deletion_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"
  deletion_policy                   = var.deletion_protection ? "ABANDON" : "DELETE"

  depends_on = [google_project_service.apis]
}

# Composite indexes for the contract's queries (single-field indexes are
# automatic). Order of fields matters: equality field first, then created_at.
locals {
  firestore_indexes = {
    traces_status   = { collection = "traces", fields = [["status", "ASCENDING"], ["created_at", "DESCENDING"]] }
    traces_uid      = { collection = "traces", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    traces_kind     = { collection = "traces", fields = [["kind", "ASCENDING"], ["created_at", "DESCENDING"]] }
    sessions_uid    = { collection = "sessions", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    reports_uid     = { collection = "reports", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    payments_uid    = { collection = "payments", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    refunds_status  = { collection = "refunds", fields = [["status", "ASCENDING"], ["created_at", "DESCENDING"]] }
    refunds_uid     = { collection = "refunds", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    support_status  = { collection = "support_tickets", fields = [["status", "ASCENDING"], ["created_at", "DESCENDING"]] }
    support_uid     = { collection = "support_tickets", fields = [["uid", "ASCENDING"], ["created_at", "DESCENDING"]] }
    users_plan      = { collection = "users", fields = [["plan", "ASCENDING"], ["plan_expires_at", "ASCENDING"]] }
    profiles_client = { collection = "profiles", fields = [["relation", "ASCENDING"], ["created_at", "DESCENDING"]] }
  }
}

resource "google_firestore_index" "idx" {
  for_each   = local.firestore_indexes
  database   = google_firestore_database.main.name
  collection = each.value.collection

  dynamic "fields" {
    for_each = each.value.fields
    content {
      field_path = fields.value[0]
      order      = fields.value[1]
    }
  }
}
