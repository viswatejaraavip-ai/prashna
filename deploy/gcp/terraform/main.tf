# Udhyath on Google Cloud: Cloud Run + Firestore + GCS + Secret Manager +
# Cloud Scheduler + Artifact Registry (+ optional HTTPS load balancer and
# budget alert). See docs/launch/DEPLOY_GCP.md for the runbook.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10, < 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
  # State holds generated secrets: keep it in a private, versioned bucket.
  #   terraform init -backend-config="bucket=<project>-tfstate"
  backend "gcs" {
    prefix = "udhyath/gcp"
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.this.number
  # Deterministic Cloud Run URL, known before the service exists (used as the
  # Cloud Scheduler OIDC audience without a dependency cycle).
  run_url      = "https://${var.service_name}-${local.project_number}.${var.region}.run.app"
  public_url   = var.domain != "" ? "https://${var.domain}" : local.run_url
  bucket_name  = var.bucket_name != "" ? var.bucket_name : "${var.project_id}-udhyath-files"
  image        = var.image != "" ? var.image : "us-docker.pkg.dev/cloudrun/container/hello"
  cron_targets = { for k, v in var.cron_jobs : k => v }
}
