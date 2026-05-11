import logging
import json
from json import JSONDecodeError
from time import sleep
from typing import Any, Callable, Dict, Optional, Tuple, Union

import requests
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError  # type: ignore
from requests_oauthlib import OAuth2Session  # type: ignore

from pyatmo.exceptions import ApiError, InvalidRoomError, NoDeviceError, NoScheduleError
#from pyatmo.helpers import ERRORS



ERRORS: Dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    406: "Not Acceptable",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}



LOG = logging.getLogger(__name__)

_APP_NETATMO_BASE_URL : str = "https://app.netatmo.net/"
#_APP_NETATMO_BASE_URL : str = "https://api.netatmo.net/"
_APP_NETATMO_API_TYPE : str = "app_magellan"
_APP_NETATMO_API_VERSION : str = "3.5.2.0"

_GETHOMESDATA_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/homesdata"
_GETHOMESTATUS_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "syncapi/v1/homestatus"
_SETTHERMMODE_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/setthermmode"
_SETHOMEDATA_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/sethomedata"
_SETROOMTHERMPOINT_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/setroomthermpoint"
_GETROOMMEASURE_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/getroommeasure"
_SWITCHHOMESCHEDULE_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "api/switchhomeschedule"
_SETSTATE_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "syncapi/v1/setstate"
_AUTH_SYNCAPI_REQ = _APP_NETATMO_BASE_URL + "oauth2/token"


AUTH_REQ = _APP_NETATMO_BASE_URL + "oauth2/token"
AUTH_URL = _APP_NETATMO_BASE_URL + "oauth2/authorize"
WEBHOOK_URL_ADD = _APP_NETATMO_BASE_URL + "api/addwebhook"
WEBHOOK_URL_DROP = _APP_NETATMO_BASE_URL + "api/dropwebhook"


# Possible scops
ALL_SCOPES = [
    "read_station",
    "read_camera",
    "access_camera",
    "write_camera",
    "read_presence",
    "access_presence",
    "write_presence",
    "read_homecoach",
    "read_smokedetector",
    "read_thermostat",
    "write_thermostat",
    "magellan_scopes",
]

DEVICE_TYPES = [
    "NAPlug","BNS","NLG","NBG","TPSG", "NLE", "OTH"
]


