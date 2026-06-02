import multiprocessing
from pathlib import Path
import shutil
import argparse
import logging
from typing import Any, Dict, Optional
import pycolmap
import torch
import gc
from run_command import run_command

from hloc import (
    extract_features,
    match_features,
    reconstruction,
    triangulation,
    pairs_from_retrieval
)


def custom_estimation_and_geometric_verification(database_path: Path, pairs_path: Path, verbose: bool = False):
    # launch colmap verification using colmap subprocess. This is because pycolmap doesn't support GPU for verify_geometry.
    run_command(["colmap", "matches_importer",
                 "--database_path", str(database_path), 
                 "--match_list_path", str(pairs_path), 
                 "--TwoViewGeometry.min_inlier_ratio", "0.1", 
                 "--TwoViewGeometry.max_num_trials", "20000"])

triangulation.estimation_and_geometric_verification = custom_estimation_and_geometric_verification


def custom_import_images(
    image_dir: Path,
    database_path: Path,
    camera_mode: pycolmap.CameraMode,
    image_list: Optional[list] = None,
    options: Optional[Dict[str, Any]] = None,
):
    """Custom import_images function that properly converts arguments for pycolmap."""
    logger.info("Importing images into the database...")
    if options is None:
        options = {}
    
    # Convert options dict to ImageReaderOptions object
    image_reader_options = pycolmap.ImageReaderOptions()
    for key, value in options.items():
        if hasattr(image_reader_options, key):
            setattr(image_reader_options, key, value)
    
    # Check if images exist
    images = list(image_dir.iterdir())
    if len(images) == 0:
        raise IOError(f"No images found in {image_dir}.")
    
    with pycolmap.ostream():
        pycolmap.import_images(
            str(database_path),
            str(image_dir),
            camera_mode,
            options=image_reader_options,
        )

# Patch the import_images function in the hloc.reconstruction module
import hloc.reconstruction
hloc.reconstruction.import_images = custom_import_images

def custom_run_reconstruction(    
    sfm_dir: Path,
    database_path: Path,
    image_dir: Path,
    verbose: bool = False,
    options: Optional[Dict[str, Any]] = None
):
    models_path = sfm_dir / "sparse"
    models_path.mkdir(exist_ok=True, parents=True)
    logger.info("Running 3D reconstruction...")
    if options is None:
        options = {}
    options = {"num_threads": min(multiprocessing.cpu_count(), 16), **options}
    with triangulation.OutputCapture(verbose):
        with pycolmap.ostream():
            reconstructions = pycolmap.incremental_mapping(
                str(database_path), str(image_dir), str(models_path), options=options
            )
    if len(reconstructions) == 0:
        logger.error("Could not reconstruct any model!")
        return None
    logger.info(f"Reconstructed {len(reconstructions)} model(s).")
    return reconstructions[0]



# Patch the run_reconstruction function in the hloc.reconstruction module  
hloc.reconstruction.run_reconstruction = custom_run_reconstruction


logger = logging.getLogger(__name__)



def run_sfm(image_dir, output_dir, kill_check = None, reconstruction_method = 'glomap'):
    logger.info("Running HLOC SfM pipeline...")
    output_dir = Path(output_dir)
    image_dir = Path(image_dir)
    retrieval_conf = extract_features.confs["eigenplaces"]
    feature_conf = extract_features.confs["aliked-n16"]
    matcher_conf = match_features.confs["aliked+lightglue"]
    sfm_pairs = output_dir / "pairs-eigenplaces.txt"
    sfm_dir = output_dir

    logger.info("Doing retrieval")
    retrieval_path = extract_features.main(retrieval_conf, image_dir, output_dir)
    logger.info("Doing pairs")
    pairs_from_retrieval.main(retrieval_path, sfm_pairs, num_matched=32)
    if kill_check and kill_check():
        logger.info("Job was deleted after pairs, stopping")
        return None
    logger.info("Doing features")
    feature_path = extract_features.main(feature_conf, image_dir, output_dir)
    logger.info("Doing matches")
    match_path = match_features.main(matcher_conf, sfm_pairs, feature_conf["output"], output_dir)
    
    if kill_check and kill_check():
        logger.info("Job was deleted after retrieving, stopping")
        return None

    sparse_dir = sfm_dir / "sparse"
    if sparse_dir.exists():
        shutil.rmtree(sparse_dir)
    # Make the sparse folder
    sparse_dir.mkdir(exist_ok=True, parents=True)

    if reconstruction_method == 'glomap':
        # Use GLOMAP to generate the SfM model
        database = sfm_dir / "database.db"
        camera_mode = pycolmap.CameraMode.SINGLE
        reconstruction.create_empty_db(database)
        custom_import_images(image_dir, database, camera_mode, None, None)
        image_ids = reconstruction.get_image_ids(database)
        reconstruction.import_features(image_ids, database, feature_path)
        reconstruction.import_matches(
            image_ids,
            database,
            sfm_pairs,
            match_path,
            None, 
            False
        )
        triangulation.estimation_and_geometric_verification(database, sfm_pairs, True)
        run_command(["glomap", "mapper", 
                     "--database_path", str(database), 
                     "--image_path", str(image_dir), 
                     "--output_path", str(sparse_dir),
                     "--ba_iteration_num", "5",
                     "--skip_pruning", "0",
                     "--GlobalPositioning.max_num_iterations", "300",
                     "--BundleAdjustment.max_num_iterations", "500",
                     "--Thresholds.max_epipolar_error_E=0.5",
                     "--Thresholds.max_epipolar_error_F=1.5",
                     "--Thresholds.max_epipolar_error_H=1.5",
                     "--Thresholds.min_inlier_num=50",
                     "--Thresholds.min_inlier_ratio=0.4",
                     "--Thresholds.max_rotation_error=5"
                    ], kill_check=kill_check)
    
        # Re-register images, since it was pruned
        run_command(["colmap", "image_registrator", 
                    "--database_path", str(database), 
                    "--input_path",  str(sparse_dir / "0"), 
                    "--output_path", str(sparse_dir / "0")], kill_check=kill_check)
    else:
        # Makes it more robust for drone video where the triangulation
        # angle between images may be very small.
        incremental_mapper_options = pycolmap.IncrementalMapperOptions()
        incremental_mapper_options.init_min_tri_angle = 5
        incremental_pipeline_options = {"mapper": incremental_mapper_options}
        reconstruction.main(sfm_dir, image_dir, sfm_pairs, feature_path, match_path, mapper_options=incremental_pipeline_options)


    with torch.no_grad():
        torch.cuda.empty_cache()
    gc.collect()
    return str(sparse_dir)


def main():
    parser = argparse.ArgumentParser(
        description="3D SfM pointmap generation using COLMAP CLI."
    )
    parser.add_argument("image_dir", help="Directory containing the image frames.")
    parser.add_argument("output_dir", help="Directory to store the output SfM model.")

    args = parser.parse_args()

    # Run the SfM pipeline using COLMAP CLI
    model = run_sfm(args.image_dir, args.output_dir, kill_check=None)

    if model:
        logger.info(f"3D pointmap generation completed. Model saved to: {model}")
    else:
        logger.warning("No model generated.")


if __name__ == "__main__":
    main()
