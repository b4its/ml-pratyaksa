# edge/drivers/pressure_transducer.py
import spidev

class PressureTransducer:
    def __init__(self, channel=0, v_ref=5.0, max_pressure_bar=10):
        self.channel = channel
        self.v_ref = v_ref
        self.max_pressure = max_pressure_bar
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)  # bus 0, device 0
        self.spi.max_speed_hz = 1350000

    def read_voltage(self):
        adc = self.spi.xfer2([1, (8 + self.channel) << 4, 0])
        data = ((adc[1] & 3) << 8) + adc[2]
        return (data * self.v_ref) / 1023.0

    def read_pressure(self):
        voltage = self.read_voltage()
        # Asumsikan 0.5V = 0 bar, 4.5V = max pressure
        pressure = (voltage - 0.5) * self.max_pressure / 4.0
        return max(0, pressure)