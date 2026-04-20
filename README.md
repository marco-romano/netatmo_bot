# netatmo_bot

## Description

`netatmo_bridge.py` is a bridge application that connects Netatmo smart home devices (such as thermostats and energy monitors) to an MQTT broker. It has been tested and works with most BTicino Living Now devices. It periodically fetches home data and status from the Netatmo API, publishes updates to MQTT topics, and listens for real-time events via WebSocket. Additionally, it subscribes to MQTT command topics to control Netatmo devices, allowing seamless integration with home automation systems like Home Assistant or OpenHAB.

## Dependencies

The application depends on the following Python libraries:

- `requests` - For HTTP requests to the Netatmo API
- `websockets` - For WebSocket connections to Netatmo
- `aiomqtt` - For asynchronous MQTT client operations
- `pyatmo` - Official Netatmo API library
- `oauthlib` - For OAuth2 authentication
- `requests-oauthlib` - For OAuth2 session handling with requests

## Installation

1. **Clone the repository:**
   ```
   git clone https://github.com/marco-romano/netatmo_bot.git
   cd netatmo_bot
   ```

2. **Install dependencies:**
   ```
   pip install requests websockets aiomqtt pyatmo oauthlib requests-oauthlib
   ```

3. **Configure the application:**
   - Copy `netatmo_config_template.xml` to `netatmo_config.xml`.
   - Edit `netatmo_config.xml` with your Netatmo API credentials, MQTT broker details, and other settings.

4. **Run the application:**
   - **Manual execution:**
     ```
     python3 netatmo_bridge.py
     ```
   - **Using crontab (for automatic startup):**
     Add the following line to your crontab (`crontab -e`):
     ```
     @reboot /path/to/python3 /path/to/netatmo_bot/netatmo_bridge.py
     ```
     Replace `/path/to/` with the actual paths.
   - **Using systemd service (recommended for production):**
     - Copy `netatmo.service` to `/etc/systemd/system/netatmo.service`.
     - Edit the service file to match your paths and user.
     - Enable and start the service:
       ```
       sudo systemctl daemon-reload
       sudo systemctl enable netatmo
       sudo systemctl start netatmo
       ```