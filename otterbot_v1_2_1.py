# Otterbot v1.2.1
# Version History:
# v1.2.1 (2025-05-03): Fixed rant detection by accessing livestream.chat.recent_rants instead of livestream.rants.
#                      Improved rant ID generation to include created_on timestamp for uniqueness.
#                      Added detailed logging for rant processing to aid debugging.
# v1.2.0 (2025-04-29): Fixed Queue.Empty error in process_event_queue by using queue.Empty.
#                      Simplified event handling by removing event_queue and process_event_queue thread.
#                      Ensured sources are disabled after timer by validating WebSocket connection.
#                      Added WebSocket reconnection logic in toggle_source for robustness.
#                      Improved logging for timer and disable actions.
# v1.1.9 (2025-04-29): Fixed `watchers_data` typo in simulate_test_event for subscriber events.
#                      Improved toggle_source to use threading.Timer for reliable source disabling.
#                      Added event queuing to prevent overlapping source toggles.
#                      Added WebSocket reconnection logic in poll_rumble_api for robustness.
#                      Ensured subscriber events are processed consistently with polling.
# v1.0.0 (2025-04-28): Initial GUI release with scene configuration, start/stop polling, and real-time log display.
#                      Added Clear Log button in the Log tab.
#                      Added otter emoji (🦦) to the title bar.
#                      Added persistent state saving/loading to prevent re-triggering old events on startup.
#                      Fixed state file saving by using absolute path and improved error logging.
#                      Improved gifted sub detection to avoid duplicates.
# v1.1.0 (2025-04-29): Added saving of scene names to state file.
#                      Added Reset State button to clear event tracking.
#                      Added Test Mode button to simulate new events.
#                      Added status indicator for polling state.
#                      Added adjustable polling interval and scene switch duration.
#                      Added display of latest event details (follower, subscriber, gifted sub).
#                      Fixed global variable declaration issue in test_event method.
# v1.1.1 (2025-04-30): Fixed polling thread termination to be more responsive by breaking sleep into smaller intervals.
#                      Made thread joining non-blocking to prevent GUI freeze.
# v1.1.2 (2025-04-30): Fixed test event functionality to work without polling being active.
#                      Ensured WebSocket connection is available during test events.
#                      Added better logging for test event simulation.
# v1.1.3 (2025-04-30): Added support for detecting and handling new rants (monetary tips) during livestreams.
#                      Added scene switching for new rants and test mode simulation for rants.
#                      Added display of latest rant in the GUI.
# v1.1.4 (2025-04-29): Replaced scene switching with source visibility toggling for followers, subscribers, gifted subs, and rants.
#                      Updated GUI to configure source names instead of scenes.
#                      Used SetSceneItemEnabled for OBS WebSocket 5.x to toggle sources.
# v1.1.5 (2025-04-29): Fixed missing sceneItemId in SetSceneItemEnabled requests by adding get_scene_item_id helper.
#                      Ensured test mode and polling correctly toggle sources.
# v1.1.6 (2025-04-29): Fixed get_scene_item_id to correctly extract sceneItemId from responseData, resolving test button failure.
# v1.1.7 (2025-04-29): Fixed toggle_source to use sceneItemEnabled instead of enabled in SetSceneItemEnabled requests.
# v1.1.8 (2025-04-29): Improved WebSocket and thread management in test_event and wait_for_test_event to fix test button failure during polling.

import pycurl
import json
import time
import websocket
import uuid
import hashlib
import base64
from io import BytesIO
import logging
import random
import threading
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from queue import Queue
import os
import queue  # Added for queue.Empty

