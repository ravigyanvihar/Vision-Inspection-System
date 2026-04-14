YOLOv8 Training & Integration Guide
To use AI-powered inspection in this system, you need to train a YOLOv8 model and place it in the correct recipe folder. This system is designed to load models dynamically per recipe.

1. Prepare Your Dataset
Collect Images: Take 100-200 photos of your part in the actual factory lighting. Include "Good" parts and "Bad" parts.

Labeling: Use Roboflow or Label Studio.

Create a class called anchor (if using AI for alignment).

Create classes for your specific parts (e.g., bolt, washer, scratch).

Export: Export your dataset in YOLOv8 format.

2. Train the Model
The fastest way to train is using Google Colab (GPU). You can use this simple Python script:

Python
from ultralytics import YOLO

# Load a pretrained 'nano' model (fastest for Raspberry Pi)
model = YOLO('yolov8n.pt')

# Train the model
results = model.train(
    data='path/to/your/data.yaml',
    epochs=50,
    imgsz=640,
    device=0  # Use 'cpu' if no GPU available
)
3. Deployment (Copy & Paste)
Once training is finished, YOLO will create a file named best.pt in the runs/detect/train/weights/ folder.

To integrate it into this software, follow this exact folder structure:

Navigate to your project folder.

Go to recipes/ -> [Your_Recipe_Name]/.

Create a folder named yolo.

Paste your best.pt file inside that folder and rename it to model.pt.
