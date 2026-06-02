#!/usr/bin/env python3
"""
Render-based mesh extraction from Gaussian splat.

This uses the GS2Mesh approach:
1. Generate virtual cameras around the scene
2. Render depth maps using gsplat
3. Fuse depth maps into TSDF
4. Extract mesh via marching cubes
"""

import argparse
import math
import numpy as np
import torch
import open3d as o3d
from pathlib import Path
from tqdm import tqdm


def load_splat_ply(path: str, device: str = "cuda"):
    """Load Gaussian splat from PLY file into gsplat format."""
    from plyfile import PlyData

    ply = PlyData.read(path)
    v = ply["vertex"]

    # Positions
    xyz = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float32)

    # Quaternions (wxyz convention for gsplat)
    quats = np.stack([
        v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]
    ], axis=1).astype(np.float32)
    # Normalize
    quats = quats / (np.linalg.norm(quats, axis=1, keepdims=True) + 1e-8)

    # Scales (stored as log in PLY)
    scales = np.stack([
        v["scale_0"], v["scale_1"], v["scale_2"]
    ], axis=1).astype(np.float32)
    scales = np.exp(scales)

    # Opacity (stored as logit in PLY)
    opacity_raw = v["opacity"].astype(np.float32)
    opacity = 1.0 / (1.0 + np.exp(-opacity_raw))

    # SH coefficients for color (just DC for now)
    sh_dc = np.stack([
        v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]
    ], axis=1).astype(np.float32)
    # Convert SH to RGB
    colors = (sh_dc * 0.28209479177387814) + 0.5  # SH0 normalization
    colors = np.clip(colors, 0, 1)

    return {
        "means": torch.tensor(xyz, device=device),
        "quats": torch.tensor(quats, device=device),
        "scales": torch.tensor(scales, device=device),
        "opacities": torch.tensor(opacity, device=device),
        "colors": torch.tensor(colors, device=device),
    }


def generate_cubemap_grid(bbox_min: np.ndarray, bbox_max: np.ndarray,
                          grid_size: int = 5,
                          width: int = 512, height: int = 512):
    """Generate a 3D grid of cubemap camera rigs within the bounding box.
    
    Each rig position has 6 cameras (±X, ±Y, ±Z) with 90° FOV,
    giving complete spherical coverage at each grid point.
    """
    # Cubemap face directions (6 faces)
    face_dirs = np.array([
        [1, 0, 0],   # +X
        [-1, 0, 0],  # -X
        [0, 1, 0],   # +Y
        [0, -1, 0],  # -Y
        [0, 0, 1],   # +Z
        [0, 0, -1],  # -Z
    ], dtype=np.float32)
    
    # Up vectors for each face (to avoid gimbal lock)
    face_ups = np.array([
        [0, 1, 0],   # +X: up is +Y
        [0, 1, 0],   # -X: up is +Y
        [0, 0, -1],  # +Y: up is -Z
        [0, 0, 1],   # -Y: up is +Z
        [0, 1, 0],   # +Z: up is +Y
        [0, 1, 0],   # -Z: up is +Y
    ], dtype=np.float32)
    
    # Create grid of positions within bounding box (with padding)
    # No inward padding - we want cameras at the edges too
    xs = np.linspace(bbox_min[0], bbox_max[0], grid_size)
    ys = np.linspace(bbox_min[1], bbox_max[1], grid_size)
    zs = np.linspace(bbox_min[2], bbox_max[2], grid_size)
    
    extent = bbox_max - bbox_min
    spacing = extent / (grid_size - 1) if grid_size > 1 else extent
    print(f"  Grid spacing: {spacing}")
    
    # Generate all grid positions
    positions = []
    for x in xs:
        for y in ys:
            for z in zs:
                positions.append([x, y, z])
    positions = np.array(positions, dtype=np.float32)
    
    n_rigs = len(positions)
    print(f"  Grid: {grid_size}³ = {n_rigs} cubemap rigs × 6 faces = {n_rigs * 6} cameras")
    
    # Intrinsics for 90° FOV cubemap face
    fov = 90.0
    fx = fy = width / (2 * np.tan(np.radians(fov) / 2))
    cx, cy = width / 2, height / 2
    K = np.array([
        [fx, 0, cx],
        [0, fy, cy],
        [0, 0, 1]
    ], dtype=np.float32)
    
    viewmats = []
    Ks = []
    
    for pos in positions:
        for forward, up in zip(face_dirs, face_ups):
            right = np.cross(forward, up)
            right = right / (np.linalg.norm(right) + 1e-8)
            up = np.cross(right, forward)
            
            # World-to-camera (view matrix)
            R = np.stack([right, -up, forward], axis=0)
            t = -R @ pos
            
            viewmat = np.eye(4, dtype=np.float32)
            viewmat[:3, :3] = R
            viewmat[:3, 3] = t
            
            viewmats.append(viewmat)
            Ks.append(K)
    
    return np.stack(viewmats), np.stack(Ks), width, height


