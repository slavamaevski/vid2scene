import numpy as np
import logging
from pathlib import Path
import pycolmap
from typing import Dict, Optional
import cv2

logger = logging.getLogger(__name__)

try:
    from pupil_apriltags import Detector
    APRILTAG_AVAILABLE = True
except ImportError:
    print("WARNING:","pupil_apriltags not installed. AprilTag calibration will not be available.")
    APRILTAG_AVAILABLE = False


def detect_apriltags_in_images(
    image_dir: Path,
    tag_family: str = "tagStandard41h12"
) -> Dict:
    """
    Detect AprilTags in all images in the directory.
    
    Args:
        image_dir: Directory containing images
        tag_family: AprilTag family to detect
        
    Returns:
        Dictionary mapping image_name to list of detections
    """
    if not APRILTAG_AVAILABLE:
        raise ImportError("pupil_apriltags is required for AprilTag calibration. "
                        "Install with: pip install pupil-apriltags")
    
    detector = Detector(families=tag_family)
    detections_per_image = {}
    
    image_files = sorted(list(image_dir.glob("*.jpg")) + list(image_dir.glob("*.png")))
    print(f"Detecting AprilTags in {len(image_files)} images...")
    
    detected_count = 0
    for img_path in image_files:
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        
        # Ensure uint8 (required by pupil_apriltags)
        if img.dtype != np.uint8:
            img = cv2.convertScaleAbs(img)
            
        detections = detector.detect(img)
        
        if detections:
            detections_per_image[img_path.name] = detections
            detected_count += len(detections)
            print(f"DEBUG: Found {len(detections)} tag(s) in {img_path.name}")
    
    print(f"Total: {detected_count} detections across {len(detections_per_image)} images")
    
    if not detections_per_image:
        print("WARNING:","No AprilTags detected in any images!")
    
    return detections_per_image


def _triangulate_point_robust(
    observations: list,
    reconstruction: pycolmap.Reconstruction
) -> Optional[np.ndarray]:
    """
    Triangulate a 3D point from multiple 2D observations using pycolmap's robust estimator.
    
    Uses pycolmap.estimate_triangulation() which employs LO-RANSAC for robustness.
    
    Args:
        observations: List of (image, pixel) tuples
        reconstruction: COLMAP reconstruction with camera poses
        
    Returns:
        3D point in world coordinates, or None if triangulation fails
    """
    if len(observations) < 2:
        return None
    
    # Prepare data for pycolmap.estimate_triangulation
    points_2d = []  # 2D pixel coordinates
    cams_from_world = []  # Camera poses
    cameras = []  # Camera intrinsics
    
    for image, pixel in observations:
        points_2d.append(pixel)
        cams_from_world.append(image.cam_from_world)
        cameras.append(reconstruction.cameras[image.camera_id])
    
    points_2d = np.array(points_2d, dtype=np.float64)  # Shape: (N, 2)
    
    # Use pycolmap's robust triangulation (LO-RANSAC)
    try:
        result = pycolmap.estimate_triangulation(
            points_2d,
            cams_from_world,
            cameras
        )
        
        if result is None:
            return None
        
        # Result is a dict with 'xyz' and other info
        point_3d = result.get('xyz')
        if point_3d is None:
            return None
        
        return np.array(point_3d)
        
    except Exception as e:
        print(f"DEBUG: Triangulation failed: {e}")
        return None


