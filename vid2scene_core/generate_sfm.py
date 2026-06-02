import os
import argparse
import subprocess
import logging
from run_command import run_command

logger = logging.getLogger(__name__)



def run_sfm(image_dir, output_dir, vocab_tree_path):
    # Set up paths for the database and model
    database_path = os.path.join(output_dir, "database.db")
    sparse_model_path = os.path.join(output_dir, "sparse")

    # Ensure the output directories exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Step 1: Create a new database
    if os.path.exists(database_path):
        os.remove(database_path)  # Remove existing database to start fresh

    # Step 2: Feature extraction (using PINHOLE camera model)
    feature_extraction_command = [
        "colmap",
        "feature_extractor",
        "--database_path",
        database_path,
        "--image_path",
        image_dir,
        "--ImageReader.camera_model",
        "PINHOLE",  # Using pinhole camera model
        "--ImageReader.single_camera",
        "1",
    ]
    logger.info("Extracting features...")
    run_command(feature_extraction_command)

    # Step 3: Sequential matching with optional vocabulary tree
    feature_matching_command = [
        "colmap",
        "sequential_matcher",
        "--database_path",
        database_path,
    ]

    if vocab_tree_path:
        feature_extraction_command.extend(
            [
                "--SequentialMatching.vocab_tree_path",
                vocab_tree_path,
                "--SequentialMatching.loop_detection",
                "1",
            ]
        )

    logger.info("Matching features sequentially...")
    run_command(feature_matching_command)

    if not os.path.exists(sparse_model_path):
        os.makedirs(sparse_model_path)

    # Step 4: Run incremental SfM
    sfm_command = [
        "colmap",
        "mapper",
        "--database_path",
        database_path,
        "--image_path",
        image_dir,
        "--output_path",
        sparse_model_path,
    ]
    logger.info("Running Incremental Structure-from-Motion...")
    run_command(sfm_command)

    return sparse_model_path


def main():
    parser = argparse.ArgumentParser(
        description="3D SfM pointmap generation using COLMAP CLI."
    )
    parser.add_argument("image_dir", help="Directory containing the image frames.")
    parser.add_argument("output_dir", help="Directory to store the output SfM model.")
    parser.add_argument("--vocab_tree_path", help="Path to the vocabulary tree file.")

    args = parser.parse_args()

    # Run the SfM pipeline using COLMAP CLI
    model = run_sfm(args.image_dir, args.output_dir, args.vocab_tree_path)

    if model:
        logger.info(f"3D pointmap generation completed. Model saved to: {model}")
    else:
        logger.warning("No model generated.")


if __name__ == "__main__":
    main()
