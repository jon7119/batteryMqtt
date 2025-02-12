import os
import asyncio
import websockets
import json
import requests
from paho.mqtt import client as mqtt_client

# Function to get an environment variable, raising an error if not set
def get_env_variable(var_name):
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(f"⚠️ Error: Environment variable {var_name} is required but not set.")
    return value

# Configuration settings
broker = get_env_variable('MQTT_BROKER')
port = int(os.getenv('MQTT_PORT', 1883))
topic_battery = os.getenv('MQTT_TOPIC_BATTERY', 'battery/reportEquip')
topic_output = os.getenv('MQTT_TOPIC_OUTPUT', 'battery/outputEquip')
topic_firmware = os.getenv('MQTT_TOPIC_FIRMWARE', 'battery/firmwareEquip')
command_topic = os.getenv('MQTT_TOPIC_COMMAND', 'battery/commandEquip')
username = os.getenv('MQTT_USERNAME', None)
password = os.getenv('MQTT_PASSWORD', None)
ws_uri = "ws://baterway.com:9501/equip/info/"
token_url = "http://baterway.com/api/user/app/login"
firmware_url = "http://baterway.com/api/equip/version/need/upgrade"
output_url = "http://baterway.com/api/scene/user/list/V2"
heartbeat_interval = int(os.getenv('HEARTBEAT_INTERVAL', 60))
reconnect_delay = int(os.getenv('RECONNECT_DELAY', 5))

app_code = os.getenv('APP_CODE', 'Storcube')
login_name = get_env_variable('LOGIN_NAME')
password_auth = get_env_variable('PASSWORD')
deviceId = get_env_variable('DEVICE_ID')

token_credentials = {
    "appCode": app_code,
    "loginName": login_name,
    "password": password_auth
}

# Function to fetch authentication token
def get_auth_token():
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(token_url, json=token_credentials, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 200:
            return data['data']['token']
        raise Exception(f"❌ Authentication error: {data.get('message', 'Unknown response')}")
    except requests.RequestException as e:
        print(f"⚠️ Error retrieving token: {e}")
        return None

# Function to fetch output data (outputEquip)
def get_output_info(token):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        response = requests.get(output_url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.RequestException as e:
        print(f"⚠️ Error retrieving output data: {e}")
        return {}

# Function to fetch firmware update status (firmwareEquip)
def get_firmware_update_status(token):
    url = f"{firmware_url}?equipId={deviceId}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.RequestException as e:
        print(f"⚠️ Error retrieving firmware status: {e}")
        return {}

# Function to connect to the MQTT broker with an updated on_connect callback
def connect_mqtt():
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    if username and password:
        client.username_pw_set(username, password)

    # The on_connect function must have 5 parameters (updated for paho-mqtt)
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("✅ Connected to MQTT broker!")
            client.subscribe(command_topic)
        else:
            print(f"❌ MQTT connection error: Code {rc}")

    client.on_connect = on_connect
    client.connect(broker, port)
    client.loop_start()
    return client

# WebSocket function with MQTT topic publishing corrections
async def websocket_to_mqtt():
    client = connect_mqtt()
    while True:
        try:
            token = get_auth_token()
            if not token:
                print("❌ Unable to retrieve a token, retrying in a few seconds...")
                await asyncio.sleep(reconnect_delay)
                continue

            uri = f"{ws_uri}{token}"
            headers = {
                "Authorization": token,
                "content-type": "application/json",
                "User-Agent": "okhttp/3.12.11"
            }
            async with websockets.connect(uri, extra_headers=headers) as websocket:
                print("📡 WebSocket connected!")

                # Send an initial request to get equipment information
                request_data = json.dumps({"reportEquip": [deviceId]})
                await websocket.send(request_data)
                print(f"📡 Request sent: {request_data}")

                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=heartbeat_interval + 5)
                        print(f"📡 Received message: {message}")

                        # Publish battery data to MQTT
                        client.publish(topic_battery, message)
                        print("✅ Battery data published to MQTT")

                        # Retrieve and publish additional data (output & firmware)
                        token = get_auth_token()
                        output_data = get_output_info(token)
                        firmware_data = get_firmware_update_status(token)

                        if output_data:
                            client.publish(topic_output, json.dumps(output_data))
                            print("✅ Output data published to MQTT")

                        if firmware_data:
                            client.publish(topic_firmware, json.dumps(firmware_data))
                            print("✅ Firmware update data published to MQTT")

                    except asyncio.TimeoutError:
                        print("⚠️ No WebSocket message received, sending a heartbeat request...")
                        await websocket.send(request_data)
                    except websockets.exceptions.ConnectionClosed:
                        print("❌ WebSocket closed, attempting to reconnect...")
                        break

        except Exception as e:
            print(f"❌ WebSocket error: {e}, retrying in {reconnect_delay} seconds...")
            await asyncio.sleep(reconnect_delay)

# Main function that manages WebSocket and MQTT communication
async def main():
    while True:
        try:
            await websocket_to_mqtt()
        except Exception as e:
            print(f"❌ Main error: {e}")
            await asyncio.sleep(reconnect_delay)

# Start the script using asyncio
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Stopping the program...")
