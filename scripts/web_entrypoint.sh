#!/bin/sh
# Entrypoint for the vid2scene web container: prepare the app, then serve it.
set -e

cd /app/vid2scene_server

echo "[entrypoint] Applying database migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Ensuring Azurite blob containers + CORS rules..."
python - <<'PY'
import os
import time
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vid2scene_server.settings")
django.setup()
from django.conf import settings
from azure.storage.blob import BlobServiceClient, CorsRule

aliases = ("default", "thumbnails")
# sorl-thumbnail renders the examples-page thumbnails into the "thumbnails"
# container and embeds the storage's plain .url() (no SAS token, since no URL
# expiration is configured). Anonymous browser reads only succeed if that
# container allows public blob access, so create/keep it public-read. The
# "default" (media) container stays private — the app always hands out SAS URLs
# for it.
public_access = {"thumbnails": "blob"}
# Azurite (and Azure Storage) reject browser preflight requests with 403 unless
# CORS rules are configured on the blob service. The browser uploads videos and
# downloads SOG/LOD blobs direct-to-storage via SAS URLs, so we need permissive
# rules here. The account is only reachable on localhost in the self-host stack.
cors_rules = [CorsRule(
    allowed_origins=['*'],
    allowed_methods=['GET', 'HEAD', 'PUT', 'POST', 'OPTIONS', 'DELETE'],
    allowed_headers=['*'],
    exposed_headers=['*'],
    max_age_in_seconds=3600,
)]

for attempt in range(30):
    try:
        for alias in aliases:
            opts = settings.STORAGES[alias]["OPTIONS"]
            container = opts["azure_container"]
            access = public_access.get(alias)
            client = BlobServiceClient.from_connection_string(opts["connection_string"])
            try:
                client.create_container(container, public_access=access)
                print(f"[entrypoint]   created container '{container}' (public_access={access})")
            except Exception:
                # Already exists — make sure its public-access level is correct
                # (e.g. created private by an older entrypoint).
                if access:
                    try:
                        client.get_container_client(container).set_container_access_policy(
                            signed_identifiers={}, public_access=access
                        )
                        print(f"[entrypoint]   set container '{container}' public_access={access}")
                    except Exception as exc:
                        print(f"[entrypoint]   could not set access on '{container}': {exc}")
        # CORS is account-wide; once is enough.
        opts = settings.STORAGES["default"]["OPTIONS"]
        client = BlobServiceClient.from_connection_string(opts["connection_string"])
        client.set_service_properties(cors=cors_rules)
        print("[entrypoint]   set blob-service CORS rules")

        # sorl-thumbnail tracks generated thumbnails in its key-value store, which
        # here is the Django cache (Redis DB 1). If blob storage (Azurite) is reset
        # without also clearing Redis, those references go stale and the examples
        # page serves 404s for thumbnails that no longer exist. `thumbnail clear`
        # does not reliably purge the cached_db store, so flush the cache DB
        # outright — everything in it (thumbnail refs, the examples list) is cheap
        # to regenerate, and this makes the stack self-heal no matter which volume
        # was wiped.
        from django.core.cache import cache
        cache.clear()
        print("[entrypoint]   flushed cache (resets stale sorl thumbnail refs)")
        break
    except Exception as exc:
        print(f"[entrypoint]   waiting for storage ({attempt + 1}/30): {exc}")
        time.sleep(2)
PY

echo "[entrypoint] Seeding example scenes (first run only)..."
python manage.py seed_examples || echo "[entrypoint]   seed_examples failed (non-fatal); continuing"

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[entrypoint] Ensuring superuser '$DJANGO_SUPERUSER_USERNAME' exists..."
    python manage.py createsuperuser --noinput 2>/dev/null || true
fi

echo "[entrypoint] Starting gunicorn..."
exec gunicorn vid2scene_server.wsgi:application \
    --bind "${GUNICORN_BIND:-0.0.0.0:8000}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 120
