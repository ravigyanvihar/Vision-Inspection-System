import os
import base64
from mistralai import Mistral

# Your specific key and path
api_key = "M4Sq2QzCO3tDRIzZ6NjgpIFTot2hodRJ"
client = Mistral(api_key=api_key)
file_path = r"C:\Users\DELL\Downloads\image_1.jpg"

def run_ocr():
    with open(file_path, "rb") as f:
        encoded_image = base64.b64encode(f.read()).decode("utf-8")
    
    # In v2.x, the call looks like this:
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{encoded_image}"
        }
    )
    
    for page in ocr_response.pages:
        print(page.markdown)

if __name__ == "__main__":
    run_ocr()