import sys
import threading
import ctypes
import numpy as np
import cv2
from MvImport.MvCameraControl_class import *

class HikCamera:
    def __init__(self, ip_address=None, index=0):
        self.cam = MvCamera()
        self.handle = None
        self.data_buf = None
        self.n_payload_size = 0
        self.is_open = False
        self.target_ip = ip_address
        self.device_index = index

    def open(self):
        """Finds and connects to the Hikrobot camera."""
        # 1. Enumerate Devices
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        
        ret = self.cam.MV_CC_EnumDevices(tlayerType, deviceList)
        if ret != 0:
            print(f"HikDriver: EnumDevices failed! ret={hex(ret)}")
            return False

        if deviceList.nDeviceNum == 0:
            print("HikDriver: No Hikrobot cameras found!")
            return False

        # 2. Find the specific camera (by IP or Index)
        target_device = None
        
        # If IP is provided, search for it
        if self.target_ip and self.target_ip != "0":
            print(f"HikDriver: Searching for IP {self.target_ip}...")
            for i in range(deviceList.nDeviceNum):
                mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
                if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
                    # Parse IP address from structure
                    nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
                    nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
                    nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
                    nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
                    current_ip = f"{nip1}.{nip2}.{nip3}.{nip4}"
                    
                    if current_ip == self.target_ip:
                        target_device = deviceList.pDeviceInfo[i]
                        break
        else:
            # Otherwise use index
            if self.device_index < deviceList.nDeviceNum:
                target_device = deviceList.pDeviceInfo[self.device_index]

        if not target_device:
            print("HikDriver: Camera not found.")
            return False

        # 3. Create Handle & Open
        ret = self.cam.MV_CC_CreateHandle(target_device)
        if ret != 0: return False

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0: return False

        # 4. Configure Basic Settings
        # Turn off Trigger Mode (Continuous Grab) - change to ON if using PLC hardware trigger later
        self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
        self.cam.MV_CC_SetEnumValue("PixelFormat", PixelType_Gvsp_BGR8_Packed) # Force RGB
        
        # Get Payload Size for buffer
        stParam = MVCC_INTVALUE()
        memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
        ret = self.cam.MV_CC_GetIntValue("PayloadSize", stParam)
        self.n_payload_size = stParam.nCurValue
        
        # Allocate buffer
        self.data_buf = (c_ubyte * self.n_payload_size)()

        # 5. Start Grabbing
        ret = self.cam.MV_CC_StartGrabbing()
        if ret != 0: return False

        self.is_open = True
        print(f"HikDriver: Camera {self.target_ip or self.device_index} Connected!")
        return True

    def read(self):
        """mimics cv2.read(): returns (ret, image)"""
        if not self.is_open: return False, None

        stFrameInfo = MV_FRAME_OUT_INFO_EX()
        memset(byref(stFrameInfo), 0, sizeof(stFrameInfo))
        
        # Timeout 1000ms
        ret = self.cam.MV_CC_GetOneFrameTimeout(byref(self.data_buf), self.n_payload_size, stFrameInfo, 1000)
        
        if ret == 0:
            # Success - Convert Raw Buffer to Numpy
            # Note: We forced BGR8 Packed above, so we can reshape directly
            
            # Pointer to buffer
            p_data = (c_ubyte * stFrameInfo.nFrameLen).from_address(addressof(self.data_buf))
            image_data = np.frombuffer(p_data, dtype=np.uint8)
            
            # Reshape based on Width/Height
            image = image_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth, 3)) # 3 for BGR
            
            return True, image
        else:
            # print(f"HikDriver: GetFrame Failed. ret={hex(ret)}")
            return False, None

    def release(self):
        if self.is_open:
            self.cam.MV_CC_StopGrabbing()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
        self.is_open = False