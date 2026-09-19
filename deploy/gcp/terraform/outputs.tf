output "service_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "public_url" {
  value = local.public_url
}

output "cron_audience" {
  description = "Must equal the actual service URL (compare with service_url)."
  value       = local.run_url
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}/api"
}

output "runtime_service_account" {
  description = "Invite this in Play Console (Users and permissions) for purchase verification."
  value       = google_service_account.run.email
}

output "build_service_account" {
  value = google_service_account.build.email
}

output "build_staging_bucket" {
  value = google_storage_bucket.build_staging.name
}

output "files_bucket" {
  value = google_storage_bucket.files.name
}

output "lb_ip" {
  description = "A record for var.domain (when a custom domain is configured)."
  value       = var.domain != "" ? google_compute_global_address.lb[0].address : null
}
