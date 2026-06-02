import requests
import time
import os
import json
import argparse

# Your API key — generate one in the web UI, then set it here or via env.
API_KEY = os.environ.get("VID2SCENE_API_KEY", "your-api-key-here")
BASE_URL = os.environ.get("VID2SCENE_BASE_URL", "http://localhost:8000/api/v1")
headers = {"Authorization": f"Api-Key {API_KEY}"}

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Test vid2scene API with video upload and processing")
parser.add_argument("--remove-background", action="store_true", help="Remove background from images before processing")
parser.add_argument("--video", default="vid2scene_core/test_assets/gym.mov", help="Path to video file")
parser.add_argument("--apriltag-size-mm", type=float, default=None, help="Size of AprilTag in millimeters (enables AprilTag-based calibration)")
parser.add_argument("--camera-type", choices=["orbital", "drone"], default=None, help="Default camera control type (orbital or drone)")
args = parser.parse_args()

def print_response(step, response, show_json=True):
    """Print formatted response information"""
    print(f"\n{'='*50}")
    print(f"STEP {step}")
    print(f"{'='*50}")
    print(f"Status Code: {response.status_code}")
    print(f"URL: {response.url}")
    print(f"Headers: {dict(response.headers)}")
    
    if show_json and response.headers.get('content-type', '').startswith('application/json'):
        try:
            json_data = response.json()
            print(f"Response JSON:\n{json.dumps(json_data, indent=2)}")
        except:
            print(f"Response Text: {response.text}")
    elif response.text and len(response.text) < 1000:
        print(f"Response Text: {response.text}")
    print(f"{'='*50}\n")

# Step 1: Generate upload URL
print("🚀 Starting vid2scene API test...")
video_file = args.video
file_extension = os.path.splitext(video_file)[1].lstrip('.')

print(f"📁 Video file: {video_file}")
print(f"📄 File extension: {file_extension}")
if args.remove_background:
    print("🎨 Background removal: ENABLED")
else:
    print("🎨 Background removal: disabled")
if args.apriltag_size_mm:
    print(f"🏷️  AprilTag detection: ENABLED (size: {args.apriltag_size_mm}mm)")
else:
    print("🏷️  AprilTag detection: disabled")
if args.camera_type:
    print(f"📷 Camera type: {args.camera_type}")
else:
    print("📷 Camera type: not set (will use viewer default)")
print("🔗 Generating upload URL...")

upload_response = requests.post(
    f"{BASE_URL}/generate-upload-url/",
    headers={**headers, "Content-Type": "application/json"},
    json={"file_extension": file_extension}
)
print_response("1: Generate Upload URL", upload_response)
upload_response.raise_for_status()
upload_data = upload_response.json()

# Step 2: Upload video
print("📤 Uploading video to blob storage...")
file_size = os.path.getsize(video_file)
print(f"📊 File size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")

with open(video_file, 'rb') as f:
    upload_result = requests.put(
        upload_data["url"],
        headers={"x-ms-blob-type": "BlockBlob"},
        data=f
    )
    print_response("2: Upload Video", upload_result, show_json=False)
    upload_result.raise_for_status()

print("✅ Video upload complete!")

# Step 3: Create job
print("🎬 Creating processing job...")
job_payload = {
    "blob_name": upload_data["blob_name"],
    "title": "My Python Upload",
    "public": False,
    "reconstruction_method": "glomap",
    "training_max_num_gaussians": 300000,
    "training_num_steps": 10000,
    "remove_background": args.remove_background,
}

# Add optional parameters if specified
if args.apriltag_size_mm:
    job_payload["apriltag_size_mm"] = args.apriltag_size_mm
if args.camera_type:
    job_payload["camera_type"] = args.camera_type

print(f"📋 Job payload:\n{json.dumps(job_payload, indent=2)}")

job_response = requests.post(
    f"{BASE_URL}/submit-job/",
    headers={**headers, "Content-Type": "application/json"},
    json=job_payload
)
print_response("3: Create Job", job_response)
job_response.raise_for_status()
job_data = job_response.json()
job_id = job_data["job_id"]

