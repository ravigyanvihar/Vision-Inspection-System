import os
import json
import traceback
import base64
from flask import Flask, request, redirect, url_for, render_template, flash, jsonify, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from plc_worker import PLCWorker
from camera_manager import CameraManager
import cv2
from inspection_engine import run_full_inspection
from datetime import datetime
import shutil
import time
import glob
from datetime import datetime
from flask import send_from_directory
import shutil
from datetime import datetime, timedelta



import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)


app.secret_key = 'super_secret_key_for_session_management'

# ==========================================
# 1. GLOBAL SETTINGS & FILE PATHS
# ==========================================
SYSTEM_SETTINGS = None
CURRENT_ACTIVE_RECIPE = None # Holds the recipe data currently loaded for inspection
GLOBAL_INSPECTION_RESULTS = {} # <--- NEW: Stores results for the web UI


# Updated Global State
GLOBAL_SYSTEM_STATE = {
    "last_update": "Waiting...",
    "inspection_id": 0,  # <--- Added this to track unique events
    "overall_status": "IDLE",
    "recipe_name": "None",
    "results": {}
}



plc_thread_instance = None
camera_manager_instance = CameraManager()
CONFIG_FOLDER = 'config'
RECIPE_FOLDER = 'recipes'
CONFIG_FILE = os.path.join(CONFIG_FOLDER, 'settings.json')
CLASSES_FILE = os.path.join('static', 'classes.txt')
LAST_RECIPE_STATE = os.path.join(CONFIG_FOLDER, 'last_active.json')
LATEST_IMG_FOLDER = os.path.join('static', 'cam_latest')
TEMP_IMG_FOLDER = os.path.join('static', 'temp') 

def ensure_folders():
    if not os.path.exists(CONFIG_FOLDER): os.makedirs(CONFIG_FOLDER)
    if not os.path.exists(RECIPE_FOLDER): os.makedirs(RECIPE_FOLDER)
    if not os.path.exists(LATEST_IMG_FOLDER): os.makedirs(LATEST_IMG_FOLDER)
    if not os.path.exists(TEMP_IMG_FOLDER): os.makedirs(TEMP_IMG_FOLDER)

def load_classes():
    """Reads static/classes.txt using absolute path."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    class_file = os.path.join(base_dir, 'static', 'classes.txt')
    
    if not os.path.exists(class_file):
        return ["default_object"] 
    
    with open(class_file, 'r') as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def get_existing_recipes():
    """Returns list of folder names that contain valid recipe.json files"""
    if not os.path.exists(RECIPE_FOLDER):
        return []
    
    valid_folders = []
    for item in os.listdir(RECIPE_FOLDER):
        full_path = os.path.join(RECIPE_FOLDER, item)
        if os.path.isdir(full_path):
            if os.path.exists(os.path.join(full_path, "recipe.json")):
                valid_folders.append(item)
    
    return sorted(valid_folders)


def save_last_recipe(filename):
    with open(LAST_RECIPE_STATE, 'w') as f:
        json.dump({"filename": filename}, f)

def load_last_recipe():
    """Reads the last used recipe folder from disk and loads it into memory on boot."""
    global CURRENT_ACTIVE_RECIPE, GLOBAL_SYSTEM_STATE
    
    if os.path.exists(LAST_RECIPE_STATE):
        try:
            with open(LAST_RECIPE_STATE, 'r') as f:
                data = json.load(f)
                folder_name = data.get('filename') # This actually holds the folder name
                
            if folder_name:
                json_path = os.path.join(RECIPE_FOLDER, folder_name, "recipe.json")
                if os.path.exists(json_path):
                    with open(json_path, 'r') as rf:
                        CURRENT_ACTIVE_RECIPE = json.load(rf)
                        CURRENT_ACTIVE_RECIPE['folder_name'] = folder_name
                        
                        # Sync the global state for the display page immediately
                        GLOBAL_SYSTEM_STATE["recipe_name"] = folder_name
                        GLOBAL_SYSTEM_STATE["overall_status"] = "READY"
                        print(f"🔄 Auto-loaded last recipe: {folder_name}")
                else:
                    print(f"⚠️ Last used recipe folder '{folder_name}' no longer exists.")
        except Exception as e:
            print(f"⚠️ Failed to auto-load recipe: {e}")




def cleanup_old_history(days_to_keep=30):
    """Scans the history folder and permanently deletes folders older than 30 days."""
    history_dir = 'history'
    if not os.path.exists(history_dir):
        return

    # Calculate the exact date 30 days ago
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)

    for folder_name in os.listdir(history_dir):
        folder_path = os.path.join(history_dir, folder_name)

        # Skip files like 'daily_counter.json'
        if not os.path.isdir(folder_path):
            continue

        try:
            # Try to read the folder name as a date (e.g., "2026-03-15")
            folder_date = datetime.strptime(folder_name, "%Y-%m-%d")
            
            # If the folder date is older than 30 days ago, delete it
            if folder_date < cutoff_date:
                print(f"🧹 MAINTENANCE: Deleting old history data -> {folder_name}")
                shutil.rmtree(folder_path) # Deletes the folder and all images inside
                
        except ValueError:
            # If a folder isn't named like a date, just ignore it safely
            pass

def get_next_inspection_id():
    """Reads the last ID, resets if it's a new day, cleans up old files, and returns new ID."""
    id_file = os.path.join('history', 'daily_counter.json')
    os.makedirs('history', exist_ok=True)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_id = 0
    saved_date = ""
    
    if os.path.exists(id_file):
        try:
            with open(id_file, 'r') as f:
                data = json.load(f)
                saved_date = data.get("date", "")
                current_id = data.get("last_id", 0)
        except Exception:
            pass 
            
    # Reset logic: Same day = add 1. New day = reset to 1 AND run maintenance.
    if today_str == saved_date:
        next_id = current_id + 1
    else:
        next_id = 1
        
        # ==========================================================
        # ✅ AUTOMATIC MAINTENANCE: Run cleanup on the first trigger of a new day!
        # ==========================================================
        try:
            cleanup_old_history(days_to_keep=30)
        except Exception as e:
            print(f"⚠️ Maintenance Error: {e}")
        
    with open(id_file, 'w') as f:
        json.dump({"date": today_str, "last_id": next_id}, f)
        
    return next_id


