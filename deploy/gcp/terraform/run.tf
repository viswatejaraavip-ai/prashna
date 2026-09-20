locals {
  run_env = merge(
    {
      GOOGLE_CLOUD_PROJECT     = var.project_id
      FIREBASE_PROJECT_ID      = var.project_id
      FIREBASE_AUTH_DOMAIN     = "${var.project_id}.firebaseapp.com"
      FIREBASE_WEB_API_KEY     = var.firebase_web_api_key
      FIREBASE_WEB_APP_ID      = var.firebase_web_app_id
      GCS_BUCKET               = google_storage_bucket.files.name
      ADMIN_EMAILS             = var.admin_emails
      DEFAULT_LANG             = var.default_lang
      PLAY_PACKAGE_NAME        = var.play_package_name
      PUBLIC_BASE_URL          = local.public_url
      CRON_AUDIENCES           = join(",", compact([local.run_url, var.domain != "" ? "https://${var.domain}" : ""]))
      CRON_SA_EMAIL            = google_service_account.scheduler.email
      GEMINI_MODEL             = "gemini-3.5-flash-lite"
      CLAUDE_MODEL             = "claude-opus-4-5"
      QUERY_PRICE_UNITS        = "1000"
      QUERY_COST_CEILING_UNITS = "500"
      USD_TO_INR               = "90"
      # Prime Firestore, the Firebase signing certs, the places dataset, the
      # i18n templates and the ephemeris in a background thread as soon as the
      # container starts, instead of inside somebody's first request.
      WARMUP_ON_START = "1"
      # firebase-admin's revocation check costs an extra Identity Toolkit round
      # trip on every sign-in (~250-350 ms) and buys almost nothing here; see
      # platform_auth.CHECK_REVOKED. Set to "1" to turn it back on.
      AUTH_CHECK_REVOKED = "0"
      TRIAL_CREDIT_UNITS       = "1000"
      PRO_PLAN_UNITS           = "49900"
      PRO_PLAN_DAYS            = "30"
    },
    var.app_env,
  )
}

resource "google_cloud_run_v2_service" "api" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.deletion_protection

  template {
    service_account                  = google_service_account.run.email
    timeout                          = "${var.request_timeout_seconds}s"
    max_instance_request_concurrency = var.concurrency
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle = !var.cpu_always_allocated
        # Full CPU during container start, so the Python imports and the
        # warm-up thread finish before the first request lands.
        startup_cpu_boost = true
      }
      # No custom startup_probe on purpose: the default TCP probe passes the
      # moment uvicorn binds, which is already after the app has imported, and
      # an HTTP probe would only add its poll interval to every cold start.
      # The readiness that matters (Firestore, Firebase certs, ephemeris) is
      # handled by the WARMUP_ON_START thread, which overlaps with traffic.

      dynamic "env" {
        for_each = local.run_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_names
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    # Cloud Build rolls out new images; don't roll them back on apply.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.app,
    google_secret_manager_secret_iam_member.run_access,
    google_project_iam_member.run,
  ]
}

# Public API: the app authenticates requests itself (Firebase -> app JWT;
# /internal/cron/* verifies Cloud Scheduler OIDC tokens in code).
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}
