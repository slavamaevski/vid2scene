"""
Wrapper function to run Quest 3D reconstruction and export to COLMAP format.
"""

import os
import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def run_quest_to_colmap(
    quest_project_dir,
    output_dir,
    kill_check=None,
    use_colored_pointcloud=False,
    use_optimized_color_dataset=False,
    interval=1,
    skip_yuv_conversion=False,
    skip_reconstruction=False,
    config_path=None
):
    """
    Run Quest 3D reconstruction pipeline and export to COLMAP format.
    
    Args:
        quest_project_dir: Path to the Quest project directory containing QRC data
        output_dir: Path to the output directory where COLMAP model files will be saved
        kill_check: Function that returns True if processing should be terminated
        use_colored_pointcloud: Include colored 3D point cloud if available
        use_optimized_color_dataset: Use optimized color datasets if available
        interval: Sampling interval for image export (use every N-th image)
        skip_yuv_conversion: Skip YUV to RGB conversion (assumes already done)
        skip_reconstruction: Skip scene reconstruction (assumes already done)
        config_path: Path to the YAML config file for the pipeline (default: config/pipeline_config.yml)
        
    Returns:
        Path to the sparse/0 directory, or None if processing was terminated
    """
    # Add quest-3d-reconstruction/scripts to path
    quest_scripts_dir = Path(__file__).parent.parent / "quest-3d-reconstruction" / "scripts"
    if quest_scripts_dir.exists():
        sys.path.insert(0, str(quest_scripts_dir))
    else:
        logger.error(f"Quest scripts directory not found: {quest_scripts_dir}")
        raise ValueError(f"Quest scripts directory not found: {quest_scripts_dir}")
    
    try:
        from e2e_quest_to_colmap import main as quest_main
    except ImportError as e:
        logger.error(f"Failed to import e2e_quest_to_colmap: {e}")
        raise
    
    # Check if we should abort
    if kill_check and kill_check():
        logger.info("Job was deleted before Quest reconstruction, stopping")
        return None
    
    # Prepare arguments
    class Args:
        def __init__(self):
            self.project_dir = Path(quest_project_dir)
            self.output_dir = Path(output_dir)
            if config_path:
                self.config = Path(config_path)
            else:
                # Default config path relative to quest-3d-reconstruction
                default_config = Path(__file__).parent.parent / "quest-3d-reconstruction" / "config" / "pipeline_config.yml"
                if default_config.exists():
                    self.config = default_config
                else:
                    # Fallback to relative path from scripts directory
                    self.config = Path("config/pipeline_config.yml")
            self.use_colored_pointcloud = use_colored_pointcloud
            self.use_optimized_color_dataset = use_optimized_color_dataset
            self.interval = interval
            self.skip_yuv_conversion = skip_yuv_conversion
            self.skip_reconstruction = skip_reconstruction
    
    args = Args()
    
    # Validate project directory
    if not args.project_dir.is_dir():
        raise ValueError(f"Quest project directory does not exist: {args.project_dir}")
    
    # Create output directory if it doesn't exist
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Running Quest reconstruction from {args.project_dir} to {args.output_dir}")
    
    # Run the quest reconstruction pipeline
    try:
        quest_main(args)
    except KeyboardInterrupt:
        logger.info("Quest reconstruction interrupted by user")
        return None
    except Exception as e:
        logger.error(f"Quest reconstruction failed: {e}")
        raise
    
    # Check if we should abort after reconstruction
    if kill_check and kill_check():
        logger.info("Job was deleted after Quest reconstruction, stopping")
        return None
    
    # Return path to sparse/0 directory
    sparse_dir = args.output_dir / "sparse" / "0"
    if not sparse_dir.exists():
        raise ValueError(f"Quest reconstruction did not create expected sparse/0 directory: {sparse_dir}")
    
    logger.info(f"Quest reconstruction completed. COLMAP model saved to: {sparse_dir}")
    return str(sparse_dir)

