import serial
import time

class NextionAlert:
    def __init__(self, port="/dev/ttyS0", baud=9600):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        time.sleep(0.1)

    def send(self, level: str, message: str):
        # Ganti komponen sesuai desain HMI
        cmd = f'tAlert.txt="{message}"'
        self.ser.write(cmd.encode('ascii') + b'\xff\xff\xff')
        if level == "critical":
            self.ser.write(b'page critical\xff\xff\xff')
        elif level == "warning":
            self.ser.write(b'page warning\xff\xff\xff')