class NetatmoOAuth2SyncAPI:
    """
    Handle authentication with OAuth2
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        redirect_uri: Optional[str] = None,
        token: Optional[Dict[str, str]] = None,
        token_updater: Optional[Callable[[str], None]] = None,
        scope: Optional[str] = "read_station",
    ) -> None:
        """Initialize self.

        Keyword Arguments:
            client_id {str} -- Application client ID delivered by Netatmo on dev.netatmo.com (default: {None})
            client_secret {str} -- Application client secret delivered by Netatmo on dev.netatmo.com (default: {None})
            redirect_uri {Optional[str]} -- Redirect URI where to the authorization server will redirect with an authorization code (default: {None})
            token {Optional[Dict[str, str]]} -- Authorization token (default: {None})
            token_updater {Optional[Callable[[str], None]]} -- Callback when the token is updated (default: {None})
            scope {Optional[str]} -- List of scopes (default: {"read_station"})
                read_station: to retrieve weather station data (Getstationsdata, Getmeasure)
                access_camera: to access the camera, the videos and the live stream
                write_camera: to set home/away status of persons (Setpersonsaway, Setpersonshome)
                read_thermostat: to retrieve thermostat data (Getmeasure, Getthermostatsdata)
                write_thermostat: to set up the thermostat (Syncschedule, Setthermpoint)
                read_presence: to retrieve Presence data (Gethomedata, Getcamerapicture)
                access_presence: to access the live stream, any video stored on the SD card and to retrieve Presence's lightflood status
                read_homecoach: to retrieve Home Coache data (Gethomecoachsdata)
                read_smokedetector: to retrieve the smoke detector status (Gethomedata)
                Several values can be used at the same time, ie: 'read_station read_camera'
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_updater = token_updater

        if token:
            self.scope = " ".join(token["scope"])

        else:
            self.scope = " ".join(ALL_SCOPES) if not scope else scope

        self.extra = {"client_id": self.client_id, "client_secret": self.client_secret}

        self._oauth = OAuth2Session(
            client_id=self.client_id,
            token=token,
            token_updater=self.token_updater,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
        )

    def refresh_tokens(self) -> Dict[str, Union[str, int]]:
        """Refresh and return new tokens."""
        token = self._oauth.refresh_token(AUTH_REQ, **self.extra)

        if self.token_updater is not None:
            self.token_updater(token)

        return token

    def post_request(
        self, url: str, params: Optional[Dict] = None, timeout: int = 5,
    ) -> Any:
        """Wrapper for post requests."""
        resp = None
        if not params:
            params = {}

        if "json" in params:
            json_params: Optional[str] = params.pop("json")

        else:
            json_params = None

        if "https://" not in url:
            try:
                resp = requests.post(url, data=params, timeout=timeout)
            except requests.exceptions.ChunkedEncodingError:
                LOG.debug("Encoding error when connecting to '%s'", url)
            except requests.exceptions.ConnectTimeout:
                LOG.debug("Connection to %s timed out", url)
            except requests.exceptions.ConnectionError:
                LOG.debug("Remote end closed connection without response (%s)", url)

        else:

            def query(url: str, params: Dict, timeout: int, retries: int) -> Any:
                if retries == 0:
                    LOG.error("Too many retries")
                    return

                try:
                    if json_params:
                        rsp = self._oauth.post(
                            url=url, json=json_params, timeout=timeout
                        )

                    else:
                        rsp = self._oauth.post(url=url, data=params, timeout=timeout)

                    return rsp

                except (
                    TokenExpiredError,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.ConnectionError,
                ):
                    self._oauth.token = self.refresh_tokens()
                    # Sleep for 1 sec to prevent authentication related
                    # timeouts after a token refresh.
                    sleep(1)
                    return query(url, params, timeout * 2, retries - 1)

            resp = query(url, params, timeout, 10)

        if resp is None:
            LOG.debug("Resp is None - %s", resp)
            return None

        if not resp.ok:
            LOG.debug("The Netatmo API returned %s", resp.status_code)
            LOG.debug("Netato API error: %s", resp.content)
            try:
                raise ApiError(
                    f"{resp.status_code} - "
                    f"{ERRORS.get(resp.status_code, '')} - "
                    f"{resp.json()['error']['message']} "
                    f"({resp.json()['error']['code']}) "
                    f"when accessing '{url}'"
                )

            except JSONDecodeError:
                raise ApiError(
                    f"{resp.status_code} - "
                    f"{ERRORS.get(resp.status_code, '')} - "
                    f"when accessing '{url}'"
                )

        try:
            if "application/json" in resp.headers.get("content-type", []):
                return resp.json()

            if resp.content not in [b"", b"None"]:
                return resp.content

        except (TypeError, AttributeError):
            LOG.debug("Invalid response %s", resp)

        return None

    def get_authorization_url(self, state: Optional[str] = None) -> Tuple[str, str]:
        return self._oauth.authorization_url(AUTH_URL, state)

    def request_token(
        self, authorization_response: Optional[str] = None, code: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Generic method for fetching a Netatmo access token.
        :param authorization_response: Authorization response URL, the callback
                                       URL of the request back to you.
        :param code: Authorization code
        :return: A token dict
        """
        return self._oauth.fetch_token(
            AUTH_REQ,
            authorization_response=authorization_response,
            code=code,
            client_secret=self.client_secret,
            include_client_id=True,
        )

    def addwebhook(self, webhook_url: str) -> None:
        post_params = {"url": webhook_url}
        resp = self.post_request(WEBHOOK_URL_ADD, post_params)
        LOG.debug("addwebhook: %s", resp)

    def dropwebhook(self) -> None:
        post_params = {"app_types": "app_security"}
        resp = self.post_request(WEBHOOK_URL_DROP, post_params)
        LOG.debug("dropwebhook: %s", resp)


class ClientAuthSyncAPI(NetatmoOAuth2SyncAPI):
    """
    Request authentication and keep access token available through token method. Renew it automatically if necessary
    Args:
        clientId (str): Application clientId delivered by Netatmo on dev.netatmo.com
        clientSecret (str): Application Secret key delivered by Netatmo on dev.netatmo.com
        username (str)
        password (str)
        scope (Optional[str]):
            read_station: to retrieve weather station data (Getstationsdata, Getmeasure)
            read_camera: to retrieve Welcome data (Gethomedata, Getcamerapicture)
            access_camera: to access the camera, the videos and the live stream
            write_camera: to set home/away status of persons (Setpersonsaway, Setpersonshome)
            read_thermostat: to retrieve thermostat data (Getmeasure, Getthermostatsdata)
            write_thermostat: to set up the thermostat (Syncschedule, Setthermpoint)
            read_presence: to retrieve Presence data (Gethomedata, Getcamerapicture)
            access_presence: to access the live stream, any video stored on the SD card and to retrieve Presence's lightflood status
            read_homecoach: to retrieve Home Coache data (Gethomecoachsdata)
            read_smokedetector: to retrieve the smoke detector status (Gethomedata)
            Several value can be used at the same time, ie: 'read_station read_camera'
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        scope="read_station",
    ):
        # pylint: disable=super-init-not-called
        self._client_id = client_id
        self._client_secret = client_secret

        self.extra = {"client_id": self._client_id, "client_secret": self._client_secret}
        self.token_updater = None

        self._oauth = OAuth2Session(client=LegacyApplicationClient(client_id=client_id))
        self._oauth.fetch_token(
            token_url=_AUTH_SYNCAPI_REQ,
            username=username,
            password=password,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
            include_client_id=True,
        )



