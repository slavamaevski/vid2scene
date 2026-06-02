import os
import argparse
import numpy as np
import torch
import glob
import struct
import gc
from scipy.spatial.transform import Rotation
import sys
from PIL import Image
import cv2
import requests
import json
from torchvision import transforms as TF
import pycolmap
import pyceres
import shutil

import logging
logger = logging.getLogger(__name__)

sys.path.append("../vggt/")
from vggt.models.vggt import VGGT
from vggt.utils.pose_enc import pose_encoding_to_extri_intri
from vggt.utils.geometry import unproject_depth_map_to_point_map

from huggingface_hub import hf_hub_download

# Default configuration for VGGT processing
DEFAULT_VGGT_CONF_THRESHOLD = 80.0
DEFAULT_VGGT_STRIDE = 1
DEFAULT_VGGT_BATCH_SIZE = 30  # Chunk size for DPT head processing to manage GPU memory (optimized for ~10GB GPU)


def load_model(device=None):
    """Load and initialize the VGGT model."""
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    
    model = VGGT.from_pretrained("facebook/VGGT-1B")

    # model = VGGT()
    # _URL = "https://huggingface.co/facebook/VGGT-1B/resolve/main/model.pt"
    # model.load_state_dict(torch.hub.load_state_dict_from_url(_URL))
    
    model.eval()
    model = model.to(device)
    return model, device

def load_model_commercial(device=None):
    print("Initializing and loading VGGT model...")
    
    # Set up device
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    # Download only the config from facebook/VGGT-1B (no weights)
    print("Downloading config from facebook/VGGT-1B...")
    config_path = hf_hub_download(
        repo_id="facebook/VGGT-1B",
        filename="config.json"
    )
    print(f"Config file downloaded to: {config_path}")

    # Download model weights from VGGT-1B-Commercial
    print("Downloading model weights from VGGT-1B-Commercial...")
    model_weights_path = hf_hub_download(
        repo_id="facebook/VGGT-1B-Commercial",
        filename="vggt_1B_commercial.pt"
    )
    print(f"Model weights downloaded to: {model_weights_path}")

    # Load config and create model efficiently
    print("Loading config and creating model...")
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Create model with config parameters (no weight download)
    model = VGGT(
        img_size=config['img_size'],
        patch_size=config['patch_size'],
        embed_dim=config['embed_dim'],
    )

    # Load the commercial weights and move to device
    print("Loading commercial weights...")
    model.load_state_dict(torch.load(model_weights_path, map_location=device))
    
    # Use half precision to reduce memory, bfloat16 is preferred on new GPUs
    model_dtype = torch.bfloat16 if device.type == 'cuda' and torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    model = model.to(device, dtype=model_dtype)

    model.eval()  # Set to evaluation mode
    
    print(f"Model loaded successfully on {device} with dtype {model_dtype}")
    return model, device

def load_and_preprocess_images_with_padding_info(image_path_list, target_size=518):
    """
    Load and preprocess images using padding to preserve aspect ratio.
    Returns both the preprocessed images and padding information needed for intrinsics adjustment.
    
    Args:
        image_path_list (list): List of paths to image files
        target_size (int): Target size for the largest dimension
        
    Returns:
        tuple: (images_tensor, padding_info)
            - images_tensor: Batched tensor of preprocessed images
            - padding_info: List of dicts with padding/scaling info for each image
    """
    if len(image_path_list) == 0:
        raise ValueError("At least 1 image is required")
    
    images = []
    padding_info = []
    to_tensor = TF.ToTensor()
    
    for image_path in image_path_list:
        # Open image
        img = Image.open(image_path)
        
        # Handle alpha channel
        if img.mode == "RGBA":
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(background, img)
        
        img = img.convert("RGB")
        
        # Get original dimensions
        original_width, original_height = img.size
        
        # Calculate new dimensions maintaining aspect ratio
        # Make the largest dimension equal to target_size
        if original_width >= original_height:
            new_width = target_size
            new_height = round(original_height * (target_size / original_width) / 14) * 14  # Divisible by 14
        else:
            new_height = target_size
            new_width = round(original_width * (target_size / original_height) / 14) * 14  # Divisible by 14
        
        # Resize the image
        img = img.resize((new_width, new_height), Image.Resampling.BICUBIC)
        
        # Convert to tensor
        img_tensor = to_tensor(img)
        
        # Calculate padding to make square
        h_padding = target_size - new_height
        w_padding = target_size - new_width
        
        pad_top = h_padding // 2
        pad_bottom = h_padding - pad_top
        pad_left = w_padding // 2
        pad_right = w_padding - pad_left
        
        # Store padding and scaling information
        info = {
            'original_width': original_width,
            'original_height': original_height,
            'resized_width': new_width,
            'resized_height': new_height,
            'pad_left': pad_left,
            'pad_top': pad_top,
            'pad_right': pad_right,
            'pad_bottom': pad_bottom,
            'scale': max(original_width, original_height) / target_size
        }
        padding_info.append(info)
        
        # Apply padding with white (value=1.0)
        if h_padding > 0 or w_padding > 0:
            img_tensor = torch.nn.functional.pad(
                img_tensor, (pad_left, pad_right, pad_top, pad_bottom), 
                mode="constant", value=1.0
            )
        
        images.append(img_tensor)
    
    # Stack all images
    images = torch.stack(images)
    
    # Add batch dimension if single image
    if len(image_path_list) == 1 and images.dim() == 3:
        images = images.unsqueeze(0)
    
    return images, padding_info


