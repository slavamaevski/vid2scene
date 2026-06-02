"""Seed the examples page with the bundled example scenes.

Reads ``examples_data/manifest.json`` and creates one ``SceneProcessingJob``
per entry, flagged as an example, with its SPZ splat, preview image and camera
data uploaded into the configured storage backend.

The command is idempotent: a scene whose ID already exists is skipped, so it is
safe to run on every container startup (it only does work the first time, or for
any newly added examples).
"""

import json
import os

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from video_processor.models import SceneProcessingJob

# examples_data lives next to manage.py (BASE_DIR), one level up from this app.
EXAMPLES_DATA_DIR = os.path.join(settings.BASE_DIR, "examples_data")
MANIFEST_PATH = os.path.join(EXAMPLES_DATA_DIR, "manifest.json")
STUB_VIDEO_PATH = os.path.join(EXAMPLES_DATA_DIR, "video.mp4")


class Command(BaseCommand):
    help = "Pre-populate the examples page from examples_data/manifest.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-create example scenes even if they already exist.",
        )

    def handle(self, *args, **options):
        if not os.path.exists(MANIFEST_PATH):
            self.stdout.write(
                self.style.WARNING(
                    f"No manifest at {MANIFEST_PATH}; nothing to seed."
                )
            )
            return

        with open(MANIFEST_PATH) as fh:
            manifest = json.load(fh)

        force = options["force"]
        created = skipped = failed = 0

        for entry in manifest:
            job_id = entry["id"]
            title = entry.get("title") or "Untitled"

            exists = SceneProcessingJob.objects.filter(id=job_id).exists()
            if exists and not force:
                skipped += 1
                continue

            try:
                self._seed_one(entry, replace=exists)
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  seeded {title!r} ({job_id})"))
            except Exception as exc:  # keep going; one bad scene shouldn't abort seeding
                failed += 1
                self.stderr.write(f"  ! failed to seed {title!r} ({job_id}): {exc}")

        self.stdout.write(
            f"Examples: {created} seeded, {skipped} already present, {failed} failed."
        )

    def _seed_one(self, entry, replace):
        job_id = entry["id"]
        job_dir = os.path.join(EXAMPLES_DATA_DIR, job_id)

        if replace:
            SceneProcessingJob.objects.filter(id=job_id).delete()

        spj = SceneProcessingJob(
            id=job_id,
            title=entry.get("title") or "Untitled",
            camera_data=entry.get("camera_data"),
            example=True,
            example_sort_order=entry.get("sort_order", 0),
            public=True,
            allow_as_example=True,
        )

        # Every job requires a video_file; reuse the shared stub.
        with open(STUB_VIDEO_PATH, "rb") as fh:
            spj.video_file.save(f"{job_id}.mp4", File(fh), save=False)

        # Splat: the manifest currently always ships SPZ.
        splat_file = entry.get("splat_file")
        splat_type = entry.get("splat_type", "spz")
        if splat_file:
            splat_path = os.path.join(job_dir, splat_file)
            field = getattr(spj, f"{splat_type}_file")
            with open(splat_path, "rb") as fh:
                field.save(f"{job_id}.{splat_type}", File(fh), save=False)

        # Preview image.
        preview_file = entry.get("preview_file")
        if preview_file:
            preview_path = os.path.join(job_dir, preview_file)
            ext = os.path.splitext(preview_file)[1] or ".jpg"
            with open(preview_path, "rb") as fh:
                spj.preview_image.save(f"{job_id}{ext}", File(fh), save=False)

        spj.save()
