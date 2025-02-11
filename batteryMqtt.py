import os
import asyncio
import websockets
import json
import requests
from paho.mqtt import client as mqtt_client

# Fonction pour récupérer une variable d'environnement
def get_env_variable(var_name):
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(f"⚠️ Erreur: La variable d'environnement {var_name} est requise mais non définie.")
    return value

# Configuration des paramètres
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

# Récupération du token d'authentification
def get_auth_token():
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(token_url, json=token_credentials, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 200:
            return data['data']['token']
        raise Exception(f"❌ Erreur d'authentification: {data.get('message', 'Réponse inconnue')}")
    except requests.RequestException as e:
        print(f"⚠️ Erreur lors de la récupération du token: {e}")
        return None

# Récupération des informations de sortie (outputEquip)
def get_output_info(token):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        response = requests.get(output_url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.RequestException as e:
        print(f"⚠️ Erreur récupération output: {e}")
        return {}

# Récupération du statut de mise à jour du firmware (firmwareEquip)
def get_firmware_update_status(token):
    url = f"{firmware_url}?equipId={deviceId}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.RequestException as e:
        print(f"⚠️ Erreur récupération firmware: {e}")
        return {}

# Connexion au broker MQTT avec correction de `on_connect`
def connect_mqtt():
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    if username and password:
        client.username_pw_set(username, password)

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("✅ Connecté au broker MQTT!")
            client.subscribe(command_topic)
        else:
            print(f"❌ Erreur de connexion MQTT: Code {rc}")

    client.on_connect = on_connect
    client.connect(broker, port)
    client.loop_start()
    return client

# Fonction WebSocket avec correction des publications MQTT
async def websocket_to_mqtt():
    client = connect_mqtt()
    while True:
        try:
            token = get_auth_token()
            if not token:
                print("❌ Impossible de récupérer un token, nouvel essai dans quelques secondes...")
                await asyncio.sleep(reconnect_delay)
                continue

            uri = f"{ws_uri}{token}"
            headers = {
                "Authorization": token,
                "content-type": "application/json",
                "User-Agent": "okhttp/3.12.11"
            }
            async with websockets.connect(uri, extra_headers=headers) as websocket:
                print("📡 WebSocket connecté!")

                # Envoi d'une requête initiale pour obtenir les infos de l'équipement
                request_data = json.dumps({"reportEquip": [deviceId]})
                await websocket.send(request_data)
                print(f"📡 Requête envoyée: {request_data}")

                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=heartbeat_interval + 5)
                        print(f"📡 Message reçu: {message}")

                        client.publish(topic_battery, message)
                        print("✅ Données batterie publiées sur MQTT")

                        # Récupération et publication des données supplémentaires
                        token = get_auth_token()
                        output_data = get_output_info(token)
                        firmware_data = get_firmware_update_status(token)

                        if output_data:
                            client.publish(topic_output, json.dumps(output_data))
                            print("✅ Données Output publiées sur MQTT")

                        if firmware_data:
                            client.publish(topic_firmware, json.dumps(firmware_data))
                            print("✅ Données Firmware publiées sur MQTT")

                    except asyncio.TimeoutError:
                        print("⚠️ Pas de message WebSocket, envoi d'un signal heartbeat...")
                        await websocket.send(request_data)
                    except websockets.exceptions.ConnectionClosed:
                        print("❌ WebSocket fermé, reconnexion...")
                        break

        except Exception as e:
            print(f"❌ Erreur WebSocket: {e}, tentative de reconnexion dans {reconnect_delay} secondes...")
            await asyncio.sleep(reconnect_delay)

# Fonction principale qui gère WebSocket et MQTT
async def main():
    while True:
        try:
            await websocket_to_mqtt()
        except Exception as e:
            print(f"❌ Erreur principale: {e}")
            await asyncio.sleep(reconnect_delay)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Arrêt du programme...")
