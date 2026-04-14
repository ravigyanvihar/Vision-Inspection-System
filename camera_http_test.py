import requests
from requests.auth import HTTPDigestAuth
import cv2
import numpy as np
import urllib3
import time
import os  # Added for folder and path management
from datetime import datetime  # Added for timestamps

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Configuration ---
URL = "https://192.168.1.64/onvif-http/snapshot?Profile_1"
USER = "onvif"
PASS = "Sunbeam_12"
SAVE_FOLDER = "images"

def take_timed_snapshot():
    # 1. Create the folder if it doesn't exist
    if not os.path.exists(SAVE_FOLDER):
        os.makedirs(SAVE_FOLDER)
        print(f"Created folder: {SAVE_FOLDER}")

    try:
        start_time = time.perf_counter()

        response = requests.get(
            URL, 
            auth=HTTPDigestAuth(USER, PASS), 
            verify=False, 
            timeout=10
        )
        
        end_time = time.perf_counter()
        total_time = end_time - start_time

        if response.status_code == 200:
            nparr = np.frombuffer(response.content, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is not None:
                # 2. Generate a unique filename using current date and time
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"snapshot_{timestamp}.jpg"
                filepath = os.path.join(SAVE_FOLDER, filename)

                # 3. Save the image in full resolution
                cv2.imwrite(filepath, img)

                print("-" * 30)
                print(f"✅ Success!")
                print(f"📁 Saved to: {filepath}")
                print(f"⏱️ Total Script Time:  {total_time:.3f} seconds")
                print("-" * 30)
                return img
        else:
            print(f"❌ Failed: Status {response.status_code}")
            
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")
    return None

# Run the test
image = take_timed_snapshot()

if image is not None:
    # Display at 50% scale for preview, but original is saved in full resolution
    cv2.imshow("Preview (Press any key)", cv2.resize(image, (0,0), fx=0.5, fy=0.5))
    cv2.waitKey(0)
    cv2.destroyAllWindows()