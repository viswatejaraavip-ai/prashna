# Secret Manager secrets, exposed to Cloud Run as env vars.
# JWT_SECRET is generated here; ANTHROPIC_API_KEY and GEMINI_API_KEY come
# from tfvars; Razorpay and extra secrets are created only
# when a value is supplied (Cloud Run refuses to start with a secret that has
# no version). You can instead add versions by hand and pass a placeholder:
#   echo -n "value" | gcloud secrets versions add NAME --data-file=-

resource "random_password" "jwt" {
  length  = 64
  special = false
}

locals {
  secret_values = merge(
    {
      JWT_SECRET        = random_password.jwt.result
      ANTHROPIC_API_KEY = var.anthropic_api_key
      GEMINI_API_KEY    = var.gemini_api_key
    },
    var.razorpay_key_id != "" ? { RAZORPAY_KEY_ID = var.razorpay_key_id } : {},
    var.razorpay_key_secret != "" ? { RAZORPAY_KEY_SECRET = var.razorpay_key_secret } : {},
    var.razorpay_webhook_secret != "" ? { RAZORPAY_WEBHOOK_SECRET = var.razorpay_webhook_secret } : {},
    var.extra_secrets,
  )
  # Names are not sensitive; iterate over them so for_each keys stay plannable.
  secret_names = nonsensitive(toset(concat(
    ["JWT_SECRET", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"],
    var.razorpay_key_id != "" ? ["RAZORPAY_KEY_ID"] : [],
    var.razorpay_key_secret != "" ? ["RAZORPAY_KEY_SECRET"] : [],
    var.razorpay_webhook_secret != "" ? ["RAZORPAY_WEBHOOK_SECRET"] : [],
    keys(var.extra_secrets),
  )))
}

resource "google_secret_manager_secret" "app" {
  for_each  = local.secret_names
  secret_id = "udhyath-${lower(replace(each.value, "_", "-"))}"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "app" {
  for_each    = local.secret_names
  secret      = google_secret_manager_secret.app[each.value].id
  secret_data = local.secret_values[each.value]
}

resource "google_secret_manager_secret_iam_member" "run_access" {
  for_each  = local.secret_names
  secret_id = google_secret_manager_secret.app[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}