def generate_icosphere_cameras(center: np.ndarray, radius: float,
                               n_cameras: int = 42, fov: float = 60.0,
                               width: int = 512, height: int = 512,
                               gaussian_positions: np.ndarray = None):
    """Generate cameras on icosphere looking at center (for object-centric scenes)."""
    # Generate icosphere vertices for camera positions
    t = (1.0 + np.sqrt(5.0)) / 2.0
    vertices = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]
    ], dtype=np.float32)
    vertices = vertices / np.linalg.norm(vertices, axis=1, keepdims=True)

    faces = [
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
    ]

    def subdivide(verts, tris):
        new_tris = []
        edge_midpoints = {}
        for tri in tris:
            mids = []
            for i in range(3):
                edge = tuple(sorted([tri[i], tri[(i + 1) % 3]]))
                if edge not in edge_midpoints:
                    mid = (verts[edge[0]] + verts[edge[1]]) / 2
                    mid = mid / np.linalg.norm(mid)
                    edge_midpoints[edge] = len(verts)
                    verts = np.vstack([verts, mid])
                mids.append(edge_midpoints[edge])
            new_tris.extend([
                [tri[0], mids[0], mids[2]],
                [tri[1], mids[1], mids[0]],
                [tri[2], mids[2], mids[1]],
                [mids[0], mids[1], mids[2]],
            ])
        return verts, new_tris

    while len(vertices) < n_cameras:
        vertices, faces = subdivide(vertices, faces)
    vertices = vertices[:n_cameras]

    viewmats = []
    Ks = []
    fx = fy = width / (2 * np.tan(np.radians(fov) / 2))
    cx, cy = width / 2, height / 2
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float32)

    for v in vertices:
        cam_pos = center + v * radius
        forward = center - cam_pos
        forward = forward / np.linalg.norm(forward)
        up = np.array([0, 1, 0], dtype=np.float32)
        if abs(np.dot(forward, up)) > 0.99:
            up = np.array([0, 0, 1], dtype=np.float32)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        R = np.stack([right, -up, forward], axis=0)
        t = -R @ cam_pos
        viewmat = np.eye(4, dtype=np.float32)
        viewmat[:3, :3] = R
        viewmat[:3, 3] = t
        viewmats.append(viewmat)
        Ks.append(K)

    return np.stack(viewmats), np.stack(Ks), width, height


def render_depth_maps(splat: dict, viewmats: np.ndarray, Ks: np.ndarray,
                      width: int, height: int, device: str = "cuda"):
    """Render depth maps from all cameras using gsplat."""
    from gsplat.rendering import rasterization

    means = splat["means"]
    quats = splat["quats"]
    scales = splat["scales"]
    opacities = splat["opacities"]
    colors = splat["colors"]

    viewmats_t = torch.tensor(viewmats, device=device, dtype=torch.float32)
    Ks_t = torch.tensor(Ks, device=device, dtype=torch.float32)

    n_cams = len(viewmats)
    all_depths = []
    all_masks = []
    all_colors = []

    print(f"  Rendering {n_cams} depth maps ...")
    for i in tqdm(range(n_cams)):
        vm = viewmats_t[i:i+1]  # [1, 4, 4]
        K = Ks_t[i:i+1]  # [1, 3, 3]

        with torch.no_grad():
            render_colors, render_alphas, _ = rasterization(
                means=means,
                quats=quats,
                scales=scales,
                opacities=opacities,
                colors=colors,
                viewmats=vm,
                Ks=K,
                width=width,
                height=height,
                render_mode="RGB+ED",
                near_plane=0.1,
                far_plane=10000.0,  # Large scene support
            )

        # Depth is last channel
        depth = render_colors[0, :, :, -1].cpu().numpy()
        alpha = render_alphas[0, :, :, 0].cpu().numpy()

        # Mask out invalid regions
        mask = alpha > 0.5
        depth[~mask] = 0

        all_depths.append(depth)
        all_masks.append(mask)
        
        # Also save RGB for visualization
        rgb = render_colors[0, :, :, :3].cpu().numpy()
        all_colors.append(rgb)

    # Print depth statistics
    valid_depths = np.concatenate([d[m] for d, m in zip(all_depths, all_masks) if m.any()])
    if len(valid_depths) > 0:
        print(f"  Depth range: [{valid_depths.min():.2f}, {valid_depths.max():.2f}]")
        print(f"  Depth median: {np.median(valid_depths):.2f}")
    else:
        print("  WARNING: No valid depth pixels rendered!")

    return all_depths, all_masks, all_colors, viewmats, Ks