def triangulate_tag_corners_from_detections(
    detections_per_image: Dict,
    reconstruction: pycolmap.Reconstruction,
    debug_dir: Optional[Path] = None,
    image_dir: Optional[Path] = None
) -> Dict[int, np.ndarray]:
    """
    Triangulate AprilTag corners from 2D detections across multiple views.
    
    This is more accurate than searching for existing 3D points because:
    1. ALIKED may not track the exact corner pixels
    2. Direct triangulation gives us the true corner position
    3. Using multiple view pairs with median reduces outliers
    
    Args:
        detections_per_image: Dictionary mapping image names to detection lists
        reconstruction: COLMAP reconstruction with camera poses
        debug_dir: If provided, saves debug images showing detections
        image_dir: Required if debug_dir is provided
        
    Returns:
        Dictionary mapping tag_id to 4x3 array of corner positions
    """
    print("Triangulating AprilTag corners from detections...")
    
    # Build image name index
    image_name_to_image = {img.name: img for img in reconstruction.images.values()}
    
    # Collect observations for each tag corner
    # tag_id -> corner_idx -> [(image, pixel), ...]
    tag_corner_observations = {}
    
    # Track detections for debug visualization
    debug_detections = {}  # img_name -> [(tag_id, corner_idx, pixel), ...]
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
    
    for img_name, detections in detections_per_image.items():
        image = image_name_to_image.get(img_name)
        
        if image is None:
            print("DEBUG:", f"Image {img_name} not in reconstruction")
            continue
        
        if debug_dir and img_name not in debug_detections:
            debug_detections[img_name] = []
        
        for detection in detections:
            tag_id = detection.tag_id
            
            if tag_id not in tag_corner_observations:
                tag_corner_observations[tag_id] = {0: [], 1: [], 2: [], 3: []}
            
            # Record each corner observation
            for corner_idx, detected_pixel in enumerate(detection.corners):
                tag_corner_observations[tag_id][corner_idx].append((image, detected_pixel))
                
                if debug_dir:
                    debug_detections[img_name].append((tag_id, corner_idx, detected_pixel))
    
    # Triangulate each corner
    tag_corners_3d = {}
    
    for tag_id, corners_obs in tag_corner_observations.items():
        corners_3d = []
        
        for corner_idx in range(4):
            observations = corners_obs[corner_idx]
            
            if len(observations) < 2:
                print("WARNING:", f"Tag {tag_id} corner {corner_idx}: only {len(observations)} observation(s), need ≥2")
                break
            
            # Triangulate from multiple views
            corner_3d = _triangulate_point_robust(observations, reconstruction)
            
            if corner_3d is None:
                print("WARNING:", f"Tag {tag_id} corner {corner_idx}: triangulation failed")
                break
            
            corners_3d.append(corner_3d)
            print("DEBUG:", f"Tag {tag_id} corner {corner_idx}: triangulated from {len(observations)} views")
        
        if len(corners_3d) == 4:
            tag_corners_3d[tag_id] = np.array(corners_3d)
            print(f"✓ Triangulated all 4 corners for tag {tag_id}")
        else:
            print("WARNING:", f"✗ Tag {tag_id}: only triangulated {len(corners_3d)}/4 corners")
    
    # Generate debug visualizations if requested
    if debug_dir and image_dir and debug_detections:
        print(f"Saving debug visualizations to {debug_dir}...")
        _save_debug_visualizations_triangulation(debug_detections, tag_corners_3d, image_dir, debug_dir)
    
    return tag_corners_3d


