#!/usr/bin/env python3
"""
Script to reduce the number of 3D points in a COLMAP SfM reconstruction.

Usage:
    python reduce_colmap_points.py <input_dir> <output_dir> --num_points <N>
    or
    python reduce_colmap_points.py <input_dir> <output_dir> --percentage <P>
"""

import argparse
import shutil
import struct
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional
import sys


class Camera:
    def __init__(self, id, model, width, height, params):
        self.id = id
        self.model = model
        self.width = width
        self.height = height
        self.params = params


class Image:
    def __init__(self, id, qvec, tvec, camera_id, name, xys, point3D_ids):
        self.id = id
        self.qvec = qvec
        self.tvec = tvec
        self.camera_id = camera_id
        self.name = name
        self.xys = xys
        self.point3D_ids = point3D_ids


class Point3D:
    def __init__(self, id, xyz, rgb, error, image_ids, point2D_idxs):
        self.id = id
        self.xyz = xyz
        self.rgb = rgb
        self.error = error
        self.image_ids = image_ids
        self.point2D_idxs = point2D_idxs


def read_next_bytes(fid, num_bytes, format_char_sequence, endian_character="<"):
    """Read and unpack the next bytes from a binary file."""
    data = fid.read(num_bytes)
    return struct.unpack(endian_character + format_char_sequence, data)


def read_cameras_binary(path_to_model_file):
    """Read cameras from binary file."""
    cameras = {}
    with open(path_to_model_file, "rb") as fid:
        num_cameras = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_cameras):
            camera_properties = read_next_bytes(fid, 24, "iiQQ")
            camera_id = camera_properties[0]
            model_id = camera_properties[1]
            width = camera_properties[2]
            height = camera_properties[3]
            num_params = (model_id == 0 and 3) or (model_id in [1, 2] and 4) or \
                        (model_id in [3, 4, 5] and 5) or (model_id in [6, 7] and 8) or \
                        (model_id in [8, 9] and 10) or 12
            params = read_next_bytes(fid, 8 * num_params, "d" * num_params)
            cameras[camera_id] = Camera(camera_id, model_id, width, height, np.array(params))
    return cameras


def read_images_binary(path_to_model_file):
    """Read images from binary file."""
    images = {}
    with open(path_to_model_file, "rb") as fid:
        num_reg_images = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_reg_images):
            binary_image_properties = read_next_bytes(fid, 64, "idddddddi")
            image_id = binary_image_properties[0]
            qvec = np.array(binary_image_properties[1:5])
            tvec = np.array(binary_image_properties[5:8])
            camera_id = binary_image_properties[8]
            image_name = ""
            current_char = read_next_bytes(fid, 1, "c")[0]
            while current_char != b"\x00":
                image_name += current_char.decode("utf-8")
                current_char = read_next_bytes(fid, 1, "c")[0]
            num_points2D = read_next_bytes(fid, 8, "Q")[0]
            x_y_id_s = read_next_bytes(fid, 24 * num_points2D, "ddq" * num_points2D)
            xys = np.column_stack([tuple(map(float, x_y_id_s[0::3])),
                                   tuple(map(float, x_y_id_s[1::3]))])
            point3D_ids = np.array(tuple(map(int, x_y_id_s[2::3])))
            images[image_id] = Image(image_id, qvec, tvec, camera_id, image_name, xys, point3D_ids)
    return images


def read_points3D_binary(path_to_model_file):
    """Read 3D points from binary file."""
    points3D = {}
    with open(path_to_model_file, "rb") as fid:
        num_points = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_points):
            binary_point_line_properties = read_next_bytes(fid, 43, "QdddBBBd")
            point3D_id = binary_point_line_properties[0]
            xyz = np.array(binary_point_line_properties[1:4])
            rgb = np.array(binary_point_line_properties[4:7])
            error = binary_point_line_properties[7]
            track_length = read_next_bytes(fid, 8, "Q")[0]
            track_elems = read_next_bytes(fid, 8 * track_length, "ii" * track_length)
            image_ids = np.array(tuple(map(int, track_elems[0::2])))
            point2D_idxs = np.array(tuple(map(int, track_elems[1::2])))
            points3D[point3D_id] = Point3D(point3D_id, xyz, rgb, error, image_ids, point2D_idxs)
    return points3D


