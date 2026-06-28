# edge/drivers/adxl345.py
import smbus
import time

ADXL345_ADDR = 0x53
POWER_CTL = 0x2D
DATA_FORMAT = 0x31
DATAX0 = 0x32

class ADXL345:
    def __init__(self, bus=1):
        self.bus = smbus.SMBus(bus)
        # Inisialisasi
        self.bus.write_byte_data(ADXL345_ADDR, POWER_CTL, 0x08)  # wake up
        time.sleep(0.01)

    def read_accel(self):
        data = self.bus.read_i2c_block_data(ADXL345_ADDR, DATAX0, 6)
        x = self._twos_comp(data[0] | (data[1] << 8))
        y = self._twos_comp(data[2] | (data[3] << 8))
        z = self._twos_comp(data[4] | (data[5] << 8))
        # Konversi ke g (skala default ±2g)
        scale = 2 / 512.0
        return x * scale, y * scale, z * scale

    @staticmethod
    def _twos_comp(val):
        if val >= 0x8000:
            return -((65535 - val) + 1)
        else:
            return val