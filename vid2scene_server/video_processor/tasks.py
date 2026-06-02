import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
from .models import SceneProcessingJob
import uuid  # To generate unique filenames
from django.core.files.storage import default_storage
import logging
from django.conf import settings
from .email_utils import send_job_completion_email
from django.test import RequestFactory
import waffle


BASE_DIR = settings.BASE_DIR

# Add the path to vid2scene
vid2scene_path = Path(os.path.join(os.pardir, "vid2scene_core"))
sys.path.append(str(vid2scene_path.absolute()))
import vid2scene as v2s

logger = logging.getLogger(__name__)

def upload_file_to_storage(file_path, storage_path):
    with open(file_path, "rb") as f:
        # Sometimes, the saved file path is not the same as the storage path 
        # if a file with the same name already exists. It returns the correct 
        # path to the saved file.
        saved_file_path = default_storage.save(storage_path, f)
    return saved_file_path

def generate_lod_files(workspace_path, local_ply_path, sog_output_dir, logger):
    """
    Helper function to run 3dgs-autolod and ply-to-sog for LOD generation.
    Returns True if successful, raises an Exception otherwise.
    """
    lod_base_path = os.path.join(workspace_path, "lod_base.ply")
    
    try:
        autolod_cmd = [
            "/app/3dgs-autolod/build/3dgs-autolod",
            local_ply_path,
            lod_base_path,
            "-r", "50,25,10,5,2",
            "--cluster",
            "--scale-boost",
            "1.04",
            "--cluster-size",
            "12",
            "--reduce-to",
            "9",
            "--cluster-filter",
            "0.96"
        ]
        logger.info(f"Running 3dgs-autolod: {' '.join(autolod_cmd)}")
        result = subprocess.run(autolod_cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            logger.info(f"3dgs-autolod stdout: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"3dgs-autolod failed: {e.stderr}")
        raise Exception(f"Failed to generate LODs: {e.stderr}")
        
    import glob
    lod_files = glob.glob(os.path.join(workspace_path, "lod_base_lod*.ply"))
    lod_files.sort(key=lambda x: int(os.path.basename(x).split('_lod')[1].split('_')[0]))
    
    # Check original PLY file size
    ply_size_bytes = os.path.getsize(local_ply_path)
    # Threshold: ~2GB
    LARGE_PLY_THRESHOLD = 2 * 1024 * 1024 * 1024
    
    sog_cmd = ["/app/ply-to-sog/build/ply-to-sog"]
    sog_cmd.extend(["-C", "256", "--sh-iter", "30", "-H", "1"])
    
    if ply_size_bytes < LARGE_PLY_THRESHOLD:
        logger.info(f"PLY size ({ply_size_bytes / 1024 / 1024:.2f}MB) is under threshold. Using original as LOD0 and dropping lowest generated LOD.")
        sog_cmd.extend([local_ply_path, "-l", "0"])
        # Use first 4 LODs (drop the lowest/last one)
        for i, lod_file in enumerate(lod_files[:-1]):
            sog_cmd.extend([lod_file, "-l", str(i+1)])
    else:
        logger.info(f"PLY size ({ply_size_bytes / 1024 / 1024:.2f}MB) is over threshold. Using first generated LOD as LOD0 and keeping all generated LODs.")
        # Do not use local_ply_path at all. Shift all generated LODs up by 1.
        for i, lod_file in enumerate(lod_files):
            sog_cmd.extend([lod_file, "-l", str(i)])
    
    sog_lod_meta_path = os.path.join(sog_output_dir, "lod-meta.json")
    sog_cmd.append(sog_lod_meta_path)
    
    try:
        logger.info(f"Running ply-to-sog for LODs: {' '.join(sog_cmd)}")
        result = subprocess.run(sog_cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            logger.info(f"ply-to-sog stdout: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"ply-to-sog failed with return code {e.returncode}")
        if e.stdout:
            logger.warning(f"ply-to-sog stdout: {e.stdout}")
        if e.stderr:
            logger.warning(f"ply-to-sog stderr: {e.stderr}")
        raise Exception(f"Failed to generate LODs: {e.stderr}")

def process_video_task(scene_processing_job_id):
    """
    This function processes the video into a 3D scene and stores the output PLY file
    in the MEDIA_ROOT directory with a unique filename, then cleans up the temporary workspace.
    """
    workspace_path = None
    preserve_workspace = False

    try:
        # Retrieve the video object from the database
        spj = SceneProcessingJob.objects.get(id=scene_processing_job_id)

        # Get the original video path from Django's storage API
        original_video = spj.video_file

        # Create a temporary workspace directory
        workspace_path = tempfile.mkdtemp(prefix="vid2scene_workspace_")

        # Copy the video file to the temporary workspace using Django's storage API
        video_filename = os.path.basename(original_video.name)
        video_path_in_workspace = os.path.join(workspace_path, video_filename)

        # Use default_storage to read the file from storage and write it to the temp workspace
        with default_storage.open(spj.video_file.name, "rb") as f:
            with open(video_path_in_workspace, "wb") as temp_file:
                shutil.copyfileobj(f, temp_file)
        
        # Handle Quest qscan files - extract to a temporary directory
        # Note: .qscan files are typically zip archives, so we can extract them as zip files
        quest_project_dir = None
        quest_extract_dir = None
        if spj.reconstruction_method == SceneProcessingJob.ReconstructionMethod.QUEST:
            import zipfile
            # Extract qscan (zip) to a temporary directory
            quest_extract_dir = tempfile.mkdtemp(prefix="quest_project_")
            logger.info(f"Extracting Quest qscan file to: {quest_extract_dir}")
            with zipfile.ZipFile(video_path_in_workspace, 'r') as zip_ref:
                zip_ref.extractall(quest_extract_dir)
            
            # Handle the case where the zip contains a single parent folder
            # instead of the files at the root level
            extracted_items = os.listdir(quest_extract_dir)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(quest_extract_dir, extracted_items[0])):
                # If there's only one item and it's a directory, use it as the project dir
                quest_project_dir = os.path.join(quest_extract_dir, extracted_items[0])
                logger.info(f"Detected single parent folder in zip: {extracted_items[0]}")
            else:
                # Otherwise, use the extract directory directly
                quest_project_dir = quest_extract_dir
            
            logger.info(f"Quest project extracted to: {quest_project_dir}")

        # This is an array because we can't mutate a Python primitive from a lambda function unless it's inside an array
        num_preview_images = [0]
        
        # Flag to track if the job was deleted
        job_deleted = [False]
        
        # Create a kill_check function to check if the job still exists
        def should_kill_process():
            try:
                # Check if job still exists in database
                spj_exists = SceneProcessingJob.objects.filter(id=scene_processing_job_id).exists()
                if not spj_exists:
                    logger.info(f"Job {scene_processing_job_id} has been deleted, signaling process termination")
                    job_deleted[0] = True
                    return True
                return False
            except Exception as e:
                logger.error(f"Error checking if job exists: {e}")
                # If we can't check, assume we should continue
                return False

        def on_new_preview(preview_path):
            # Check if job still exists in database before processing
            if should_kill_process():
                logger.info(f"Job {scene_processing_job_id} has been deleted, skipping preview update")
                return
                
            step_number, ext = os.path.splitext(os.path.basename(preview_path))
            if ext == ".json":
                logger.info("Camera data detected. Saving to camera_data field.")
                try:
                    with open(preview_path, "r") as f:
                        new_camera_data = json.load(f)
                    
                    # Preserve cameraType if it was set at job creation or via API
                    if spj.camera_data and 'cameraType' in spj.camera_data:
                        new_camera_data['cameraType'] = spj.camera_data['cameraType']
                        logger.info(f"Preserving cameraType: {spj.camera_data['cameraType']}")

                        if spj.camera_data['cameraType'] == 'orbital':
                            new_camera_data['lookAt'] = {
                                'x': 0.0,
                                'y': 0.0,
                                'z': 0.0
                            }

                    
                    spj.camera_data = new_camera_data
                    spj.save()
                    logger.info(f"Saved camera data to camera_data field.")
                except Exception as e:
                    logger.error(f"Error saving camera data from {preview_path}: {e}")
            else:
                storage_preview_image_path = os.path.join("preview_images", f"{scene_processing_job_id}_{step_number}_{num_preview_images[0]}{ext}")
                with open(preview_path, "rb") as f:
                    logger.info(f"New preview image detected: {preview_path}")
                    resolved_storage_preview_image_path = default_storage.save(storage_preview_image_path, f)
                    spj.preview_image.name = resolved_storage_preview_image_path
                    logger.info(f"Saved preview image to: {resolved_storage_preview_image_path}")
                    spj.save()
                    num_preview_images[0] += 1

        # Process the video into a 3D scene using vid2scene
        local_ply_path_pruned = None
        local_spz_path = None
        sog_output_dir = os.path.join(workspace_path, "sog_output")
        sog_conversion_success = False
        logger.info(f"Processing video for job {scene_processing_job_id}")
        logger.info(f"Reconstruction method: {spj.reconstruction_method}")
        if spj.reconstruction_method == SceneProcessingJob.ReconstructionMethod.GENERATE_LOD:
            local_ply_path = video_path_in_workspace
            logger.info(f"Using uploaded PLY directly for LOD generation: {local_ply_path}")
            os.makedirs(sog_output_dir, exist_ok=True)
            
            sog_conversion_success = generate_lod_files(
                workspace_path=workspace_path,
                local_ply_path=local_ply_path,
                sog_output_dir=sog_output_dir,
                logger=logger
            )
            
        else:
            if not settings.USE_TEST_ASSET_SFM:
                # Convert AprilTag size from mm to meters for vid2scene
                apriltag_size_meters = None
                if spj.apriltag_size_mm is not None:
                    apriltag_size_meters = spj.apriltag_size_mm / 1000.0
                
                local_ply_path = v2s.process_video_to_scene(
                    video_path=None if quest_project_dir else video_path_in_workspace, 
                    output_dir=workspace_path, 
                    preview_data_handler=on_new_preview, 
                    remove_background_from_images=spj.remove_background,
                    equirectangular=spj.equirectangular,
                    use_background_sphere=spj.use_background_sphere,
                    apply_pilgram_filter_name=spj.pilgram_filter,
                    training_max_num_gaussians=spj.training_max_num_gaussians,
                    training_num_steps=spj.training_num_steps,
                    kill_check=should_kill_process,
                    reconstruction_method=spj.reconstruction_method,
                    quest_project_dir=quest_project_dir,
                    apriltag_size_meters=apriltag_size_meters,
                    mock=False
                )
            else:
                # Process the video into a 3D scene using a test asset SfM model
                sfm_test_asset = os.path.join(os.path.dirname(BASE_DIR), "vid2scene_core", "test_assets", "gym_hloc", "sfm_output")
                local_ply_path = v2s.process_video_to_scene(
                    sfm_dir=sfm_test_asset, 
                    output_dir=os.path.dirname(sfm_test_asset), 
                    preview_data_handler=on_new_preview, 
                    remove_background_from_images=spj.remove_background,
                    equirectangular=spj.equirectangular,
                    use_background_sphere=spj.use_background_sphere,
                    apply_pilgram_filter_name=spj.pilgram_filter,
                    training_max_num_gaussians=spj.training_max_num_gaussians,
                    training_num_steps=spj.training_num_steps,
                    kill_check=should_kill_process,
                    reconstruction_method=spj.reconstruction_method,
                    mock=False
                )
                
            # Check if the job was deleted during processing
            if job_deleted[0]:
                logger.info(f"Job {scene_processing_job_id} was deleted during processing, stopping")
                return  # Exit the function early
                
            logger.info(f"Local PLY file: {local_ply_path}")

            # Prune the PLY file
            local_ply_path_pruned = os.path.join(os.path.dirname(local_ply_path), os.path.basename(local_ply_path).replace(".ply", "_pruned.ply"))

            alpha_prune_threshold = 12
            
            v2s.prune_ply(local_ply_path, local_ply_path_pruned, alpha_prune_threshold=alpha_prune_threshold)

            # Convert the PLY file to a SPZ file
            local_spz_path = os.path.join(os.path.dirname(local_ply_path_pruned), os.path.basename(local_ply_path_pruned).replace(".ply", ".spz"))
            v2s.convert_ply_to_spz(local_ply_path_pruned, local_spz_path)
            logger.info(f"Local SPZ file: {local_spz_path}")

            # Convert pruned PLY to unbundled SOG format (meta.json + .webp textures)
            sog_meta_path = os.path.join(sog_output_dir, "meta.json")
            try:
                result = subprocess.run(
                    ["/app/ply-to-sog/build/ply-to-sog", local_ply_path_pruned, sog_output_dir, "--k-means-iter", "30"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                sog_conversion_success = True
                logger.info(f"SOG conversion successful. Output directory: {sog_output_dir}")
                if result.stdout:
                    logger.info(f"ply-to-sog stdout: {result.stdout}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"SOG conversion failed with return code {e.returncode}")
                if e.stdout:
                    logger.warning(f"ply-to-sog stdout: {e.stdout}")
                if e.stderr:
                    logger.warning(f"ply-to-sog stderr: {e.stderr}")
                logger.warning("Skipping SOG format. SPZ and PLY will still be available.")
            except FileNotFoundError as e:
                logger.warning(f"ply-to-sog not found: {e}")
                logger.warning("Skipping SOG format. SPZ and PLY will still be available.")

        # Check again if the job was deleted before uploading files
        if should_kill_process():
            logger.info(f"Job {scene_processing_job_id} was deleted before file upload, stopping")
            return

        # Generate a unique filename for the PLY file (e.g., using video_id and uuid)
        unique_filename = f"{scene_processing_job_id}_{uuid.uuid4()}"
        storage_ply_path = os.path.join("ply_files", unique_filename + ".ply")
        storage_spz_path = os.path.join("ply_files", unique_filename + ".spz")
    
        # Upload the SPZ file to storage
        saved_spz_path = None
        if local_spz_path and os.path.exists(local_spz_path):
            saved_spz_path = upload_file_to_storage(local_spz_path, storage_spz_path)
            logger.info(f"Uploaded SPZ file to: {saved_spz_path}")

        # Upload the PLY file to storage
        saved_ply_path = None
        if local_ply_path_pruned and os.path.exists(local_ply_path_pruned):
            saved_ply_path = upload_file_to_storage(local_ply_path_pruned, storage_ply_path)
            logger.info(f"Uploaded PLY file to: {saved_ply_path}")

        # Upload SOG files to storage (all files under a prefix)
        saved_sog_meta_path = None
        saved_lod_meta_path = None
        
        if sog_conversion_success and os.path.isdir(sog_output_dir):
            if spj.reconstruction_method == SceneProcessingJob.ReconstructionMethod.GENERATE_LOD:
                # Use lod_files prefix for GENERATE_LOD
                sog_storage_prefix = os.path.join("lod_files", unique_filename)
            else:
                sog_storage_prefix = os.path.join("sog_files", unique_filename)
                
            for root, dirs, files in os.walk(sog_output_dir):
                for sog_filename in files:
                    local_sog_file = os.path.join(root, sog_filename)
                    # Keep relative path for storage
                    rel_sog_path = os.path.relpath(local_sog_file, sog_output_dir)
                    storage_sog_path = os.path.join(sog_storage_prefix, rel_sog_path)
                    
                    saved_path = upload_file_to_storage(local_sog_file, storage_sog_path)
                    logger.info(f"Uploaded SOG/LOD file to: {saved_path}")
                    
                    # Track metadata files
                    if rel_sog_path == "meta.json":
                        saved_sog_meta_path = saved_path
                    elif rel_sog_path == "lod-meta.json":
                        saved_lod_meta_path = saved_path

        # Check one more time before final save
        if should_kill_process():
            logger.info(f"Job {scene_processing_job_id} was deleted before final save, stopping")
            return

        # Save the file reference to the SceneProcessingJob entry
        if spj.reconstruction_method == SceneProcessingJob.ReconstructionMethod.GENERATE_LOD:
            spj.ply_file.name = spj.video_file.name
        else:
            spj.ply_file.name = saved_ply_path
            
        spj.spz_file.name = saved_spz_path
        if saved_sog_meta_path:
            spj.sog_file.name = saved_sog_meta_path
        if saved_lod_meta_path:
            spj.lod_file.name = saved_lod_meta_path
            
        spj.save()

        logger.info(f"Processing completed successfully for job {scene_processing_job_id}")
        
        # Send email notification for successful completion with delay
        try:
            # Create a fake request for waffle flag checking
            factory = RequestFactory()
            fake_request = factory.get('/')
            fake_request.user = spj.user if spj.user else None
            
            if waffle.flag_is_active(fake_request, 'enable_completion_emails'):
                send_job_completion_email(spj, delay_seconds=60)
        except Exception as e:
            logger.error(f"Failed to send completion email for job {scene_processing_job_id}: {e}")

    except SceneProcessingJob.DoesNotExist as e:
        logger.error(f"Video with id {scene_processing_job_id} does not exist")
        preserve_workspace = True
        raise e
    except Exception as e:
        logger.error(f"Error processing video {scene_processing_job_id}: {e}")
        preserve_workspace = True
        if workspace_path:
            logger.info(f"Debug: Preserving workspace directory for failed job at {workspace_path}")
        
        raise e
        
    finally:
        # Clean up the workspace directory if it exists and we don't need to preserve it
        if workspace_path and os.path.exists(workspace_path) and not preserve_workspace:
            try:
                shutil.rmtree(workspace_path)
                logger.info(f"Temporary workspace at {workspace_path} deleted.")
            except Exception as e:
                logger.error(f"Error cleaning up workspace: {e}")
        elif workspace_path and os.path.exists(workspace_path) and preserve_workspace:
            logger.info(f"Preserving workspace at {workspace_path} for debugging")
        
        # Clean up Quest extraction directory if it exists
        if 'quest_extract_dir' in locals() and quest_extract_dir and os.path.exists(quest_extract_dir) and not preserve_workspace:
            try:
                shutil.rmtree(quest_extract_dir)
                logger.info(f"Cleaned up Quest extraction directory: {quest_extract_dir}")
            except Exception as e:
                logger.error(f"Error cleaning up Quest extraction directory {quest_extract_dir}: {e}") 