#!/usr/bin/env python

import getopt
import re
import asyncio
import sys
import requests
import websockets
import socket
import logging
import json
import importlib
import xml.etree.ElementTree as ET

importlib.import_module("netatmo_syncapi")

from aiomqtt import Client, MqttError
from netatmo_syncapi import ClientAuthSyncAPI, HomeDataSyncAPI, HomeStatusSyncAPI

from typing import Dict

from pyatmo.exceptions import ApiError, InvalidRoomError, NoDeviceError, NoScheduleError
from websockets.exceptions import ConnectionClosedError
from requests.exceptions import ConnectionError

# Disable globally IPV6 since the connectivity fails for IPV6 destination
# https://stackoverflow.com/questions/33046733/force-requests-to-use-ipv4-ipv6
requests.packages.urllib3.util.connection.HAS_IPV6 = False


def load_config():
    """Load configuration from XML file."""
    tree = ET.parse('netatmo_config.xml')
    root = tree.getroot()
    config = {}
    config['refresh_homedata_timer'] = int(root.find('timers/refresh_homedata').text)
    config['base_mqtt_topic'] = root.find('mqtt/base_topic').text
    config['mqtt_endpoint'] = root.find('mqtt/endpoint').text
    config['mqtt_username'] = root.find('mqtt/username').text
    config['mqtt_password'] = root.find('mqtt/password').text
    config['ws_endpoint'] = root.find('websocket/endpoint').text
    config['netatmo_client_id'] = root.find('netatmo/client_id').text
    config['netatmo_client_secret'] = root.find('netatmo/client_secret').text
    config['reconnect_interval'] = int(root.find('timers/reconnect_interval').text)
    config['max_reconnect_interval'] = int(root.find('timers/max_reconnect_interval').text)
    config['backoff_multiplier'] = float(root.find('timers/backoff_multiplier').text)
    config['logging_prefix'] = root.find('logging/prefix').text
    config['logging_level'] = root.find('logging/level').text
    config['netatmo_username'] = root.find('netatmo/username').text
    config['netatmo_password'] = root.find('netatmo/password').text
    return config


def usage():
    """Print the command-line usage information and exit."""
    print("Usage: "+sys.argv[0]+" [OPTION]\n"
     "Execute the Gateway to Netatmo and bridge to MQTT.\n\n"
     "Configuration is loaded from netatmo_config.xml\n\n"
     "\t-h, --help  display this help and exit")


async def main():
    """Main entry point: parse arguments, load config, set up logging, authenticate, and start the connection loop with reconnection."""
    config = load_config()
    args = sys.argv[1:]
    options = "h"
    long_options = ["help"]
    log_level = logging.INFO
    try:
        arguments, values = getopt.getopt(args, options, long_options)
        for currentArg, currentVal in arguments:
            if currentArg in ("-h", "--help"):
                usage()
                sys.exit()
    except getopt.error as err:
        print(str(err))
        sys.exit()

    # log level from XML config
    try:
        log_level = getattr(logging, config.get('logging_level', 'INFO').upper())
    except AttributeError:
        print(f"Invalid log level in configuration: {config.get('logging_level')} - defaulting to INFO")
        log_level = logging.INFO

    # Configure logging for app and imported APIs
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=log_level)

    # Run sync auth creation in executor
    loop = asyncio.get_event_loop()
    auth = await loop.run_in_executor(
        None,
        lambda: ClientAuthSyncAPI(
            client_id=config['netatmo_client_id'],
            client_secret=config['netatmo_client_secret'],
            username=config['netatmo_username'],
            password=config['netatmo_password'],
            scope="read_thermostat write_thermostat read_smarther write_smarther magellan_scopes"
        )
    )

    home_status = await query_snapshot(auth, config)
    asyncio.get_event_loop().create_task(periodic(auth, config))

    reconnect_interval = config['reconnect_interval']
    while True:
        try:               
            await connect_netatmo(home_status, auth, config)
            logging.getLogger(config['logging_prefix']).debug("Connection successful")
            reconnect_interval = config['reconnect_interval']  # Reset on success
        except (ConnectionError, ConnectionClosedError, socket.gaierror, MqttError, ApiError, Exception) as error:
            logging.getLogger(config['logging_prefix']).warning(f'Error "{error}". Reconnecting in {reconnect_interval} seconds.')
            reconnect_interval = min(reconnect_interval * config['backoff_multiplier'], config['max_reconnect_interval'])
        finally:
            await asyncio.sleep(reconnect_interval)
     #asyncio.get_event_loop().run_until_complete(connect_netatmo())

async def periodic(auth, config):
    """Periodically refresh Netatmo home data to keep the WebSocket connection alive."""
    while True:
        await asyncio.sleep(config['refresh_homedata_timer'])
        await query_snapshot(auth, config)

