locals {
  services = concat([
    "androidpublisher.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "fcm.googleapis.com",
    "firebase.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "speech.googleapis.com",
    "storage.googleapis.com",
    "texttospeech.googleapis.com",
    ],
    var.domain != "" ? ["compute.googleapis.com"] : [],
    var.billing_account != "" ? ["billingbudgets.googleapis.com"] : [],
  )
}

resource "google_project_service" "apis" {
  for_each                   = toset(local.services)
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}
