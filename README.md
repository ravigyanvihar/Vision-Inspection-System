🏭 Industrial Vision Inspection Framework
A High-Performance, Low-CapEx AI Inspection System

This project is a Flask-based web application designed to bring high-end computer vision to the shop floor using standard hardware. It bridges the gap between Python 3.10, AI (YOLOv8), and Industrial PLCs (Modbus TCP).

🏗️ System Architecture
The system operates on a "Two-Pass" inspection logic:

Pass 1 (Alignment): Uses OpenCV Template Matching to find an "Anchor" and calculate part misalignment.

Pass 2 (Inspection): Runs AI (YOLO) and Math (Gray Average/Color) tools on the shifted coordinates to ensure 100% accuracy even if the part moves.

🔌 Hardware Setup
Camera: Supports any ONVIF-compatible IP Camera, USB Webcam, or Raspberry Pi Camera. (RTSP streams are handled via OpenCV).

Processor: Raspberry Pi 4 (8GB) or any PC running Python 3.10.

PLC: Any controller supporting Modbus TCP (Siemens S7, Delta, Schneider, etc.).

Printer: Industrial ZPL-compatible network printer (optional).

📦 Software Installation
1. Environment Setup
Ensure you are using Python 3.10 for maximum library stability.

2. Configure PLC & Camera
Edit the SYSTEM_SETTINGS.json (or the top of app.py):

Camera URL: rtsp://admin:password@192.168.1.50:554/stream (For ONVIF/IP Cameras).

PLC IP: 192.168.1.10

🧠 YOLO AI Integration Guide
1. Training
Train your model using YOLOv8 Nano (yolov8n.pt) for the best speed on edge devices.

Classes: Include an anchor class for alignment and specific defect classes (e.g., scratch, missing_bolt).

2. Deployment (The Recipe Folder)
For every new part, create a folder in recipes/. The system loads these dynamically:

Example classes.txt:

🖥️ How to Run
Start the server:

Open your browser to: http://127.0.0.1:5000

Note: Locked to localhost for shop-floor security.

Operation:

The PLC sends a "Trigger" signal via Modbus.

Python captures the image from the ONVIF/IP camera.

The system runs Pass 1 (Align) and Pass 2 (Inspect).

Results are written back to PLC registers and saved to a 30-day rolling history.

📊 Analytics & Traceability
Master-Detail View: Handles 1000+ inspections per shift without crashing the browser.

Failure Breakdown: Automatically generates charts showing which specific "Box" or "Tool" is failing most frequently.

Auto-Maintenance: Automatically deletes images older than 30 days to protect SD card health.

⚖️ License & Contributions
This is an open-source project created to demonstrate that high-quality vision inspection can be achieved with standard IP cameras and smart logic. Feel free to fork, modify, and use in your own local industries!
