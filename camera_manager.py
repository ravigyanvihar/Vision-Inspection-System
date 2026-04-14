import cv2
import numpy as np
import requests
from requests.auth import HTTPDigestAuth
import urllib3
import platform
import subprocess

# Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURATION ---
HTTP_USER = "onvif"
HTTP_PASS = "onvif_pass"

URL_TEMPLATE = "https://{ip}/onvif-http/snapshot?Profile_1"

class CameraManager:
    def __init__(self):
        self.caps = {} 
        self.status = {}
        
        for i in range(5):
            self.status[i] = {
                "ip": "Disabled", 
                "connected": False, 
                "error": "Not Configured",
                "type": "NONE",
                "lens_k1": 0.0,
                "lens_k2": 0.0
            }

    def _ping_ip(self, ip_address):
        """Pings the IP address directly."""
        try:
            if not ip_address: return False
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', ip_address]
            return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
        except:
            return False

    def start_camera(self, cam_id, source, lens_k1=-0.15, lens_k2=0.0):
        ip_address = str(source).strip()
        
        # Save BOTH curves into the status dictionary
        try:
            self.status[cam_id]["lens_k1"] = float(lens_k1)
            self.status[cam_id]["lens_k2"] = float(lens_k2)
        except ValueError:
            self.status[cam_id]["lens_k1"] = -0.15
            self.status[cam_id]["lens_k2"] = 0.0
        
        if not ip_address or ip_address == "0" or ip_address == "Disabled":
            self.status[cam_id]["ip"] = "Disabled"
            self.status[cam_id]["connected"] = False
            self.status[cam_id]["error"] = "Disabled"
            return False

        print(f"📷 Configuring Camera {cam_id} with IP: {ip_address}")

        self.status[cam_id]["ip"] = ip_address
        self.status[cam_id]["type"] = "HTTP"

        if "http" in ip_address:
            full_url = ip_address
        else:
            full_url = URL_TEMPLATE.format(ip=ip_address)

        self.caps[cam_id] = full_url

        if self._ping_ip(ip_address):
            self.status[cam_id]["connected"] = True
            self.status[cam_id]["error"] = "Online (Ping OK)"
            print(f"   ✅ Camera {cam_id} ({ip_address}) is Online")
            return True
        else:
            self.status[cam_id]["connected"] = False
            self.status[cam_id]["error"] = "Unreachable"
            print(f"   ❌ Camera {cam_id} ({ip_address}) Unreachable")
            return False

    def get_frame(self, cam_id):
        if cam_id not in self.caps:
            return False, None

        target_url = self.caps[cam_id]
        
        try:
            response = requests.get(
                target_url, 
                auth=HTTPDigestAuth(HTTP_USER, HTTP_PASS), 
                verify=False, 
                timeout=5
            )
            
            if response.status_code == 200:
                nparr = np.frombuffer(response.content, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if img is not None:
                    # --- APPLY LENS CORRECTION (PER-CAMERA) ---
                    current_k1 = self.status[cam_id].get("lens_k1", 0.0)
                    current_k2 = self.status[cam_id].get("lens_k2", 0.0)
                    
                    if current_k1 != 0.0 or current_k2 != 0.0:
                        h, w = img.shape[:2]
                        
                        focal_length = w
                        center_x = w / 2
                        center_y = h / 2
                        camera_matrix = np.array([
                            [focal_length, 0, center_x],
                            [0, focal_length, center_y],
                            [0, 0, 1]
                        ], dtype=np.float32)
                        
                        # OpenCV expects: [k1, k2, p1, p2, k3]. Inject k1 and k2!
                        dist_coeffs = np.array([current_k1, current_k2, 0, 0, 0], dtype=np.float32)
                        
                        # Calculate the optimal crop so we don't end up with black curved edges
                        new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
                            camera_matrix, dist_coeffs, (w, h), 1, (w, h)
                        )
                        
                        # Actually flatten the image
                        img = cv2.undistort(img, camera_matrix, dist_coeffs, None, new_camera_matrix)
                        
                        # Crop out the weird black edges created by pushing the corners out
                        x, y, crop_w, crop_h = roi
                        img = img[y:y+crop_h, x:x+crop_w]
                    # -----------------------------

                    self.status[cam_id]["error"] = "Active"
                    return True, img
            else:
                self.status[cam_id]["error"] = f"HTTP {response.status_code}"
                print(f"   ❌ HTTP Error: {response.status_code}")

        except Exception as e:
            self.status[cam_id]["error"] = "Timeout"
            
        return False, None

    def stop_camera(self, cam_id):
        if cam_id in self.caps: del self.caps[cam_id]
        self.status[cam_id]["connected"] = False
        self.status[cam_id]["error"] = "Stopped"

    def get_jpeg_frame(self, cam_id):
        success, frame = self.get_frame(cam_id)
        if success and frame is not None:
            try:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret: return buffer.tobytes()
            except: pass
        return None

    def get_all_status(self):
        return self.status