print(f"🎯 Job created successfully!")
print(f"🆔 Job ID: {job_id}")

# Step 4: Monitor progress
print("⏳ Monitoring job progress...")
start_time = time.time()
check_count = 0

while True:
    check_count += 1
    elapsed_time = time.time() - start_time
    print(f"\n⏱️  Check #{check_count} (elapsed: {elapsed_time:.1f}s)")
    
    status_response = requests.get(
        f"{BASE_URL}/jobs/{job_id}/",
        headers=headers
    )
    print_response(f"4.{check_count}: Check Status", status_response)
    status_response.raise_for_status()
    status_data = status_response.json()

    pc = status_data.get('percent_complete')
    pc_str = f" ({pc}%)" if pc is not None else ""
    status = status_data['status']
    
    print(f"📊 Status: {status}{pc_str}")
    
    # Print additional status details if available
    if 'current_step' in status_data:
        print(f"🔄 Current step: {status_data['current_step']}")
    if 'estimated_time_remaining' in status_data:
        print(f"⏰ ETA: {status_data['estimated_time_remaining']}")

    if status == "Finished":
        print("🎉 Processing complete!")
        break
    if status == "Failed":
        print("❌ Processing failed!")
        if 'error_message' in status_data:
            print(f"💥 Error: {status_data['error_message']}")
        break

    print("💤 Waiting 30 seconds before next check...")
    time.sleep(30)

# Step 5: Get results
if status_data["status"] == "Finished":
    print("\n🎁 Downloading results...")
    
    # Download PLY file (follows redirect automatically)
    print("📥 Attempting to download PLY file...")
    try:
        ply_response = requests.get(
            f"{BASE_URL}/jobs/{job_id}/download/ply/",
            headers=headers,
            stream=True
        )
        print_response("5.1: Download PLY", ply_response, show_json=False)
        
        if ply_response.status_code == 200:
            filename = f"{job_id}_scene.ply"
            with open(filename, 'wb') as f:
                downloaded = 0
                for chunk in ply_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (1024*1024) == 0:  # Print every MB
                            print(f"📥 Downloaded: {downloaded/1024/1024:.1f} MB")
            
            final_size = os.path.getsize(filename)
            print(f"✅ PLY file downloaded: {filename} ({final_size:,} bytes)")
        else:
            print("⚠️  PLY not available for this job")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading PLY file: {e}")

    # Download SPZ file (follows redirect automatically)
    print("📥 Attempting to download SPZ file...")
    try:
        spz_response = requests.get(
            f"{BASE_URL}/jobs/{job_id}/download/spz/",
            headers=headers,
            stream=True
        )
        print_response("5.2: Download SPZ", spz_response, show_json=False)
        
        if spz_response.status_code == 200:
            filename = f"{job_id}_scene.spz"
            with open(filename, 'wb') as f:
                downloaded = 0
                for chunk in spz_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (1024*1024) == 0:  # Print every MB
                            print(f"📥 Downloaded: {downloaded/1024/1024:.1f} MB")
            
            final_size = os.path.getsize(filename)
            print(f"✅ SPZ file downloaded: {filename} ({final_size:,} bytes)")
        else:
            print("⚠️  SPZ not available for this job")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading SPZ file: {e}")

    # Get preview image (302 redirect)
    print("🖼️  Getting preview image URL...")
    preview_head = requests.head(
        f"{BASE_URL}/jobs/{job_id}/preview/",
        headers=headers,
        allow_redirects=False
    )
    print_response("5.3: Get Preview URL", preview_head, show_json=False)
    
    if preview_head.status_code == 302:
        preview_url = preview_head.headers.get('Location')
        print(f"🖼️  Preview image URL: {preview_url}")
    else:
        print("⚠️  Preview image not available")

print(f"\n🏁 Script completed! Total runtime: {time.time() - start_time:.1f} seconds")