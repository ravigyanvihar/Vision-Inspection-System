import os
import cv2
from ultralytics import YOLO

# --- Configuration ---
# Using r"..." (raw string) is important for Windows paths so the slashes don't cause errors
MODEL_PATH = r"C:\Users\Kanchi\Downloads\best.pt"
IMAGE_DIR = r"C:\Users\Kanchi\Downloads\test_image\images"

def run_folder_test():
    print("=========================================")
    print("🤖 YOLO FOLDER INSPECTION TESTER")
    print("=========================================")

    # 1. Load the Custom AI Model
    print(f"\n🧠 Loading AI Engine from: {MODEL_PATH}...")
    try:
        model = YOLO(MODEL_PATH)
    except Exception as e:
        print(f"❌ Failed to load model. Check the path! Error: {e}")
        return

    # 2. Gather Images
    if not os.path.exists(IMAGE_DIR):
        print(f"❌ Error: Could not find folder {IMAGE_DIR}")
        return

    valid_extensions = ('.jpg', '.jpeg', '.png')
    images = [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(valid_extensions)]
    
    if not images:
        print(f"❌ No valid images found in {IMAGE_DIR}")
        return

    print(f"✅ Found {len(images)} images. Starting inspection...\n")

    # Setup a resizable window
    window_name = "AI Inspection Output"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    # 3. Run the Engine!
    for img_name in images:
        img_path = os.path.join(IMAGE_DIR, img_name)
        print(f"\n📸 Analyzing: {img_name}...")
        
        # Run the AI (50% confidence threshold)
        results = model.predict(source=img_path, conf=0.5, verbose=False)
        
        # Draw the outlines
        annotated_img = results[0].plot()
        
        # Print results to terminal
        detections = results[0].boxes
        if len(detections) > 0:
            print(f"  🎯 Found {len(detections)} defect(s):")
            for box in detections:
                class_id = int(box.cls[0])
                class_name = model.names[class_id]
                confidence = float(box.conf[0])
                print(f"    - {class_name} ({confidence*100:.1f}%)")
        else:
            print("  ✅ No detections (Part is Good).")

        # Display the result
        cv2.imshow(window_name, annotated_img)
        print("  ---> Press [SPACE] for next image, or [Q] to quit.")
        
        # Wait for Spacebar (ASCII 32) or Q/Esc
        while True:
            key = cv2.waitKey(0) & 0xFF
            if key == 32:  # Spacebar key
                break
            elif key == ord('q') or key == 27:  # 'q' or 'Esc' key
                print("\n⏹️ Testing stopped by user.")
                cv2.destroyAllWindows()
                return

    cv2.destroyAllWindows()
    print("\n✅ Reached the end of the folder. Testing Complete.")

if __name__ == "__main__":
    run_folder_test()