@app.route('/api/get_date_stats/<date>')
def get_date_stats(date):
    """Calculates deep analytics for a specific date."""
    date_path = os.path.join('history', date)
    if not os.path.exists(date_path):
        return jsonify({"status": "error", "message": "Date not found"}), 404
        
    stats = {
        "total_inspections": 0,
        "passed": 0,
        "failed": 0,
        "camera_fails": {},
        "tool_fails": {}
    }
    
    ids = [i for i in os.listdir(date_path) if os.path.isdir(os.path.join(date_path, i))]
    stats["total_inspections"] = len(ids)
    
    for i in ids:
        id_path = os.path.join(date_path, i)
        reports = [f for f in os.listdir(id_path) if f.endswith('_report.json')]
        
        inspection_failed = False
        
        for r in reports:
            cam_name = f"Camera {int(r.split('_')[1]) + 1}"
            try:
                with open(os.path.join(id_path, r), 'r') as f:
                    data = json.load(f)
                    
                    if data.get("overall_result") != "PASS":
                        inspection_failed = True
                        stats["camera_fails"][cam_name] = stats["camera_fails"].get(cam_name, 0) + 1
                        
                        # Dig into regions to find EXACTLY what tool failed
                        for region in data.get("regions", []):
                            if region.get("result") != "PASS":
                                tool = region.get("region_method", "Unknown Tool")
                                stats["tool_fails"][tool] = stats["tool_fails"].get(tool, 0) + 1
            except Exception:
                pass
                
        if inspection_failed:
            stats["failed"] += 1
        else:
            stats["passed"] += 1
            
    return jsonify(stats)

def save_to_history(inspection_id, cam_id, report, annotated_frame):
    """Saves the permanent record to history/YYYY-MM-DD/ID/"""
    
    # Extract the exact date string from the JSON report (e.g. "2026-04-15")
    inspection_date = report.get("time", datetime.now().strftime("%Y-%m-%d")).split(" ")[0]
    
    # Create the nested folder: history/2026-04-15/1/
    folder_path = os.path.join('history', inspection_date, str(inspection_id))
    os.makedirs(folder_path, exist_ok=True) 

    # 1. Save Image
    img_path = os.path.join(folder_path, f"cam_{cam_id}_result.jpg")
    cv2.imwrite(img_path, annotated_frame)

    # 2. Save JSON
    json_path = os.path.join(folder_path, f"cam_{cam_id}_report.json")
    def clean_numpy(obj):
        if hasattr(obj, 'item'): return obj.item()
        return str(obj)
        
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=4, default=clean_numpy)

# ==========================================
# HISTORY VIEWER ROUTES
# ==========================================

# ==========================================
# HISTORY VIEWER ROUTES (OPTIMIZED)
# ==========================================
@app.route('/history')
def view_history():
    return render_template('history.html', active_page='history')

@app.route('/api/get_history_summary')
def get_history_summary():
    """Returns ONLY the lightweight list of IDs and Statuses to prevent crashing."""
    history_summary = {}
    
    if os.path.exists('history'):
        dates = sorted([d for d in os.listdir('history') if os.path.isdir(os.path.join('history', d))], reverse=True)
        
        for date in dates:
            history_summary[date] = []
            date_path = os.path.join('history', date)
            
            ids = [i for i in os.listdir(date_path) if os.path.isdir(os.path.join(date_path, i))]
            try:
                ids.sort(key=int, reverse=True) # Sort newest first
            except ValueError:
                pass 
                
            for i in ids:
                id_path = os.path.join(date_path, i)
                reports = [f for f in os.listdir(id_path) if f.endswith('_report.json')]
                
                if not reports:
                    continue
                    
                # Read just the FIRST report quickly to grab the time and status
                status = "FAIL" 
                time_str = "--:--"
                try:
                    with open(os.path.join(id_path, reports[0]), 'r') as f:
                        data = json.load(f)
                        time_str = data.get("time", "Unknown").split(" ")[1] 
                        status = data.get("overall_result", "ERROR")
                except Exception:
                    pass
                
                history_summary[date].append({
                    "id": i,
                    "time": time_str,
                    "status": status
                })

    return jsonify(history_summary)