def tsdf_fusion(depths: list, masks: list, viewmats: np.ndarray,
                Ks: np.ndarray, width: int, height: int,
                voxel_size: float = 0.01, sdf_trunc: float = 0.04):
    """Fuse depth maps into TSDF volume."""
    print("  TSDF fusion ...")

    # Create TSDF volume
    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel_size,
        sdf_trunc=sdf_trunc,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
    )

    for i in tqdm(range(len(depths)), desc="  Fusing"):
        depth = depths[i]
        mask = masks[i]

        if not mask.any():
            continue

        # Create depth image
        depth_o3d = o3d.geometry.Image(depth.astype(np.float32))

        # Create intrinsics
        K = Ks[i]
        intrinsic = o3d.camera.PinholeCameraIntrinsic(
            width=width, height=height,
            fx=K[0, 0], fy=K[1, 1],
            cx=K[0, 2], cy=K[1, 2]
        )

        # View matrix to pose (cam-to-world)
        viewmat = viewmats[i]
        pose = np.linalg.inv(viewmat)

        # Integrate
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((height, width, 3), dtype=np.uint8)),
            depth_o3d,
            depth_scale=1.0,
            depth_trunc=sdf_trunc * 100,  # Allow large depth range
            convert_rgb_to_intensity=False
        )

        volume.integrate(rgbd, intrinsic, np.linalg.inv(pose))

    # Extract mesh
    print("  Extracting mesh ...")
    mesh = volume.extract_triangle_mesh()
    mesh.compute_vertex_normals()

    return mesh


