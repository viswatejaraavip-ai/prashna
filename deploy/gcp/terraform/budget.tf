# Monthly budget alert (50/90/100% actual, 100% forecast). Needs
# roles/billing.costsManager (or billing admin) on the billing account for
# whoever runs terraform.

resource "google_monitoring_notification_channel" "budget_email" {
  for_each     = var.billing_account != "" ? toset(var.budget_alert_emails) : toset([])
  display_name = "Udhyath budget - ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

resource "google_billing_budget" "monthly" {
  count           = var.billing_account != "" ? 1 : 0
  billing_account = var.billing_account
  display_name    = "Udhyath monthly (${var.project_id})"

  budget_filter {
    projects        = ["projects/${local.project_number}"]
    calendar_period = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [for c in google_monitoring_notification_channel.budget_email : c.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.apis]
}