# Configure logging
logging.basicConfig(
    filename="rumble_obs.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Rumble API configuration
API_URL = ""

# OBS WebSocket configuration
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = ""
OBS_WS_URL = f"ws://{OBS_HOST}:{OBS_PORT}"

# Default source configurations
DEFAULT_SCENE_CONFIG = {
    "TARGET_SOURCE_FOLLOWER": "FollowerOverlay",
    "TARGET_SOURCE_SUBSCRIBER": "SubscriberOverlay",
    "TARGET_SOURCE_GIFTED_SUB": "GiftedSubOverlay",
    "TARGET_SOURCE_RANT": "RantOverlay",
    "DEFAULT_SCENE": "Big Screen"
}
DEFAULT_POLLING_INTERVAL = 10  # Default polling interval in seconds
DEFAULT_SCENE_SWITCH_DURATION = 10  # Default duration to display the source (in seconds)
SLEEP_INTERVAL = 0.5  # Small interval for breaking up sleep in polling loop
THREAD_TIMEOUT = 15  # Timeout for waiting for polling thread to terminate (seconds)

# State file for persisting last seen data (use absolute path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "otterbot_state.json")

# Load initial state from file (if it exists)
def load_state(scene_vars, polling_interval_var, scene_switch_duration_var):
    global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                last_follower = state.get("last_follower")
                last_subscriber = state.get("last_subscriber")
                last_seen_gifted_subs = set(state.get("last_seen_gifted_subs", []))
                last_seen_rants = set(state.get("last_seen_rants", []))
                # Load source/scene names
                for key in DEFAULT_SCENE_CONFIG:
                    scene_vars[key].set(state.get("scene_names", {}).get(key, DEFAULT_SCENE_CONFIG[key]))
                # Load polling interval and source display duration
                polling_interval_var.set(state.get("polling_interval", DEFAULT_POLLING_INTERVAL))
                scene_switch_duration_var.set(state.get("scene_switch_duration", DEFAULT_SCENE_SWITCH_DURATION))
                logging.info(f"Loaded state from {STATE_FILE}")
        else:
            last_follower = None
            last_subscriber = None
            last_seen_gifted_subs = set()
            last_seen_rants = set()
            # Set default source/scene names
            for key in DEFAULT_SCENE_CONFIG:
                scene_vars[key].set(DEFAULT_SCENE_CONFIG[key])
            polling_interval_var.set(DEFAULT_POLLING_INTERVAL)
            scene_switch_duration_var.set(DEFAULT_SCENE_SWITCH_DURATION)
            logging.info(f"No state file found at {STATE_FILE}, starting with empty state")
    except Exception as e:
        logging.error(f"Failed to load state from {STATE_FILE}: {e}")
        last_follower = None
        last_subscriber = None
        last_seen_gifted_subs = set()
        last_seen_rants = set()
        for key in DEFAULT_SCENE_CONFIG:
            scene_vars[key].set(DEFAULT_SCENE_CONFIG[key])
        polling_interval_var.set(DEFAULT_POLLING_INTERVAL)
        scene_switch_duration_var.set(DEFAULT_SCENE_SWITCH_DURATION)

# Save state to file
def save_state(scene_vars, polling_interval_var, scene_switch_duration_var):
    try:
        state = {
            "last_follower": last_follower,
            "last_subscriber": last_subscriber,
            "last_seen_gifted_subs": list(last_seen_gifted_subs),
            "last_seen_rants": list(last_seen_rants),
            "scene_names": {key: scene_vars[key].get() for key in DEFAULT_SCENE_CONFIG},
            "polling_interval": polling_interval_var.get(),
            "scene_switch_duration": scene_switch_duration_var.get()
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        logging.info(f"Saved state to {STATE_FILE}")
    except Exception as e:
        logging.error(f"Failed to save state to {STATE_FILE}: {e}")

# Reset state
def reset_state(scene_vars, polling_interval_var, scene_switch_duration_var):
    global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants
    try:
        last_follower = None
        last_subscriber = None
        last_seen_gifted_subs = set()
        last_seen_rants = set()
        # Reset source/scene names to defaults
        for key in DEFAULT_SCENE_CONFIG:
            scene_vars[key].set(DEFAULT_SCENE_CONFIG[key])
        polling_interval_var.set(DEFAULT_POLLING_INTERVAL)
        scene_switch_duration_var.set(DEFAULT_SCENE_SWITCH_DURATION)
        save_state(scene_vars, polling_interval_var, scene_switch_duration_var)
        logging.info("State reset successfully")
    except Exception as e:
        logging.error(f"Failed to reset state: {e}")

# Load the initial state when the script starts
last_follower = None
last_subscriber = None
last_seen_gifted_subs = set()
last_seen_rants = set()

# Global variables for polling control
polling_thread = None
stop_polling_flag = threading.Event()
log_queue = Queue()  # Queue to pass log messages to the GUI
event_lock = threading.Lock()  # Lock to prevent overlapping source toggles
active_timers = {}  # Track active timers for each source

def log_to_queue_handler(record):
    """Custom logging handler to send log messages to the GUI via a queue."""
    msg = logging.getLogger().handlers[0].format(record)
    log_queue.put(msg)

def connect_to_obs():
    """Connect to OBS WebSocket server with retry logic."""
    try:
        ws = websocket.WebSocket()
        ws.connect(OBS_WS_URL, timeout=5)
        logging.info("WebSocket connection established")

        for attempt in range(5):
            try:
                if ws.connected:
                    response_raw = ws.recv()
                    logging.info(f"Raw Hello response: {repr(response_raw)}")
                    response = json.loads(response_raw)
                    logging.info(f"Parsed Hello response: {response}")
                    break
                else:
                    logging.warning(f"WebSocket not connected on Hello attempt {attempt + 1}")
                    if attempt == 4:
                        logging.error("WebSocket disconnected during Hello response")
                        return None
                    time.sleep(1)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON decode error on Hello attempt {attempt + 1}: {e}")
                if attempt == 4:
                    logging.error("Failed to parse Hello response after retries")
                    return None
                time.sleep(1)
            except websocket.WebSocketTimeoutException:
                logging.error("Timeout waiting for Hello response")
                return None
            except websocket.WebSocketConnectionClosedException:
                logging.error("WebSocket connection closed during Hello response")
                return None

        if response["op"] != 0:
            logging.error(f"Expected Hello (op 0), got: {response}")
            return None

        if "authentication" in response["d"]:
            if not OBS_PASSWORD:
                logging.error("OBS requires authentication, but OBS_PASSWORD is empty")
                return None
            salt = response["d"]["authentication"]["salt"]
            challenge = response["d"]["authentication"]["challenge"]
            secret = base64.b64encode(hashlib.sha256((OBS_PASSWORD + salt).encode()).digest()).decode()
            auth = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
            logging.info("Sending authentication message")
            ws.send(json.dumps({
                "op": 1,
                "d": {
                    "rpcVersion": 1,
                    "authentication": auth,
                    "eventSubscriptions": 0
                }
            }))
            time.sleep(2)
            for attempt in range(5):
                try:
                    if ws.connected:
                        auth_response_raw = ws.recv()
                        logging.info(f"Raw authentication response: {repr(auth_response_raw)}")
                        auth_response = json.loads(auth_response_raw)
                        logging.info(f"Parsed authentication response: {auth_response}")
                        break
                    else:
                        logging.warning(f"WebSocket not connected on auth attempt {attempt + 1}")
                        if attempt == 4:
                            logging.error("WebSocket disconnected during authentication response")
                            return None
                        time.sleep(1)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error on auth attempt {attempt + 1}: {e}")
                    if attempt == 4:
                        logging.error("Failed to parse authentication response after retries")
                        return None
                    time.sleep(1)
                except websocket.WebSocketTimeoutException:
                    logging.error("Timeout waiting for authentication response")
                    return None
                except websocket.WebSocketConnectionClosedException:
                    logging.error("WebSocket connection closed during authentication response")
                    return None
            if auth_response["op"] != 2 or not auth_response["d"].get("authenticated", False):
                logging.error(f"Authentication failed: {auth_response}")
                return None
        else:
            logging.info("No authentication required, sending Identify")
            ws.send(json.dumps({
                "op": 1,
                "d": {
                    "rpcVersion": 1,
                    "eventSubscriptions": 0
                }
            }))
            time.sleep(2)
            for attempt in range(5):
                try:
                    if ws.connected:
                        identify_response_raw = ws.recv()
                        logging.info(f"Raw Identify response: {repr(identify_response_raw)}")
                        identify_response = json.loads(identify_response_raw)
                        logging.info(f"Parsed Identify response: {identify_response}")
                        break
                    else:
                        logging.warning(f"WebSocket not connected on identify attempt {attempt + 1}")
                        if attempt == 4:
                            logging.error("WebSocket disconnected during Identify response")
                            return None
                        time.sleep(1)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error on identify attempt {attempt + 1}: {e}")
                    if attempt == 4:
                        logging.error("Failed to parse Identify response after retries")
                        return None
                    time.sleep(1)
                except websocket.WebSocketTimeoutException:
                    logging.error("Timeout waiting for Identify response")
                    return None
                except websocket.WebSocketConnectionClosedException:
                    logging.error("WebSocket connection closed during Identify response")
                    return None
            if identify_response["op"] != 2:
                logging.error(f"Identify failed: {identify_response}")
                return None

        logging.info("Successfully connected to OBS WebSocket")
        return ws
    except Exception as e:
        logging.error(f"Failed to connect to OBS: {e}")
        return None

def get_rumble_data(test_mode=False, test_event_type=None):
    """Fetch data from Rumble API using pycurl or simulate data in test mode."""
    if test_mode:
        fake_username = f"TestUser_{random.randint(1000, 9999)}"
        logging.info(f"Test mode: Simulating new {test_event_type} event for {fake_username}")
        if test_event_type == "follower":
            return {
                "followers": {
                    "num_followers": 1,
                    "latest_follower": {"username": fake_username, "followed_on": "2025-04-29T12:00:00-04:00"}
                },
                "subscribers": {"num_subscribers": 0, "latest_subscriber": None},
                "gifted_subs": {"num_gifted_subs": 0, "latest_gifted_sub": None, "recent_gifted_subs": []},
                "livestreams": []
            }
        elif test_event_type == "subscriber":
            return {
                "followers": {"num_followers": 0, "latest_follower": None},
                "subscribers": {
                    "num_subscribers": 1,
                    "latest_subscriber": {"username": fake_username, "amount_dollars": 5, "subscribed_on": "2025-04-29T12:00:00-04:00"}
                },
                "gifted_subs": {"num_gifted_subs": 0, "latest_gifted_sub": None, "recent_gifted_subs": []},
                "livestreams": []
            }
        elif test_event_type == "gifted_sub":
            return {
                "followers": {"num_followers": 0, "latest_follower": None},
                "subscribers": {"num_subscribers": 0, "latest_subscriber": None},
                "gifted_subs": {
                    "num_gifted_subs": 1,
                    "latest_gifted_sub": {"purchased_by": fake_username, "video_id": 12345},
                    "recent_gifted_subs": [{"purchased_by": fake_username, "video_id": 12345, "total_gifts": 1}]
                },
                "livestreams": []
            }
        elif test_event_type == "rant":
            return {
                "followers": {"num_followers": 0, "latest_follower": None},
                "subscribers": {"num_subscribers": 0, "latest_subscriber": None},
                "gifted_subs": {"num_gifted_subs": 0, "latest_gifted_sub": None, "recent_gifted_subs": []},
                "livestreams": [
                    {
                        "id": "TEST123",
                        "title": "Test Stream",
                        "created_on": "2025-04-29T12:00:00-04:00",
                        "is_live": True,
                        "chat": {
                            "recent_rants": [
                                {
                                    "username": fake_username,
                                    "amount_dollars": 5,
                                    "text": "Great stream!",
                                    "created_on": "2025-04-29T12:00:00-04:00"
                                }
                            ]
                        }
                    }
                ]
            }
    
    buffer = BytesIO()
    c = pycurl.Curl()
    for attempt in range(3):
        try:
            c.setopt(c.URL, API_URL)
            c.setopt(c.WRITEDATA, buffer)
            c.setopt(c.FOLLOWLOCATION, True)
            c.setopt(c.TIMEOUT, 10)
            c.perform()
            status_code = c.getinfo(c.RESPONSE_CODE)
            logging.info(f"API request attempt {attempt + 1} status code: {status_code}")
            if status_code == 200:
                body = buffer.getvalue().decode('utf-8')
                logging.info(f"Raw API response: {repr(body)}")
                try:
                    data = json.loads(body)
                    logging.info(f"Full parsed API response: {json.dumps(data)}")
                    return data
                except json.JSONDecodeError as e:
                    logging.error(f"Failed to parse API response as JSON: {e}")
                    logging.error(f"Full API response: {repr(body)}")
                    return None
            else:
                logging.error(f"API request failed with status code: {status_code}")
                if attempt == 2:
                    return None
                time.sleep(2)
        except pycurl.error as e:
            logging.error(f"Error fetching Rumble API data on attempt {attempt + 1}: {e}")
            if attempt == 2:
                return None
            time.sleep(2)
        finally:
            c.close()
            buffer.close()
    return None

def get_scene_item_id(ws, scene_name, source_name):
    """Retrieve the sceneItemId for a source in a scene."""
    if ws is None or not ws.connected:
        logging.error("Cannot get sceneItemId: WebSocket connection is not established")
        return None
    try:
        request_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestType": "GetSceneItemId",
                "requestId": request_id,
                "requestData": {
                    "sceneName": scene_name,
                    "sourceName": source_name
                }
            }
        }))
        for attempt in range(5):
            try:
                if ws.connected:
                    response_raw = ws.recv()
                    logging.info(f"Raw GetSceneItemId response: {repr(response_raw)}")
                    response = json.loads(response_raw)
                    logging.info(f"Parsed GetSceneItemId response: {response}")
                    break
                else:
                    logging.warning(f"WebSocket not connected on GetSceneItemId attempt {attempt + 1}")
                    if attempt == 4:
                        logging.error("WebSocket disconnected during GetSceneItemId response")
                        return None
                    time.sleep(1)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON decode error on GetSceneItemId attempt {attempt + 1}: {e}")
                if attempt == 4:
                    logging.error("Failed to parse GetSceneItemId response after retries")
                    return None
                time.sleep(1)
            except websocket.WebSocketTimeoutException:
                logging.error("Timeout waiting for GetSceneItemId response")
                return None
            except websocket.WebSocketConnectionClosedException:
                logging.error("WebSocket connection closed during GetSceneItemId response")
                return None
        if response.get("d", {}).get("requestStatus", {}).get("result", False):
            scene_item_id = response["d"].get("responseData", {}).get("sceneItemId")
            if scene_item_id is not None:
                logging.info(f"Retrieved sceneItemId {scene_item_id} for source {source_name} in scene {scene_name}")
                return scene_item_id
            else:
                logging.error(f"No sceneItemId found in response: {response}")
                return None
        else:
            logging.error(f"Failed to get sceneItemId: {response}")
            return None
    except Exception as e:
        logging.error(f"Error getting sceneItemId for source {source_name}: {e}")
        return None