def process_images(image_dir, model, device, kill_check=None):
    """Process images with VGGT while properly handling aspect ratios and 3D point unprojection."""
    image_names = glob.glob(os.path.join(image_dir, "*"))
    image_names = sorted([f for f in image_names if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    print(f"Found {len(image_names)} images")
    
    if len(image_names) == 0:
        raise ValueError(f"No images found in {image_dir}")

    # Load all original images
    original_images = []
    for img_path in image_names:
        img = Image.open(img_path).convert('RGB')
        original_images.append(np.array(img))
    
    # Preprocess all images with padding to maintain aspect ratio
    print("Preprocessing images with aspect ratio preservation...")
    images, padding_info = load_and_preprocess_images_with_padding_info(image_names)
    images = images.to(device, dtype=next(model.parameters()).dtype)
    print(f"Preprocessed images shape: {images.shape}")
    
    # The processed images are always square (518x518 or similar)
    processed_size = images.shape[-1]  # Should be 518
    
    # Check if we should abort after preprocessing
    if kill_check and kill_check():
        print("Job was deleted after preprocessing images, stopping")
        return None, None
    
    with torch.no_grad():
        # Add batch dimension if needed
        if len(images.shape) == 4:
            images = images.unsqueeze(0)
        
        print("Running feature aggregator on full sequence...")
        if device.type == 'cuda':
            torch.cuda.empty_cache()
        model.train()  # Enable gradient checkpointing
        aggregated_tokens_list, patch_start_idx = model.aggregator(images)
        model.eval()  # Return to evaluation mode
        
        if kill_check and kill_check():
            print("Job was deleted after feature aggregation, stopping")
            return None, None
        
        predictions = {}
        
        # Use mixed precision context
        amp_context = torch.cuda.amp.autocast(
            dtype=torch.bfloat16 if device.type == 'cuda' and torch.cuda.get_device_capability()[0] >= 8 else torch.float16,
            enabled=device.type == 'cuda'
        )
        
        with amp_context:
            # Process camera head
            if model.camera_head is not None:
                print("Processing camera poses...")
                pose_enc_list = model.camera_head(aggregated_tokens_list)
                predictions["pose_enc"] = pose_enc_list[-1]
                predictions["pose_enc_list"] = pose_enc_list
                
                if kill_check and kill_check():
                    print("Job was deleted after camera head processing, stopping")
                    return None, None
        
        # Process DPT heads with chunking
        chunk_size = 1
        print(f"Processing depth head with chunking (chunk size: {chunk_size})...")
        
        if model.depth_head is not None:
            depth, depth_conf = model.depth_head(
                aggregated_tokens_list, 
                images=images, 
                patch_start_idx=patch_start_idx,
                frames_chunk_size=chunk_size
            )
            predictions["depth"] = depth
            predictions["depth_conf"] = depth_conf
            
            if kill_check and kill_check():
                print("Job was deleted after depth head processing, stopping")
                return None, None
        
        print(f"Processing point head with chunking (chunk size: {chunk_size})...")
        
        if model.point_head is not None:
            pts3d, pts3d_conf = model.point_head(
                aggregated_tokens_list, 
                images=images, 
                patch_start_idx=patch_start_idx,
                frames_chunk_size=chunk_size
            )
            predictions["world_points"] = pts3d
            predictions["world_points_conf"] = pts3d_conf
            
            if kill_check and kill_check():
                print("Job was deleted after point head processing, stopping")
                return None, None
    
    print("Converting pose encoding to camera parameters...")
    pose_enc_tensor = predictions["pose_enc"]
    if not isinstance(pose_enc_tensor, torch.Tensor):
        pose_enc_tensor = torch.from_numpy(pose_enc_tensor)
    
    # Get intrinsics for the FULL padded square image (518x518)
    # This is what the model sees and predicts for
    extrinsic, intrinsic_padded = pose_encoding_to_extri_intri(
        pose_enc_tensor, (processed_size, processed_size)
    )
    
    # Create adjusted intrinsics for COLMAP output (original resolution)
    intrinsics_for_colmap = []
    # Create intrinsics for depth unprojection (padded space, no scaling)
    intrinsics_for_depth = []
    
    for i, info in enumerate(padding_info):
        # For COLMAP output - need intrinsics at original resolution
        K_colmap = intrinsic_padded[0, i].clone() if intrinsic_padded.dim() == 4 else intrinsic_padded[i].clone()
        
        # The model outputs intrinsics for the full 518x518 padded image
        # But the actual image content is only in the unpadded region
        # So we need to:
        # 1. Adjust principal point for padding
        # 2. Scale to original resolution
        
        # Adjust principal point for padding (shift to unpadded region)
        K_colmap[0, 2] -= info['pad_left']  # Shift cx
        K_colmap[1, 2] -= info['pad_top']   # Shift cy
        
        # Scale from resized (unpadded) dimensions to original dimensions
        scale_x = info['original_width'] / info['resized_width']
        scale_y = info['original_height'] / info['resized_height']
        
        K_colmap[0, 0] *= scale_x  # Scale fx
        K_colmap[0, 2] *= scale_x  # Scale cx (already shifted)
        K_colmap[1, 1] *= scale_y  # Scale fy
        K_colmap[1, 2] *= scale_y  # Scale cy (already shifted)
        
        intrinsics_for_colmap.append(K_colmap)
        
        # For depth unprojection - use the padded intrinsics as-is
        # The depth map is in the full 518x518 space, so we use those intrinsics
        K_depth = intrinsic_padded[0, i].clone() if intrinsic_padded.dim() == 4 else intrinsic_padded[i].clone()
        intrinsics_for_depth.append(K_depth)
    
    # Stack adjusted intrinsics for COLMAP
    intrinsic_colmap = torch.stack(intrinsics_for_colmap).unsqueeze(0) if len(intrinsics_for_colmap) > 0 else None
    intrinsic_depth = torch.stack(intrinsics_for_depth) if len(intrinsics_for_depth) > 0 else None
    
    predictions["extrinsic"] = extrinsic
    predictions["intrinsic"] = intrinsic_colmap  # This will be used for COLMAP output
    predictions["padding_info"] = padding_info
    
    print("Computing 3D points from depth maps...")
    # For unprojecting depth, use the FULL PADDED intrinsics
    # because the depth map is predicted for the entire 518x518 image
    
    # Remove batch dimension for unprojection
    depth_map = predictions["depth"]
    if depth_map.dim() == 5:
        depth_map = depth_map.squeeze(0)
    if extrinsic.dim() == 4:
        extrinsic_temp = extrinsic.squeeze(0)
    else:
        extrinsic_temp = extrinsic
    
    # Convert BFloat16 to Float32 if needed
    if isinstance(depth_map, torch.Tensor) and depth_map.dtype == torch.bfloat16:
        depth_map = depth_map.float()
    if isinstance(extrinsic_temp, torch.Tensor) and extrinsic_temp.dtype == torch.bfloat16:
        extrinsic_temp = extrinsic_temp.float()
    if isinstance(intrinsic_depth, torch.Tensor) and intrinsic_depth.dtype == torch.bfloat16:
        intrinsic_depth = intrinsic_depth.float()
    
    # Use the FULL PADDED intrinsics for unprojection
    world_points = unproject_depth_map_to_point_map(depth_map, extrinsic_temp, intrinsic_depth)
    predictions["world_points_from_depth"] = world_points
    
    # If we have direct point predictions, they should also be in the correct space
    if "world_points" in predictions:
        # The point head predictions are also in the padded space
        # They should be used as-is since they're already in world coordinates
        pass
    
    # Convert to numpy
    for key in predictions.keys():
        if isinstance(predictions[key], torch.Tensor):
            tensor = predictions[key].cpu()
            if tensor.dtype == torch.bfloat16:
                tensor = tensor.float()
            predictions[key] = tensor.numpy().squeeze(0)
    
    predictions["original_images"] = original_images
    
    # Create normalized images at the processed resolution
    S, H, W = world_points.shape[:3]
    normalized_images = np.zeros((S, H, W, 3), dtype=np.float32)
    
    for i, img in enumerate(original_images):
        # First resize to match the resized dimensions (before padding)
        info = padding_info[i]
        resized = cv2.resize(img, (info['resized_width'], info['resized_height']))
        
        # Then pad to match the full processed size
        if info['pad_top'] > 0 or info['pad_bottom'] > 0 or info['pad_left'] > 0 or info['pad_right'] > 0:
            resized = cv2.copyMakeBorder(
                resized,
                info['pad_top'], info['pad_bottom'],
                info['pad_left'], info['pad_right'],
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255)  # White padding
            )
        
        # Finally resize to the output size if needed
        if resized.shape[:2] != (H, W):
            resized = cv2.resize(resized, (W, H))
        
        normalized_images[i] = resized / 255.0
    
    predictions["images"] = normalized_images
    
    # Store dimensions for later use
    predictions["original_width"] = padding_info[0]['original_width']
    predictions["original_height"] = padding_info[0]['original_height']
    predictions["processed_width"] = padding_info[0]['resized_width']
    predictions["processed_height"] = padding_info[0]['resized_height']
    
    # Clear GPU memory
    if device.type == 'cuda':
        torch.cuda.empty_cache()
    
    return predictions, image_names

def extrinsic_to_colmap_format(extrinsics):
    """Convert extrinsic matrices to COLMAP format (quaternion + translation)."""
    num_cameras = extrinsics.shape[0]
    quaternions = []
    translations = []
    
    for i in range(num_cameras):
        # VGGT's extrinsic is camera-to-world (R|t) format
        R = extrinsics[i, :3, :3]
        t = extrinsics[i, :3, 3]
        
        # Convert rotation matrix to quaternion
        # COLMAP quaternion format is [qw, qx, qy, qz]
        rot = Rotation.from_matrix(R)
        quat = rot.as_quat()  # scipy returns [x, y, z, w]
        quat = np.array([quat[3], quat[0], quat[1], quat[2]])  # Convert to [w, x, y, z]
        
        quaternions.append(quat)
        translations.append(t)
    
    return np.array(quaternions), np.array(translations)

def download_file_from_url(url, filename):
    """Downloads a file from a URL, handling redirects."""
    try:
        response = requests.get(url, allow_redirects=False)
        response.raise_for_status() 

        if response.status_code == 302:  
            redirect_url = response.headers["Location"]
            response = requests.get(redirect_url, stream=True)
            response.raise_for_status()
        else:
            response = requests.get(url, stream=True)
            response.raise_for_status()

        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Downloaded {filename} successfully.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Error downloading file: {e}")
        return False

def segment_sky(image_path, onnx_session, mask_filename=None):
    """
    Segments sky from an image using an ONNX model.
    """
    image = cv2.imread(image_path)

    result_map = run_skyseg(onnx_session, [320, 320], image)
    result_map_original = cv2.resize(result_map, (image.shape[1], image.shape[0]))

    # Fix: Invert the mask so that 255 = non-sky, 0 = sky
    # The model outputs low values for sky, high values for non-sky
    output_mask = np.zeros_like(result_map_original)
    output_mask[result_map_original < 32] = 255  # Use threshold of 32

    if mask_filename is not None:
        os.makedirs(os.path.dirname(mask_filename), exist_ok=True)
        cv2.imwrite(mask_filename, output_mask)
    
    return output_mask

def run_skyseg(onnx_session, input_size, image):
    """
    Runs sky segmentation inference using ONNX model.
    """
    import copy
    
    temp_image = copy.deepcopy(image)
    resize_image = cv2.resize(temp_image, dsize=(input_size[0], input_size[1]))
    x = cv2.cvtColor(resize_image, cv2.COLOR_BGR2RGB)
    x = np.array(x, dtype=np.float32)
    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]
    x = (x / 255 - mean) / std
    x = x.transpose(2, 0, 1)
    x = x.reshape(-1, 3, input_size[0], input_size[1]).astype("float32")

    input_name = onnx_session.get_inputs()[0].name
    output_name = onnx_session.get_outputs()[0].name
    onnx_result = onnx_session.run([output_name], {input_name: x})

    onnx_result = np.array(onnx_result).squeeze()
    min_value = np.min(onnx_result)
    max_value = np.max(onnx_result)
    onnx_result = (onnx_result - min_value) / (max_value - min_value)
    onnx_result *= 255
    onnx_result = onnx_result.astype("uint8")

    return onnx_result