class HomeDataSyncAPI:
    """
    Class of Netatmo energy devices (relays, thermostat modules and valves)
    """

    def __init__(self, auth: NetatmoOAuth2SyncAPI) -> None:
        """Initialize self.

        Arguments:
            auth {NetatmoOAuth2} -- Authentication information with a valid access token

        Raises:
            NoDevice: No devices found.
        """
        self.auth = auth

        post_params = {
            "app_type" : _APP_NETATMO_API_TYPE,
            "app_version" : _APP_NETATMO_API_VERSION,
            "device_types" : DEVICE_TYPES
        }

        resp = self.auth.post_request(url=_GETHOMESDATA_SYNCAPI_REQ, params=post_params)
        if resp is None or "body" not in resp:
            raise NoDevice("No thermostat data returned by Netatmo server")

        self.raw_data = resp["body"].get("homes")
        if not self.raw_data:
            raise NoDevice("No thermostat data available")

        self.homes: Dict = {d["id"]: d for d in self.raw_data}

        self.modules: Dict = {}
        self.rooms: Dict = {}
        self.schedules: Dict = {}
        self.zones: Dict = {}
        self.setpoint_duration: Dict = {}

        for item in self.raw_data:
            home_id = item.get("id")
            home_name = item.get("name")

            if not home_name:
                home_name = "Unknown"
                self.homes[home_id]["name"] = home_name

            if "modules" in item:
                if home_id not in self.modules:
                    self.modules[home_id] = {}

                for module in item["modules"]:
                    self.modules[home_id][module["id"]] = module

                if home_id not in self.rooms:
                    self.rooms[home_id] = {}

                if home_id not in self.schedules:
                    self.schedules[home_id] = {}

                if home_id not in self.zones:
                    self.zones[home_id] = {}

                if home_id not in self.setpoint_duration:
                    self.setpoint_duration[home_id] = {}

                if "therm_setpoint_default_duration" in item:
                    self.setpoint_duration[home_id] = item[
                        "therm_setpoint_default_duration"
                    ]

                if "rooms" in item:
                    for room in item["rooms"]:
                        self.rooms[home_id][room["id"]] = room

                if "therm_schedules" in item:
                    for schedule in item["therm_schedules"]:
                        self.schedules[home_id][schedule["id"]] = schedule

                    for schedule in item["therm_schedules"]:
                        schedule_id = schedule["id"]
                        if schedule_id not in self.zones[home_id]:
                            self.zones[home_id][schedule_id] = {}

                        for zone in schedule["zones"]:
                            self.zones[home_id][schedule_id][zone["id"]] = zone

    def _get_selected_schedule(self, home_id: str) -> Dict:
        """Get the selected schedule for a given home ID."""
        for value in self.schedules.get(home_id, {}).values():
            if "selected" in value.keys():
                return value

        return {}

    def switch_home_schedule(self, home_id: str, schedule_id: str) -> Any:
        """Switch the schedule for a give home ID."""
        schedules = {
            self.schedules[home_id][s]["name"]: self.schedules[home_id][s]["id"]
            for s in self.schedules.get(home_id, {})
        }
        if schedule_id not in list(schedules.values()):
            raise NoSchedule("%s is not a valid schedule id" % schedule_id)

        post_params = {
            "home_id": home_id,
            "schedule_id": schedule_id,
        }
        resp = self.auth.post_request(url=_SWITCHHOMESCHEDULE_SYNCAPI_REQ, params=post_params)
        LOG.debug("Response: %s", resp)

    def get_hg_temp(self, home_id: str) -> Optional[float]:
        """Return frost guard temperature value."""
        return self._get_selected_schedule(home_id).get("hg_temp")

    def get_away_temp(self, home_id: str) -> Optional[float]:
        """Return the configured away temperature value."""
        return self._get_selected_schedule(home_id).get("away_temp")

    def get_thermostat_type(self, home_id: str, room_id: str) -> Optional[str]:
        """Return the thermostat type of the room."""
        for module in self.modules.get(home_id, {}).values():
            if module.get("room_id") == room_id:
                return module.get("type")

        return None


