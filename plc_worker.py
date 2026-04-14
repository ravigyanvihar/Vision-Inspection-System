import threading
import time

# Try importing the client (Handles v3 paths)
try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    try:
        from pymodbus.client.sync import ModbusTcpClient
    except ImportError:
        print("❌ CRITICAL: PyModbus not installed.")
        raise

class PLCWorker:
    def __init__(self, ip, port=502, trigger_callback=None):
        self.ip = ip
        self.port = port
        self.client = ModbusTcpClient(ip, port=port)
        self.running = False
        self.trigger_callback = trigger_callback 
        
        self.state = {
            "connected": False,
            "last_error": None
        }
        # Memory variables
        self.prev_trigger_val = 0
        self.ok_val = 0     # Added to track OK signal
        self.nok_val = 0    # Added to track NOK signal
        self.heartbeat_val = 0   
        
    # ==========================================
    # DASHBOARD STATUS FUNCTION
    # ==========================================
    def get_status(self):
        """Returns current PLC connection status for the web dashboard."""
        return {
            "connected": self.state["connected"],
            "last_error": self.state["last_error"],
            "ip": self.ip,
            "regs": {
                "trigger": self.prev_trigger_val,
                "ok_fb": self.ok_val,       # Added to fix 'undefined'
                "nok_fb": self.nok_val,     # Added to fix 'undefined'
                "heartbeat": self.heartbeat_val
            }
        }

    # ==========================================
    # THE MASTER PLC FUNCTION
    # ==========================================
    def set_register(self, address, value, hold_time=0):
        """
        Sets a PLC register. If hold_time > 0, it holds the value then resets to 0.
        """
        if not self.state["connected"]:
            return
            
        if hold_time > 0:
            # Spawn a thread to handle timing so the main app doesn't lag
            threading.Thread(target=self._write_pulse, args=(address, value, hold_time), daemon=True).start()
        else:
            try:
                self.client.write_register(address=address, value=value, device_id=1)
            except Exception as e:
                print(f"❌ PLC Write Error: {e}")

    def _write_pulse(self, address, value, hold_time):
        """Internal helper for pulsing registers (OK/NOK/Hooter)."""
        try:
            self.client.write_register(address=address, value=value, device_id=1)
            time.sleep(hold_time)
            self.client.write_register(address=address, value=0, device_id=1)
        except Exception as e:
            print(f"❌ PLC Pulse Error: {e}")

    # ==========================================
    # BACKGROUND LOOP
    # ==========================================
    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run_loop, daemon=True).start()
            print(f"🔌 PLC Worker started targeting {self.ip}:{self.port}")

    def stop(self):
        self.running = False

    def _run_loop(self):
        """
        Main background loop that handles Heartbeat and detects 
        the 'Rising Edge' of the trigger register.
        """
        while self.running:
            try:
                if not self.client.connect():
                    self.state["connected"] = False
                    time.sleep(2)
                    continue
                
                self.state["connected"] = True
                
                # 1. READ TRIGGER, OK, and NOK (Address 0, 1, and 2)
                # We change count=1 to count=3 to grab all three at once
                result = self.client.read_holding_registers(address=0, count=3, device_id=1)
                
                if not result.isError():
                    curr_trig = result.registers[0]
                    self.ok_val = result.registers[1]   # Store OK Feedback
                    self.nok_val = result.registers[2]  # Store NOK Feedback
                    
                    # --- SOFTWARE LATCH LOGIC ---
                    if curr_trig == 1 and self.prev_trigger_val == 0:
                        print("⚡ Modbus Trigger Received! (Firing Inspection Once)")
                        
                        self.prev_trigger_val = 1 
                        
                        if self.trigger_callback:
                            self.trigger_callback()
                    
                    elif curr_trig == 0:
                        self.prev_trigger_val = 0

                    # 2. WRITE HEARTBEAT (Address 8)
                    self.heartbeat_val = 1 if self.heartbeat_val == 0 else 0
                    self.client.write_register(address=8, value=self.heartbeat_val, device_id=1)
                else:
                    self.state["connected"] = False

            except Exception as e:
                self.state["connected"] = False
            
            # Polling speed: 0.5s per custom hardware logic requirements
            time.sleep(0.5)