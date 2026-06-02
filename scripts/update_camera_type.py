import requests

API_KEY = "Your_API_Key_Here"
BASE_URL = "https://vid2scene.com/api/v1"
headers = {"Authorization": f"Api-Key {API_KEY}"}

job_id = "Your_Job_ID_Here"

# Step 1: Get the current job data (including camera_data)
response = requests.get(
    f"{BASE_URL}/jobs/{job_id}/",
    headers=headers
)
response.raise_for_status()
job_data = response.json()

# Step 2: Get the camera_data and add orbital type
camera_data = job_data.get('camera_data')

if camera_data:
    # If camera data exists, just add the cameraType
    print(f"Camera data exists: {camera_data}")
    camera_data['cameraType'] = 'orbital'
else:
    # If no camera data exists yet, create default values
    print("No camera data exists, creating default values")
    camera_data = {
        "lookAt": {"x": 0.0, "y": 0.0, "z": 0.0},
        "position": {"x": 0.0, "y": 0.0, "z": -3.0},
        "up": {"x": 0.0, "y": 1.0, "z": 0.0},
        "cameraType": "orbital"
    }

# Step 3: PATCH it back to update the job
update_response = requests.patch(
    f"{BASE_URL}/jobs/{job_id}/",
    headers={**headers, "Content-Type": "application/json"},
    json={"camera_data": camera_data}
)
update_response.raise_for_status()

print("✅ Camera type set to orbital!")
print(f"Response: {update_response.json()}")