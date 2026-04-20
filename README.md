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