def filter_and_prepare_points(predictions, conf_threshold, mask_sky=False, mask_black_bg=False, 
                             mask_white_bg=False, stride=1, prediction_mode="depthmap_camera",
                             min_track_length=2):
    """
    Filter points based on confidence and prepare for COLMAP format.
    Handles padded images correctly by mapping coordinates through padding transformations.
    
    Args:
        predictions: Dictionary containing VGGT predictions
        conf_threshold: Percentile threshold for confidence filtering
        mask_sky: Filter out sky regions
        mask_black_bg: Filter out black background
        mask_white_bg: Filter out white background
        stride: Sampling stride for points
        prediction_mode: "depthmap_camera" or "pointmap"
        min_track_length: Minimum number of views a point must be observed in (default=2 for COLMAP)
    """
    
    # Get padding information
    padding_info = predictions.get("padding_info", None)
    if padding_info is None:
        raise ValueError("Padding information not found in predictions")
    
    # Assuming all images have the same original dimensions (typical for video frames)
    original_width = padding_info[0]['original_width']
    original_height = padding_info[0]['original_height']
    
    print(f"Mapping points from padded space to original {original_width}x{original_height} images")
    
    if prediction_mode == "pointmap":
        print("Using Pointmap Branch")
        if "world_points" in predictions:
            pred_world_points = predictions["world_points"]
            pred_world_points_conf = predictions.get("world_points_conf", np.ones_like(pred_world_points[..., 0]))
        else:
            print("Warning: world_points not found in predictions, falling back to depth-based points")
            pred_world_points = predictions["world_points_from_depth"]
            pred_world_points_conf = predictions.get("depth_conf", np.ones_like(pred_world_points[..., 0]))
    else:
        print("Using Depthmap and Camera Branch")
        pred_world_points = predictions["world_points_from_depth"]
        pred_world_points_conf = predictions.get("depth_conf", np.ones_like(pred_world_points[..., 0]))

    colors_rgb = predictions["images"] 
    
    S, H, W = pred_world_points.shape[:3]
    if colors_rgb.shape[:3] != (S, H, W):
        print(f"Reshaping colors_rgb from {colors_rgb.shape} to match {(S, H, W, 3)}")
        reshaped_colors = np.zeros((S, H, W, 3), dtype=np.float32)
        for i in range(S):
            if i < len(colors_rgb):
                reshaped_colors[i] = cv2.resize(colors_rgb[i], (W, H))
        colors_rgb = reshaped_colors
    
    colors_rgb = (colors_rgb * 255).astype(np.uint8)
    
    # Apply sky masking if requested (code omitted for brevity but same as before)
    if mask_sky:
        print("Applying sky segmentation mask")
        # ... (sky masking code remains the same)
    
    vertices_3d = pred_world_points.reshape(-1, 3)
    conf = pred_world_points_conf.reshape(-1)
    colors_rgb_flat = colors_rgb.reshape(-1, 3)

    if len(conf) != len(colors_rgb_flat):
        print(f"WARNING: Shape mismatch between confidence ({len(conf)}) and colors ({len(colors_rgb_flat)})")
        min_size = min(len(conf), len(colors_rgb_flat))
        conf = conf[:min_size]
        vertices_3d = vertices_3d[:min_size]
        colors_rgb_flat = colors_rgb_flat[:min_size]
    
    if conf_threshold == 0.0:
        conf_thres_value = 0.0
    else:
        conf_thres_value = np.percentile(conf, conf_threshold)
    
    print(f"Using confidence threshold: {conf_threshold}% (value: {conf_thres_value:.4f})")
    conf_mask = (conf >= conf_thres_value) & (conf > 1e-5)
    
    if mask_black_bg:
        print("Filtering black background")
        black_bg_mask = colors_rgb_flat.sum(axis=1) >= 16
        conf_mask = conf_mask & black_bg_mask
    
    if mask_white_bg:
        print("Filtering white background")
        white_bg_mask = ~((colors_rgb_flat[:, 0] > 240) & (colors_rgb_flat[:, 1] > 240) & (colors_rgb_flat[:, 2] > 240))
        conf_mask = conf_mask & white_bg_mask
    
    # FIRST PASS: Collect all potential points and their observations
    point_observations = {}  # point_hash -> list of (img_idx, x, y, rgb)
    
    print(f"First pass: collecting point observations with stride {stride}...")
    
    for img_idx in range(S):
        info = padding_info[img_idx]
        
        # Calculate scale factors for this specific image
        scale_x = info['original_width'] / info['resized_width']
        scale_y = info['original_height'] / info['resized_height']
        
        for y in range(0, H, stride):
            for x in range(0, W, stride):
                flat_idx = img_idx * H * W + y * W + x
                
                if flat_idx >= len(conf):
                    continue
                
                if conf[flat_idx] < conf_thres_value or conf[flat_idx] <= 1e-5:
                    continue
                
                if mask_black_bg and colors_rgb_flat[flat_idx].sum() < 16:
                    continue
                
                if mask_white_bg and all(colors_rgb_flat[flat_idx] > 240):
                    continue
                
                # Check if this point is in the padded region (skip if so)
                if (x < info['pad_left'] or x >= W - info['pad_right'] or
                    y < info['pad_top'] or y >= H - info['pad_bottom']):
                    continue
                
                point3D = vertices_3d[flat_idx]
                rgb = colors_rgb_flat[flat_idx]
                
                if not np.all(np.isfinite(point3D)):
                    continue
                
                point_hash = hash_point(point3D, scale=100)
                
                # Map 2D coordinates from padded space to original image space
                x_unpadded = x - info['pad_left']
                y_unpadded = y - info['pad_top']
                x_original = x_unpadded * scale_x
                y_original = y_unpadded * scale_y
                
                # Store observation
                if point_hash not in point_observations:
                    point_observations[point_hash] = {
                        'xyz': point3D,
                        'observations': []
                    }
                
                point_observations[point_hash]['observations'].append({
                    'img_idx': img_idx,
                    'x': x_original,
                    'y': y_original,
                    'rgb': rgb
                })
    
    # SECOND PASS: Create final points only if they have enough observations
    points3D = []
    point_indices = {}
    image_points2D = [[] for _ in range(S)]
    
    print(f"Second pass: filtering points with minimum track length {min_track_length}...")
    
    single_view_count = 0
    multi_view_count = 0
    
    for point_hash, point_data in point_observations.items():
        observations = point_data['observations']
        
        # Skip points that don't have enough observations
        if len(observations) < min_track_length:
            single_view_count += 1
            continue
        
        multi_view_count += 1
        
        # Create the point entry
        point_idx = len(points3D)
        point_indices[point_hash] = point_idx
        
        # Use average RGB from all observations
        avg_rgb = np.mean([obs['rgb'] for obs in observations], axis=0).astype(np.uint8)
        
        # Build track and add to image_points2D
        track = []
        for obs in observations:
            img_idx = obs['img_idx']
            point2d_idx = len(image_points2D[img_idx])
            track.append((img_idx, point2d_idx))
            image_points2D[img_idx].append((obs['x'], obs['y'], point_idx))
        
        point_entry = {
            "id": point_idx,
            "xyz": point_data['xyz'],
            "rgb": avg_rgb,
            "error": 1.0,
            "track": track
        }
        points3D.append(point_entry)
    
    print(f"Filtered out {single_view_count} single-view points, kept {multi_view_count} multi-view points")
    
    if len(points3D) == 0:
        print(f"Warning: No points with track length >= {min_track_length} remaining. Adding a dummy point.")
        # Add a dummy point to prevent empty reconstruction
        points3D.append({
            "id": 0,
            "xyz": np.array([0, 0, 5]),  # Place it 5 units in front
            "rgb": np.array([128, 128, 128]),
            "error": 1.0,
            "track": [(0, 0), (1, 0)] if S > 1 else [(0, 0)]
        })
        # Add dummy observations
        for i in range(min(2, S)):
            image_points2D[i].append((original_width/2, original_height/2, 0))
    
    # Print statistics
    track_lengths = [len(p["track"]) for p in points3D]
    if track_lengths:
        avg_track = np.mean(track_lengths)
        max_track = np.max(track_lengths)
        min_track = np.min(track_lengths)
        print(f"Track length stats: min={min_track}, avg={avg_track:.2f}, max={max_track}")
    
    print(f"Prepared {len(points3D)} 3D points with {sum(len(pts) for pts in image_points2D)} observations for COLMAP")
    return points3D, image_points2D

