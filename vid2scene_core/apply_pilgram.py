import argparse
from pathlib import Path
import concurrent.futures
from PIL import Image
import numpy as np
import pilgram

def apply_filter(image_path, filter_name, output_dir):
    """Apply pilgram filter to an image and save to output directory."""
    try:
        # Open the image
        img = Image.open(image_path)
        has_alpha = img.mode == 'RGBA'
        
        # Extract alpha channel if present
        if has_alpha:
            img_array = np.array(img)
            alpha_channel = img_array[:, :, 3]
        
        # Get the filter function from pilgram
        filter_func = getattr(pilgram, filter_name)
        
        # Apply the filter (pilgram only works with RGB)
        filtered_img = filter_func(img.convert('RGB'))
        
        # Re-apply alpha channel if original had one
        if has_alpha:
            filtered_array = np.array(filtered_img)
            # Create a new array with alpha channel
            result_array = np.zeros((filtered_array.shape[0], filtered_array.shape[1], 4), dtype=np.uint8)
            result_array[:, :, :3] = filtered_array
            result_array[:, :, 3] = alpha_channel
            filtered_img = Image.fromarray(result_array)
        
        # Determine output path
        output_path = Path(output_dir) / f"{Path(image_path).stem}{Path(image_path).suffix}"
        
        # Save the filtered image
        filtered_img.save(output_path)
        return f"Processed: {image_path} -> {output_path}"
        
    except Exception as e:
        return f"Error processing {image_path}: {e}"

def apply_filters_to_directory(directory, filter_name, output_dir, max_workers=None):
    """
    Apply pilgram filter to all images in directory using multiprocessing.
    
    Args:
        directory: Path to directory containing images
        filter_name: Name of the pilgram filter to apply
        output_dir: Directory to save output images
        max_workers: Maximum number of processes to use
    
    Returns:
        List of processed image paths
    """
    input_dir = Path(directory)
    
    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
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
        future_to_path = {executor.submit(apply_filter, path, filter_name, output_dir): path for path in image_files}
        
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

def list_available_filters():
    """List all available pilgram filters."""
    filters = [
        "_1977", "aden", "brannan", "brooklyn", "clarendon", "earlybird", 
        "gingham", "hudson", "inkwell", "kelvin", "lark", "lofi", 
        "maven", "mayfair", "moon", "nashville", "perpetua", "reyes", 
        "rise", "slumber", "stinson", "toaster", "valencia", "walden", 
        "willow", "xpro2"
    ]
    return filters

def main():
    parser = argparse.ArgumentParser(description="Apply pilgram filters to images")
    parser.add_argument("input_dir", help="Directory containing images to process")
    parser.add_argument("output_dir", help="Directory to save filtered images")
    parser.add_argument("--filter", help="Filter to apply", choices=list_available_filters(), required=True)
    parser.add_argument("--processes", type=int, default=None, 
                        help="Number of processes to use (default: auto)")
    args = parser.parse_args()
    
    apply_filters_to_directory(args.input_dir, args.filter, args.output_dir, max_workers=args.processes)

if __name__ == "__main__":
    main()