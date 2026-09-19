"""Cloud Storage helper (report PDFs, share cards, matching PDFs).

    upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str
        Upload to bucket GCS_BUCKET; returns "gs://<bucket>/<path>".
    signed_url(path: str, minutes: int = 60) -> str
        V4 signed GET URL. ``path`` may be "gs://bucket/obj" or a bare object path.
    delete_prefix(prefix: str) -> int

Path convention (per-user prefixes; the account purge job deletes
``{prefix}/{uid}/`` for every prefix in USER_PREFIXES, and bucket lifecycle
rules expire the regenerable ones):
    reports/{uid}/{report_id}.pdf    kept (Nearline after 90 days)
    matching/{uid}/{id}.pdf          deleted after 7 days
    share/{uid}/{id}.png             deleted after 30 days
    users/{uid}/...                  anything else per-user
    tmp/...                          deleted after 1 day

On Cloud Run the runtime credentials have no private key, so URLs are signed
through the IAM signBlob API; the runtime service account needs
roles/iam.serviceAccountTokenCreator on itself (granted by terraform).
"""

import os
from datetime import timedelta
from typing import Tuple

GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
USER_PREFIXES = ("reports", "matching", "share", "users")

_client = None


def _gcs():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    return _client


def _split(path: str) -> Tuple[str, str]:
    if path.startswith("gs://"):
        bucket, _, name = path[5:].partition("/")
        return bucket, name
    if not GCS_BUCKET:
        raise RuntimeError("GCS_BUCKET is not set")
    return GCS_BUCKET, path.lstrip("/")


def upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    bucket, name = _split(path)
    blob = _gcs().bucket(bucket).blob(name)
    blob.upload_from_string(data, content_type=content_type)
    return "gs://%s/%s" % (bucket, name)


def signed_url(path: str, minutes: int = 60) -> str:
    bucket, name = _split(path)
    blob = _gcs().bucket(bucket).blob(name)
    kwargs = {"version": "v4", "expiration": timedelta(minutes=minutes), "method": "GET"}
    import google.auth
    from google.auth.transport import requests as g_requests
    creds, _ = google.auth.default()
    if not hasattr(creds, "sign_bytes") or not getattr(creds, "signer_email", None):
        # Cloud Run metadata credentials (or local gcloud user creds): sign via
        # IAM signBlob. Locally set SIGNING_SERVICE_ACCOUNT to the runtime SA
        # and hold roles/iam.serviceAccountTokenCreator on it.
        creds.refresh(g_requests.Request())
        email = (os.environ.get("SIGNING_SERVICE_ACCOUNT")
                 or getattr(creds, "service_account_email", None))
        if not email or email == "default":
            raise RuntimeError("Cannot sign GCS URLs: set SIGNING_SERVICE_ACCOUNT")
        kwargs.update(service_account_email=email, access_token=creds.token)
    return blob.generate_signed_url(**kwargs)


def delete_prefix(prefix: str) -> int:
    bucket, name = _split(prefix)
    n = 0
    for blob in _gcs().bucket(bucket).list_blobs(prefix=name):
        blob.delete()
        n += 1
    return n
