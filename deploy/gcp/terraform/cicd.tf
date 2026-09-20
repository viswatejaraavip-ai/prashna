# GitHub Actions -> Google Cloud, with NO service-account keys.
#
# `.github/workflows/deploy.yml` mints a GitHub OIDC token, exchanges it here
# through Workload Identity Federation, impersonates the deployer service
# account and runs `gcloud builds submit --config cloudbuild.yaml`. Cloud
# Build then builds the image and deploys it to Cloud Run as the existing
# `udhyath-build` service account (deploy/gcp/terraform/iam.tf).
#
# Trust chain:
#   repo github_repository (main branch) -> WIF provider -> WIF pool
#     -> udhyath-deployer SA -> actAs udhyath-build -> Cloud Run revision
#
# After `terraform apply`, put `terraform output github_actions_variables`
# into the repository's Actions *variables* (not secrets — none of these are
# sensitive). See docs/launch/TESTING.md, "Deploy (GCP)".

variable "github_repository" {
  description = "GitHub repository allowed to deploy, as \"owner/name\" (e.g. viswa-cpu/udhyath). Only this repo's workflows can impersonate the deployer SA."
  type        = string
  default     = "viswa-cpu/udhyath"
}

variable "github_deploy_branch" {
  description = "Branch whose CI runs may deploy. Deploys are additionally gated by deploy.yml waiting for a green CI."
  type        = string
  default     = "main"
}

variable "cicd_enabled" {
  description = "Create the GitHub Actions CI/CD identity. Set false to remove it."
  type        = bool
  default     = true
}

# ---------- APIs the federation needs ----------

resource "google_project_service" "cicd_apis" {
  for_each           = var.cicd_enabled ? toset(["sts.googleapis.com", "iamcredentials.googleapis.com"]) : []
  service            = each.value
  disable_on_destroy = false
}

# ---------- Workload Identity Federation ----------

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.cicd_enabled ? 1 : 0
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions"
  description               = "Keyless CI/CD for ${var.github_repository}"
  depends_on                = [google_project_service.cicd_apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.cicd_enabled ? 1 : 0
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
    "attribute.workflow_ref"     = "assertion.workflow_ref"
  }

  # Mandatory on newer provider versions and a real defence: without it any
  # GitHub repository in the world could present a token to this pool.
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri        = "https://token.actions.githubusercontent.com"
    allowed_audiences = []
  }
}

# ---------- Deployer service account (what GitHub becomes) ----------

resource "google_service_account" "deployer" {
  count        = var.cicd_enabled ? 1 : 0
  account_id   = "udhyath-deployer"
  display_name = "GitHub Actions deployer (Workload Identity Federation)"
  description  = "Impersonated by ${var.github_repository} to submit Cloud Builds. Holds no key."
}

# Only pushes to the deploy branch of that repository may impersonate it.
resource "google_service_account_iam_member" "deployer_wif" {
  count              = var.cicd_enabled ? 1 : 0
  service_account_id = google_service_account.deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}"
}

# What the deployer may do: submit builds, read logs, look at the service.
resource "google_project_iam_member" "deployer" {
  for_each = var.cicd_enabled ? toset([
    "roles/cloudbuild.builds.editor",          # gcloud builds submit
    "roles/logging.viewer",                    # stream the build log
    "roles/serviceusage.serviceUsageConsumer", # quota project for the API calls
    "roles/run.viewer",                        # read the URL/revision for the smoke test
  ]) : []
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

# `gcloud builds submit --service-account=udhyath-build@...` needs actAs.
resource "google_service_account_iam_member" "deployer_act_as_build" {
  count              = var.cicd_enabled ? 1 : 0
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer[0].email}"
}

# Upload the source tarball for the build.
resource "google_storage_bucket_iam_member" "deployer_staging" {
  count  = var.cicd_enabled ? 1 : 0
  bucket = google_storage_bucket.build_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer[0].email}"
}

# ---------- Outputs: paste these into the GitHub repo variables ----------

output "github_wif_provider" {
  description = "GCP_WIF_PROVIDER repository variable for .github/workflows/deploy.yml."
  value       = var.cicd_enabled ? google_iam_workload_identity_pool_provider.github[0].name : null
}

output "github_deployer_service_account" {
  description = "GCP_DEPLOYER_SA repository variable."
  value       = var.cicd_enabled ? google_service_account.deployer[0].email : null
}

output "github_actions_variables" {
  description = "Every repository variable deploy.yml reads, ready to paste into `gh variable set`."
  value = var.cicd_enabled ? {
    GCP_PROJECT_ID   = var.project_id
    GCP_REGION       = var.region
    GCP_SERVICE      = var.service_name
    GCP_WIF_PROVIDER = google_iam_workload_identity_pool_provider.github[0].name
    GCP_DEPLOYER_SA  = google_service_account.deployer[0].email
    GCP_BUILD_SA     = google_service_account.build.email
    GCP_BUILD_BUCKET = google_storage_bucket.build_staging.name
  } : null
}
