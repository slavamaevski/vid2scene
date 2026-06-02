#!/usr/bin/env python3
"""Upload LOD octree files to Azure Blob Storage.

Usage:
    python upload_lod_to_azure.py <source_dir> <scene_id> [--container <name>] [--connection-string <conn_str>]

Examples:
    # Local dev (Azurite) — uses default Azurite connection string
    python upload_lod_to_azure.py \
        ../vid2scene_core/test_assets/Tondabayashi_Koh/playcanvas_lod/output \
        tondabayashi

    # Production — pass your real connection string
    python upload_lod_to_azure.py \
        /path/to/lod/output \
        my-scene-id \
        --connection-string "DefaultEndpointsProtocol=https;AccountName=..."

After uploading, set lod_file in Django admin to:
    lod_files/<scene_id>/lod-meta.json
"""

import argparse
import os
import sys
from azure.storage.blob import BlobServiceClient

# Azurite default connection string
AZURITE_CONN_STR = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)


def upload_lod(source_dir: str, scene_id: str, container: str, connection_string: str):
    if not os.path.isdir(source_dir):
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    meta_path = os.path.join(source_dir, "lod-meta.json")
    if not os.path.isfile(meta_path):
        print(f"Error: lod-meta.json not found in {source_dir}")
        sys.exit(1)

    client = BlobServiceClient.from_connection_string(connection_string)
    prefix = f"lod_files/{scene_id}"

    # Count files first
    file_count = sum(
        1 for root, _, files in os.walk(source_dir)
        for f in files if not f.endswith(":Zone.Identifier")
    )
    print(f"Uploading {file_count} files to {container}/{prefix}/")

    uploaded = 0
    for root, dirs, files in os.walk(source_dir):
        for filename in files:
            if filename.endswith(":Zone.Identifier"):
                continue
            local_path = os.path.join(root, filename)
            relative_path = os.path.relpath(local_path, source_dir)
            blob_path = f"{prefix}/{relative_path}"

            blob_client = client.get_blob_client(container, blob_path)
            with open(local_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)

            uploaded += 1
            print(f"  [{uploaded}/{file_count}] {relative_path}")

    print(f"\nDone! Uploaded {uploaded} files.")
    print(f"\nSet lod_file in Django admin to:\n  {prefix}/lod-meta.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload LOD files to Azure Blob Storage")
    parser.add_argument("source_dir", help="Path to LOD output directory (containing lod-meta.json)")
    parser.add_argument("scene_id", help="Scene identifier (used as subdirectory under lod_files/)")
    parser.add_argument("--container", default="media", help="Azure container name (default: media)")
    parser.add_argument("--connection-string", default=AZURITE_CONN_STR,
                        help="Azure connection string (default: Azurite local)")
    args = parser.parse_args()

    upload_lod(args.source_dir, args.scene_id, args.container, args.connection_string)