def toggle_source(ws, scene_name, source_name, duration):
    """Toggle a source's visibility in the specified scene for the given duration using a timer."""
    try:
        with event_lock:
            # Ensure WebSocket is connected
            if ws is None or not ws.connected:
                logging.warning(f"WebSocket disconnected for {source_name}, attempting to reconnect")
                if ws:
                    ws.close()
                ws = connect_to_obs()
                if not ws:
                    logging.error(f"Cannot toggle source {source_name}: Failed to reconnect to OBS")
                    return None

            # Cancel any existing timer for this source
            if source_name in active_timers:
                active_timers[source_name].cancel()
                logging.info(f"Cancelled existing timer for {source_name}")

            # Get sceneItemId
            scene_item_id = get_scene_item_id(ws, scene_name, source_name)
            if scene_item_id is None:
                logging.error(f"Cannot toggle source {source_name}: Failed to retrieve sceneItemId")
                return ws

            # Show the source
            request_id = str(uuid.uuid4())
            ws.send(json.dumps({
                "op": 6,
                "d": {
                    "requestType": "SetSceneItemEnabled",
                    "requestId": request_id,
                    "requestData": {
                        "sceneName": scene_name,
                        "sceneItemId": scene_item_id,
                        "sceneItemEnabled": True
                    }
                }
            }))
            for attempt in range(5):
                try:
                    if ws.connected:
                        response_raw = ws.recv()
                        logging.info(f"Raw source enable response: {repr(response_raw)}")
                        response = json.loads(response_raw)
                        logging.info(f"Parsed source enable response: {response}")
                        break
                    else:
                        logging.warning(f"WebSocket not connected on source enable attempt {attempt + 1}")
                        if attempt == 4:
                            logging.error("WebSocket disconnected during source enable response")
                            return ws
                        time.sleep(1)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error on source enable attempt {attempt + 1}: {e}")
                    if attempt == 4:
                        logging.error("Failed to parse source enable response after retries")
                        return ws
                    time.sleep(1)
                except websocket.WebSocketTimeoutException:
                    logging.error("Timeout waiting for source enable response")
                    return ws
                except websocket.WebSocketConnectionClosedException:
                    logging.error("WebSocket connection closed during source enable response")
                    return ws
            if response.get("d", {}).get("requestStatus", {}).get("result", False):
                logging.info(f"Enabled source: {source_name} in scene: {scene_name}")
            else:
                logging.error(f"Failed to enable source: {response}")
                return ws

            # Schedule source disable
            def disable_source():
                with event_lock:
                    try:
                        # Ensure WebSocket is connected
                        nonlocal ws
                        if not ws or not ws.connected:
                            logging.warning(f"WebSocket disconnected for disabling {source_name}, attempting to reconnect")
                            if ws:
                                ws.close()
                            ws = connect_to_obs()
                            if not ws:
                                logging.error(f"Cannot disable source {source_name}: Failed to reconnect to OBS")
                                return

                        # Re-fetch sceneItemId in case scene changed
                        scene_item_id = get_scene_item_id(ws, scene_name, source_name)
                        if scene_item_id is None:
                            logging.error(f"Cannot disable source {source_name}: Failed to retrieve sceneItemId")
                            return

                        request_id = str(uuid.uuid4())
                        ws.send(json.dumps({
                            "op": 6,
                            "d": {
                                "requestType": "SetSceneItemEnabled",
                                "requestId": request_id,
                                "requestData": {
                                    "sceneName": scene_name,
                                    "sceneItemId": scene_item_id,
                                    "sceneItemEnabled": False
                                }
                            }
                        }))
                        for attempt in range(5):
                            try:
                                if ws.connected:
                                    response_raw = ws.recv()
                                    logging.info(f"Raw source disable response: {repr(response_raw)}")
                                    response = json.loads(response_raw)
                                    logging.info(f"Parsed source disable response: {response}")
                                    break
                                else:
                                    logging.warning(f"WebSocket not connected on source disable attempt {attempt + 1}")
                                    if attempt == 4:
                                        logging.error("WebSocket disconnected during source disable response")
                                        return
                                    time.sleep(1)
                            except json.JSONDecodeError as e:
                                logging.warning(f"JSON decode error on source disable attempt {attempt + 1}: {e}")
                                if attempt == 4:
                                    logging.error("Failed to parse source disable response after retries")
                                    return
                                time.sleep(1)
                            except websocket.WebSocketTimeoutException:
                                logging.error("Timeout waiting for source disable response")
                                return
                            except websocket.WebSocketConnectionClosedException:
                                logging.error("WebSocket connection closed during source disable response")
                                return
                        if response.get("d", {}).get("requestStatus", {}).get("result", False):
                            logging.info(f"Disabled source: {source_name} in scene: {scene_name}")
                        else:
                            logging.error(f"Failed to disable source: {response}")
                    except Exception as e:
                        logging.error(f"Error disabling source {source_name}: {e}")
                    finally:
                        if source_name in active_timers:
                            del active_timers[source_name]
                            logging.info(f"Cleared timer for {source_name}")

            timer = threading.Timer(duration, disable_source)
            timer.start()
            active_timers[source_name] = timer
            logging.info(f"Scheduled {duration}s timer to disable source {source_name}")
            return ws
    except Exception as e:
        logging.error(f"Error toggling source {source_name}: {e}")
        return ws

