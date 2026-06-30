FROM python:3.11-slim
WORKDIR /app
RUN pip install paho-mqtt redis
COPY bridge.py .
ENV MQTT_USER=pratyaksa
ENV MQTT_PASS=pratyaksa_mqtt
CMD ["python", "bridge.py"]