@app.route('/api/get_inspection_details/<date>/<inspection_id>')
def get_inspection_details(date, inspection_id):
    """Fetches the heavy data and images ONLY when the user clicks an ID."""
    id_path = os.path.join('history', date, inspection_id)
    
    if not os.path.exists(id_path):
        return jsonify({"status": "error", "message": "Inspection not found"}), 404

    reports = [f for f in os.listdir(id_path) if f.endswith('_report.json')]
    inspection_data = {"id": inspection_id, "date": date, "cameras": []}
    
    for r in reports:
        cam_id = r.split('_')[1] 
        try:
            with open(os.path.join(id_path, r), 'r') as f:
                data = json.load(f)
                inspection_data["cameras"].append({
                    "cam_name": f"Camera {int(cam_id) + 1}",
                    "status": data.get("overall_result", "ERROR"),
                    "image_url": f"/history_img/{date}/{inspection_id}/cam_{cam_id}_result.jpg",
                    "regions": data.get("regions", []) # Send the detailed tool data
                })
        except Exception:
            pass
            
    return jsonify(inspection_data)

@app.route('/history_img/<date>/<inspection_id>/<filename>')
def serve_history_img(date, inspection_id, filename):
    path = os.path.join('history', date, inspection_id)
    return send_from_directory(path, filename)







