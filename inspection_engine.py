import cv2
import numpy as np
import os
from datetime import datetime
from ultralytics import YOLO

# ==========================================
# 1. DYNAMIC MODEL CACHE
# ==========================================
# Stores YOLO models in RAM so they run instantly on every trigger
LOADED_MODELS = {}

def get_yolo_model(recipe_folder):
    global LOADED_MODELS
    
    if recipe_folder in LOADED_MODELS:
        return LOADED_MODELS[recipe_folder]
        
    model_path = os.path.join('recipes', recipe_folder, 'yolo', 'model.pt')
    
    if os.path.exists(model_path):
        print(f"🧠 Loading new YOLO Model into memory: {model_path}")
        try:
            model = YOLO(model_path)
            LOADED_MODELS[recipe_folder] = model
            return model
        except Exception as e:
            print(f"❌ Failed to load YOLO model. Error: {e}")
            return None
    else:
        print(f"⚠️ No YOLO model found at: {model_path}")
        return None

# ==========================================
# 2. MAIN INSPECTION ENGINE
# ==========================================
def run_full_inspection(frame, recipe_data, recipe_folder, cam_id):
    """
    Evaluates all regions and returns a structured JSON dictionary and the drawn image.
    """
    annotated_frame = frame.copy()
    
    # ---------------------------------------------------------
    # MASTER JSON RESULT STRUCTURE
    # ---------------------------------------------------------
    final_report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "recipe": recipe_folder,
        "camera_number": cam_id + 1,
        "overall_result": "PASS",
        "regions": []
    }
    
    cam_data = recipe_data.get('cameras', {}).get(str(cam_id), {})
    regions = cam_data.get('regions', [])

    if not regions:
        final_report["overall_result"] = "FAIL (No Regions)"
        return final_report, annotated_frame

    all_regions_passed = True

    # Loop through every box drawn on the UI for this camera
    for idx, region in enumerate(regions):
        x, y, w, h = int(region['x']), int(region['y']), int(region['w']), int(region['h'])
        tool_type = region.get('tool_type')
        params = region.get('tool_params', {})
        
        # Ensure we don't try to crop outside the image boundaries
        img_h, img_w = frame.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = max(1, min(w, img_w - x))
        h = max(1, min(h, img_h - y))
        
        # Crop the exact region from the image (This is our Live ROI)
        roi_img = frame[y:y+h, x:x+w]
        
        region_status = "FAIL"
        details = ""

        # ==========================================
        # TOOL 1: YOLO REGION VALIDATION (AI)
        # ==========================================
        if tool_type == "YOLO_CHECK":
            target_class = str(params.get('class_name', '')).lower().strip()
            min_conf = float(params.get('confidence', 80)) / 100.0  
            
            # NEW: How many pixels can the part shift from the exact center?
            allowed_tolerance_px = int(params.get('tolerance_px', 20)) 
            
            model = get_yolo_model(recipe_folder)
            
            if model is None:
                # ... (Keep your existing error handling) ...
                pass
            else:
                ai_results = model.predict(source=roi_img, conf=min_conf, verbose=False)
                best_conf = 0.0
                best_box_coords = None
                
                for r in ai_results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        detected_name = model.names[cls_id].lower().strip()
                        
                        if detected_name == target_class and conf > best_conf:
                            best_conf = conf
                            bx1, by1, bx2, by2 = box.xyxy[0].cpu().numpy()
                            best_box_coords = (int(bx1), int(by1), int(bx2), int(by2))

                if best_box_coords is not None:
                    # 1. Calculate the center of the bounding box YOLO found
                    obj_center_x = (best_box_coords[0] + best_box_coords[2]) / 2
                    obj_center_y = (best_box_coords[1] + best_box_coords[3]) / 2
                    
                    # 2. Calculate the exact center of your drawn ROI box
                    roi_center_x = w / 2
                    roi_center_y = h / 2
                    
                    # 3. Calculate how far off-center the object is
                    distance = ((obj_center_x - roi_center_x)**2 + (obj_center_y - roi_center_y)**2) ** 0.5
                    
                    actual_x1, actual_y1 = x + best_box_coords[0], y + best_box_coords[1]
                    actual_x2, actual_y2 = x + best_box_coords[2], y + best_box_coords[3]
                    
                    # 4. Evaluate both Confidence AND Position
                    if distance <= allowed_tolerance_px:
                        region_status = "PASS"
                        details = f"Found '{target_class}' (Off-center: {int(distance)}px)"
                        cv2.rectangle(annotated_frame, (actual_x1, actual_y1), (actual_x2, actual_y2), (0, 255, 0), 3)
                        cv2.putText(annotated_frame, f"PASS: {int(distance)}px shift", (actual_x1, actual_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                    else:
                        region_status = "FAIL"
                        details = f"'{target_class}' out of position! (Shift: {int(distance)}px > Max: {allowed_tolerance_px}px)"
                        cv2.rectangle(annotated_frame, (actual_x1, actual_y1), (actual_x2, actual_y2), (0, 165, 255), 3) # Orange box for positional fail
                        cv2.putText(annotated_frame, f"FAIL: Shifted {int(distance)}px", (actual_x1, actual_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 2)
                        
                else:
                    details = f"Missing '{target_class}' entirely"
        
        # ==========================================
        # TOOL 2: RELATIVE GRAYSCALE DIFFERENCE (Math)
        # ==========================================
        elif tool_type == "GRAY_AVERAGE":
            min_diff = int(params.get('min_gray', 0))
            max_diff = int(params.get('max_gray', 30))
            
            master_img_path = os.path.join('recipes', recipe_folder, f"cam_{cam_id}.jpg")
            master_frame = cv2.imread(master_img_path)
            
            if master_frame is None:
                details = "Master Image Not Found"
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                cv2.putText(annotated_frame, f"[{idx+1}] FAIL: No Master", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            else:
                master_roi = master_frame[y:y+h, x:x+w]
                gray_master = cv2.cvtColor(master_roi, cv2.COLOR_BGR2GRAY)
                master_avg = int(np.mean(gray_master))
                
                gray_live = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
                live_avg = int(np.mean(gray_live))
                
                diff = abs(master_avg - live_avg)
                
                if min_diff <= diff <= max_diff:
                    region_status = "PASS"
                    details = f"Diff: {diff} (Master:{master_avg}, Live:{live_avg})"
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 255, 0), 3)
                    cv2.putText(annotated_frame, f"[{idx+1}] PASS (Diff: {diff})", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                else:
                    region_status = "FAIL"
                    details = f"Diff: {diff} exceeds tolerance {min_diff}-{max_diff}"
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                    cv2.putText(annotated_frame, f"[{idx+1}] FAIL (Diff: {diff})", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # ==========================================
        # TOOL 3: HSV COLOR PIXEL COUNTING (Color)
        # ==========================================
        elif tool_type == "COLOR_MATCH":
            h_min = int(params.get('h_min', 0))
            h_max = int(params.get('h_max', 10))
            min_target_px = int(params.get('min_px', 150))
            
            hsv_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
            
            # Create a binary mask locking Saturation & Value to ignore shadows/glare
            if h_min > h_max:
                mask1 = cv2.inRange(hsv_roi, np.array([h_min, 50, 50]), np.array([179, 255, 255]))
                mask2 = cv2.inRange(hsv_roi, np.array([0, 50, 50]), np.array([h_max, 255, 255]))
                mask = cv2.bitwise_or(mask1, mask2)
            else:
                lower_bound = np.array([h_min, 50, 50])
                upper_bound = np.array([h_max, 255, 255])
                mask = cv2.inRange(hsv_roi, lower_bound, upper_bound)
            
            matching_pixels = cv2.countNonZero(mask)
            
            if matching_pixels >= min_target_px:
                region_status = "PASS"
                details = f"Color Match: {matching_pixels}px (Need > {min_target_px})"
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 255, 0), 3)
                cv2.putText(annotated_frame, f"[{idx+1}] PASS: {matching_pixels}px", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            else:
                region_status = "FAIL"
                details = f"Color Miss: Only {matching_pixels}px (Need > {min_target_px})"
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                cv2.putText(annotated_frame, f"[{idx+1}] FAIL: {matching_pixels}px", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # ==========================================
        # TOOL 4: TEMPLATE MATCHING (Pattern)
        # ==========================================
        elif tool_type == "TEMPLATE_MATCH":
            match_thresh = float(params.get('match_threshold', 85)) / 100.0
            
            master_img_path = os.path.join('recipes', recipe_folder, f"cam_{cam_id}.jpg")
            master_frame = cv2.imread(master_img_path)
            
            if master_frame is None:
                details = "Master Image Not Found"
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                cv2.putText(annotated_frame, f"[{idx+1}] FAIL: No Master", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            else:
                # 1. Extract the Template from the Master Image
                template = master_frame[y:y+h, x:x+w]
                
                # 2. Convert both the Live Frame and Template to Grayscale
                live_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                
                # 3. Slide the template over the ENTIRE live image
                res = cv2.matchTemplate(live_gray, template_gray, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                
                match_pct = int(max_val * 100)
                
                # 4. Evaluate Pass/Fail
                if max_val >= match_thresh:
                    region_status = "PASS"
                    details = f"Match: {match_pct}% (Need > {int(match_thresh*100)}%)"
                    
                    # Draw a thin white box where the part WAS expected
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (255, 255, 255), 1)
                    
                    # Draw a thick GREEN box exactly where the part IS NOW
                    top_left = max_loc
                    bottom_right = (top_left[0] + w, top_left[1] + h)
                    
                    cv2.rectangle(annotated_frame, top_left, bottom_right, (0, 255, 0), 3)
                    cv2.putText(annotated_frame, f"[{idx+1}] PASS: {match_pct}%", (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                else:
                    region_status = "FAIL"
                    details = f"No Match: Best was {match_pct}%"
                    
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                    cv2.putText(annotated_frame, f"[{idx+1}] FAIL (Best: {match_pct}%)", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # ==========================================
        # TOOL 5: BLOB ANALYSIS (Shape & Count)
        # ==========================================
        elif tool_type == "BLOB_FIND":
            min_area = int(params.get('min_area', 100))
            expected_count = int(params.get('expected_count', 1))
            
            # 1. Convert Live ROI to Grayscale
            gray_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            
            # 2. Apply automatic OTSU Thresholding
            _, binary = cv2.threshold(gray_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # 3. Find the "Blobs" (Contours)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 4. Filter blobs by size to ignore dust and noise
            valid_blobs = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area >= min_area:
                    valid_blobs.append(cnt)
                    
            blob_count = len(valid_blobs)
            
            # 5. Evaluate Pass/Fail
            if blob_count == expected_count:
                region_status = "PASS"
                details = f"Found {blob_count} blobs (Need exactly {expected_count})"
                
                # Draw a green bounding box around the whole region
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                
                # Draw the exact outlines of the valid blobs we found
                for cnt in valid_blobs:
                    cnt_offset = cnt + np.array([[x, y]])
                    cv2.drawContours(annotated_frame, [cnt_offset], -1, (0, 255, 0), 2)
                    
                cv2.putText(annotated_frame, f"[{idx+1}] PASS: {blob_count}/{expected_count}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                
            else:
                region_status = "FAIL"
                details = f"Found {blob_count} blobs (Need exactly {expected_count})"
                
                # Draw a red bounding box around the region
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                
                # Draw the exact outlines of the blobs in red to show the operator what it saw
                for cnt in valid_blobs:
                    cnt_offset = cnt + np.array([[x, y]])
                    cv2.drawContours(annotated_frame, [cnt_offset], -1, (0, 0, 255), 2)
                    
                cv2.putText(annotated_frame, f"[{idx+1}] FAIL: {blob_count}/{expected_count}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # ==========================================
        # TOOL 6: GOLDEN SUBTRACTION (Defects & Scratches)
        # ==========================================
        elif tool_type == "GOLDEN_SUBTRACT":
            diff_thresh = int(params.get('diff_thresh', 30))
            max_diff_px = int(params.get('max_diff_px', 500))
            
            master_img_path = os.path.join('recipes', recipe_folder, f"cam_{cam_id}.jpg")
            master_frame = cv2.imread(master_img_path)
            
            if master_frame is None:
                details = "Master Image Not Found"
                cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                cv2.putText(annotated_frame, f"[{idx+1}] FAIL: No Master", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            else:
                # 1. Crop Master and Live images
                master_roi = master_frame[y:y+h, x:x+w]
                
                # 2. Convert to Grayscale
                gray_master = cv2.cvtColor(master_roi, cv2.COLOR_BGR2GRAY)
                gray_live = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
                
                # 3. Apply a slight Gaussian Blur (Crucial for factory environments!)
                # This absorbs micro-vibrations so the edges of the part don't look like defects
                gray_master = cv2.GaussianBlur(gray_master, (5, 5), 0)
                gray_live = cv2.GaussianBlur(gray_live, (5, 5), 0)
                
                # 4. Pixel-by-Pixel Absolute Subtraction
                diff_img = cv2.absdiff(gray_master, gray_live)
                
                # 5. Apply the Threshold (Ignore minor lighting changes, keep hard defects)
                _, thresh = cv2.threshold(diff_img, diff_thresh, 255, cv2.THRESH_BINARY)
                
                # 6. Count the Defect Pixels
                defect_pixels = cv2.countNonZero(thresh)
                
                # 7. Evaluate Pass/Fail
                if defect_pixels <= max_diff_px:
                    region_status = "PASS"
                    details = f"Clean: {defect_pixels} bad px (Max {max_diff_px})"
                    
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                    cv2.putText(annotated_frame, f"[{idx+1}] PASS: {defect_pixels}px", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                else:
                    region_status = "FAIL"
                    details = f"Defect Found: {defect_pixels} bad px (Max {max_diff_px})"
                    
                    cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
                    
                    # Highlight the EXACT defect by drawing the threshold map over the live image in RED!
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contours:
                        cnt_offset = cnt + np.array([[x, y]]) # Offset to main frame coordinates
                        cv2.drawContours(annotated_frame, [cnt_offset], -1, (0, 0, 255), -1) # -1 fills it solid red
                        
                    cv2.putText(annotated_frame, f"[{idx+1}] FAIL: {defect_pixels}px", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # ==========================================
        # CATCH-ALL FOR UNKNOWN TOOLS
        # ==========================================
        else:
            details = f"Unknown tool: {tool_type}"
            cv2.rectangle(annotated_frame, (x, y), (x+w, y+h), (0, 0, 255), 3)

        # ---------------------------------------------------------
        # AGGREGATE RESULTS
        # ---------------------------------------------------------
        if region_status == "FAIL":
            all_regions_passed = False

        # ✅ THE FIX: Combine the Tool Type with its exact Box Number!
        # Example: "GRAY_AVERAGE" becomes "GRAY_AVERAGE (Box 1)"
        tool_name_with_id = f"{tool_type} (Box {idx + 1})"

        final_report["regions"].append({
            "region_number": idx + 1,
            "region_method": tool_name_with_id,  # <--- Use the new name here
            "result": region_status,
            "details": details
        })

    # Set the Master Status for the whole image
    final_report["overall_result"] = "PASS" if all_regions_passed else "FAIL"
    return final_report, annotated_frame