def hash_point(point, scale=100):
    """Create a hash for a 3D point by quantizing coordinates."""
    quantized = tuple(np.round(point * scale).astype(int))
    return hash(quantized)


def write_colmap_cameras_txt(file_path, intrinsics, image_width, image_height):
    """Write camera intrinsics to COLMAP cameras.txt format."""
    with open(file_path, 'w') as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"# Number of cameras: {len(intrinsics)}\n")
        
        for i, intrinsic in enumerate(intrinsics):
            camera_id = i + 1  # COLMAP uses 1-indexed camera IDs
            model = "PINHOLE" 
            
            fx = intrinsic[0, 0]
            fy = intrinsic[1, 1]
            cx = intrinsic[0, 2]
            cy = intrinsic[1, 2]
            
            f.write(f"{camera_id} {model} {image_width} {image_height} {fx} {fy} {cx} {cy}\n")

def write_colmap_images_txt(file_path, quaternions, translations, image_points2D, image_names):
    """Write camera poses and keypoints to COLMAP images.txt format."""
    with open(file_path, 'w') as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        
        num_points = sum(len(points) for points in image_points2D)
        avg_points = num_points / len(image_points2D) if image_points2D else 0
        f.write(f"# Number of images: {len(quaternions)}, mean observations per image: {avg_points:.1f}\n")
        
        for i in range(len(quaternions)):
            image_id = i + 1 
            camera_id = i + 1  
          
            qw, qx, qy, qz = quaternions[i]
            tx, ty, tz = translations[i]
            
            f.write(f"{image_id} {qw} {qx} {qy} {qz} {tx} {ty} {tz} {camera_id} {os.path.basename(image_names[i])}\n")
            
            points_line = " ".join([f"{x} {y} {point3d_id+1}" for x, y, point3d_id in image_points2D[i]])
            f.write(f"{points_line}\n")

