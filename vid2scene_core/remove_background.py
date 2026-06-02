import os
import argparse
import logging
import sys
from PIL import Image
from transparent_background import Remover
from tqdm import tqdm

logger = logging.getLogger(__name__)

def remove_background(
    input_dir, 
    output_dir, 
    bg_type="rgba", 
    mode="fast", 
    device="cuda:0", 
    threshold=0.8, 
    resize="static",
    reverse=False
):
    """
    Process all images in a directory to remove backgrounds.
    
    Args:
        input_dir (str): Directory containing input images
        output_dir (str): Directory to save processed images
        bg_type (str): Background type ('rgba', 'map', 'green', 'white', 'blur', 'overlay') 
                       or a color like [255,0,0] or an image path
        mode (str): Remover mode ('fast', 'base-nightly', etc.)
        device (str): Device to use ('cuda:0', 'cpu', etc.)
        threshold (float, optional): Threshold for hard prediction
        resize (str): Resize method ('dynamic' or 'static')
        reverse (bool): Reverse output (background -> foreground)
    """
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize the remover
    logger.info(f"Initializing background remover with mode={mode}, device={device}")
    remover = Remover(mode=mode, device=device, resize=resize)
    
    # Get all image files in the input directory
    image_files = [
        f for f in os.listdir(input_dir) 
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))
    ]
    
    if not image_files:
        logger.warning(f"No image files found in {input_dir}")
        return
    
    logger.info(f"Found {len(image_files)} images to process")
    
    success_count = 0
    
    # Process images sequentially with progress bar
    for filename in tqdm(image_files, desc="Removing backgrounds", file=sys.stdout):
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, filename)
        
        # If output is RGBA, make sure the output format supports transparency
        if bg_type == "rgba" and not output_path.lower().endswith('.png'):
            output_path = os.path.splitext(output_path)[0] + '.png'
        
        try:
            img = Image.open(input_path).convert('RGB')
            
            # Process the image
            kwargs = {"type": bg_type, "reverse": reverse}
            if threshold is not None:
                kwargs["threshold"] = threshold
                
            out = remover.process(img, **kwargs)
            
            # Save the result
            out.save(output_path)
            success_count += 1
        except Exception as e:
            logger.error(f"Error processing {input_path}: {e}")
    
    logger.info(f"Processed {success_count}/{len(image_files)} images successfully")
    logger.info(f"Background removal complete. Images saved to {output_dir}")

def main():
    parser = argparse.ArgumentParser(
        description="Remove backgrounds from images using transparent_background."
    )
    parser.add_argument("input_dir", help="Directory containing input images")
    parser.add_argument("output_dir", help="Directory to save processed images")
    parser.add_argument(
        "--bg_type", 
        default="rgba",
        help="Background type: 'rgba', 'map', 'green', 'white', 'blur', 'overlay', a color [r,g,b], or an image path"
    )
    parser.add_argument(
        "--mode", 
        default="fast",
        help="Remover mode: 'fast', 'base-nightly', etc."
    )
    parser.add_argument(
        "--device", 
        default="cuda:0",
        help="Device to use: 'cuda:0', 'cpu', etc."
    )
    parser.add_argument(
        "--threshold", 
        type=float,
        help="Threshold for hard prediction",
        default=None
    )
    parser.add_argument(
        "--resize", 
        default="dynamic",
        help="Resize method: 'dynamic' or 'static'"
    )
    parser.add_argument(
        "--reverse", 
        action="store_true",
        help="Reverse output (background -> foreground)"
    )

    args = parser.parse_args()
    
    # Handle color arrays in bg_type
    if args.bg_type.startswith('[') and args.bg_type.endswith(']'):
        try:
            args.bg_type = eval(args.bg_type)  # Convert string representation to actual list
        except:
            logger.error(f"Invalid color format: {args.bg_type}. Using 'rgba' instead.")
            args.bg_type = "rgba"

    # Run background removal
    remove_background(
        args.input_dir, 
        args.output_dir, 
        args.bg_type, 
        args.mode, 
        args.device, 
        args.threshold,
        args.resize,
        args.reverse
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    main() 