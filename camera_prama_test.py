import cv2

# Your working RTSP URL with credentials
rtsp_url = "rtsp://onvif:Sunbeam_12@192.168.1.64:554/Streaming/Channels/101?transportmode=unicast&profile=Profile_1"

# Open the stream
cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

if not cap.isOpened():
    print("Error: Cannot open RTSP stream")
    print("Check: URL, credentials, network, camera power, OpenCV FFmpeg support")
    exit()

print("Connected to camera. Capturing one frame...")

# Read one frame
ret, frame = cap.read()

# Immediately release the capture (we only want one image)
cap.release()

if not ret:
    print("Error: Failed to capture frame")
    exit()

# Get original dimensions
height, width = frame.shape[:2]
print(f"Original size: {width} × {height}")

# Scale to 10% (both width and height)
scale_percent = 10
new_width = int(width * scale_percent / 100)
new_height = int(height * scale_percent / 100)

# Resize – use INTER_AREA for downscaling (good quality)
small_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)

print(f"Scaled size: {new_width} × {new_height}")

# Optional: Save the original and/or small version
cv2.imwrite("prama_original.jpg", frame)
cv2.imwrite("prama_10percent.jpg", small_frame)
print("Saved: prama_original.jpg and prama_10percent.jpg")

# Display the small version
cv2.imshow("Prama Camera – 10% Scale", small_frame)

# Wait for any key press to close the window
cv2.waitKey(0)
cv2.destroyAllWindows()

print("Done.")