# ---------- Runtime service account (Cloud Run) ----------

resource "google_service_account" "run" {
  account_id   = "udhyath-run"
  display_name = "Udhyath API runtime"
}

locals {
  run_project_roles = [
    "roles/datastore.user",                    # Firestore read/write
    "roles/firebasecloudmessaging.admin",      # FCM send (no narrower predefined role)
    "roles/firebaseauth.admin",                # revoke/delete users on account erasure
    "roles/speech.client",                     # Cloud Speech-to-Text
    "roles/serviceusage.serviceUsageConsumer", # quota project for Speech/TTS calls
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ]
}

resource "google_project_iam_member" "run" {
  for_each = toset(local.run_project_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.run.email}"
}

# Signed GCS URLs on Cloud Run use IAM signBlob as the runtime SA itself.
resource "google_service_account_iam_member" "run_self_sign" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.run.email}"
}

# ---------- Cloud Scheduler caller ----------

resource "google_service_account" "scheduler" {
  account_id   = "udhyath-scheduler"
  display_name = "Udhyath Cloud Scheduler (OIDC caller for /internal/cron)"
}

# The Cloud Scheduler service agent mints OIDC tokens as the scheduler SA.
resource "google_service_account_iam_member" "scheduler_agent" {
  service_account_id = google_service_account.scheduler.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${local.project_number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
  depends_on         = [google_project_service.apis]
}

# ---------- Cloud Build deployer ----------

resource "google_service_account" "build" {
  account_id   = "udhyath-build"
  display_name = "Udhyath Cloud Build deployer"
}

resource "google_project_iam_member" "build" {
  for_each = toset([
    "roles/run.developer",
    "roles/logging.logWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.build.email}"
}

# Deploying a revision that runs as udhyath-run requires actAs on it.
resource "google_service_account_iam_member" "build_act_as_run" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.build.email}"
}

resource "google_artifact_registry_repository_iam_member" "build_push" {
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "build_staging" {
  bucket = google_storage_bucket.build_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.build.email}"
}
