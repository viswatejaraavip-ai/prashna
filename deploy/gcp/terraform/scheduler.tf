# Daily jobs -> POST /internal/cron/<name> with a Google-signed OIDC token
# (audience = service URL, email = udhyath-scheduler). Verified in code by
# platform_cron.verify_cron.
resource "google_cloud_scheduler_job" "cron" {
  for_each         = local.cron_targets
  name             = "udhyath-${each.key}"
  region           = var.scheduler_region
  schedule         = each.value.schedule
  time_zone        = "Asia/Kolkata"
  attempt_deadline = "${var.request_timeout_seconds}s"

  retry_config {
    retry_count          = each.value.retries
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
  }

  http_target {
    http_method = "POST"
    uri         = "${local.run_url}/internal/cron/${each.key}"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.run_url
    }
  }

  depends_on = [
    google_project_service.apis,
    google_service_account_iam_member.scheduler_agent,
    google_cloud_run_v2_service.api,
  ]
}
