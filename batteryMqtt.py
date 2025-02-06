import os
import asyncio
import websockets
import json
import requests
from paho.mqtt import client as mqtt_client

# Function to retrieve an environment variable and raise an error if not set
def get_env_variable(var_name):
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(f"Environment variable {var_name} is required but not set.")
    return value

# Configuration
broker = get_env_variable('MQTT_BROKER')
port = int(os.getenv('MQTT_PORT', 1883))
topic = os.getenv('MQTT_TOPIC', 'battery/reportEquip')
username = os.getenv('MQTT_USERNAME', None)
password = os.getenv('MQTT_PASSWORD', None)
ws_uri = "ws://baterway.com:9501/equip/info/"
token_url = "http://baterway.com/api/user/app/login"
firmware_url = "http://baterway.com/api/device/firmware"
update_url = "http://baterway.com/api/device/update"
heartbeat_interval = int(os.getenv('HEARTBEAT_INTERVAL', 60))
reconnect_delay = int(os.getenv('RECONNECT_DELAY', 60))
data_refresh_interval = int(os.getenv('DATA_REFRESH_INTERVAL', 10))
app_code = os.getenv('APP_CODE', 'ASGOFT')
login_name = get_env_variable('LOGIN_NAME')
password_auth = get_env_variable('PASSWORD')
token_credentials = {
    "appCode": app_code,
    "loginName": login_name,
    "password": password_auth
}
deviceId = get_env_variable('DEVICE_ID')

# Retrieve authentication token
def get_auth_token():
    headers = {'Content-Type': 'application/json'}
    response = requests.post(token_url, json=token_credentials, headers=headers)
    if response.status_code == 200:
        response_data = response.json()
        if response_data['code'] == 200:
            return response_data['data']['token']
        else:
            raise Exception(f"Failed to retrieve token: {response_data['message']}")
    else:
        raise Exception(f"HTTP error during token retrieval: Status {response.status_code}")

# Retrieve firmware version
def get_firmware_version(token):
    headers = {"Authorization": token, "content-type": "application/json"}
    response = requests.get(firmware_url, headers=headers)
    if response.status_code == 200:
        data = response.json().get("data", {})
        firmware_info = {
            "storcube_lastBigVersion": data.get("lastBigVersion", "Unknown"),
            "storcube_currentBigVersion": data.get("currentBigVersion", "Unknown"),
            "storcube_upgradeAvailable": data.get("upgread", False)
        }
        print(f"🔍 Firmware Info Retrieved: {firmware_info}")
        return firmware_info
    print("❌ No firmware data received from API.")
    return {}

# Initiate firmware update
def update_firmware(token):
    headers = {"Authorization": token, "content-type": "application/json"}
    payload = {"device_id": deviceId}
    response = requests.post(update_url, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()
    return {"error": "Failed to start update"}

# Connect to the MQTT broker
def connect_mqtt():
    client = mqtt_client.Client()
    if username and password:
        client.username_pw_set(username, password)
    client.connect(broker, port)
    return client

# Receive and process WebSocket messages
async def receive_messages(websocket, mqtt_client, token):
    try:
        request_data = json.dumps({"reportEquip": [deviceId]})
        await websocket.send(request_data)
        print(f"📡 Request sent: {request_data}")
        await asyncio.sleep(2)
        iteration_count = 0  # Count iterations to prevent overflow

        firmware_info = get_firmware_version(token)
        if firmware_info:
            firmware_message = json.dumps(firmware_info)
            print(f"📤 DEBUG Sending Firmware MQTT: {firmware_message}")
            mqtt_client.publish(topic, firmware_message)
        
        while True:
            message = await websocket.recv()
            print(f"📡 Message received: {message}")

            try:
                parsed_message = json.loads(message)
                print(f"🧐 JSON interpreted: {json.dumps(parsed_message, indent=2)}")

                if deviceId in parsed_message:
                    equip_data = parsed_message[deviceId]
                    formatted_data = {}
                    
                    for key, value in equip_data.items():
                        if isinstance(value, list) and key == "list":
                            formatted_data["storcube_list"] = [
                                {f"storcube_{subkey}": subvalue for subkey, subvalue in item.items()}
                                for item in value
                            ]
                        else:
                            formatted_data[f"storcube_{key}"] = value
                    
                    formatted_data["storcube_battery_status"] = "OK"
                    full_message = json.dumps(formatted_data)
                    
                    print(f"📤 Sending MQTT: {full_message}")
                    mqtt_client.publish(topic, full_message)
                    print("✅ MQTT message successfully published!")
                else:
                    print("⚠️ Equipment ID not yet found in the data. Waiting...")

                iteration_count += 1
                if iteration_count >= 20:
                    print("🔄 Reconnecting WebSocket to prevent overflow...")
                    break  # Exit loop to restart connection

                await asyncio.sleep(data_refresh_interval)  # Adjust waiting time between received messages

            except json.JSONDecodeError:
                print("❌ Error: The received message is not valid JSON.")

    except websockets.exceptions.ConnectionClosed:
        print("🔌 WebSocket disconnected. Keeping the connection open...")

# Main WebSocket and MQTT loop
async def websocket_to_mqtt():
    client = connect_mqtt()
    client.loop_start()
    while True:
        try:
            token = get_auth_token()
            uri = ws_uri + token
            headers = {
                "Authorization": token,
                "content-type": "application/json",
                "User-Agent": "okhttp/3.12.11"
            }
            async with websockets.connect(uri, extra_headers=list(headers.items())) as websocket:
                await receive_messages(websocket, client, token)
        except Exception as e:
            print(f"❌ Error: {e}, reconnecting in {reconnect_delay} seconds...")
            await asyncio.sleep(reconnect_delay)

# Execute the asyncio loop
async def main():
    await websocket_to_mqtt()

asyncio.run(main())
