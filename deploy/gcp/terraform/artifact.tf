resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "udhyath"
  format        = "DOCKER"
  description   = "Udhyath API images"

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.apis]
}
