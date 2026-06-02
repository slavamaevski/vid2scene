# AprilTag Scale Calibration Guide

## Overview

AprilTag scale calibration allows you to automatically set the correct physical scale for your 3D reconstruction by placing AprilTags in your scene. This ensures your 3D model has accurate real-world dimensions.

## What You Need

### 1. Print AprilTags

Download and print AprilTags from: https://github.com/AprilRobotics/apriltag-imgs

**Recommended family**: `tagStandard41h12` (most robust to blur and occlusion)

- Choose any tag ID (e.g., tag_0, tag_1, tag_2, etc.)
- Print on regular paper or cardstock
- Multiple tags provide more accurate calibration

### 2. Measure Your Tags

Use a ruler or calipers to measure the **inner white square** (detection corners) of your printed tag:

```
┌─────────────────┐
│█████████████████│
│██┌─────────┐████│  ← Measure this distance
│██│         │████│     (inner white square)
│██│ Tag ID  │████│
│██│         │████│
│██└─────────┘████│
│█████████████████│
└─────────────────┘
```

**Example**: If the inner white square measures 95.6mm, use `0.0956` (meters) for CLI or `95.6` (millimeters) for API.

**Important**: Be accurate! A 1mm measurement error = 1% scale error.

### 3. Place Tags in Scene

- Mount tags **flat** on walls, floors, or rigid surfaces
- Ensure tags are visible in **multiple frames** (3+ recommended)
- Avoid curved surfaces, glare, shadows, and blur
- Tags don't need to be the focus - just visible in the video

### 4. Record Video

- Film your scene normally
- Include the tags naturally in some frames
- Make sure tags are visible from different angles
- Keep tags in focus

## Usage

### Basic Usage

```bash
python vid2scene.py \
    --video_path your_video.mp4 \
    output_directory \
    --apriltag_size 0.15
```

This will:
1. Extract frames from your video
2. Detect AprilTags automatically
3. Run 3D reconstruction (SfM)
4. Find tag corners in the reconstruction
5. Calculate scale factor
6. Rescale the entire model
7. Generate Gaussian splat with correct scale

### Advanced Options

```bash
python vid2scene.py \
    --video_path your_video.mp4 \
    output_directory \
    --apriltag_size 0.15 \
    --target_framecount 600  # More frames = better reconstruction
```

### Without AprilTags (Default Behavior)

If you don't specify `--apriltag_size`, the system works as before with arbitrary scale:

```bash
python vid2scene.py \
    --video_path your_video.mp4 \
    output_directory
```

### API Usage

AprilTag calibration is also available via the API. AprilTags will only be detected when the `apriltag_size_mm` parameter is provided:

```bash
# 1. Generate upload URL
curl -X POST https://vid2scene.com/api/v1/generate-upload-url/ \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"file_extension": "mp4"}'

# 2. Upload video to the returned URL
curl -X PUT "UPLOAD_URL_FROM_STEP_1" \
  -H "x-ms-blob-type: BlockBlob" \
  --data-binary @your_video.mp4

# 3. Submit job with AprilTag calibration
curl -X POST https://vid2scene.com/api/v1/submit-job/ \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Room with Scale",
    "blob_name": "BLOB_NAME_FROM_STEP_1",
    "apriltag_size_mm": 95.6
  }'
```

**Note**: API accepts `apriltag_size_mm` in **millimeters** (e.g., `95.6`), while CLI uses **meters** (e.g., `0.0956`).

## Tips for Best Results

### ✅ Do:
- Use **multiple tags** (2-4 tags) for robust calibration
- Make tags **10cm or larger** for better detection
- Ensure **high contrast** (print on white paper)
- Mount tags on **flat, rigid surfaces**
- Include tags in **5-10 frames** from different angles
- **Measure carefully** with a good ruler or calipers
- Use **good lighting** (diffuse, even illumination)

### ❌ Don't:
- Place tags on **curved or flexible surfaces**
- Let tags get **blurry** or out of focus
- Use **very small tags** (< 5cm)
- Place tags where they'll be **partially hidden**
- Mix different tag sizes (all tags should be same size)
- Forget to measure accurately!