def write_colmap_points3D_txt(file_path, points3D):
    """Write 3D points and tracks to COLMAP points3D.txt format."""
    with open(file_path, 'w') as f:
        f.write("# 3D point list with one line of data per point:\n")
        f.write("#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n")
        
        avg_track_length = sum(len(point["track"]) for point in points3D) / len(points3D) if points3D else 0
        f.write(f"# Number of points: {len(points3D)}, mean track length: {avg_track_length:.4f}\n")
        
        for point in points3D:
            point_id = point["id"] + 1  
            x, y, z = point["xyz"]
            r, g, b = point["rgb"]
            error = point["error"]
            
            track = " ".join([f"{img_id+1} {point2d_idx}" for img_id, point2d_idx in point["track"]])
            
            f.write(f"{point_id} {x} {y} {z} {int(r)} {int(g)} {int(b)} {error} {track}\n")

def write_colmap_cameras_bin(file_path, intrinsics, image_width, image_height):
    """Write camera intrinsics to COLMAP cameras.bin format."""
    with open(file_path, 'wb') as fid:
        # Write number of cameras (uint64)
        fid.write(struct.pack('<Q', len(intrinsics)))
        
        for i, intrinsic in enumerate(intrinsics):
            camera_id = i + 1
            model_id = 1 
            
            fx = float(intrinsic[0, 0])
            fy = float(intrinsic[1, 1])
            cx = float(intrinsic[0, 2])
            cy = float(intrinsic[1, 2])
            
            # Camera ID (uint32)
            fid.write(struct.pack('<I', camera_id))
            # Model ID (uint32)
            fid.write(struct.pack('<I', model_id))
            # Width (uint64)
            fid.write(struct.pack('<Q', image_width))
            # Height (uint64)
            fid.write(struct.pack('<Q', image_height))
            
            # Parameters (double)
            fid.write(struct.pack('<dddd', fx, fy, cx, cy))