@app.route('/delete_recipe', methods=['POST'])
@login_required
def delete_recipe():
    global CURRENT_ACTIVE_RECIPE
    try:
        data = request.json
        recipe_name = data.get('recipe_name')
        if not recipe_name:
            return jsonify({"status": "error", "message": "No recipe specified"}), 400

        # Sanitize folder name just like we do when saving
        safe_folder_name = "".join([c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(' ', '_')
        target_dir = os.path.join(RECIPE_FOLDER, safe_folder_name)

        if os.path.exists(target_dir):
            import shutil
            shutil.rmtree(target_dir) # Permanently deletes the folder and everything inside it
            
            # If the user deleted the recipe that is currently running, clear it from memory
            if CURRENT_ACTIVE_RECIPE and CURRENT_ACTIVE_RECIPE.get('folder_name') == safe_folder_name:
                CURRENT_ACTIVE_RECIPE = None
                
            return jsonify({"status": "success", "message": "Recipe deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Recipe not found on disk"}), 404
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



def initialize_settings():
    global SYSTEM_SETTINGS
    ensure_folders()

    if not os.path.exists(CONFIG_FILE):
        default_settings = {
            "machine": {"name": "Vision Station 01"},
            "plc": {"ip": "127.0.0.1"},
            "cameras": [
                {"id": 0, "enabled": True, "ip": "192.168.1.100", "lens_k1": -0.15, "lens_k2": 0.0},
                {"id": 1, "enabled": True, "ip": "192.168.1.101", "lens_k1": -0.15, "lens_k2": 0.0},
                {"id": 2, "enabled": False, "ip": "192.168.1.102", "lens_k1": -0.15, "lens_k2": 0.0},
                {"id": 3, "enabled": False, "ip": "192.168.1.103", "lens_k1": -0.15, "lens_k2": 0.0},
                {"id": 4, "enabled": False, "ip": "192.168.1.104", "lens_k1": -0.15, "lens_k2": 0.0}
            ]
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_settings, f, indent=4)
        SYSTEM_SETTINGS = default_settings
    else:
        with open(CONFIG_FILE, 'r') as f:
            SYSTEM_SETTINGS = json.load(f)





import numpy as np

def clean_for_json(obj):
    """
    Recursively converts OpenCV/Numpy data types into standard 
    web-safe Python types to prevent JSON serialization errors.
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    return obj




import traceback

# ==========================================
# HARDWARE PLC TRIGGER LOGIC (FIXED & PROTECTED)
# ==========================================
def hardware_trigger_callback():
    """
    Executed by the PLC Worker thread when a hardware trigger is received.
    """
    global CURRENT_ACTIVE_RECIPE, SYSTEM_SETTINGS, GLOBAL_INSPECTION_RESULTS, GLOBAL_SYSTEM_STATE
    
    start_time = time.time()
    
    try:
        print("\n" + "="*40)
        print("⚡ PLC HARDWARE TRIGGER RECEIVED ⚡")
        print("="*40)
        
        if not CURRENT_ACTIVE_RECIPE:
            print("❌ ABORTED: No Recipe Loaded.")
            return
            
        if plc_thread_instance:
            plc_thread_instance.set_register(address=3, value=0)
            
        overall_system_pass = True
        local_results = {} # Temporary storage for this specific trigger
        
        camera_configs = SYSTEM_SETTINGS.get('cameras', [])
        iterator = camera_configs.items() if isinstance(camera_configs, dict) else enumerate(camera_configs)

        # ==========================================================
        # ✅ THE FIX: CREATE THE SIMPLE COUNTER ID (1, 2, 3...)
        # ==========================================================
        new_id = get_next_inspection_id()

        # --- START CAMERA LOOP ---
        for cam_id_raw, cam_info in iterator:
            cam_id = int(cam_id_raw)
            if not cam_info.get('enabled', False):
                continue
                
            success, frame = camera_manager_instance.get_frame(cam_id)
            if not success or frame is None:
                overall_system_pass = False
                continue
                
            recipe_payload = CURRENT_ACTIVE_RECIPE.get('data', CURRENT_ACTIVE_RECIPE)
            folder_name = CURRENT_ACTIVE_RECIPE.get('folder_name', 'default')
            
            report, annotated_frame = run_full_inspection(frame, recipe_payload, folder_name, cam_id)
            
            if report.get("overall_result") != "PASS":
                overall_system_pass = False
                
            img_filename = f"cam_{cam_id}_latest.jpg"
            img_path = os.path.join(LATEST_IMG_FOLDER, img_filename)
            cv2.imwrite(img_path, annotated_frame)
            
            # ==========================================================
            # ✅ THE FIX: SAVE PERMANENT COPY TO HISTORY FOLDER
            # ==========================================================
            save_to_history(new_id, cam_id, report, annotated_frame)
            
            # Save to temporary local results
            local_results[str(cam_id)] = clean_for_json({
                "name": f"Camera {cam_id + 1}",
                "status": report.get("overall_result", "ERROR"),
                "image_url": f"/static/cam_latest/{img_filename}?t={time.time()}",
                "inspections": report
            })
        # --- END CAMERA LOOP ---


        # ==========================================================
        # ✅ THE FIX: USE THE NEW COUNTER ID FOR THE DASHBOARD
        # ==========================================================
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        # 1. Update the ID to trigger the HTML "Latch"
        GLOBAL_SYSTEM_STATE["inspection_id"] = new_id 
        
        # 2. Update the metadata for the display
        GLOBAL_SYSTEM_STATE["last_update"] = datetime.now().strftime("%H:%M:%S")
        GLOBAL_SYSTEM_STATE["inspection_time_ms"] = duration_ms
        GLOBAL_SYSTEM_STATE["overall_status"] = "PASS" if overall_system_pass else "FAIL"
        
        # 3. Update the actual data
        GLOBAL_SYSTEM_STATE["results"] = local_results
        GLOBAL_INSPECTION_RESULTS.update(local_results) 
        # ==========================================================


        # --- FINAL PLC COMMUNICATION ---
        if overall_system_pass:
            print(f"🏁 PASS ({duration_ms}ms)")
            if plc_thread_instance:
                plc_thread_instance.set_register(address=1, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=3, value=1)
        else:
            print(f"🏁 FAIL ({duration_ms}ms)")
            if plc_thread_instance:
                plc_thread_instance.set_register(address=2, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=4, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=3, value=1)

    except Exception as e:
        print("\n❌ CRITICAL CRASH IN HARDWARE_TRIGGER_CALLBACK:")
        import traceback
        traceback.print_exc()



# ==========================================
# 5. UI TRIGGER (MANUAL WEBPAGE INSPECT)
# ==========================================
@app.route('/trigger_inspection', methods=['POST'])
def trigger_inspection():
    global CURRENT_ACTIVE_RECIPE, SYSTEM_SETTINGS, GLOBAL_INSPECTION_RESULTS, GLOBAL_SYSTEM_STATE
    
    try:
        if not CURRENT_ACTIVE_RECIPE:
            return jsonify({"status": "error", "message": "No Active Recipe."}), 400
            
        if plc_thread_instance:
            plc_thread_instance.set_register(address=3, value=0)

        results = {}
        overall_system_pass = True

        camera_configs = SYSTEM_SETTINGS.get('cameras', [])
        iterator = camera_configs.items() if isinstance(camera_configs, dict) else enumerate(camera_configs)

        # ==========================================================
        # ✅ GENERATE ID BEFORE THE LOOP (Crucial for saving)
        # ==========================================================
        new_id = get_next_inspection_id()

        # --- START CAMERA LOOP ---
        for cam_id_raw, cam_info in iterator:
            cam_id = int(cam_id_raw)
            if not cam_info.get('enabled', False):
                continue
                
            success, frame = camera_manager_instance.get_frame(cam_id)
            if not success or frame is None:
                overall_system_pass = False
                if plc_thread_instance:
                    plc_thread_instance.set_register(address=4, value=1, hold_time=2.0)
                continue
                
            recipe_payload = CURRENT_ACTIVE_RECIPE.get('data', CURRENT_ACTIVE_RECIPE)
            folder_name = CURRENT_ACTIVE_RECIPE.get('folder_name', 'default')
            
            # Run Vision Engine
            report, annotated_frame = run_full_inspection(frame, recipe_payload, folder_name, cam_id)
            
            if report.get("overall_result") != "PASS":
                overall_system_pass = False
                
            # 1. Save temporary image for the Web UI
            img_filename = f"cam_{cam_id}_manual.jpg"
            img_path = os.path.join(LATEST_IMG_FOLDER, img_filename)
            cv2.imwrite(img_path, annotated_frame)
            
            # 2. Save permanent copy to history/1/, history/2/, etc.
            save_to_history(new_id, cam_id, report, annotated_frame)
            
            results[str(cam_id)] = {
                "cam_id": cam_id,
                "name": f"Camera {cam_id + 1}", 
                "status": report.get("overall_result", "ERROR"),  
                "image_url": f"/static/cam_latest/{img_filename}?t={time.time()}",
                "inspections": report
            }
        # --- END CAMERA LOOP ---

        # ==========================================================
        # ✅ UPDATE GLOBAL STATE AFTER ALL CAMERAS ARE DONE
        # ==========================================================
        GLOBAL_SYSTEM_STATE["inspection_id"] = new_id
        GLOBAL_SYSTEM_STATE["last_update"] = datetime.now().strftime("%H:%M:%S")
        GLOBAL_SYSTEM_STATE["overall_status"] = "PASS" if overall_system_pass else "FAIL"
        
        # Sync results to global storage for the polling API
        GLOBAL_INSPECTION_RESULTS.update(results)
        GLOBAL_SYSTEM_STATE["results"] = results 

        # ==========================================
        # FINAL PLC COMMUNICATION 
        # ==========================================
        if overall_system_pass:
            print("🌐 WEB INSPECT COMPLETE: PASS")
            if plc_thread_instance:
                plc_thread_instance.set_register(address=1, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=3, value=1)
        else:
            print("🌐 WEB INSPECT COMPLETE: FAIL (NOK)")
            if plc_thread_instance:
                plc_thread_instance.set_register(address=2, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=4, value=1, hold_time=2.0)
                plc_thread_instance.set_register(address=3, value=1)
                
        def clean_numpy(obj):
            if hasattr(obj, 'item'): return obj.item()
            return str(obj)
            
        safe_results = json.loads(json.dumps(results, default=clean_numpy))
        
        # Return the new_id so JS can update its 'lastRenderedId' latch
        return jsonify({
            "status": "success", 
            "overall_pass": overall_system_pass,
            "results": safe_results,
            "inspection_id": new_id
        })

    except Exception as e:
        print(f"\n❌ CRITICAL CRASH IN TRIGGER_INSPECTION ❌")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Server crash: {str(e)}"}), 500





def load_system_settings():
    """Helper to cleanly load settings from disk."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return SYSTEM_SETTINGS

def save_settings_to_disk(new_data):
    global SYSTEM_SETTINGS
    SYSTEM_SETTINGS = new_data
    with open(CONFIG_FILE, 'w') as f:
        json.dump(new_data, f, indent=4)

initialize_settings()


# ==========================================
# 1.5 NEW: MASTER HARDWARE CONFIGURATOR
# ==========================================
def apply_hardware_settings(config_data):
    """
    Pushes the current configuration dictionary to all physical hardware.
    """
    global plc_thread_instance
    
    print("\n" + "="*40)
    print("⚙️ APPLYING HARDWARE SETTINGS...")
    print("="*40)
    
    # 1. Apply PLC Settings
    plc_ip = config_data.get('plc', {}).get('ip', '127.0.0.1')
    print(f"🎯 Configuring PLC at: {plc_ip}")
    
    if plc_thread_instance: 
        plc_thread_instance.stop()
        
    # <--- NEW: Replaced run_inspection_logic_internal with our new function
    plc_thread_instance = PLCWorker(ip=plc_ip, trigger_callback=hardware_trigger_callback)
    plc_thread_instance.start()
    
    # 2. Apply Camera Settings
    camera_configs = config_data.get('cameras', [])
    print(f"\n📷 Configuring Camera Slots...")
    
    for i in range(5):
        cam_conf = camera_configs[i] if i < len(camera_configs) else {}
        
        target_ip = cam_conf.get('ip', '0')
        is_enabled = cam_conf.get('enabled', False)
        lens_k1 = cam_conf.get('lens_k1', -0.15)
        lens_k2 = cam_conf.get('lens_k2', 0.0)  # <--- Read k2 from dictionary
        
        # Update UI Status text
        camera_manager_instance.status[i]["ip"] = str(target_ip)
        
        if is_enabled:
            print(f"   🟢 Starting Camera {i+1} [{target_ip}] (Curves: k1={lens_k1}, k2={lens_k2})")
            # Pass BOTH curves to the Camera Manager
            camera_manager_instance.start_camera(i, target_ip, lens_k1, lens_k2)
        else:
            print(f"   🔴 Stopping Camera {i+1}")
            camera_manager_instance.stop_camera(i)
            camera_manager_instance.status[i]["error"] = "Disabled"
            camera_manager_instance.status[i]["connected"] = False
            
    print("="*40 + "\n")

# ==========================================
# 2. FLASK-LOGIN SETUP
# ==========================================

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

users = { "admin": {"password": "1234"} }

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id) if user_id in users else None


# ==========================================
# 3. CAMERA INTERFACE
# ==========================================

@app.route('/camera_status')
@login_required
def camera_status():
    return render_template('camera_status.html')

@app.route('/api/camera_status')
@login_required
def api_camera_status():
    return jsonify(camera_manager_instance.get_all_status())

@app.route('/snapshot/<int:cam_id>')
def snapshot(cam_id):
    jpeg_bytes = camera_manager_instance.get_jpeg_frame(cam_id)
    if jpeg_bytes:
        return Response(jpeg_bytes, mimetype='image/jpeg')
    else:
        return "Camera Offline", 503

def capture_snapshot_base64(cam_id):
    success, frame = camera_manager_instance.get_frame(cam_id)
    if success and frame is not None:
        try:
            retval, buffer = cv2.imencode('.jpg', frame)
            b64_str = base64.b64encode(buffer).decode('utf-8')
            return True, f"data:image/jpeg;base64,{b64_str}"
        except Exception as e:
            print(f"❌ Encoding Error Cam {cam_id}: {e}")
    return False, ""


# ==========================================
# 4. ROUTES
# ==========================================

@app.route('/')
def home():
    return redirect(url_for('inspection')) if current_user.is_authenticated else redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            user = User(username)
            login_user(user)
            return redirect(url_for('inspection'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/inspection')
@login_required
def inspection():
    recipes = [
        d for d in os.listdir(RECIPE_FOLDER) 
        if os.path.isdir(os.path.join(RECIPE_FOLDER, d)) and d != 'images'
    ]
    return render_template(
        'inspection.html', 
        available_recipes=recipes, 
        current_recipe=CURRENT_ACTIVE_RECIPE
    )


@app.route('/set_active_recipe', methods=['POST'])
@login_required
def set_active_recipe():
    global CURRENT_ACTIVE_RECIPE, GLOBAL_SYSTEM_STATE
    folder_name = request.form.get('recipe_filename')
    
    if not folder_name:
        flash("Please select a recipe.")
        return redirect(url_for('inspection'))

    # Your specific structure: recipes/FOLDER_NAME/recipe.json
    json_path = os.path.join(RECIPE_FOLDER, folder_name, "recipe.json")

    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                CURRENT_ACTIVE_RECIPE = json.load(f)
            
            # Set the metadata so the UI knows what is running
            CURRENT_ACTIVE_RECIPE['folder_name'] = folder_name
            
            # --- NEW: Persistence ---
            # Save the folder name to last_active.json
            save_last_recipe(folder_name)
            
            # --- NEW: Update Operator Dashboard State ---
            GLOBAL_SYSTEM_STATE["recipe_name"] = folder_name
            GLOBAL_SYSTEM_STATE["overall_status"] = "READY"
            GLOBAL_SYSTEM_STATE["last_update"] = datetime.now().strftime("%H:%M:%S")
            
            flash(f"Successfully loaded: {folder_name}")
        except Exception as e:
            flash(f"Error reading recipe file: {e}")
            print(f"❌ Recipe Load Error: {e}")
    else:
        flash(f"Recipe file not found at: {json_path}")
        
    return redirect(url_for('inspection'))



@app.route('/capture_single_frame/<int:cam_id>', methods=['POST'])
@login_required
def capture_single_frame(cam_id):
    status = camera_manager_instance.status.get(cam_id, {})
    if not status.get("connected"):
        return jsonify({"status": "error", "message": "Camera not connected"}), 400

    success, frame = camera_manager_instance.get_frame(cam_id)
    
    if success and frame is not None:
        ensure_folders()
        filename = f"cam_{cam_id}.jpg"
        save_path = os.path.join(LATEST_IMG_FOLDER, filename)
        cv2.imwrite(save_path, frame)
        
        return jsonify({
            "status": "success", 
            "image_url": url_for('static', filename=f'cam_latest/{filename}')
        })
    
    return jsonify({"status": "error", "message": "Failed to capture image"}), 500




import glob

# ==========================================
# YOLO MODEL & CLASS UPLOAD ROUTES
# ==========================================

@app.route('/upload_yolo_files', methods=['POST'])
@login_required
def upload_yolo_files():
    recipe_name = request.form.get('recipe_name', '').strip()
    if not recipe_name:
        return jsonify({"status": "error", "message": "Recipe Name is required to upload models."}), 400

    # Ensure clean folder name
    safe_folder_name = "".join([c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(' ', '_')
    yolo_dir = os.path.join(RECIPE_FOLDER, safe_folder_name, "yolo")
    
    # Create the yolo directory inside the recipe folder if it doesn't exist
    os.makedirs(yolo_dir, exist_ok=True)

    pt_file = request.files.get('pt_file')
    txt_file = request.files.get('txt_file')

    if not pt_file and not txt_file:
         return jsonify({"status": "error", "message": "No files provided."}), 400

    # SAFETY FEATURE: Delete existing .pt and .txt files so they don't conflict
    if pt_file:
        for f in glob.glob(os.path.join(yolo_dir, "*.pt")):
            os.remove(f)
    if txt_file:
        for f in glob.glob(os.path.join(yolo_dir, "*.txt")):
            os.remove(f)

    # Save the new files with standard names so the Inspection Engine always knows what to load
    if pt_file:
        pt_path = os.path.join(yolo_dir, "model.pt")
        pt_file.save(pt_path)
    
    if txt_file:
        txt_path = os.path.join(yolo_dir, "classes.txt")
        txt_file.save(txt_path)

    return jsonify({"status": "success", "message": "YOLO files updated successfully!"})


@app.route('/api/get_recipe_classes', methods=['GET'])
@login_required
def get_recipe_classes():
    """Reads the classes.txt from the active recipe folder and returns it to the dropdown."""
    recipe_name = request.args.get('recipe_name', '').strip()
    safe_folder_name = "".join([c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(' ', '_')
    
    classes_path = os.path.join(RECIPE_FOLDER, safe_folder_name, "yolo", "classes.txt")
    classes = []
    
    if os.path.exists(classes_path):
        with open(classes_path, 'r') as f:
            classes = [line.strip() for line in f.readlines() if line.strip()]
            
    return jsonify({"status": "success", "classes": classes})



@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    global SYSTEM_SETTINGS
    
    if request.method == 'POST':
        # Create a fresh copy to update
        new_settings = SYSTEM_SETTINGS.copy()
        
        new_settings['machine']['name'] = request.form.get('machine_name', 'Default Machine')
        new_settings['plc']['ip'] = request.form.get('plc_ip', '127.0.0.1')
        
        for i in range(5):
            # Ensure the camera dictionary exists
            while len(new_settings['cameras']) <= i:
                new_settings['cameras'].append({})
                
            # Extract values from HTML form
            is_enabled = request.form.get(f'cam_{i}_enable') == 'on'
            ip_address = request.form.get(f'cam_{i}_ip', '')
            lens_k1 = request.form.get(f'cam_{i}_lens_k1', -0.15)
            lens_k2 = request.form.get(f'cam_{i}_lens_k2', 0.0) # <--- Catch k2 from HTML
            
            new_settings['cameras'][i]['enabled'] = is_enabled
            new_settings['cameras'][i]['ip'] = ip_address
            new_settings['cameras'][i]['lens_k1'] = float(lens_k1)
            new_settings['cameras'][i]['lens_k2'] = float(lens_k2) # <--- Save k2 as a float

        # Save to JSON file on disk
        save_settings_to_disk(new_settings)
        
        # APPLY INSTANTLY TO HARDWARE (No restart needed!)
        apply_hardware_settings(new_settings)

        flash('Settings saved and hardware updated successfully!', 'success')
        return redirect(url_for('settings'))
        
    return render_template('settings.html', active_page='settings', config_data=SYSTEM_SETTINGS)




# Allowed directory serving for custom recipe paths
from flask import send_from_directory
@app.route('/recipes/<path:filename>')
@login_required
def custom_static(filename):
    return send_from_directory(RECIPE_FOLDER, filename)


@app.route('/recipe_setup', methods=['GET'])
@login_required
def recipe_setup():
    ensure_folders()
    available_recipes = [d for d in os.listdir(RECIPE_FOLDER) if os.path.isdir(os.path.join(RECIPE_FOLDER, d))]
    
    recipe_to_load = request.args.get('load_recipe')
    loaded_data = None
    if recipe_to_load:
        json_path = os.path.join(RECIPE_FOLDER, recipe_to_load, "recipe.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    loaded_data = json.load(f)
                flash(f"Loaded recipe: {recipe_to_load}")
            except Exception as e:
                flash(f"Error reading recipe file: {e}")
        else:
            flash("Recipe JSON not found in folder.")

    active_cameras = camera_manager_instance.get_all_status()
    object_classes = load_classes()

    return render_template(
        'recipe.html', 
        available_recipes=available_recipes, 
        loaded_data=loaded_data, 
        active_cameras=active_cameras, 
        object_classes=object_classes,
        system_settings=SYSTEM_SETTINGS 
    )


@app.route('/api/capture_master/<int:cam_id>', methods=['GET'])
@login_required
def api_capture_master(cam_id):
    success, frame = camera_manager_instance.get_frame(cam_id)
    if not success or frame is None:
        return jsonify({"status": "error", "message": "Failed to capture image"}), 503

    try:
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        b64 = base64.b64encode(buffer).decode('utf-8')
        return jsonify({"status": "success", "image": f"data:image/jpeg;base64,{b64}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/save_recipe', methods=['POST'])
@login_required
def save_recipe():
    print("\n>>> 📂 ORGANIZED SAVE: STARTING...")
    try:
        data = request.json
        recipe_name = data.get('recipe_name', '').strip()
        camera_data = data.get('camera_data') or data.get('cameras') or {}

        if not recipe_name:
            return jsonify({"status": "error", "message": "Recipe name is required"}), 400

        safe_folder_name = "".join([c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(' ', '_')
        this_recipe_dir = os.path.join(RECIPE_FOLDER, safe_folder_name)
        
        if not os.path.exists(this_recipe_dir):
            os.makedirs(this_recipe_dir)

        final_save_data = {
            "recipe_name": recipe_name,
            "cameras": {}
        }

        for cam_id_str, cam_content in camera_data.items():
            regions = cam_content.get('regions', [])
            b64_image = cam_content.get('master_image')
            saved_web_path = ""
            
            if b64_image and len(b64_image) > 50:
                try:
                    encoded = b64_image.split(",", 1)[1] if "," in b64_image else b64_image
                    binary_data = base64.b64decode(encoded)
                    
                    img_filename = f"cam_{cam_id_str}.jpg"
                    full_system_path = os.path.join(this_recipe_dir, img_filename)
                    
                    with open(full_system_path, 'wb') as f:
                        f.write(binary_data)
                    
                    saved_web_path = f"recipes/{safe_folder_name}/{img_filename}"
                    print(f"   ✅ Saved Image: {saved_web_path}")
                except Exception as e:
                    print(f"   ❌ Image Error: {e}")

            final_save_data["cameras"][cam_id_str] = {
                "regions": regions,
                "master_image_path": saved_web_path
            }

        json_path = os.path.join(this_recipe_dir, "recipe.json")
        with open(json_path, 'w') as f:
            json.dump(final_save_data, f, indent=4)
            
        print(f"🏁 SUCCESS: Everything saved in {this_recipe_dir}")
        return jsonify({"status": "success", "message": f"Recipe '{recipe_name}' saved in its own folder!"})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/live_feed')
@login_required
def live_feed():
    # Grab the current status of all cameras so we know which ones to display
    active_cameras = camera_manager_instance.get_all_status()
    
    return render_template(
        'live.html', 
        active_page='live', 
        active_cameras=active_cameras
    )




@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def run_inspection_logic_internal():
    """
    Called by the PLC Worker when a trigger occurs.
    """
    print(">>> 📸 CAPTURING IMAGE & INSPECTING (Triggered by PLC) <<<")
    import random
    result = "PASS" if random.random() > 0.3 else "FAIL"
    print(f">>> Result: {result}")
    return result

@app.route('/plc_status')
@login_required
def plc_status():
    current_state = plc_thread_instance.get_status() if plc_thread_instance else {}
    return render_template('plc_status.html', plc_state=current_state)

@app.route('/api/plc_data')
@login_required
def api_plc_data():
    if plc_thread_instance:
        return jsonify(plc_thread_instance.get_status())
    return jsonify({"connected": False, "error": "System not initialized"})


# ==========================================
# DATA COLLECTION ROUTES (THE NEW CLASSIFY WORKFLOW)
# ==========================================

@app.route('/data_collection')
@login_required
def data_collection():
    active_cameras = camera_manager_instance.get_all_status()
    return render_template('data_collection.html', active_cameras=active_cameras)

@app.route('/api/snap_temp/<int:cam_id>', methods=['POST'])
@login_required
def snap_temp(cam_id):
    try:
        success, frame = camera_manager_instance.get_frame(cam_id)
        if not success or frame is None:
            return jsonify({"status": "error", "message": "Failed to capture. Camera offline."}), 503

        ensure_folders()
        filename = f"temp_cam_{cam_id}.jpg"
        filepath = os.path.join(TEMP_IMG_FOLDER, filename)
        
        cv2.imwrite(filepath, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        
        cache_buster = int(time.time() * 1000)
        image_url = url_for('static', filename=f'temp/{filename}') + f"?t={cache_buster}"
        
        return jsonify({"status": "success", "image_url": image_url})
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

@app.route('/api/save_labeled_image', methods=['POST'])
@login_required
def save_labeled_image():
    try:
        data = request.json
        cam_id = data.get('cam_id')
        label = data.get('label') 

        if cam_id is None or not label:
            return jsonify({"status": "error", "message": "Invalid data received."}), 400

        temp_filepath = os.path.join(TEMP_IMG_FOLDER, f"temp_cam_{cam_id}.jpg")
        if not os.path.exists(temp_filepath):
            return jsonify({"status": "error", "message": "No temporary image found."}), 404

        date_str = datetime.now().strftime("%Y-%m-%d")
        dataset_dir = os.path.join('dataset', date_str, f'cam_{cam_id}', label)
        
        if not os.path.exists(dataset_dir):
            os.makedirs(dataset_dir)

        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        filename = f"{label}_{timestamp}.jpg"
        target_filepath = os.path.join(dataset_dir, filename)
        
        shutil.move(temp_filepath, target_filepath)

        count_ok = len(os.listdir(os.path.join('dataset', date_str, f'cam_{cam_id}', 'ok'))) if os.path.exists(os.path.join('dataset', date_str, f'cam_{cam_id}', 'ok')) else 0
        count_nok = len(os.listdir(os.path.join('dataset', date_str, f'cam_{cam_id}', 'not_ok'))) if os.path.exists(os.path.join('dataset', date_str, f'cam_{cam_id}', 'not_ok')) else 0

        return jsonify({
            "status": "success", 
            "message": f"Saved as {label.upper()}",
            "count_ok": count_ok,
            "count_nok": count_nok
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_latest_results')
def get_latest_results():
    global GLOBAL_SYSTEM_STATE
    # We wrap the state in a 'success' status so the HTML can verify it
    return jsonify({
        "status": "success",
        "inspection_id": GLOBAL_SYSTEM_STATE.get("inspection_id", 0),
        "results": GLOBAL_SYSTEM_STATE.get("results", {})
    })


# ==========================================
# 5. MAIN ENTRY POINT 
# ==========================================

if __name__ == '__main__':
    ensure_folders()
    
    print("🚀 System Booting... Initializing Hardware!")
    
    # 1. Load the saved settings from the settings.json file
    config_data = load_system_settings()
    
    # 2. Push those settings directly to the PLC and Cameras
    apply_hardware_settings(config_data)
    load_last_recipe()
    print("🌐 Hardware Ready... Starting Web Server!")
    
    # 3. Start Web Server
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    #app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)