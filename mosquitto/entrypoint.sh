#!/bin/sh
set -e

PASSWD_FILE="/mosquitto/config/passwd"
MQTT_USER="${MQTT_USER:-pratyaksa}"
MQTT_PASS="${MQTT_PASS:-pratyaksa_mqtt}"

if [ ! -f "$PASSWD_FILE" ] || [ ! -s "$PASSWD_FILE" ]; then
    mosquitto_passwd -b "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PASS" 2>/dev/null
    echo "Mosquitto password file created for user: $MQTT_USER"
fi

exec /docker-entrypoint.sh "$@"