def write_cameras_binary(cameras, path_to_model_file):
    """Write cameras to binary file."""
    with open(path_to_model_file, "wb") as fid:
        fid.write(struct.pack("<Q", len(cameras)))
        for camera in cameras.values():
            fid.write(struct.pack("<iiQQ", camera.id, camera.model, camera.width, camera.height))
            fid.write(struct.pack("<" + "d" * len(camera.params), *camera.params))


def write_images_binary(images, path_to_model_file):
    """Write images to binary file."""
    with open(path_to_model_file, "wb") as fid:
        fid.write(struct.pack("<Q", len(images)))
        for img in images.values():
            fid.write(struct.pack("<i", img.id))
            fid.write(struct.pack("<dddd", *img.qvec))
            fid.write(struct.pack("<ddd", *img.tvec))
            fid.write(struct.pack("<i", img.camera_id))
            fid.write(img.name.encode("utf-8") + b"\x00")
            fid.write(struct.pack("<Q", len(img.point3D_ids)))
            for xy, point3D_id in zip(img.xys, img.point3D_ids):
                fid.write(struct.pack("<ddq", xy[0], xy[1], point3D_id))


def write_points3D_binary(points3D, path_to_model_file):
    """Write 3D points to binary file."""
    with open(path_to_model_file, "wb") as fid:
        fid.write(struct.pack("<Q", len(points3D)))
        for point in points3D.values():
            fid.write(struct.pack("<Q", point.id))
            fid.write(struct.pack("<ddd", *point.xyz))
            fid.write(struct.pack("<BBB", *point.rgb))
            fid.write(struct.pack("<d", point.error))
            fid.write(struct.pack("<Q", len(point.image_ids)))
            for image_id, point2D_idx in zip(point.image_ids, point.point2D_idxs):
                fid.write(struct.pack("<ii", image_id, point2D_idx))


