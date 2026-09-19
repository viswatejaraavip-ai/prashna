# Optional custom domain via a global external Application Load Balancer
# (Cloud Run domain mappings are not available in asia-south1). Point an A
# record for var.domain at output.lb_ip; the managed certificate provisions
# once DNS resolves (15-60 min).

resource "google_compute_region_network_endpoint_group" "run" {
  count                 = var.domain != "" ? 1 : 0
  name                  = "${var.service_name}-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_backend_service" "run" {
  count                 = var.domain != "" ? 1 : 0
  name                  = "${var.service_name}-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  backend {
    group = google_compute_region_network_endpoint_group.run[0].id
  }
}

resource "google_compute_url_map" "https" {
  count           = var.domain != "" ? 1 : 0
  name            = "${var.service_name}-https"
  default_service = google_compute_backend_service.run[0].id
}

resource "google_compute_managed_ssl_certificate" "cert" {
  count = var.domain != "" ? 1 : 0
  name  = "${var.service_name}-cert"
  managed {
    domains = [var.domain]
  }
}

resource "google_compute_target_https_proxy" "https" {
  count            = var.domain != "" ? 1 : 0
  name             = "${var.service_name}-https"
  url_map          = google_compute_url_map.https[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.cert[0].id]
}

resource "google_compute_global_address" "lb" {
  count = var.domain != "" ? 1 : 0
  name  = "${var.service_name}-ip"
}

resource "google_compute_global_forwarding_rule" "https" {
  count                 = var.domain != "" ? 1 : 0
  name                  = "${var.service_name}-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_https_proxy.https[0].id
  ip_address            = google_compute_global_address.lb[0].address
  port_range            = "443"
}

# http:// -> https:// redirect
resource "google_compute_url_map" "redirect" {
  count = var.domain != "" ? 1 : 0
  name  = "${var.service_name}-redirect"
  default_url_redirect {
    https_redirect         = true
    strip_query            = false
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  count   = var.domain != "" ? 1 : 0
  name    = "${var.service_name}-redirect"
  url_map = google_compute_url_map.redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count                 = var.domain != "" ? 1 : 0
  name                  = "${var.service_name}-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_http_proxy.redirect[0].id
  ip_address            = google_compute_global_address.lb[0].address
  port_range            = "80"
}
