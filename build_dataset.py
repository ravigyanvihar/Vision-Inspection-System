import os
import shutil
import random
import tkinter as tk
from tkinter import filedialog

def create_yolo_dataset():
    # 1. Open a pop-up window to select the folder
    root = tk.Tk()
    root.withdraw()  # Hide the main background window
    print("Opening file browser... Please select your extracted Label Studio folder.")
    
    source_dir = filedialog.askdirectory(title="Select Extracted Label Studio Export Folder")
    if not source_dir:
        print("❌ No folder selected. Exiting.")
        return

    # Check if this is the right folder
    img_source = os.path.join(source_dir, 'images')
    lbl_source = os.path.join(source_dir, 'labels')
    classes_file = os.path.join(source_dir, 'classes.txt')

    if not os.path.exists(img_source) or not os.path.exists(lbl_source):
        print("❌ Error: Could not find 'images' or 'labels' folders in the selected directory.")
        return

    # 2. Read the class names
    classes = []
    if os.path.exists(classes_file):
        with open(classes_file, 'r') as f:
            classes = [line.strip() for line in f.readlines() if line.strip()]
    else:
        print("⚠️ Warning: classes.txt not found. Defaulting to ['Class_0']")
        classes = ['Class_0']

    print(f"✅ Found {len(classes)} classes: {classes}")

    # 3. Create the Target Directory Structure
    target_dir = os.path.join(os.getcwd(), 'yolo_dataset')
    folders_to_make = [
        os.path.join(target_dir, 'images', 'train'),
        os.path.join(target_dir, 'images', 'val'),
        os.path.join(target_dir, 'labels', 'train'),
        os.path.join(target_dir, 'labels', 'val')
    ]
    
    # Clean up old dataset if it exists
    if os.path.exists(target_dir):
        print("🧹 Cleaning up old yolo_dataset folder...")
        shutil.rmtree(target_dir)

    for folder in folders_to_make:
        os.makedirs(folder)

    # 4. Get all images and Shuffle them
    all_images = [f for f in os.listdir(img_source) if f.endswith(('.jpg', '.png', '.jpeg'))]
    random.seed(42) # Keeps the shuffle consistent if you run it multiple times
    random.shuffle(all_images)

    # 5. Calculate the 80/20 Split
    split_index = int(len(all_images) * 0.8)
    train_images = all_images[:split_index]
    val_images = all_images[split_index:]

    print(f"📦 Found {len(all_images)} total images. Splitting: {len(train_images)} Train / {len(val_images)} Val.")

    # 6. Copy Files Function
    def move_files(image_list, split_name):
        for img_name in image_list:
            # Copy Image
            src_img_path = os.path.join(img_source, img_name)
            dst_img_path = os.path.join(target_dir, 'images', split_name, img_name)
            shutil.copy(src_img_path, dst_img_path)

            # Copy Matching Label (.txt)
            lbl_name = os.path.splitext(img_name)[0] + '.txt'
            src_lbl_path = os.path.join(lbl_source, lbl_name)
            dst_lbl_path = os.path.join(target_dir, 'labels', split_name, lbl_name)
            
            # Label Studio might not generate a txt for a perfectly blank image. 
            # We create an empty one if it's missing so YOLO knows it's a "good" part.
            if os.path.exists(src_lbl_path):
                shutil.copy(src_lbl_path, dst_lbl_path)
            else:
                open(dst_lbl_path, 'w').close()

    # Execute the copy
    print("⏳ Copying files...")
    move_files(train_images, 'train')
    move_files(val_images, 'val')

    # 7. Create data.yaml
    yaml_path = os.path.join(target_dir, 'data.yaml')
    with open(yaml_path, 'w') as f:
        f.write(f"path: {os.path.abspath(target_dir)}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n\n")
        f.write(f"nc: {len(classes)}\n")
        f.write(f"names: {classes}\n")

    print(f"\n🎉 DONE! Your dataset is perfectly formatted and ready for training.")
    print(f"📁 Location: {os.path.abspath(target_dir)}")

if __name__ == "__main__":
    create_yolo_dataset()