def main():
    parser = argparse.ArgumentParser(
        description="Extract mesh from Gaussian splat using render-based TSDF fusion."
    )
    parser.add_argument("input", help="Input .ply Gaussian splat")
    parser.add_argument("-o", "--output", default="mesh.obj",
                        help="Output mesh file")
    parser.add_argument("--n-cameras", type=int, default=100,
                        help="Number of virtual cameras (default: 100)")
    parser.add_argument("--resolution", type=int, default=512,
                        help="Render resolution (default: 512)")
    parser.add_argument("--voxel-size", type=float, default=0.0,
                        help="TSDF voxel size (0 = auto from scene scale)")
    parser.add_argument("--sdf-trunc", type=float, default=0.0,
                        help="TSDF truncation (0 = 4x voxel size)")
    parser.add_argument("--camera-distance", type=float, default=0.0,
                        help="Camera distance from center (0 = auto)")
    parser.add_argument("--fov", type=float, default=60.0,
                        help="Camera field of view (default: 60)")
    parser.add_argument("--device", default="cuda",
                        help="Device (cuda or cpu)")
    parser.add_argument("--voxel-ratio", type=float, default=500,
                        help="Ratio: scene_radius / voxel_size (default: 500, higher = finer mesh)")
    parser.add_argument("--object", action="store_true",
                        help="Object-centric mode: cameras outside looking in (default: cubemap grid)")
    parser.add_argument("--grid-size", type=int, default=8,
                        help="Cubemap grid resolution per axis (default: 8, gives 8³×6=3072 cameras)")
    parser.add_argument("--save-depths", type=int, default=0,
                        help="Save N sample depth maps as PNG (default: 0 = don't save)")

    args = parser.parse_args()

    print(f"Loading splat from {args.input} ...")
    splat = load_splat_ply(args.input, device=args.device)
    n_gauss = len(splat["means"])
    print(f"  {n_gauss:,} Gaussians")

    # Compute scene bounds - use percentiles to exclude outliers
    means = splat["means"].cpu().numpy()
    center = means.mean(axis=0)
    
    # Tight bounding box using percentiles (ignore outlier splats)
    bbox_min = np.percentile(means, 2, axis=0)  # 2nd percentile
    bbox_max = np.percentile(means, 98, axis=0)  # 98th percentile
    extent = bbox_max - bbox_min
    scene_radius = np.linalg.norm(extent) / 2

    print(f"  Scene center: {center}")
    print(f"  Scene radius: {scene_radius:.2f}")
    print(f"  Tight bbox (2-98%): [{bbox_min}] to [{bbox_max}]")

    # Generate virtual cameras using cubemap grid
    print("Generating virtual cameras ...")
    
    if args.object:
        # Object-centric: cameras outside looking in
        print("  Mode: object-centric (icosphere cameras)")
        cam_radius = args.camera_distance if args.camera_distance > 0 else scene_radius * 1.5
        viewmats, Ks, width, height = generate_icosphere_cameras(
            center, cam_radius,
            n_cameras=args.n_cameras,
            fov=args.fov,
            width=args.resolution,
            height=args.resolution,
        )
    else:
        # Full scene: cubemap grid throughout the volume
        print("  Mode: cubemap grid (cameras inside scene)")
        viewmats, Ks, width, height = generate_cubemap_grid(
            bbox_min, bbox_max,
            grid_size=args.grid_size,
            width=args.resolution,
            height=args.resolution,
        )
    
    print(f"  Total: {len(viewmats)} cameras at {width}x{height}")

    # Render depth maps
    print("Rendering depth maps ...")
    depths, masks, colors, viewmats, Ks = render_depth_maps(
        splat, viewmats, Ks, width, height, device=args.device
    )

    # Save sample depth maps if requested
    if args.save_depths > 0:
        import matplotlib.pyplot as plt
        from pathlib import Path as P
        out_dir = P(args.output).parent / "depth_samples"
        out_dir.mkdir(exist_ok=True)
        n_save = min(args.save_depths, len(depths))
        indices = np.linspace(0, len(depths)-1, n_save, dtype=int)
        for idx in indices:
            d, m, c = depths[idx], masks[idx], colors[idx]
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))
            # RGB
            axes[0].imshow(np.clip(c, 0, 1))
            axes[0].set_title(f"RGB #{idx}")
            axes[0].axis("off")
            # Depth
            d_vis = d.copy()
            d_vis[~m] = np.nan
            im = axes[1].imshow(d_vis, cmap="turbo")
            axes[1].set_title(f"Depth #{idx}")
            axes[1].axis("off")
            plt.colorbar(im, ax=axes[1], fraction=0.046)
            # Mask
            axes[2].imshow(m, cmap="gray")
            axes[2].set_title(f"Alpha Mask #{idx}")
            axes[2].axis("off")
            plt.tight_layout()
            plt.savefig(out_dir / f"depth_{idx:04d}.png", dpi=100)
            plt.close()
        print(f"  Saved {n_save} depth samples to {out_dir}/")

    # Auto-compute voxel size if not specified
    voxel_size = args.voxel_size
    if voxel_size <= 0:
        voxel_size = scene_radius / args.voxel_ratio
    sdf_trunc = max(args.sdf_trunc, voxel_size * 4)
    print(f"  TSDF voxel size: {voxel_size:.4f}")
    print(f"  TSDF truncation: {sdf_trunc:.4f}")

    # TSDF fusion
    print("TSDF fusion ...")
    mesh = tsdf_fusion(
        depths, masks, viewmats, Ks, width, height,
        voxel_size=voxel_size,
        sdf_trunc=sdf_trunc
    )

    print(f"  {len(mesh.vertices):,} vertices, {len(mesh.triangles):,} faces")

    # Save
    output_path = Path(args.output)
    o3d.io.write_triangle_mesh(str(output_path), mesh)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
