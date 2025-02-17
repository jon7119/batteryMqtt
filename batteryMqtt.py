import os
import asyncio
import websockets
import logging
import json
import requests
from datetime import datetime
from paho.mqtt import client as mqtt_client

# Configuration du logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

def log(message, level="info"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted_message = f"{timestamp} - {message}"
    if level == "error":
        logging.error(formatted_message)
    elif level == "warning":
        logging.warning(formatted_message)
    else:
        logging.info(formatted_message)

# Fonction pour récupérer une variable d'environnement
def get_env_variable(var_name):
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(f"⚠️ Erreur: La variable d'environnement {var_name} est requise mais non définie.")
    return value

# Configuration des paramètres MQTT et API
broker = get_env_variable('MQTT_BROKER')
port = int(os.getenv('MQTT_PORT', 1883))
topic_battery = os.getenv('MQTT_TOPIC_BATTERY', 'battery/reportEquip')
topic_output = os.getenv('MQTT_TOPIC_OUTPUT', 'battery/outputEquip')
topic_firmware = os.getenv('MQTT_TOPIC_FIRMWARE', 'battery/firmwareEquip')
topic_power = os.getenv('MQTT_TOPIC_POWER', 'battery/set_power')
topic_output_power = os.getenv('MQTT_TOPIC_OUTPUT_POWER', 'battery/outputPower')

username = os.getenv('MQTT_USERNAME', None)
password = os.getenv('MQTT_PASSWORD', None)

ws_uri = "ws://baterway.com:9501/equip/info/"
token_url = "http://baterway.com/api/user/app/login"
firmware_url = "http://baterway.com/api/equip/version/need/upgrade"
output_url = "http://baterway.com/api/scene/user/list/V2"
set_power_url = "http://baterway.com/api/slb/equip/set/power"

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
            print("✅ Token récupéré avec succès !")
            return data['data']['token']
        raise Exception(f"❌ Erreur d'authentification: {data.get('message', 'Réponse inconnue')}")
    except requests.RequestException as e:
        print(f"⚠️ Erreur lors de la récupération du token: {e}")
        return None
		
# Fonction pour modifier la puissance (`power`)
def set_power_value(token, new_power_value):
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "appCode": app_code
    }
    params = {
        "equipId": deviceId,
        "power": new_power_value
    }

    print(f"📡 Tentative de modification de `power` à {new_power_value}W...")

    try:
        response = requests.get(set_power_url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200:
                print(f"✅ Puissance mise à jour à {new_power_value}W !")
                return True
            else:
                print(f"❌ Échec API: {data.get('message', 'Réponse inconnue')}")
        else:
            print(f"⚠️ Réponse API: {response.text}")

        response.raise_for_status()
    except requests.RequestException as e:
        print(f"⚠️ Erreur lors de la modification de `power`: {e}")
        return False
		
# Récupération des informations de sortie (`outputEquip`)
def get_output_info(token):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        response = requests.get(output_url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.RequestException as e:
        print(f"⚠️ Erreur récupération output: {e}")
        return {}

# Récupération des informations firmware (`firmwareEquip`)
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

# Connexion au broker MQTT
def connect_mqtt():
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)

    if username and password:
        client.username_pw_set(username, password)

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("✅ Connecté au broker MQTT!")
            client.subscribe(topic_power)
            print(f"📡 Souscription aux topics MQTT : {topic_power}")
        else:
            print(f"❌ Erreur de connexion MQTT: Code {rc}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker, port)
    client.loop_start()
    return client

# Gestion des commandes MQTT depuis Home Assistant
def on_message(client, userdata, message):
    try:
        print(f"📩 DEBUG: Message MQTT brut reçu sur `{message.topic}`: {message.payload}")

        if not message.payload or message.payload.decode().strip() == "":
            print("⚠️ Message MQTT vide reçu, ignoré.")
            return

        try:
            payload = json.loads(message.payload.decode("utf-8"))
            print(f"🔍 Décode Payload: {payload}")
        except json.JSONDecodeError as e:
            print(f"❌ Erreur: Payload JSON invalide reçu: {message.payload.decode()} - Erreur: {e}")
            return

        if "power" in payload:
            try:
                new_power = int(payload["power"])
                print(f"🔄 Requête reçue: Modifier `power` à {new_power}W via MQTT...")

                token = get_auth_token()
                if token:
                    if set_power_value(token, new_power):
                        print(f"✅ `power` mis à jour à {new_power}W !")
                        client.publish(topic_output_power, json.dumps({"power": new_power}))
                        print(f"📡 Confirmation publiée sur `{topic_output_power}` : {{'power': {new_power}}}")
                    else:
                        print("❌ Erreur lors de la modification de `power` via MQTT.")
                else:
                    print("❌ Impossible de récupérer un token.")
            except ValueError:
                print(f"❌ Erreur: Valeur `power` invalide reçue: {payload['power']}")
        else:
            print(f"⚠️ Message reçu mais `power` non présent: {payload}")
    except Exception as e:
        print(f"❌ Erreur traitement MQTT: {e}")

# Fonction WebSocket pour récupérer les données de la batterie et du firmware
async def websocket_to_mqtt():
    client = connect_mqtt()
    while True:
        try:
            token = get_auth_token()
            if not token:
                print("❌ Impossible de récupérer un token, nouvel essai dans quelques secondes...")
                await asyncio.sleep(5)
                continue

            uri = f"{ws_uri}{token}"
            headers = {
                "Authorization": token,
                "content-type": "application/json",
                "User-Agent": "okhttp/3.12.11"
            }
            async with websockets.connect(uri, extra_headers=headers) as websocket:
                print("📡 WebSocket connecté!")

                request_data = json.dumps({"reportEquip": [deviceId]})
                await websocket.send(request_data)
                print(f"📡 Requête envoyée: {request_data}")

                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=60)
                        print(f"📡 DEBUG: WebSocket message reçu ➝ {message}")

                        if message.strip():
                            client.publish(topic_battery, message)
                            print(f"📡 Données batterie publiées sur MQTT ➝ {message}")

                            output_data = get_output_info(token)
                            firmware_data = get_firmware_update_status(token)

                            if output_data:
                                client.publish(topic_output, json.dumps(output_data))
                                print(f"📡 Données output publiées sur MQTT ➝ {output_data}")

                            if firmware_data:
                                client.publish(topic_firmware, json.dumps(firmware_data))
                                print(f"📡 Données firmware publiées sur MQTT ➝ {firmware_data}")

                    except asyncio.TimeoutError:
                        print("⚠️ Pas de message WebSocket, envoi d'un signal heartbeat...")
                        await websocket.send(request_data)

        except Exception as e:
            print(f"❌ Erreur WebSocket: {e}, tentative de reconnexion dans 5 secondes...")
            await asyncio.sleep(5)

# Fonction principale
async def main():
    await websocket_to_mqtt()

if __name__ == "__main__":
    asyncio.run(main())
