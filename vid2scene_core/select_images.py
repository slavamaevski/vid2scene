import argparse
import os
import random
import shutil
from pathlib import Path

def copy_images(source_dir, dest_dir, num_images, random_select=False):
    # Create destination directory if it doesn't exist
    os.makedirs(dest_dir, exist_ok=True)
    
    # Get all image files from source directory
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp')
    image_files = [f for f in os.listdir(source_dir) 
                  if f.lower().endswith(image_extensions)]
    
    if not image_files:
        print(f"No image files found in {source_dir}")
        return
    
    # Sort files by name
    image_files.sort()
    
    if random_select:
        # Randomly select images
        selected_files = random.sample(image_files, min(num_images, len(image_files)))
    else:
        # Calculate step size to get desired number of images
        step = max(1, len(image_files) // num_images)
        selected_files = image_files[::step][:num_images]
    
    # Copy selected files
    for file_name in selected_files:
        source_path = os.path.join(source_dir, file_name)
        dest_path = os.path.join(dest_dir, file_name)
        shutil.copy2(source_path, dest_path)
        print(f"Copied: {file_name}")

def main():
    parser = argparse.ArgumentParser(description='Select and copy images from a directory')
    parser.add_argument('source_dir', help='Source directory containing images')
    parser.add_argument('dest_dir', help='Destination directory for selected images')
    parser.add_argument('-n', '--num_images', type=int, help='Number of images to select', default=100)
    parser.add_argument('--random', action='store_true', 
                       help='Select images randomly (default: select systematically)')
    
    args = parser.parse_args()
    
    # Convert to absolute paths
    source_dir = os.path.abspath(args.source_dir)
    dest_dir = os.path.abspath(args.dest_dir)
    
    if not os.path.exists(source_dir):
        print(f"Error: Source directory '{source_dir}' does not exist")
        return
    
    copy_images(source_dir, dest_dir, args.num_images, args.random)

if __name__ == '__main__':
    main()