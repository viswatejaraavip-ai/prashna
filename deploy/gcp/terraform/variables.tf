variable "project_id" {
  description = "GCP project id (Firebase must be enabled on the same project)."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, GCS and Scheduler."
  type        = string
  default     = "asia-south1"
}

variable "firestore_location" {
  description = "Firestore location (fixed forever once created)."
  type        = string
  default     = "asia-south1"
}

variable "service_name" {
  type    = string
  default = "udhyath-api"
}

variable "image" {
  description = "Initial container image. Leave empty for a placeholder; Cloud Build deploys the real image and terraform ignores later image changes."
  type        = string
  default     = ""
}

variable "min_instances" {
  description = "0 = scale to zero (cheapest, ~2-4 s cold start); 1 = always warm."
  type        = number
  default     = 0
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "concurrency" {
  description = "Requests per instance. Most time is spent waiting on the model APIs, so a moderate value is fine; engine math is CPU-bound, so don't go very high."
  type        = number
  default     = 20
}

variable "cpu" {
  type    = string
  default = "2"
}

variable "memory" {
  type    = string
  default = "2Gi"
}

variable "cpu_always_allocated" {
  description = "Keep CPU allocated outside requests (instance-based billing). Needed when report chapters are generated in background threads after the HTTP response."
  type        = bool
  default     = true
}

variable "request_timeout_seconds" {
  description = "Cloud Run request timeout (report generation, cron jobs)."
  type        = number
  default     = 600
}

variable "bucket_name" {
  description = "GCS bucket for PDFs/share cards. Default: <project>-udhyath-files."
  type        = string
  default     = ""
}

variable "admin_emails" {
  description = "Operator dashboard Google accounts (comma-separated)."
  type        = string
}

variable "play_package_name" {
  type    = string
  default = "com.prashna.app"
}

variable "default_lang" {
  type    = string
  default = "te"
}

variable "firebase_web_api_key" {
  description = "Firebase Web API key (public) for the operator dashboard sign-in."
  type        = string
  default     = ""
}

variable "firebase_web_app_id" {
  type    = string
  default = ""
}

variable "app_env" {
  description = "Non-secret env vars for the service (pricing, models, legal contact...). Merged over the defaults in run.tf."
  type        = map(string)
  default     = {}
}

variable "razorpay_key_id" {
  type      = string
  default   = ""
  sensitive = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key (Claude Opus 4.5 for the reasoning stage). Stored in Secret Manager."
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Gemini API key, paid tier (Gemini Flash for planning/execution). Stored in Secret Manager."
  type        = string
  sensitive   = true
}

variable "razorpay_key_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "razorpay_webhook_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "extra_secrets" {
  description = "Additional secret env vars, e.g. { ALERT_WEBHOOK_URL = \"https://...\" }."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "cron_jobs" {
  description = "Cloud Scheduler jobs -> POST <service>/internal/cron/<name> (IST schedules)."
  type = map(object({
    schedule = string
    retries  = number
  }))
  default = {
    "daily-push"     = { schedule = "30 6 * * *", retries = 0 }
    "transit-alerts" = { schedule = "0 8 * * *", retries = 1 }
    "purge-deleted"  = { schedule = "30 3 * * *", retries = 2 }
  }
}

variable "scheduler_region" {
  description = "Cloud Scheduler location (must support App Engine-less scheduler; asia-south1 does)."
  type        = string
  default     = "asia-south1"
}

variable "domain" {
  description = "Optional custom domain (e.g. api.udhyath.com). Creates a global HTTPS load balancer with a Google-managed certificate (~US$18/month). Leave empty to use the run.app URL."
  type        = string
  default     = ""
}

variable "billing_account" {
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX) for the budget alert; empty = no budget."
  type        = string
  default     = ""
}

variable "budget_amount" {
  description = "Monthly budget in the billing account's currency."
  type        = number
  default     = 10000
}

variable "budget_currency" {
  type    = string
  default = "INR"
}

variable "budget_alert_emails" {
  type    = list(string)
  default = []
}

variable "deletion_protection" {
  type    = bool
  default = true
}