class HomeStatusSyncAPI:
    def __init__(self, auth: NetatmoOAuth2SyncAPI, home_id: str):
        self.auth = auth

        self.home_id = home_id
        post_params = {
            "app_type" : _APP_NETATMO_API_TYPE,
            "app_version" : _APP_NETATMO_API_VERSION,
            "home_id": self.home_id,
            "device_types" : DEVICE_TYPES
        }

        resp = self.auth.post_request(url=_GETHOMESTATUS_SYNCAPI_REQ, params=post_params)
        if (
            "errors" in resp
            or "body" not in resp
            or "home" not in resp["body"]
            or ("errors" in resp["body"] and "modules" not in resp["body"]["home"])
        ):
            LOG.error("Errors in response: %s", resp)
            raise NoDevice("No device found, errors in response")

        self.raw_data = resp["body"]["home"]
        self.rooms: Dict = {}
        self.thermostats: Dict = {}
        self.valves: Dict = {}
        self.relays: Dict = {}
        self.modules: Dict = {}

        for room in self.raw_data.get("rooms", []):
            self.rooms[room["id"]] = room

        for module in self.raw_data.get("modules", []):
            self.modules[module["id"]] = module

        for module in self.raw_data.get("modules", []):
            if module["type"] == "NATherm1":
                thermostat_id = module["id"]
                if thermostat_id not in self.thermostats:
                    self.thermostats[thermostat_id] = {}

                self.thermostats[thermostat_id] = module

            elif module["type"] == "NRV":
                valve_id = module["id"]
                if valve_id not in self.valves:
                    self.valves[valve_id] = {}

                self.valves[valve_id] = module

            elif module["type"] == "NAPlug":
                relay_id = module["id"]
                if relay_id not in self.relays:
                    self.relays[relay_id] = {}

                self.relays[relay_id] = module

    def get_room(self, room_id: str) -> Dict:
        for key, value in self.rooms.items():
            if value["id"] == room_id:
                return self.rooms[key]

        raise InvalidRoomError("No room with ID %s" % room_id)

    def get_thermostat(self, room_id: str) -> Dict:
        """Return thermostat data for a given room id."""
        for key, value in self.thermostats.items():
            if value["id"] == room_id:
                return self.thermostats[key]

        raise InvalidRoomError("No room with ID %s" % room_id)

    def get_relay(self, room_id: str) -> Dict:
        for key, value in self.relays.items():
            if value["id"] == room_id:
                return self.relays[key]

        raise InvalidRoomError("No room with ID %s" % room_id)

    def get_valve(self, room_id: str) -> Dict:
        for key, value in self.valves.items():
            if value["id"] == room_id:
                return self.valves[key]

        raise InvalidRoomError("No room with ID %s" % room_id)

    def set_point(self, room_id: str) -> Optional[float]:
        """Return the setpoint of a given room."""
        room = self.get_room(room_id)
        if  "therm_setpoint_temperature" in room:
                return room.get("therm_setpoint_temperature")
        else:
                return room.get("cooling_setpoint_temperature")
	#return self.get_room(room_id).get("therm_setpoint_temperature")

    def set_point_mode(self, room_id: str) -> Optional[str]:
        """Return the setpointmode of a given room."""
        room = self.get_room(room_id)
        if "therm_setpoint_mode" in room:
                return room.get("therm_setpoint_mode")
        else:
                return room.get("cooling_setpoint_mode")
