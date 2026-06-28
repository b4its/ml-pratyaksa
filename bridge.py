# bridge.py
import paho.mqtt.client as mqtt
import redis
import json
import os

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
STREAM_PREFIX = "stream:sensors:"

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def on_connect(client, userdata, flags, rc):
    client.subscribe("edge/data")
    print("Bridge connected to MQTT")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        # Asumsikan ada field equipment_type, jika tidak default 'unknown'
        etype = data.get("equipment_type", "unknown")
        # Format stream key sesuai app.py: "stream:sensors:{equipment_type}"
        stream_key = f"{STREAM_PREFIX}{etype}"
        r.xadd(stream_key, {
            "asset_id": data.get("asset_id", "edge_asset"),
            "equipment_type": etype,
            "timestamp": data.get("timestamp", ""),
            "features": json.dumps(data["sensor"]),
        })
        print(f"Data masuk ke Redis Stream: {stream_key}")
    except Exception as e:
        print("Bridge error:", e)

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect("mosquitto", 1883, 60)
client.loop_forever()