import logging
import os
import numpy as np
import argparse
import struct
from pycolmap_parser import SceneManager
# import matplotlib.pyplot as plt
# from mpl_toolkits.mplot3d import Axes3D

logger = logging.getLogger(__name__)

# Monkey patch for Python 3 compatibility - only for points3D
def _save_points3D_bin_patch(self, output_file):
    num_valid_points3D = sum(
        1 for point3D_idx in self.point3D_id_to_point3D_idx.values()
        if point3D_idx != SceneManager.INVALID_POINT3D)

    iter_point3D_id_to_point3D_idx = \
        self.point3D_id_to_point3D_idx.items()

    with open(output_file, 'wb') as fid:
        fid.write(struct.pack('L', num_valid_points3D))

        logger.info(f"Type of points3D : {type(self.points3D)}")
        for point3D_id, point3D_idx in iter_point3D_id_to_point3D_idx:
            if point3D_idx == SceneManager.INVALID_POINT3D:
                print("Invalid")
                continue

            fid.write(struct.pack('L', int(point3D_id)))
            fid.write(self.points3D[point3D_idx].tobytes())
            fid.write(self.point3D_colors[point3D_idx].tobytes())
            fid.write(self.point3D_errors[point3D_idx].tobytes())
            fid.write(
                struct.pack('L', len(self.point3D_id_to_images[point3D_id])))
            fid.write(self.point3D_id_to_images[point3D_id].tobytes())


def load_points3D_patch(self, input_file=None):
    if input_file is None:
        input_file = self.folder + 'points3D.bin'
    
    if os.path.exists(input_file):
        self._load_points3D_bin(input_file)
    else:
        input_file = self.folder + 'points3D.txt'
        if os.path.exists(input_file):
            self._load_points3D_txt(input_file)
        else:
            raise IOError('no points3D file found')


# Apply the monkey patch
SceneManager._save_points3D_bin = _save_points3D_bin_patch
SceneManager.load_points3D = load_points3D_patch

def fibonacci_sphere(samples=1000, radius=1.0, center=np.array([0, 0, 0])):
    """Generate points on a Fibonacci sphere."""
    points = []
    phi = np.pi * (3. - np.sqrt(5.))  # golden angle in radians

    for i in range(samples):
        y = 1 - (i / float(samples - 1)) * 2  # y goes from 1 to -1
        radius_at_y = np.sqrt(1 - y * y)  # radius at y
        theta = phi * i  # golden angle increment
        x = np.cos(theta) * radius_at_y
        z = np.sin(theta) * radius_at_y
        point = np.array([x, y, z]) * radius + center
        points.append(point)


    return np.array(points)


def add_background_sphere(points3D_bin_path, output_path, bg_point_count=5000, scale_factor=15.0):
    """
    Add a background sphere of points to a COLMAP model.
    
    Args:
        colmap_dir: Directory containing COLMAP sparse model
        output_path: Path to save the new points.bin file
        bg_point_count: Number of background points to add
        scale_factor: Sphere radius as a multiple of the point cloud 95th percentile distance
        visualize: Whether to visualize the points
    """
    print(f"Loading COLMAP model from {points3D_bin_path}")
    
    # Load ONLY the points3D data
    manager = SceneManager(os.path.dirname(points3D_bin_path))
    manager.load_points3D(points3D_bin_path)
    
    original_points = manager.points3D
    center = np.median(original_points, axis=0)  # Use median for center (more robust to outliers)
    distances = np.linalg.norm(original_points - center, axis=1)
    
    # Use percentiles which are completely robust to outliers
    p50_dist = np.percentile(distances, 50)  # Median distance
    p95_dist = np.percentile(distances, 95)  # 95th percentile captures most points, ignores outliers
    
    # Use 95th percentile as characteristic size (ignores the most extreme 5% of points)
    characteristic_size = p95_dist
    sphere_radius = characteristic_size * scale_factor
    
    print(f"Point cloud center (median): {center}")
    print(f"Median distance from center: {p50_dist:.3f}")
    print(f"95th percentile distance: {p95_dist:.3f}")
    print(f"Characteristic size (95th percentile): {characteristic_size:.3f}")
    print(f"Background sphere radius: {sphere_radius:.3f}")
    
    # Also show max distance for comparison
    max_dist = np.max(distances)
    print(f"Max distance (for comparison): {max_dist:.3f}")
    
    # Generate background points using fibonacci sphere
    bg_points = fibonacci_sphere(samples=bg_point_count, radius=sphere_radius, center=center)
    

    # Create new point IDs (continuing from the max existing ID)
    max_point_id = max(manager.point3D_id_to_point3D_idx.keys())
    
    # Add new points to manager
    new_point_ids = []
    for i, _ in enumerate(bg_points):
        point_id = max_point_id + i + 1
        point_idx = len(manager.points3D) + i
        new_point_ids.append(point_id)
        
        # Add point to the manager
        manager.point3D_id_to_point3D_idx[point_id] = point_idx
        
        # Empty track - no image associations
        manager.point3D_id_to_images[point_id] = np.empty((0, 2), dtype=np.uint32)
    
    # Extend the arrays
    bg_colors = np.ones((bg_point_count, 3), dtype=np.uint8) * np.array([127,127,127], dtype=np.uint8)
    bg_errors = np.ones(bg_point_count, dtype=np.float32) * np.mean(manager.point3D_errors)
    
    # Append the new points to the existing arrays
    manager.points3D = np.vstack([manager.points3D, bg_points])
    manager.point3D_colors = np.vstack([manager.point3D_colors, bg_colors])
    manager.point3D_errors = np.append(manager.point3D_errors, bg_errors)
    
    # Add new point IDs to the ID array
    manager.point3D_ids = np.append(manager.point3D_ids, np.array(new_point_ids, dtype=np.uint64))
    
    # Save ONLY the updated points
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    manager.save_points3D(os.path.dirname(output_path), os.path.basename(output_path), binary=True)
    
    print(f"Added {bg_point_count} background points to create a skybox effect")
    print(f"Total points: {len(manager.points3D)}")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add background sphere to COLMAP model for skybox effects")
    parser.add_argument("--bg_points", type=int, default=5000, help="Number of background points to add")
    parser.add_argument("--scale_factor", type=float, default=2.0, help="Sphere radius as a multiple of point cloud extent")
    parser.add_argument("points3D_bin_path", type=str, help="Path to points3D.bin file")
    parser.add_argument("output_path", type=str, help="Output points3D.bin file path")
    
    args = parser.parse_args()
    
    add_background_sphere(
        args.points3D_bin_path, 
        args.output_path, 
        bg_point_count=args.bg_points,
        scale_factor=args.scale_factor,
    )