def write_colmap_images_bin(file_path, quaternions, translations, image_points2D, image_names):
    """Write camera poses and keypoints to COLMAP images.bin format."""
    with open(file_path, 'wb') as fid:
        # Write number of images (uint64)
        fid.write(struct.pack('<Q', len(quaternions)))
        
        for i in range(len(quaternions)):
            image_id = i + 1
            camera_id = i + 1
            
            qw, qx, qy, qz = quaternions[i].astype(float)
            tx, ty, tz = translations[i].astype(float)
            
            image_name = os.path.basename(image_names[i]).encode()
            points = image_points2D[i]
            
            # Image ID (uint32)
            fid.write(struct.pack('<I', image_id))
            # Quaternion (double): qw, qx, qy, qz
            fid.write(struct.pack('<dddd', qw, qx, qy, qz))
            # Translation (double): tx, ty, tz
            fid.write(struct.pack('<ddd', tx, ty, tz))
            # Camera ID (uint32)
            fid.write(struct.pack('<I', camera_id))
            # Image name
            for char in image_name:
                fid.write(struct.pack('<c', bytes([char])))
            fid.write(struct.pack('<c', b'\x00'))
            
            # Write number of 2D points (uint64)
            fid.write(struct.pack('<Q', len(points)))
            
            # Write 2D points: x, y, point3D_id
            for x, y, point3d_id in points:
                fid.write(struct.pack('<dd', float(x), float(y)))
                fid.write(struct.pack('<Q', point3d_id + 1))

def write_colmap_points3D_bin(file_path, points3D):
    """Write 3D points and tracks to COLMAP points3D.bin format."""
    with open(file_path, 'wb') as fid:
        # Write number of points (uint64)
        fid.write(struct.pack('<Q', len(points3D)))
        
        for point in points3D:
            point_id = point["id"] + 1
            x, y, z = point["xyz"].astype(float)
            r, g, b = point["rgb"].astype(np.uint8)
            error = float(point["error"])
            track = point["track"]
            
            # Point ID (uint64)
            fid.write(struct.pack('<Q', point_id))
            # Position (double): x, y, z
            fid.write(struct.pack('<ddd', x, y, z))
            # Color (uint8): r, g, b
            fid.write(struct.pack('<BBB', int(r), int(g), int(b)))
            # Error (double)
            fid.write(struct.pack('<d', error))
            
            # Track: list of (image_id, point2D_idx)
            fid.write(struct.pack('<Q', len(track)))
            for img_id, point2d_idx in track:
                fid.write(struct.pack('<II', img_id + 1, point2d_idx))

def run_bundle_adjustment(sparse_dir, run_ba=True, ba_iterations=100, ba_refine_focal_length=True, 
                         ba_refine_principal_point=True, ba_refine_extra_params=False):
    """
    Run bundle adjustment on a COLMAP reconstruction using pycolmap.
    
    Args:
        sparse_dir: Path to sparse/0 directory containing COLMAP files
        run_ba: Whether to run bundle adjustment
        ba_iterations: Maximum number of bundle adjustment iterations
        ba_refine_focal_length: Whether to refine focal length during BA
        ba_refine_principal_point: Whether to refine principal point during BA
        ba_refine_extra_params: Whether to refine radial distortion parameters
        
    Returns:
        Path to the optimized sparse directory, or original if BA not run
    """    
    if not run_ba:
        logger.info("Bundle adjustment disabled, skipping optimization")
        return sparse_dir
    
    try:
        logger.info("Loading COLMAP reconstruction for bundle adjustment...")
        
        # Load the reconstruction
        reconstruction = pycolmap.Reconstruction(sparse_dir)
        
        # Print initial statistics
        num_images = len(reconstruction.images)
        num_points = len(reconstruction.points3D)
        logger.info(f"Loaded reconstruction with {num_images} images and {num_points} 3D points")
        
        # Configure bundle adjustment options
        ba_options = pycolmap.BundleAdjustmentOptions()
        ba_options.solver_options.max_num_iterations = ba_iterations
        # ba_options.solver_options.max_linear_solver_iterations = 200
        # ba_options.solver_options.function_tolerance = 1e-3
        # ba_options.solver_options.gradient_tolerance = 1e-4
        # ba_options.solver_options.parameter_tolerance = 1e-3
        
        # Configure what parameters to refine
        ba_options.refine_focal_length = ba_refine_focal_length
        ba_options.refine_principal_point = ba_refine_principal_point
        ba_options.refine_extra_params = ba_refine_extra_params
        ba_options.refine_extrinsics = True  # Always refine camera poses
        
        # Set loss function to be robust to outliers
        ba_options.loss_function_scale = 1.0

        
        logger.info(f"Running bundle adjustment with max {ba_iterations} iterations...")
        logger.info(f"  - Refine focal length: {ba_refine_focal_length}")
        logger.info(f"  - Refine principal point: {ba_refine_principal_point}")
        logger.info(f"  - Refine distortion: {ba_refine_extra_params}")
        
        
        # Run bundle adjustment
        pycolmap.bundle_adjustment(reconstruction, ba_options)
        
        # # Log results
        # logger.info(f"Bundle adjustment completed:")
        # logger.info(f"  - Initial cost: {summary.initial_cost:.6f}")
        # logger.info(f"  - Final cost: {summary.final_cost:.6f}")
        # logger.info(f"  - Iterations: {summary.num_iterations}")
        # logger.info(f"  - Time: {summary.total_time_in_seconds:.2f} seconds")
        
        # if summary.termination_type == pycolmap.BundleAdjustmentSummary.TerminationType.CONVERGENCE:
        #     logger.info("  - Termination: Converged successfully")
        # elif summary.termination_type == pycolmap.BundleAdjustmentSummary.TerminationType.NO_CONVERGENCE:
        #     logger.warning("  - Termination: Did not converge (reached max iterations)")
        # else:
        #     logger.warning(f"  - Termination: {summary.termination_type}")
        
        # Save the optimized reconstruction
        optimized_dir = sparse_dir.replace("/sparse/0", "/sparse/0_optimized")
        os.makedirs(optimized_dir, exist_ok=True)
        
        logger.info(f"Saving optimized reconstruction to {optimized_dir}...")
        reconstruction.write(optimized_dir)
        
        # Also create a backup of the original
        backup_dir = sparse_dir.replace("/sparse/0", "/sparse/0_before_ba")
        if not os.path.exists(backup_dir):
            logger.info(f"Creating backup of original reconstruction at {backup_dir}")
            shutil.copytree(sparse_dir, backup_dir)
        
        # Replace original with optimized
        logger.info("Replacing original reconstruction with optimized version...")
        shutil.rmtree(sparse_dir)
        shutil.copytree(optimized_dir, sparse_dir)
        
        logger.info("Bundle adjustment completed successfully!")
        return sparse_dir
        
    except Exception as e:
        logger.error(f"Error during bundle adjustment: {str(e)}")
        logger.error("Continuing with unoptimized reconstruction")
        return sparse_dir