def _save_debug_visualizations_triangulation(
    debug_detections: Dict,
    tag_corners_3d: Dict[int, np.ndarray],
    image_dir: Path,
    debug_dir: Path
):
    """
    Save debug images showing detected AprilTag corners.
    
    Args:
        debug_detections: Dictionary of img_name -> list of (tag_id, corner_idx, pixel)
        tag_corners_3d: Final triangulated corners (for info only)
        image_dir: Directory containing source images
        debug_dir: Directory to save debug images
    """
    saved_count = 0
    for img_name, detections in debug_detections.items():
        if not detections:
            continue
        
        # Load image
        img_path = image_dir / img_name
        if not img_path.exists():
            continue
        
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        
        # Draw all detected corners
        for tag_id, corner_idx, pixel in detections:
            x, y = int(pixel[0]), int(pixel[1])
            
            # Color-code corners: red, green, blue, yellow
            colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255)]
            color = colors[corner_idx]
            
            # Circle on detected corner
            cv2.circle(img, (x, y), 8, color, 2)
            
            # Label
            label = f"T{tag_id}C{corner_idx}"
            cv2.putText(img, label, (x + 10, y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        
        # Save debug image
        output_path = debug_dir / f"debug_{img_name}"
        cv2.imwrite(str(output_path), img)
        saved_count += 1
    
    print(f"Saved {saved_count} debug images to {debug_dir}")


def calculate_scale_factor(
    tag_corners_3d: Dict[int, np.ndarray],
    tag_size_meters: float
) -> float:
    """
    Calculate scale factor by comparing reconstructed distances with physical size.
    
    Args:
        tag_corners_3d: Dictionary mapping tag_id to 4x3 array of corner positions
        tag_size_meters: Physical size of tag in meters (distance between detection corners)
        
    Returns:
        Scale factor (physical_size / reconstructed_size)
    """
    if not tag_corners_3d:
        raise ValueError("No tags provided for scale calculation")
    
    scale_factors = []
    
    for tag_id, corners in tag_corners_3d.items():
        # Calculate edge lengths
        edge_lengths = []
        for i in range(4):
            next_i = (i + 1) % 4
            edge_length = np.linalg.norm(corners[next_i] - corners[i])
            edge_lengths.append(edge_length)
        
        avg_reconstructed_size = np.mean(edge_lengths)
        std_edge = np.std(edge_lengths)
        
        # Sanity check: edges should be similar (it's a square!)
        if std_edge / avg_reconstructed_size > 0.15:  # 15% tolerance
            print("WARNING:",
                f"Tag {tag_id}: edges vary by {std_edge/avg_reconstructed_size*100:.1f}%. "
                f"Edges: {[f'{e:.4f}' for e in edge_lengths]}. "
                f"May indicate poor reconstruction or tag distortion."
            )
        
        scale_factor = tag_size_meters / avg_reconstructed_size
        scale_factors.append(scale_factor)
        
        print(
            f"Tag {tag_id}: "
            f"reconstructed={avg_reconstructed_size:.4f} units, "
            f"physical={tag_size_meters:.4f}m, "
            f"scale={scale_factor:.4f}"
        )
    
    # Use median for robustness
    final_scale = np.median(scale_factors)
    
    if len(scale_factors) > 1:
        scale_std = np.std(scale_factors)
        scale_range = np.max(scale_factors) - np.min(scale_factors)
        
        print(
            f"Scale factor: {final_scale:.4f} ± {scale_std:.4f} "
            f"(median of {len(scale_factors)} tags, range: {scale_range:.4f})"
        )
        
        if scale_std / final_scale > 0.1:
            print("WARNING:",
                f"High variance in scale estimates (CV={scale_std/final_scale*100:.1f}%). "
                f"Check: 1) All tags are the same size, 2) Tags are flat, 3) Tags measured accurately"
            )
    else:
        print(f"Scale factor: {final_scale:.4f} (from 1 tag)")
    
    return final_scale


def rescale_reconstruction(
    sfm_dir: Path,
    scale_factor: float
) -> None:
    """
    Rescale a COLMAP reconstruction by the given scale factor.
    
    Args:
        sfm_dir: Directory containing sparse/0 with reconstruction
        scale_factor: Scale factor to apply
    """
    sparse_dir = sfm_dir / "sparse" / "0"
    reconstruction = pycolmap.Reconstruction(str(sparse_dir))
    
    print(f"Rescaling reconstruction by factor {scale_factor:.4f}...")
    
    # Scale camera translations
    for image_id, image in reconstruction.images.items():
        cam_from_world = image.cam_from_world
        new_translation = cam_from_world.translation * scale_factor
        new_cam_from_world = pycolmap.Rigid3d(
            rotation=cam_from_world.rotation,
            translation=new_translation
        )
        image.cam_from_world = new_cam_from_world
    
    # Scale 3D points
    for point_id, point in reconstruction.points3D.items():
        point.xyz = point.xyz * scale_factor
    
    # Backup original
    import shutil
    backup_dir = sfm_dir / "sparse" / "0_before_apriltag_scale"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    
    shutil.copytree(sparse_dir, backup_dir)
    print(f"Backed up original to {backup_dir.name}")
    
    # Save rescaled version
    reconstruction.write(str(sparse_dir))
    print(f"✓ Rescaled reconstruction saved")


def calibrate_scale_with_apriltags(
    image_dir: Path,
    sfm_dir: Path,
    tag_size_meters: float,
    tag_family: str = "tagStandard41h12",
    debug: bool = False
) -> float:
    """
    Calibrate scale by triangulating AprilTag corners from detections.
    
    This triangulates corners directly from AprilTag detections, which is more
    accurate than searching for existing 3D points.
    
    Args:
        image_dir: Directory with images
        sfm_dir: Directory with COLMAP reconstruction (containing sparse/0/)
        tag_size_meters: Physical size of tags in meters (distance between detection corners,
                        measured from inner white square where white meets black border)
        tag_family: AprilTag family (default: tagStandard41h12)
        debug: If True, saves debug images showing corner detections to sfm_dir/apriltag_debug/
        
    Returns:
        Scale factor applied to the reconstruction
    """
    print("=" * 60)
    print("AprilTag Scale Calibration")
    print("=" * 60)
    
    # Step 1: Detect AprilTags
    print("Step 1/4: Detecting AprilTags...")
    detections_per_image = detect_apriltags_in_images(image_dir, tag_family)
    
    if not detections_per_image:
        raise ValueError(
            "No AprilTags detected in any images!\n"
            "Make sure:\n"
            "  1. You placed AprilTags in the scene\n"
            "  2. Tags are visible in the video/images\n"
            "  3. You specified the correct tag family\n"
            f"  4. You're using {tag_family} tags"
        )
    
    # Step 2: Load reconstruction
    print("Step 2/4: Loading reconstruction...")
    sparse_dir = sfm_dir / "sparse" / "0"
    if not sparse_dir.exists():
        raise ValueError(f"Sparse reconstruction not found at {sparse_dir}")
    
    reconstruction = pycolmap.Reconstruction(str(sparse_dir))
    print(f"Loaded {len(reconstruction.images)} images, {len(reconstruction.points3D)} 3D points")
    
    # Step 3: Triangulate tag corners
    print("Step 3/4: Triangulating tag corners...")
    debug_dir = sfm_dir / "apriltag_debug" if debug else None
    tag_corners_3d = triangulate_tag_corners_from_detections(
        detections_per_image,
        reconstruction,
        debug_dir=debug_dir,
        image_dir=image_dir if debug else None
    )
    
    if not tag_corners_3d:
        raise ValueError(
            "Could not triangulate AprilTag corners.\n"
            "This usually means:\n"
            "  1. Tags don't appear in enough views (need ≥2 per tag)\n"
            "  2. Camera poses may be inaccurate\n"
            "  3. Tags are too far away or blurry\n"
            "Make sure tags appear clearly in multiple frames!"
        )
    
    # Step 4: Calculate and apply scale
    print("Step 4/4: Calculating and applying scale...")
    scale_factor = calculate_scale_factor(tag_corners_3d, tag_size_meters)
    rescale_reconstruction(sfm_dir, scale_factor)
    
    print("=" * 60)
    print(f"✓ AprilTag calibration complete! Scale factor: {scale_factor:.4f}x")
    print("=" * 60)
    
    return scale_factor
