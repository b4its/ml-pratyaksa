import paho.mqtt.client as mqtt
import json
from .buffer import OfflineBuffer

class EdgeMQTT:
    def __init__(self, broker="localhost", port=1883, topic="edge/data"):
        self.client = mqtt.Client()
        self.broker = broker
        self.port = port
        self.topic = topic
        self.buffer = OfflineBuffer()
        self.connected = False
        self._setup()

    def _setup(self):
        self.client.on_connect = self._on_connect

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            self._flush_buffer()

    def connect(self):
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def publish(self, data: dict):
        if self.connected:
            self.client.publish(self.topic, json.dumps(data))
        else:
            self.buffer.store(data)

    def _flush_buffer(self):
        unsent = self.buffer.get_unsent()
        for row_id, ts, payload_str in unsent:
            self.client.publish(self.topic, payload_str)
            self.buffer.mark_sent([row_id])
        self.buffer.cleanup()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()