def run_vggt_to_colmap(image_dir, output_dir, kill_check=None,
                       mask_black_bg=False, mask_white_bg=False, 
                       mask_sky=False,
                       prediction_mode="depthmap_camera",
                       run_ba=True,
                       ba_iterations=100,
                       ba_refine_focal_length=False,
                       ba_refine_principal_point=False,
                       ba_refine_extra_params=False):
    """
    Run VGGT to generate COLMAP format output with proper aspect ratio handling and optional bundle adjustment.
    
    Args:
        image_dir: Directory containing input images
        output_dir: Directory to save COLMAP files (should be the sfm_output_dir)
        kill_check: Function that returns True if processing should be terminated
        mask_black_bg: Filter out points with very dark/black color
        mask_white_bg: Filter out points with very bright/white color
        mask_sky: Filter out sky regions using segmentation
        prediction_mode: Which prediction branch to use ("depthmap_camera" or "pointmap")
        run_ba: If True, run bundle adjustment after VGGT processing
        ba_iterations: Maximum number of bundle adjustment iterations
        ba_refine_focal_length: Whether to refine focal length during BA
        ba_refine_principal_point: Whether to refine principal point during BA
        ba_refine_extra_params: Whether to refine distortion parameters during BA
        
    Returns:
        Path to the sparse directory, or None if processing was terminated
    """

    
    # Check if we should abort before starting
    if kill_check and kill_check():
        logger.info("Job was deleted before VGGT processing started, stopping")
        return None

    
    # Create sparse directory structure that matches what vid2scene expects
    sparse_dir = os.path.join(output_dir, "sparse")
    sparse_0_dir = os.path.join(sparse_dir, "0")
    os.makedirs(sparse_0_dir, exist_ok=True)
    
    model, device, predictions = None, None, None
    try:
        logger.info("Loading VGGT model...")
        model, device = load_model_commercial()
            
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.reset_accumulated_memory_stats()
        logger.info(torch.cuda.memory_summary(device=device))
        
        # Check if we should abort after loading model
        if kill_check and kill_check():
            logger.info("Job was deleted after loading VGGT model, stopping")
            return None
        
        logger.info("Processing images with VGGT (preserving aspect ratio with padding)...")
        predictions, image_names = process_images(image_dir, model, device, kill_check)
        
        # Check if processing was terminated
        if predictions is None or image_names is None:
            logger.info("VGGT processing was terminated")
            return None
        
        # Check if we should abort after processing images
        if kill_check and kill_check():
            logger.info("Job was deleted after processing images with VGGT, stopping")
            return None
        
        logger.info("Converting camera parameters to COLMAP format...")
        quaternions, translations = extrinsic_to_colmap_format(predictions["extrinsic"])
        
        logger.info(f"Filtering points with confidence threshold {DEFAULT_VGGT_CONF_THRESHOLD}% and stride {DEFAULT_VGGT_STRIDE}...")
        
        points3D, image_points2D = filter_and_prepare_points(
            predictions, 
            DEFAULT_VGGT_CONF_THRESHOLD, 
            mask_sky=mask_sky, 
            mask_black_bg=mask_black_bg,
            mask_white_bg=mask_white_bg,
            stride=DEFAULT_VGGT_STRIDE,
            prediction_mode=prediction_mode
        )
        
        # Check if we should abort after filtering points
        if kill_check and kill_check():
            logger.info("Job was deleted after filtering points, stopping")
            return None
        
        # Get the original image dimensions from padding info
        original_width = predictions["padding_info"][0]['original_width']
        original_height = predictions["padding_info"][0]['original_height']
        
        logger.info(f"Writing binary COLMAP files to {sparse_0_dir} with original resolution {original_width}x{original_height}...")
        logger.info(f"  - {len(points3D)} 3D points")
        logger.info(f"  - {len(quaternions)} camera poses")
        logger.info(f"  - {sum(len(pts) for pts in image_points2D)} 2D observations")
        
        # Always write binary files as that's what the rest of the pipeline expects
        write_colmap_cameras_bin(
            os.path.join(sparse_0_dir, "cameras.bin"), 
            predictions["intrinsic"], 
            original_width, 
            original_height
        )
        
        write_colmap_images_bin(
            os.path.join(sparse_0_dir, "images.bin"), 
            quaternions, 
            translations, 
            image_points2D, 
            image_names
        )
        
        write_colmap_points3D_bin(
            os.path.join(sparse_0_dir, "points3D.bin"), 
            points3D
        )
        
        logger.info(f"VGGT COLMAP files successfully written to {sparse_0_dir}")
        
        # Log some statistics
        if len(points3D) > 0:
            avg_track_length = sum(len(p["track"]) for p in points3D) / len(points3D)
            logger.info(f"Average track length: {avg_track_length:.2f} views per point")
        
        if len(image_points2D) > 0:
            avg_observations = sum(len(pts) for pts in image_points2D) / len(image_points2D)
            logger.info(f"Average observations: {avg_observations:.1f} points per image")
        
        # Clean up model and predictions before bundle adjustment to free memory
        logger.info("Cleaning up VGGT model to free memory before bundle adjustment...")
        del model
        del predictions
        gc.collect()
        if device and device.type == 'cuda':
            torch.cuda.empty_cache()
        
        # Run bundle adjustment if requested
        if run_ba:
            logger.info("\n" + "="*60)
            logger.info("Starting bundle adjustment optimization...")
            logger.info("="*60)
            
            sparse_0_dir = run_bundle_adjustment(
                sparse_0_dir,
                run_ba=run_ba,
                ba_iterations=ba_iterations,
                ba_refine_focal_length=ba_refine_focal_length,
                ba_refine_principal_point=ba_refine_principal_point,
                ba_refine_extra_params=ba_refine_extra_params
            )
            
            logger.info("="*60)
            logger.info("Bundle adjustment completed")
            logger.info("="*60 + "\n")
        
        return sparse_dir
        
    except Exception as e:
        logger.error(f"Error during VGGT processing: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None
        
    finally:
        # Final cleanup to release GPU memory
        logger.info("Final GPU memory cleanup...")
        if 'model' in locals() and model is not None:
            del model
        if 'predictions' in locals() and predictions is not None:
            del predictions
        gc.collect()
        if 'device' in locals() and device and device.type == 'cuda':
            torch.cuda.empty_cache()
        logger.info("GPU memory cleanup complete.")


def main():
    """Main function for standalone execution."""
    parser = argparse.ArgumentParser(description="Convert images to COLMAP format using VGGT with optional bundle adjustment")
    
    # Basic arguments
    parser.add_argument("--image_dir", type=str, required=True, 
                        help="Directory containing input images")
    parser.add_argument("--output_dir", type=str, default="colmap_output", 
                        help="Directory to save COLMAP files")
    parser.add_argument("--conf_threshold", type=float, default=75.0, 
                        help="Confidence threshold from 0 to 100 for including points")
    parser.add_argument("--mask_sky", action="store_true",
                        help="Filter out points likely to be sky")
    parser.add_argument("--mask_black_bg", action="store_true",
                        help="Filter out points with very dark/black color")
    parser.add_argument("--mask_white_bg", action="store_true",
                        help="Filter out points with very bright/white color")
    parser.add_argument("--binary", action="store_true", default=True,
                        help="Output binary COLMAP files (required for bundle adjustment)")
    parser.add_argument("--stride", type=int, default=1, 
                        help="Stride for point sampling. Higher = fewer points")
    parser.add_argument("--prediction_mode", type=str, default="depthmap_camera",
                        choices=["depthmap_camera", "pointmap"],
                        help="Which prediction branch to use")
    
    # Bundle adjustment arguments
    parser.add_argument("--bundle_adjustment", "--ba", action="store_true", default=False,
                        help="Run bundle adjustment after VGGT processing")
    parser.add_argument("--ba_iterations", type=int, default=100,
                        help="Maximum number of bundle adjustment iterations")
    parser.add_argument("--ba_refine_focal_length", action="store_true",
                        help="Refine focal length during bundle adjustment")
    parser.add_argument("--ba_refine_principal_point", action="store_true",
                        help="Refine principal point during bundle adjustment")
    parser.add_argument("--ba_refine_distortion", action="store_true",
                        help="Refine radial distortion parameters during bundle adjustment")
    
    args = parser.parse_args()
    
    # Override the global defaults with command line arguments
    global DEFAULT_VGGT_CONF_THRESHOLD, DEFAULT_VGGT_STRIDE
    DEFAULT_VGGT_CONF_THRESHOLD = args.conf_threshold
    DEFAULT_VGGT_STRIDE = args.stride
    
    # Run the full pipeline
    sparse_dir = run_vggt_to_colmap(
        image_dir=args.image_dir,
        output_dir=args.output_dir,
        mask_sky=args.mask_sky,
        mask_black_bg=args.mask_black_bg,
        mask_white_bg=args.mask_white_bg,
        prediction_mode=args.prediction_mode,
        run_ba=args.bundle_adjustment,
        ba_iterations=args.ba_iterations,
        ba_refine_focal_length=args.ba_refine_focal_length,
        ba_refine_principal_point=args.ba_refine_principal_point,
        ba_refine_extra_params=args.ba_refine_distortion
    )
    
    if sparse_dir:
        print(f"\n{'='*60}")
        print(f"SUCCESS: COLMAP reconstruction saved to {sparse_dir}")
        if args.bundle_adjustment:
            print(f"Bundle adjustment was applied successfully")
            print(f"Backup of original reconstruction: {sparse_dir.replace('/0', '/0_before_ba')}")
        print(f"{'='*60}\n")
    else:
        print("\n{'='*60}")
        print("ERROR: Failed to create COLMAP reconstruction")
        print(f"{'='*60}\n")
        sys.exit(1)



if __name__ == "__main__":
    main()