def compute_point_scores(points3D, method):
    """
    Compute importance scores for points based on various criteria.
    Higher scores = more likely to be kept.
    """
    point_ids = list(points3D.keys())
    scores = {}
    
    if method == "random":
        # Random uniform scores
        for pid in point_ids:
            scores[pid] = np.random.random()
    
    elif method == "low_error":
        # Inverse of reprojection error (lower error = higher score)
        errors = np.array([points3D[pid].error for pid in point_ids])
        max_error = np.max(errors) + 1e-6
        for pid in point_ids:
            scores[pid] = max_error - points3D[pid].error
    
    elif method == "track_length":
        # Track length (more observations = higher score)
        for pid in point_ids:
            scores[pid] = len(points3D[pid].image_ids)
    
    elif method == "combined":
        # Weighted combination of error and track length
        # Normalize both metrics to [0, 1] then combine
        errors = np.array([points3D[pid].error for pid in point_ids])
        track_lengths = np.array([len(points3D[pid].image_ids) for pid in point_ids])
        
        # Normalize error (lower is better, so invert)
        min_err, max_err = np.min(errors), np.max(errors)
        norm_errors = 1.0 - (errors - min_err) / (max_err - min_err + 1e-6)
        
        # Normalize track length (higher is better)
        min_track, max_track = np.min(track_lengths), np.max(track_lengths)
        norm_tracks = (track_lengths - min_track) / (max_track - min_track + 1e-6)
        
        # Combine: 70% error quality, 30% track length
        combined_scores = 0.7 * norm_errors + 0.3 * norm_tracks
        
        for i, pid in enumerate(point_ids):
            scores[pid] = combined_scores[i]
    
    elif method == "stratified":
        # Stratified sampling: divide points by quality tiers
        # This ensures we get a mix of high-quality and some lower-quality points
        errors = np.array([points3D[pid].error for pid in point_ids])
        track_lengths = np.array([len(points3D[pid].image_ids) for pid in point_ids])
        
        # Create quality score
        min_err, max_err = np.min(errors), np.max(errors)
        norm_errors = 1.0 - (errors - min_err) / (max_err - min_err + 1e-6)
        
        min_track, max_track = np.min(track_lengths), np.max(track_lengths)
        norm_tracks = (track_lengths - min_track) / (max_track - min_track + 1e-6)
        
        quality_scores = 0.7 * norm_errors + 0.3 * norm_tracks
        
        # Assign points to quality tiers
        # Then add random noise within each tier to create stratification
        percentiles = [0, 33, 66, 100]
        tier_boundaries = np.percentile(quality_scores, percentiles)
        
        for i, pid in enumerate(point_ids):
            base_score = quality_scores[i]
            # Find which tier this point belongs to
            tier = 0
            for j in range(len(tier_boundaries) - 1):
                if tier_boundaries[j] <= base_score <= tier_boundaries[j + 1]:
                    tier = j
                    break
            
            # Add tier offset + random noise within tier
            # Higher tiers get higher base scores, but all tiers have representation
            scores[pid] = tier * 10 + np.random.random()
    
    elif method == "spatial":
        # Spatial sampling using voxel grid
        # Points in less-dense regions get higher scores
        points_array = np.array([points3D[pid].xyz for pid in point_ids])
        
        # Create voxel grid
        mins = np.min(points_array, axis=0)
        maxs = np.max(points_array, axis=0)
        
        # Use adaptive number of voxels based on point density
        num_voxels = int(np.cbrt(len(point_ids) / 10))  # Roughly 10 points per voxel on average
        num_voxels = max(10, min(100, num_voxels))  # Clamp between 10 and 100
        
        voxel_size = (maxs - mins) / num_voxels
        
        # Count points per voxel
        voxel_counts = {}
        point_to_voxel = {}
        
        for pid in point_ids:
            xyz = points3D[pid].xyz
            voxel_idx = tuple(((xyz - mins) / (voxel_size + 1e-6)).astype(int))
            voxel_counts[voxel_idx] = voxel_counts.get(voxel_idx, 0) + 1
            point_to_voxel[pid] = voxel_idx
        
        # Assign scores: inversely proportional to voxel density
        # Also factor in point quality
        max_count = max(voxel_counts.values())
        
        errors = np.array([points3D[pid].error for pid in point_ids])
        min_err, max_err = np.min(errors), np.max(errors)
        
        for pid in point_ids:
            voxel_idx = point_to_voxel[pid]
            density_score = 1.0 - (voxel_counts[voxel_idx] / max_count)
            
            # Quality score based on error
            quality_score = 1.0 - (points3D[pid].error - min_err) / (max_err - min_err + 1e-6)
            
            # Combine: favor good points in sparse regions
            scores[pid] = 0.6 * density_score + 0.4 * quality_score
    
    else:
        raise ValueError(f"Unknown method: {method}")
    
    return scores


def reduce_points(points3D, images, target_num_points, method="combined"):
    """
    Reduce the number of 3D points using intelligent sampling.
    
    Args:
        points3D: Dictionary of Point3D objects
        images: Dictionary of Image objects
        target_num_points: Target number of points to keep
        method: Method to use for selection
    
    Returns:
        Reduced points3D dictionary and updated images dictionary
    """
    current_num_points = len(points3D)
    
    if target_num_points >= current_num_points:
        print(f"Target number of points ({target_num_points}) is >= current number ({current_num_points}). No reduction needed.")
        return points3D, images
    
    print(f"Reducing from {current_num_points} to {target_num_points} points using '{method}' method...")
    
    # Compute importance scores for all points
    scores = compute_point_scores(points3D, method)
    
    # Sort by score and keep top N
    sorted_points = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    keep_ids = set([pid for pid, _ in sorted_points[:target_num_points]])
    
    # Statistics
    kept_points = [points3D[pid] for pid in keep_ids]
    all_points = list(points3D.values())
    
    mean_error_kept = np.mean([p.error for p in kept_points])
    mean_error_all = np.mean([p.error for p in all_points])
    mean_track_kept = np.mean([len(p.image_ids) for p in kept_points])
    mean_track_all = np.mean([len(p.image_ids) for p in all_points])
    
    print(f"  Mean reprojection error: {mean_error_all:.4f} -> {mean_error_kept:.4f}")
    print(f"  Mean track length: {mean_track_all:.2f} -> {mean_track_kept:.2f}")
    
    # Create reduced points3D
    reduced_points3D = {pid: points3D[pid] for pid in keep_ids}
    
    # Update images to remove references to deleted points
    updated_images = {}
    for img_id, img in images.items():
        # Mark deleted points as -1
        new_point3D_ids = np.array([pid if pid in keep_ids else -1 for pid in img.point3D_ids])
        updated_images[img_id] = Image(
            img.id, img.qvec, img.tvec, img.camera_id, img.name, img.xys, new_point3D_ids
        )
    
    return reduced_points3D, updated_images


