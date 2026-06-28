# edge/drivers/max6675.py
import RPi.GPIO as GPIO
import time

class MAX6675:
    def __init__(self, cs_pin, clk_pin, data_pin):
        self.cs = cs_pin
        self.clk = clk_pin
        self.data = data_pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.cs, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.clk, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.data, GPIO.IN)

    def read_temp(self):
        GPIO.output(self.cs, GPIO.LOW)
        time.sleep(0.002)
        raw = 0
        for _ in range(16):
            GPIO.output(self.clk, GPIO.HIGH)
            time.sleep(0.000001)
            bit = GPIO.input(self.data)
            raw = (raw << 1) | bit
            GPIO.output(self.clk, GPIO.LOW)
        GPIO.output(self.cs, GPIO.HIGH)
        # Cek termocouple terhubung
        if raw & 0x4:
            raise RuntimeError("Thermocouple not connected")
        temp = (raw >> 3) * 0.25
        return temp