def poll_rumble_api(ws, scene_vars, polling_interval_var, scene_switch_duration_var, event_vars):
    """Main polling loop for Rumble API, runs in a separate thread."""
    global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants
    try:
        while not stop_polling_flag.is_set():
            # Ensure WebSocket is connected
            if not ws or not ws.connected:
                logging.warning("WebSocket disconnected, attempting to reconnect")
                if ws:
                    ws.close()
                ws = connect_to_obs()
                if not ws:
                    logging.error("Failed to reconnect to OBS, stopping polling")
                    stop_polling_flag.set()
                    break

            # Fetch Rumble API data
            data = get_rumble_data()
            if data is None:
                logging.warning("Failed to fetch Rumble API data, skipping this cycle")
                elapsed = 0
                polling_interval = polling_interval_var.get()
                while elapsed < polling_interval and not stop_polling_flag.is_set():
                    time.sleep(min(SLEEP_INTERVAL, polling_interval - elapsed))
                    elapsed += SLEEP_INTERVAL
                continue

            # Get source names and settings from GUI
            TARGET_SOURCE_FOLLOWER = scene_vars["TARGET_SOURCE_FOLLOWER"].get()
            TARGET_SOURCE_SUBSCRIBER = scene_vars["TARGET_SOURCE_SUBSCRIBER"].get()
            TARGET_SOURCE_GIFTED_SUB = scene_vars["TARGET_SOURCE_GIFTED_SUB"].get()
            TARGET_SOURCE_RANT = scene_vars["TARGET_SOURCE_RANT"].get()
            DEFAULT_SCENE = scene_vars["DEFAULT_SCENE"].get()
            polling_interval = polling_interval_var.get()
            scene_switch_duration = scene_switch_duration_var.get()

            # Extract the latest follower
            followers_data = data.get("followers", {})
            latest_follower_data = followers_data.get("latest_follower") or {}
            latest_follower = latest_follower_data.get("username")
            follower_timestamp = latest_follower_data.get("followed_on", "N/A")
            logging.info(f"Latest follower: {latest_follower} (followed on: {follower_timestamp})")

            # Check for new follower
            if latest_follower and latest_follower != last_follower:
                logging.info(f"New follower detected: {latest_follower}")
                last_follower = latest_follower
                event_vars["latest_follower"].set(f"Latest Follower: {latest_follower}")
                ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_FOLLOWER, scene_switch_duration)

            # Extract the latest subscriber
            subscribers_data = data.get("subscribers", {})
            latest_subscriber_data = subscribers_data.get("latest_subscriber") or {}
            latest_subscriber = latest_subscriber_data.get("username")
            subscriber_timestamp = latest_subscriber_data.get("subscribed_on", "N/A")
            subscriber_amount = latest_subscriber_data.get("amount_dollars", "N/A")
            logging.info(f"Latest subscriber: {latest_subscriber} (subscribed on: {subscriber_timestamp}, amount: ${subscriber_amount})")

            # Check for new subscriber
            if latest_subscriber and latest_subscriber != last_subscriber:
                logging.info(f"New subscriber detected: {latest_subscriber}")
                last_subscriber = latest_subscriber
                event_vars["latest_subscriber"].set(f"Latest Subscriber: {latest_subscriber}")
                ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_SUBSCRIBER, scene_switch_duration)

            # Extract and check for new gifted subscriptions
            gifted_subs_data = data.get("gifted_subs", {})
            recent_gifted_subs = gifted_subs_data.get("recent_gifted_subs", [])
            
            # Track seen gift IDs in this cycle to avoid duplicates
            seen_gift_ids_in_cycle = set()
            
            for gifted_sub in recent_gifted_subs:
                if stop_polling_flag.is_set():
                    break
                purchaser = gifted_sub.get("purchased_by")
                video_id = gifted_sub.get("video_id")
                gift_id = f"{purchaser}_{video_id}"
                if gift_id not in last_seen_gifted_subs and gift_id not in seen_gift_ids_in_cycle:
                    logging.info(f"New gifted sub detected: Purchased by {purchaser} (video ID: {video_id})")
                    last_seen_gifted_subs.add(gift_id)
                    seen_gift_ids_in_cycle.add(gift_id)
                    event_vars["latest_gifted_sub"].set(f"Latest Gifted Sub: {purchaser}")
                    ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_GIFTED_SUB, scene_switch_duration)

            # Log the latest gifted subscription for reference
            latest_gifted_sub_data = gifted_subs_data.get("latest_gifted_sub") or {}
            latest_gifted_sub_purchaser = latest_gifted_sub_data.get("purchased_by")
            gifted_sub_video_id = latest_gifted_sub_data.get("video_id", "N/A")
            logging.info(f"Latest gifted sub: Purchased by {latest_gifted_sub_purchaser} (video ID: {gifted_sub_video_id})")

            # Handle livestream events (e.g., rants/donations, chat messages)
            livestreams = data.get("livestreams", [])
            if livestreams:
                for livestream in livestreams:
                    viewers = livestream.get("watching_now", 0)
                    logging.info(f"Current viewers: {viewers}")

                    # Check for new rants
                    chat_data = livestream.get("chat", {})
                    rants = chat_data.get("recent_rants", [])
                    logging.info(f"Found {len(rants)} rants in livestream {livestream.get('id', 'unknown')}")
                    seen_rant_ids_in_cycle = set()
                    for rant in rants:
                        if stop_polling_flag.is_set():
                            break
                        username = rant.get("username")
                        amount_dollars = rant.get("amount_dollars")
                        message = rant.get("text")
                        created_on = rant.get("created_on", "")
                        if not all([username, amount_dollars is not None, message, created_on]):
                            logging.warning(f"Skipping invalid rant: {rant}")
                            continue
                        rant_id = f"{username}_{amount_dollars}_{message}_{created_on}"
                        logging.info(f"Processing rant: {username} tipped ${amount_dollars} - {message} (created: {created_on})")
                        if rant_id not in last_seen_rants and rant_id not in seen_rant_ids_in_cycle:
                            logging.info(f"New rant detected: {username} tipped ${amount_dollars} - {message}")
                            last_seen_rants.add(rant_id)
                            seen_rant_ids_in_cycle.add(rant_id)
                            event_vars["latest_rant"].set(f"Latest Rant: {username} tipped ${amount_dollars}")
                            ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_RANT, scene_switch_duration)

                    # Log chat messages
                    chat_messages = chat_data.get("recent_messages", [])
                    for msg in chat_messages:
                        username = msg.get("username")
                        message = msg.get("message")
                        logging.info(f"New chat message from {username}: {message}")

            # Save state after each polling cycle
            save_state(scene_vars, polling_interval_var, scene_switch_duration_var)

            # Wait before polling again, in small increments
            elapsed = 0
            while elapsed < polling_interval and not stop_polling_flag.is_set():
                time.sleep(min(SLEEP_INTERVAL, polling_interval - elapsed))
                elapsed += SLEEP_INTERVAL

    except Exception as e:
        logging.error(f"Unexpected error in polling loop: {e}")
    finally:
        if ws:
            ws.close()
            logging.info("Disconnected from OBS")
        # Save state when polling stops
        save_state(scene_vars, polling_interval_var, scene_switch_duration_var)

class OtterbotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🦦 Otterbot v1.2.1")
        self.root.geometry("600x500")  # Increased height to accommodate new elements

        # Add a custom logging handler to send logs to the GUI
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        handler.emit = log_to_queue_handler
        logging.getLogger().addHandler(handler)

        # Variables to store source/scene names
        self.scene_vars = {
            "TARGET_SOURCE_FOLLOWER": tk.StringVar(),
            "TARGET_SOURCE_SUBSCRIBER": tk.StringVar(),
            "TARGET_SOURCE_GIFTED_SUB": tk.StringVar(),
            "TARGET_SOURCE_RANT": tk.StringVar(),
            "DEFAULT_SCENE": tk.StringVar()
        }

        # Variables for adjustable settings
        self.polling_interval_var = tk.DoubleVar()
        self.scene_switch_duration_var = tk.DoubleVar()

        # Variables to display latest event details
        self.event_vars = {
            "latest_follower": tk.StringVar(value="Latest Follower: None"),
            "latest_subscriber": tk.StringVar(value="Latest Subscriber: None"),
            "latest_gifted_sub": tk.StringVar(value="Latest Gifted Sub: None"),
            "latest_rant": tk.StringVar(value="Latest Rant: None")
        }

        # Load state (sets scene_vars, polling_interval_var, and scene_switch_duration_var)
        load_state(self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var)

        # Create a notebook (tabbed interface)
        self.notebook = ttkb.Notebook(self.root)
        self.notebook.pack(pady=10, fill="both", expand=True)

        # Tab 1: Settings
        self.settings_tab = ttkb.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text="Settings")

        # Tab 2: Log
        self.log_tab = ttkb.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Log")

        # Setup Settings tab
        self.setup_settings_tab()

        # Setup Log tab
        self.setup_log_tab()

        # State tracking
        self.is_polling = False
        self.ws = None

        # Status label
        self.status_var = tk.StringVar(value="Polling: Stopped")
        self.status_label = ttkb.Label(self.settings_tab, textvariable=self.status_var, bootstyle=INFO)
        self.status_label.pack(pady=5)

        # Ensure state is saved when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Start the log update loop
        self.update_log()

    def setup_settings_tab(self):
        """Setup the Settings tab with source name entries, adjustable settings, and buttons."""
        # Source name entries
        settings_frame = ttkb.LabelFrame(self.settings_tab, text="Source Configuration", padding=10)
        settings_frame.pack(pady=5, padx=10, fill="x")

        # Follower Source
        ttkb.Label(settings_frame, text="Follower Source:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SOURCE_FOLLOWER"]).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Subscriber Source
        ttkb.Label(settings_frame, text="Subscriber Source:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SOURCE_SUBSCRIBER"]).grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Gifted Sub Source
        ttkb.Label(settings_frame, text="Gifted Sub Source:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SOURCE_GIFTED_SUB"]).grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Rant Source
        ttkb.Label(settings_frame, text="Rant Source:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SOURCE_RANT"]).grid(row=3, column=1, padx=5, pady=5, sticky="ew")

        # Default Scene
        ttkb.Label(settings_frame, text="Default Scene:").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["DEFAULT_SCENE"]).grid(row=4, column=1, padx=5, pady=5, sticky="ew")

        # Make columns expand properly
        settings_frame.columnconfigure(1, weight=1)

        # Adjustable settings
        timing_frame = ttkb.LabelFrame(self.settings_tab, text="Timing Settings", padding=10)
        timing_frame.pack(pady=5, padx=10, fill="x")

        # Polling Interval
        ttkb.Label(timing_frame, text="Polling Interval (seconds):").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(timing_frame, textvariable=self.polling_interval_var, width=10).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        # Source Display Duration
        ttkb.Label(timing_frame, text="Source Display Duration (seconds):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(timing_frame, textvariable=self.scene_switch_duration_var, width=10).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # Event display
        event_frame = ttkb.LabelFrame(self.settings_tab, text="Latest Events", padding=10)
        event_frame.pack(pady=5, padx=10, fill="x")

        ttkb.Label(event_frame, textvariable=self.event_vars["latest_follower"]).pack(anchor="w")
        ttkb.Label(event_frame, textvariable=self.event_vars["latest_subscriber"]).pack(anchor="w")
        ttkb.Label(event_frame, textvariable=self.event_vars["latest_gifted_sub"]).pack(anchor="w")
        ttkb.Label(event_frame, textvariable=self.event_vars["latest_rant"]).pack(anchor="w")

        # Button frame
        button_frame = ttkb.Frame(self.settings_tab)
        button_frame.pack(pady=10)

        # Start/Stop button
        self.start_stop_button = ttkb.Button(button_frame, text="START", command=self.toggle_polling, bootstyle=SUCCESS)
        self.start_stop_button.pack(side="left", padx=5)

        # Reset State button
        ttkb.Button(button_frame, text="Reset State", command=self.reset_state, bootstyle=WARNING).pack(side="left", padx=5)

        # Test Mode button with dropdown
        test_frame = ttkb.Frame(button_frame)
        test_frame.pack(side="left", padx=5)
        self.test_event_type = tk.StringVar(value="follower")
        ttkb.OptionMenu(test_frame, self.test_event_type, "follower", "follower", "subscriber", "gifted_sub", "rant").pack(side="left")
        ttkb.Button(test_frame, text="Test Event", command=self.test_event, bootstyle=INFO).pack(side="left")

    def setup_log_tab(self):
        """Setup the Log tab with a scrolling text box and a Clear Log button."""
        # Frame for log text and buttons
        log_frame = ttkb.Frame(self.log_tab)
        log_frame.pack(pady=10, padx=10, fill="both", expand=True)

        # ScrolledText widget
        self.log_text = ScrolledText(log_frame, height=15, autohide=True)
        self.log_text.pack(pady=(0, 10), fill="both", expand=True)
        self.log_text.text.configure(state="disabled")

        # Clear Log button
        clear_button = ttkb.Button(log_frame, text="Clear Log", command=self.clear_log, bootstyle=INFO)
        clear_button.pack()

    def clear_log(self):
        """Clear the log text box."""
        self.log_text.text.configure(state="normal")
        self.log_text.text.delete(1.0, tk.END)
        self.log_text.text.configure(state="disabled")

    def update_log(self):
        """Update the log text box with new log messages from the queue."""
        try:
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                self.log_text.text.configure(state="normal")  # Enable to insert text
                self.log_text.text.insert(tk.END, msg + "\n")
                self.log_text.text.see(tk.END)  # Auto-scroll to the bottom
                self.log_text.text.configure(state="disabled")  # Disable again
        except Exception as e:
            print(f"Error updating log: {e}")
        finally:
            self.root.after(100, self.update_log)  # Check again after 100ms

    def toggle_polling(self):
        """Start or stop polling the Rumble API."""
        global polling_thread, stop_polling_flag
        if not self.is_polling:
            # Start polling
            self.is_polling = True
            self.start_stop_button.configure(text="STOP", bootstyle=DANGER)
            self.status_var.set("Polling: Active")
            stop_polling_flag.clear()

            # Connect to OBS
            self.ws = connect_to_obs()
            if not self.ws:
                logging.error("Failed to connect to OBS, stopping polling")
                self.is_polling = False
                self.start_stop_button.configure(text="START", bootstyle=SUCCESS)
                self.status_var.set("Polling: Stopped")
                return

            # Start the polling thread
            polling_thread = threading.Thread(target=poll_rumble_api, args=(self.ws, self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var, self.event_vars))
            polling_thread.daemon = True  # Thread will terminate when the GUI closes
            polling_thread.start()
        else:
            # Stop polling
            self.is_polling = False
            self.start_stop_button.configure(text="START", bootstyle=SUCCESS)
            self.status_var.set("Polling: Stopped")
            stop_polling_flag.set()
            # Cancel all active timers
            with event_lock:
                for source_name, timer in active_timers.items():
                    timer.cancel()
                    logging.info(f"Cancelled timer for {source_name} due to polling stop")
                active_timers.clear()
            if self.ws:
                self.ws.close()
                self.ws = None
                logging.info("Disconnected from OBS")
            # Save state when stopping polling
            save_state(self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var)
            # Non-blocking thread join
            self.wait_for_thread_to_finish()

    def wait_for_thread_to_finish(self):
        """Check if the polling thread has finished, without blocking the GUI."""
        global polling_thread
        if polling_thread and polling_thread.is_alive():
            self.root.after(100, self.wait_for_thread_to_finish)  # Check again after 100ms
        else:
            polling_thread = None
            logging.info("Polling thread has finished")

    def reset_state(self):
        """Reset the state and update the GUI."""
        reset_state(self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var)
        self.event_vars["latest_follower"].set("Latest Follower: None")
        self.event_vars["latest_subscriber"].set("Latest Subscriber: None")
        self.event_vars["latest_gifted_sub"].set("Latest Gifted Sub: None")
        self.event_vars["latest_rant"].set("Latest Rant: None")

    def test_event(self):
        """Simulate a test event based on the selected event type."""
        global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants, polling_thread, stop_polling_flag
        event_type = self.test_event_type.get()
        
        # If polling is active, stop it and wait for the thread to finish
        was_polling = self.is_polling
        if was_polling:
            logging.info("Stopping polling for test event")
            self.is_polling = False
            stop_polling_flag.set()
            # Delay WebSocket closure until thread is confirmed stopped
            self.wait_for_test_event(event_type, was_polling, start_time=time.time())
        else:
            # If not polling, create a new WebSocket connection and simulate
            ws = connect_to_obs()
            if not ws:
                logging.error("Failed to connect to OBS for test event")
                return
            self.simulate_test_event(event_type, ws, was_polling)

    def wait_for_test_event(self, event_type, was_polling, start_time):
        """Wait for the polling thread to finish before simulating the test event, with timeout."""
        global polling_thread, stop_polling_flag
        elapsed = time.time() - start_time
        if polling_thread and polling_thread.is_alive() and elapsed < THREAD_TIMEOUT:
            self.root.after(100, lambda: self.wait_for_test_event(event_type, was_polling, start_time))
        else:
            if elapsed >= THREAD_TIMEOUT:
                logging.warning(f"Polling thread did not terminate within {THREAD_TIMEOUT} seconds")
            # Close existing WebSocket if it exists
            if self.ws:
                try:
                    self.ws.close()
                    logging.info("Disconnected from OBS after polling thread stopped")
                except Exception as e:
                    logging.error(f"Error closing WebSocket: {e}")
                self.ws = None
            # Reset polling thread
            polling_thread = None
            # Create new WebSocket connection for test event
            ws = connect_to_obs()
            if not ws:
                logging.error("Failed to connect to OBS for test event")
                if was_polling:
                    # Resume polling if it was active
                    self.resume_polling()
                return
            self.simulate_test_event(event_type, ws, was_polling)

    def resume_polling(self):
        """Resume polling after a test event."""
        global polling_thread, stop_polling_flag
        self.is_polling = True
        self.start_stop_button.configure(text="STOP", bootstyle=DANGER)
        self.status_var.set("Polling: Active")
        stop_polling_flag.clear()
        self.ws = connect_to_obs()
        if self.ws:
            polling_thread = threading.Thread(target=poll_rumble_api, args=(self.ws, self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var, self.event_vars))
            polling_thread.daemon = True
            polling_thread.start()
            logging.info("Resumed polling after test event")
        else:
            logging.error("Failed to reconnect to OBS after test event, polling not resumed")
            self.is_polling = False
            self.start_stop_button.configure(text="START", bootstyle=SUCCESS)
            self.status_var.set("Polling: Stopped")

    def simulate_test_event(self, event_type, ws, was_polling):
        """Simulate the test event using the provided WebSocket connection."""
        global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants
        try:
            logging.info(f"Starting test event simulation for {event_type}")
            # Simulate the event
            data = get_rumble_data(test_mode=True, test_event_type=event_type)
            if not data:
                logging.error("Failed to generate test event data")
                return

            # Get source names and settings
            TARGET_SOURCE_FOLLOWER = self.scene_vars["TARGET_SOURCE_FOLLOWER"].get()
            TARGET_SOURCE_SUBSCRIBER = self.scene_vars["TARGET_SOURCE_SUBSCRIBER"].get()
            TARGET_SOURCE_GIFTED_SUB = self.scene_vars["TARGET_SOURCE_GIFTED_SUB"].get()
            TARGET_SOURCE_RANT = self.scene_vars["TARGET_SOURCE_RANT"].get()
            DEFAULT_SCENE = self.scene_vars["DEFAULT_SCENE"].get()
            scene_switch_duration = self.scene_switch_duration_var.get()

            if event_type == "follower":
                followers_data = data.get("followers", {})
                latest_follower_data = followers_data.get("latest_follower") or {}
                latest_follower = latest_follower_data.get("username")
                if latest_follower and latest_follower != last_follower:
                    logging.info(f"New follower detected: {latest_follower}")
                    last_follower = latest_follower
                    self.event_vars["latest_follower"].set(f"Latest Follower: {latest_follower}")
                    ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_FOLLOWER, scene_switch_duration)
            elif event_type == "subscriber":
                subscribers_data = data.get("subscribers", {})
                latest_subscriber_data = subscribers_data.get("latest_subscriber") or {}
                latest_subscriber = latest_subscriber_data.get("username")
                if latest_subscriber and latest_subscriber != last_subscriber:
                    logging.info(f"New subscriber detected: {latest_subscriber}")
                    last_subscriber = latest_subscriber
                    self.event_vars["latest_subscriber"].set(f"Latest Subscriber: {latest_subscriber}")
                    ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_SUBSCRIBER, scene_switch_duration)
            elif event_type == "gifted_sub":
                gifted_subs_data = data.get("gifted_subs", {})
                recent_gifted_subs = gifted_subs_data.get("recent_gifted_subs", [])
                for gifted_sub in recent_gifted_subs:
                    purchaser = gifted_sub.get("purchased_by")
                    video_id = gifted_sub.get("video_id")
                    gift_id = f"{purchaser}_{video_id}"
                    if gift_id not in last_seen_gifted_subs:
                        logging.info(f"New gifted sub detected: Purchased by {purchaser} (video ID: {video_id})")
                        last_seen_gifted_subs.add(gift_id)
                        self.event_vars["latest_gifted_sub"].set(f"Latest Gifted Sub: {purchaser}")
                        ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_GIFTED_SUB, scene_switch_duration)
            elif event_type == "rant":
                livestreams = data.get("livestreams", [])
                for livestream in livestreams:
                    chat_data = livestream.get("chat", {})
                    rants = chat_data.get("recent_rants", [])
                    for rant in rants:
                        username = rant.get("username")
                        amount_dollars = rant.get("amount_dollars")
                        message = rant.get("text")
                        created_on = rant.get("created_on", "")
                        rant_id = f"{username}_{amount_dollars}_{message}_{created_on}"
                        if rant_id not in last_seen_rants:
                            logging.info(f"New rant detected: {username} tipped ${amount_dollars} - {message}")
                            last_seen_rants.add(rant_id)
                            self.event_vars["latest_rant"].set(f"Latest Rant: {username} tipped ${amount_dollars}")
                            ws = toggle_source(ws, DEFAULT_SCENE, TARGET_SOURCE_RANT, scene_switch_duration)
            logging.info(f"Completed test event simulation for {event_type}")
        except Exception as e:
            logging.error(f"Error during test event simulation: {e}")
        finally:
            # Clean up the temporary WebSocket connection
            if ws and ws != self.ws:  # Only close if it's not the polling WebSocket
                try:
                    ws.close()
                    logging.info("Disconnected from OBS after test event")
                except Exception as e:
                    logging.error(f"Error closing test event WebSocket: {e}")
            # Resume polling if it was active
            if was_polling:
                self.resume_polling()

    def on_closing(self):
        """Handle window closing by stopping polling and saving state."""
        if self.is_polling:
            self.toggle_polling()  # Stop polling if it's running
            # Wait for thread to finish before closing
            self.wait_for_thread_to_finish()
        save_state(self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var)
        self.root.destroy()

def main():
    # Create the GUI
    root = ttkb.Window(themename="darkly")  # Use a dark theme for a modern look
    app = OtterbotApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
