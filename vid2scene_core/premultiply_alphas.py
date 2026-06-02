import argparse
from pathlib import Path
import concurrent.futures
import multiprocessing
from PIL import Image
import numpy as np

def premultiply_alpha(image_path):
    """Premultiply alpha channel for an image and save in place."""
    try:
        # Open the image
        img = Image.open(image_path).convert('RGBA')
        
        # Convert to numpy array for easier manipulation
        img_array = np.array(img)
        
        # Extract RGB and alpha channels
        rgb = img_array[:, :, :3]
        alpha = img_array[:, :, 3:4] / 255.0  # Normalize alpha to 0-1
        
        # Premultiply RGB by alpha
        premultiplied = (rgb * alpha).astype(np.uint8)
        
        # Reconstruct the image with premultiplied RGB and original alpha
        result_array = np.concatenate([premultiplied, img_array[:, :, 3:4]], axis=2)
        result_img = Image.fromarray(result_array)
        
        # Save back to the same path
        result_img.save(image_path)
        return f"Processed: {image_path}"
        
    except Exception as e:
        return f"Error processing {image_path}: {e}"

def premultiply_alphas(directory, max_workers=None):
    """
    Premultiply alpha channel for all images in directory using multiprocessing.
    
    Args:
        directory: Path to directory containing images
        max_workers: Maximum number of processes to use
    
    Returns:
        List of processed image paths
    """
    input_dir = Path(directory)
    
    # Common image extensions
    image_extensions = ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp']
    
    # Find all image files
    image_files = []
    for ext in image_extensions:
        image_files.extend([p for p in input_dir.glob(f"**/*{ext}") if p.is_file()])
        image_files.extend([p for p in input_dir.glob(f"**/*{ext.upper()}") if p.is_file()])
    
    total_images = len(image_files)
    print(f"Found {total_images} images to process")
    
    # Process images in parallel using processes
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(premultiply_alpha, path): path for path in image_files}
        
        completed = 0
        for future in concurrent.futures.as_completed(future_to_path):
            path = future_to_path[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append(f"Error processing {path}: {e}")
                
            completed += 1
            if completed % 10 == 0 or completed == total_images:
                print(f"Progress: {completed}/{total_images} images")
    
    print("All images processed")
    return results

def main():
    parser = argparse.ArgumentParser(description="Premultiply alpha channel in images")
    parser.add_argument("input_dir", help="Directory containing images to process")
    parser.add_argument("--processes", type=int, default=None, 
                        help="Number of processes to use (default: auto)")
    args = parser.parse_args()
    
    premultiply_alphas(args.input_dir, max_workers=args.processes)

if __name__ == "__main__":
    main()