import cv2
import threading
import time

# Import the wrapper we created. 
# This MUST exist in the same folder as app.py
try:
    from hik_driver import HikCamera
except ImportError:
    print("❌ CRITICAL ERROR: 'hik_driver.py' not found. Please create it.")
    raise

class CameraManager:
    def __init__(self):
        # Stores active HikCamera objects: { 0: HikCameraObject, 1: ... }
        self.caps = {} 
        self.status = {}
        
        # Initialize status slots for 5 cameras
        for i in range(5):
            self.status[i] = {
                "ip": "Disabled", 
                "connected": False, 
                "error": "Not Configured"
            }

    def start_camera(self, cam_id, ip_address):
        """
        Connects exclusively using the Hikrobot Driver.
        """
        # 1. Update Status Text for UI
        self.status[cam_id]["ip"] = str(ip_address)
        
        # 2. Cleanup old connection if exists
        self.stop_camera(cam_id)

        print(f"📷 [Hikrobot] Connecting Camera {cam_id} to {ip_address}...")

        try:
            # Instantiate the driver wrapper
            new_cam = HikCamera(ip_address=str(ip_address))
            
            # Attempt to open (This calls the MVS SDK internally)
            if new_cam.open():
                self.caps[cam_id] = new_cam
                self.status[cam_id]["connected"] = True
                self.status[cam_id]["error"] = "Hikrobot Active"
                print(f"✅ Hikrobot Camera {cam_id} Connected Successfully!")
                return True
            else:
                self.status[cam_id]["connected"] = False
                self.status[cam_id]["error"] = "Open Failed (Check IP/Power)"
                print(f"❌ Hikrobot Camera {cam_id} Failed to open.")
                return False

        except Exception as e:
            print(f"❌ Exception initializing Hikrobot {cam_id}: {e}")
            self.status[cam_id]["connected"] = False
            self.status[cam_id]["error"] = str(e)
            return False

    def stop_camera(self, cam_id):
        if cam_id in self.caps:
            try:
                self.caps[cam_id].release() # Calls MV_CC_StopGrabbing / CloseDevice
            except Exception as e:
                print(f"⚠️ Error stopping camera {cam_id}: {e}")
            del self.caps[cam_id]
        
        # Update status
        self.status[cam_id]["connected"] = False
        self.status[cam_id]["error"] = "Stopped"

    def get_frame(self, cam_id):
        """
        Reads a frame from the Hikrobot camera.
        Returns: (success, numpy_image)
        """
        if cam_id in self.caps:
            # The hik_driver.read() method already returns (True, image) 
            # in a format identical to OpenCV, so the rest of your app works fine.
            return self.caps[cam_id].read()
            
        return False, None

    def get_jpeg_frame(self, cam_id):
        """Helper to get JPEG bytes for the Web UI (Live Feed)"""
        success, frame = self.get_frame(cam_id)
        if success and frame is not None:
            try:
                # Compress raw numpy array to JPEG
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    return buffer.tobytes()
            except Exception as e:
                print(f"Error encoding JPEG: {e}")
        return None

    def get_all_status(self):
        """Returns the status dictionary for the UI."""
        return self.status