# User files: report PDFs, matching PDFs, share cards. Private; the API hands
# out short-lived V4 signed URLs.
resource "google_storage_bucket" "files" {
  name                        = local.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.deletion_protection

  # Regenerable files expire: share cards 30 days, matching PDFs 7, temp 1.
  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["share/"]
    }
    action {
      type = "Delete"
    }
  }
  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["matching/"]
    }
    action {
      type = "Delete"
    }
  }
  lifecycle_rule {
    condition {
      age            = 1
      matches_prefix = ["tmp/"]
    }
    action {
      type = "Delete"
    }
  }
  # Old report PDFs are rarely re-downloaded: Nearline after 90 days.
  lifecycle_rule {
    condition {
      age                   = 90
      matches_prefix        = ["reports/"]
      matches_storage_class = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
  # Clean up abandoned resumable uploads.
  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "AbortIncompleteMultipartUpload"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "run_files" {
  bucket = google_storage_bucket.files.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.run.email}"
}

# Source uploads for `gcloud builds submit --gcs-source-staging-dir`.
resource "google_storage_bucket" "build_staging" {
  name                        = "${var.project_id}-udhyath-build"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 14
    }
    action {
      type = "Delete"
    }
  }
}
