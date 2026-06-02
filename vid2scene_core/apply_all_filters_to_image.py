import os
import sys
import argparse
from PIL import Image
import pilgram

def create_filter_previews(input_image_path, output_dir, size=(128, 128)):
    """
    Create preview images for all Pilgram filters from a single input image.
    
    Args:
        input_image_path: Path to the input image
        output_dir: Directory to save the preview images
        size: Size to resize images to (default: 128x128)
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # List of all available Pilgram filters
    filters = [
        "_1977", "aden", "brannan", "brooklyn", "clarendon", "earlybird", 
        "gingham", "hudson", "inkwell", "kelvin", "lark", "lofi", 
        "maven", "mayfair", "moon", "nashville", "perpetua", "reyes", 
        "rise", "slumber", "stinson", "toaster", "valencia", "walden", 
        "willow", "xpro2"
    ]
    
    try:
        # Open and resize the original image
        original = Image.open(input_image_path).convert('RGB')
        original = original.resize(size, Image.LANCZOS)
        
        # Save the original image
        original_path = os.path.join(output_dir, "original.jpg")
        original.save(original_path, quality=90)
        print(f"Saved original preview to: {original_path}")
        
        # Apply each filter and save the result
        for filter_name in filters:
            # Get the filter function from pilgram
            filter_func = getattr(pilgram, filter_name)
            
            # Apply the filter
            filtered_img = filter_func(original)
            
            # Save the filtered image
            output_path = os.path.join(output_dir, f"{filter_name}.jpg")
            filtered_img.save(output_path, quality=90)
            print(f"Saved {filter_name} preview to: {output_path}")
            
    except Exception as e:
        print(f"Error processing image: {e}")
        return False
        
    return True

def main():
    parser = argparse.ArgumentParser(description="Create preview images for all Pilgram filters")
    parser.add_argument("input_image", help="Path to input image")
    parser.add_argument("output_dir", help="Directory to save preview images")
    parser.add_argument("--size", type=int, default=128, help="Size of preview images (square)")
    
    args = parser.parse_args()
    
    size = (args.size, args.size)
    breakpoint()
    success = create_filter_previews(args.input_image, args.output_dir, size)
    
    if success:
        print(f"\nSuccessfully created all preview images in {args.output_dir}")
    else:
        print(f"\nFailed to create preview images")
        sys.exit(1)

if __name__ == "__main__":
    main()