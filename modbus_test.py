from pymodbus.client import ModbusTcpClient
import time

client = ModbusTcpClient("127.0.0.1", port=502)

if client.connect():
    print("Connected. Toggling register 10 every second... (Ctrl+C to stop)")
    value = 0
    
    while True:
        client.write_register(address=10, value=value, device_id=1)   # ← device_id instead of unit/slave
        print("1" if value else "0", end=" ", flush=True)
        value = 1 - value
        time.sleep(1)
else:
    print("Cannot connect to 127.0.0.1:502")