async def query_snapshot(auth, config):
    """Fetch current home data and status from Netatmo API and publish to MQTT."""
    logging.getLogger(config['logging_prefix']).info(f"Refreshing Netatmo Homedata and Homestatus")
    loop = asyncio.get_event_loop()
    homes_data = await loop.run_in_executor(None, lambda: HomeDataSyncAPI(auth))
    my_home_id = list(homes_data.homes.keys())[0]
    home_status = await loop.run_in_executor(None, lambda: HomeStatusSyncAPI(auth, my_home_id))
    async with Client(hostname=config['mqtt_endpoint'], username=config['mqtt_username'], password=config['mqtt_password']) as client:
        for home in homes_data.homes:
            subtopic = "Home_" + home
            payload = homes_data.homes[home]
            if subtopic is not None:
                 logging.getLogger(config['logging_prefix']).debug(f"Publishing to MQTT topic={config['base_mqtt_topic']}/{subtopic}, payload={payload}")
                 await client.publish(f"{config['base_mqtt_topic']}/{subtopic}", json.dumps(payload))
        for room in home_status.rooms:
            subtopic = "Room_" + room
            payload = home_status.rooms[room]
            if subtopic is not None:
                 logging.getLogger(config['logging_prefix']).debug(f"Publishing to MQTT topic={config['base_mqtt_topic']}/{subtopic}, payload={payload}")
                 await client.publish(f"{config['base_mqtt_topic']}/{subtopic}", json.dumps(payload))
        for module in home_status.modules:
            subtopic = "Module_" + module.replace(':','')
            payload = home_status.modules[module]
            if subtopic is not None:
                 logging.getLogger(config['logging_prefix']).debug(f"Publishing to MQTT topic={config['base_mqtt_topic']}/{subtopic}, payload={payload}")
                 await client.publish(f"{config['base_mqtt_topic']}/{subtopic}", json.dumps(payload))
    return home_status

def get_elements(payload):
    """Extract MQTT topics and payloads from WebSocket push data."""
    return_dict = {}
    if all(keys in payload for keys in ("push_type", "extra_params")):
        push_type = payload.get('push_type')
        extra_params = payload.get('extra_params')
        if 'home' in extra_params:
            home = extra_params.get('home')
            if push_type == 'home_event_changed':
                topic = "Home_" + home['id']
                return_dict[topic] = home
            elif push_type == 'embedded_json':
                if 'modules' in home:
                    for module in home.get('modules'):
                        topic = "Module_" + module['id'].replace(':', '')
                        return_dict[topic] = module
                if 'rooms' in home:
                    for room in home.get('rooms'):
                        topic = "Room_" + room['id']
                        return_dict[topic] = room
    return return_dict


async def route_mqtt_command(client, home_status, config, topic_filter):
    """Listen for MQTT commands and apply them to the Netatmo home status."""
    async for message in client.messages:
        if message.topic.matches(topic_filter):
            try:
                home_re = re.search(r"Home_(\w*)/(\w*)", str(message.topic))
                if (home_re):
                    home_id = home_re.group(1)
                    command = home_re.group(2)
                    json_payload = json.loads(message.payload)
                    logging.getLogger(config['logging_prefix']).info(f"Routing command: Home ID:{home_id} - Command:{command} - Value {json_payload}")
                    if 'mode' in json_payload:
                        home_status.set_thermmode(json_payload.get("mode"), json_payload.get("endtime"), json_payload.get("schedule_id"))
                    else:
                        home_status.set_coolmode(json_payload.get("cooling_mode"), json_payload.get("endtime"), json_payload.get("schedule_id"))
            # Search through modules elements
                module_re = re.search(r"Module_(\w*)/(\w*)", str(message.topic))
                if (module_re):
                    module_id = module_re.group(1)
                    module_id = ':'.join(a+b for a,b in zip(module_id[::2], module_id[1::2]))
                    command = module_re.group(2)
                    logging.getLogger(config['logging_prefix']).info(f"Routing command: Module ID:{module_id} - Command:{command} - Value {message.payload}")
                    home_status.set_module_state(module_id, command, message.payload.decode("utf-8"))

            # Search through rooms elements
                room_re = re.search(r"Room_(\w*)/(\w*)", str(message.topic))
                if (room_re):
                    room_id = room_re.group(1)
                    command = room_re.group(2)
                    logging.getLogger(config['logging_prefix']).info(f"Routing command: Room ID:{room_id} - Command:{command} - Value {message.payload}")
                    home_status.set_room_state(room_id, message.payload.decode("utf-8"))
            except (ApiError) as error:
                logging.getLogger(config['logging_prefix']).error(f'Error "{error}"')


async def connect_netatmo(home_status, auth, config):
    """Establish WebSocket connection to Netatmo and MQTT client, handle incoming messages."""
    async with websockets.connect(
        config['ws_endpoint'], ssl=True
    ) as websocket:
        logging.getLogger(config['logging_prefix']).debug(f"Started")
        json_dict = {"filter":"silent","access_token":auth._oauth.token['access_token'],"app_type":"app_magellan","action":"Subscribe","version":"1.19.2.0","platform":"Android"}
        json_string = json.dumps(json_dict, sort_keys=True)

        # Connect MQTT Client using asyncio-mqtt wrapper
        async with Client(hostname=config['mqtt_endpoint'], username=config['mqtt_username'], password=config['mqtt_password']) as client:
            asyncio.create_task(route_mqtt_command(client, home_status, config, f"{config['base_mqtt_topic']}/#"))
            await client.subscribe(f"{config['base_mqtt_topic']}/#")
            await websocket.send(json_string)
            while True:
                ws_message = await websocket.recv()
                json_processed = json.loads(ws_message)
                room_and_modules = get_elements(json_processed)
                for subtopic in room_and_modules:
                    logging.getLogger(config['logging_prefix']).debug(f"Publishing to MQTT topic={config['base_mqtt_topic']}/{subtopic}, payload={room_and_modules[subtopic]}")
                    await client.publish(f"{config['base_mqtt_topic']}/{subtopic}", json.dumps(room_and_modules[subtopic]))


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