def main():
    parser = argparse.ArgumentParser(
        description="Reduce the number of 3D points in a COLMAP SfM reconstruction.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sampling methods:
  random        - Random uniform sampling
  low_error     - Keep points with lowest reprojection error
  track_length  - Keep points visible in most images
  combined      - Weighted combination of error and track length (recommended)
  stratified    - Stratified sampling across quality tiers (preserves variety)
  spatial       - Spatial sampling favoring sparse regions and quality points
        """
    )
    parser.add_argument("input_dir", type=str, help="Input COLMAP model directory")
    parser.add_argument("output_dir", type=str, help="Output directory for reduced model")
    
    # Mutually exclusive group for specifying target number
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--num_points", type=int, help="Target number of points to keep")
    group.add_argument("--percentage", type=float, help="Percentage of points to keep (0-100)")
    
    parser.add_argument("--method", type=str, default="combined", 
                       choices=["random", "low_error", "track_length", "combined", "stratified", "spatial"],
                       help="Method for selecting points (default: combined)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Set random seed
    np.random.seed(args.seed)
    
    # Check input directory
    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f"Error: Input directory '{input_path}' does not exist.")
        sys.exit(1)
    
    # Determine if binary or text format
    cameras_bin = input_path / "cameras.bin"
    images_bin = input_path / "images.bin"
    points3D_bin = input_path / "points3D.bin"
    
    if cameras_bin.exists() and images_bin.exists() and points3D_bin.exists():
        print("Detected binary format")
        use_binary = True
    else:
        print("Error: Only binary format is currently supported.")
        print("Please convert your model to binary format using COLMAP's model_converter.")
        sys.exit(1)
    
    # Read COLMAP model
    print("Reading cameras...")
    cameras = read_cameras_binary(str(cameras_bin))
    print(f"  Found {len(cameras)} cameras")
    
    print("Reading images...")
    images = read_images_binary(str(images_bin))
    print(f"  Found {len(images)} images")
    
    print("Reading 3D points...")
    points3D = read_points3D_binary(str(points3D_bin))
    print(f"  Found {len(points3D)} points")
    
    # Determine target number of points
    if args.num_points is not None:
        target_num_points = args.num_points
    else:
        target_num_points = int(len(points3D) * args.percentage / 100.0)
    
    print(f"Target: {target_num_points} points")
    
    # Reduce points
    reduced_points3D, updated_images = reduce_points(points3D, images, target_num_points, args.method)
    
    # Create output directory
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Write reduced model
    print(f"Writing reduced model to {output_path}...")
    write_cameras_binary(cameras, str(output_path / "cameras.bin"))
    write_images_binary(updated_images, str(output_path / "images.bin"))
    write_points3D_binary(reduced_points3D, str(output_path / "points3D.bin"))
    
    print("Done!")
    print(f"Reduction: {len(points3D)} -> {len(reduced_points3D)} points ({100.0 * len(reduced_points3D) / len(points3D):.1f}%)")


if __name__ == "__main__":
    main()