#        return self.get_room(room_id).get("therm_setpoint_mode")

    def measured_temperature(self, room_id: str) -> Optional[float]:
        """Return the measured temperature of a given room."""
        return self.get_room(room_id).get("therm_measured_temperature")

    def boiler_status(self, module_id: str) -> Optional[bool]:
        return self.get_thermostat(module_id).get("boiler_status")

    def set_thermmode(
        self, mode: str, end_time: int = None, schedule_id: str = None
    ) -> Optional[str]:
        post_params = {
            "app_type" : _APP_NETATMO_API_TYPE,
            "app_version" : _APP_NETATMO_API_VERSION,
            "home_id": self.home_id,
            "mode": mode,
        }
        if end_time is not None and mode in ("hg", "away"):
            post_params["endtime"] = str(end_time)

        if schedule_id is not None and mode == "schedule":
            post_params["schedule_id"] = schedule_id

        return self.auth.post_request(url=_SETTHERMMODE_SYNCAPI_REQ, params=post_params)


    def set_coolmode(
        self, mode: str, end_time: int = None, schedule_id: str = None
    ) -> Optional[str]:
        post_params = {
          "json" : {
            "app_type" : _APP_NETATMO_API_TYPE,
            "app_version" : _APP_NETATMO_API_VERSION,
            "home": {
                     "cooling_mode": mode,
                     "timezone": "Europe/Rome",
                     "temperature_control_mode": "cooling",
                     "id": self.home_id
            }
          }
        }
        #if end_time is not None and mode in ("hg", "away"):
        #    post_params["endtime"] = str(end_time)

        #if schedule_id is not None and mode == "schedule":
        #    post_params["schedule_id"] = schedule_id

        return self.auth.post_request(url=_SETHOMEDATA_SYNCAPI_REQ, params=post_params)



    def set_room_thermpoint(
        self, room_id: str, mode: str, temp: float = None, end_time: int = None
    ) -> Optional[str]:
        post_params = {
            "app_type" : _APP_NETATMO_API_TYPE,
            "app_version" : _APP_NETATMO_API_VERSION,
            "home_id": self.home_id,
            "room_id": room_id,
            "mode": mode,
        }
        # Temp and endtime should only be send when mode=='manual', but netatmo api can
        # handle that even when mode == 'home' and these settings don't make sense
        if temp is not None:
            post_params["temp"] = str(temp)

        if end_time is not None:
            post_params["endtime"] = str(end_time)

        return self.auth.post_request(url=_SETROOMTHERMPOINT_SYNCAPI_REQ, params=post_params)

    def set_module_state(
         self, module_id: str, state, state_value
     ) -> Optional[str]:

         post_params = {
            "json": {
               "app_type":_APP_NETATMO_API_TYPE,
               "app_version":_APP_NETATMO_API_VERSION,
               "home": {
                     "timezone":"Europe/Rome",
                     "id": self.home_id,
                     "modules": [{"id":module_id, state : (state_value in ('ON','1')), "bridge" : self.modules[module_id]['bridge']}]
               }
            }
         }
         return self.auth.post_request(url=_SETSTATE_SYNCAPI_REQ, params=post_params)

    def set_room_state(
         self, room_id: str, payload: str
     ) -> Optional[str]:

         payload_json = json.loads(payload)
         payload_json["id"]=room_id
         post_params = {
            "json": {
               "app_type":_APP_NETATMO_API_TYPE,
               "app_version":_APP_NETATMO_API_VERSION,
               "home": {
                     "timezone":"Europe/Rome",
                     "id": self.home_id,
                     "rooms": [payload_json]
               }
            }
         }
         return self.auth.post_request(url=_SETSTATE_SYNCAPI_REQ, params=post_params)
