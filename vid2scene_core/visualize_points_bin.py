import os
import numpy as np
import argparse
import open3d as o3d
from pycolmap_parser import SceneManager

def visualize_points_with_open3d(colmap_dir):
    """
    Visualize COLMAP points3D.bin file using Open3D for fast rendering.
    
    Args:
        colmap_dir: Directory containing COLMAP sparse model
    """
    # Load points3D data
    manager = SceneManager(colmap_dir)
    manager.load_points3D()
    points = manager.points3D
    colors = manager.point3D_colors.astype(float) / 255.0
    
    # Create Open3D point cloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    
    # Calculate center and extent for visualization
    center = np.mean(points, axis=0)
    max_dist = np.max(np.linalg.norm(points - center, axis=1))
    
    # Create coordinate frame for reference
    coordinate_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(
        size=max_dist/5 if max_dist > 0 else 1.0, origin=center)
    
    # Visualize
    print(f"Visualizing {len(points)} points from {os.path.join(colmap_dir, 'points3D.bin')}")
    print(f"Point cloud center: {center}")
    print(f"Point cloud max extent: {max_dist}")
    
    # Visualize all points together
    o3d.visualization.draw_geometries([pcd, coordinate_frame])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize COLMAP points3D.bin file using Open3D")
    parser.add_argument("colmap_dir", type=str, help="Directory containing COLMAP sparse model")
    
    args = parser.parse_args()
    
    visualize_points_with_open3d(args.colmap_dir)