## Troubleshooting

### "No AprilTags detected in any images!"

**Problem**: Tags weren't detected in the images.

**Solutions**:
- Check you're using `tagStandard41h12` family tags
- Ensure tags are clearly visible in the video
- Verify tags aren't too small or blurry
- Make sure there's good contrast (white paper, good lighting)

### "Could not triangulate all corners for tag X"

**Problem**: Not enough views of the tag corners for robust triangulation.

**Solutions**:
1. Ensure tags appear in **multiple frames** (5+ recommended) from different angles
2. Use larger tags that fill more of the frame
3. Ensure tags are in focus and well-lit
4. Check that tags aren't occluded or partially hidden

### "High variance in scale estimates"

**Problem**: Different tags gave different scale measurements.

**Solutions**:
- Verify all tags are the **same physical size**
- Check that tags are mounted **flat** (not warped or curved)
- Re-measure your tags more carefully
- Remove tags that might be distorted or poorly placed

## Technical Details

### How It Works

1. **Detection**: AprilTag detector finds tag corners in 2D images
2. **Triangulation**: Multi-view triangulation computes 3D positions of tag corners using `pycolmap.estimate_triangulation()` with LO-RANSAC for robustness
3. **Scale Calculation**: Compares 3D distance between corners to physical tag size
4. **Median Filter**: Uses median of all tag measurements to reject outliers
5. **Rescaling**: Applies scale factor to entire reconstruction (cameras + 3D points)

### Tag Family: tagStandard41h12

- **41 bits** = Can encode 2.2 trillion unique tag IDs
- **h12** = Hamming distance of 12 (excellent error correction)
- **Most robust** to blur, occlusion, and poor lighting
- Slower detection than tag36h11 but much more reliable

### Accuracy

Expected accuracy depends on setup:
- **Best case** (high-res, calipers, multiple tags): ±0.1-0.3mm (0.1-0.3%)
- **Typical** (phone video, ruler, 1-2 tags): ±1-3mm (1-3%)
- **Poor** (low-res, blur, single tag): ±5-10mm+ (5-10%+)

The accuracy is primarily limited by:
1. How accurately you measure the tag (most important!)
2. Image resolution and quality
3. Number of views of the tags
4. Reconstruction quality

## Example Workflow

```bash
# 1. Download and print tagStandard41h12 tags
wget https://github.com/AprilRobotics/apriltag-imgs/raw/master/tagStandard41h12/tag41_12_00000.png
# Print at actual size

# 2. Measure tag with ruler: 15.0 cm = 0.15 m

# 3. Place tag on wall in your scene

# 4. Record video including the tag in some frames

# 5. Run vid2scene with AprilTag calibration
python vid2scene.py \
    --video_path my_room.mp4 \
    output/my_room \
    --apriltag_size 0.15 \
    --target_framecount 600

# 6. Check logs for scale factor:
# "✓ Applied scale factor: 12.3456"
# This means your reconstruction is now in meters!
```

## FAQ

**Q: Do I need special AprilTag tags?**  
A: No, just print standard tags from the GitHub repository. Any tag ID from tagStandard41h12 family works.

**Q: How many tags do I need?**  
A: Minimum 1, recommended 2-4 for better accuracy and redundancy.

**Q: Can I use different tag families?**  
A: Currently only tagStandard41h12 is supported. This family is the most robust.

**Q: Do tags need to be in every frame?**  
A: No! Tags just need to appear in 3+ frames from different angles. Most of your video can be without tags.

**Q: Will AprilTags appear in the final 3D model?**  
A: Yes, they'll be part of the reconstruction just like any other surface. You can remove them in post-processing if desired.

**Q: Can I add tags after recording?**  
A: No, tags must be in the scene during recording.

**Q: What units will my model be in?**  
A: Meters. After AprilTag calibration, all distances are in meters based on your tag measurement.

## Installation

AprilTag support requires the `pupil-apriltags` library:

```bash
pip install pupil-apriltags
```

Or if you're using a requirements file, it should already be included.


