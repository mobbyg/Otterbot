# Otterbot v1.1.3
# Version History:
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

import pycurl
import json
import time
import websocket
import uuid
import hashlib
import base64
from io import BytesIO
import logging
import argparse
import random
import threading
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from queue import Queue
import os

# Configure logging
logging.basicConfig(
    filename="rumble_obs.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Rumble API configuration
API_URL = "" # Place your Livestream API for Rumble here

# OBS WebSocket configuration
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = ""
OBS_WS_URL = f"ws://{OBS_HOST}:{OBS_PORT}"

# Default scene configurations (will be updated via GUI and loaded from state)
DEFAULT_SCENE_CONFIG = {
    "TARGET_SCENE_FOLLOWER": "TEST",
    "TARGET_SCENE_SUBSCRIBER": "TEST2",
    "TARGET_SCENE_GIFTED_SUB": "TEST3",
    "TARGET_SCENE_RANT": "TEST4",  # New scene for rants
    "DEFAULT_SCENE": "Big Screen"
}
DEFAULT_POLLING_INTERVAL = 10  # Default polling interval in seconds
DEFAULT_SCENE_SWITCH_DURATION = 10  # Default duration to display the target scene (in seconds)
SLEEP_INTERVAL = 0.5  # Small interval for breaking up sleep in polling loop

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
                # Load scene names
                for key in DEFAULT_SCENE_CONFIG:
                    scene_vars[key].set(state.get("scene_names", {}).get(key, DEFAULT_SCENE_CONFIG[key]))
                # Load polling interval and scene switch duration
                polling_interval_var.set(state.get("polling_interval", DEFAULT_POLLING_INTERVAL))
                scene_switch_duration_var.set(state.get("scene_switch_duration", DEFAULT_SCENE_SWITCH_DURATION))
                logging.info(f"Loaded state from {STATE_FILE}")
        else:
            last_follower = None
            last_subscriber = None
            last_seen_gifted_subs = set()
            last_seen_rants = set()
            # Set default scene names
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
        # Reset scene names to defaults
        for key in DEFAULT_SCENE_CONFIG:
            scene_vars[key].set(DEFAULT_SCENE_CONFIG[key])
        polling_interval_var.set(DEFAULT_POLLING_INTERVAL)
        scene_switch_duration_var.set(DEFAULT_SCENE_SWITCH_DURATION)
        # Save the reset state
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
                        "rants": [
                            {
                                "username": fake_username,
                                "amount_dollars": 5,
                                "message": "Great stream!"
                            }
                        ]
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

def switch_scene(ws, scene_name):
    """Switch to the specified scene in OBS."""
    if ws is None:
        logging.error("Cannot switch scene: WebSocket connection is not established")
        return
    try:
        request_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestType": "SetCurrentProgramScene",
                "requestId": request_id,
                "requestData": {"sceneName": scene_name}
            }
        }))
        for attempt in range(5):
            try:
                if ws.connected:
                    response_raw = ws.recv()
                    logging.info(f"Raw scene switch response: {repr(response_raw)}")
                    response = json.loads(response_raw)
                    logging.info(f"Parsed scene switch response: {response}")
                    break
                else:
                    logging.warning(f"WebSocket not connected on scene switch attempt {attempt + 1}")
                    if attempt == 4:
                        logging.error("WebSocket disconnected during scene switch response")
                        return
                    time.sleep(1)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON decode error on scene switch attempt {attempt + 1}: {e}")
                if attempt == 4:
                    logging.error("Failed to parse scene switch response after retries")
                    return
                time.sleep(1)
            except websocket.WebSocketTimeoutException:
                logging.error("Timeout waiting for scene switch response")
                return
            except websocket.WebSocketConnectionClosedException:
                logging.error("WebSocket connection closed during scene switch response")
                return
        if response.get("d", {}).get("requestStatus", {}).get("result", False):
            logging.info(f"Switched to scene: {scene_name}")
        else:
            logging.error(f"Failed to switch scene: {response}")
    except Exception as e:
        logging.error(f"Error switching scene: {e}")

def poll_rumble_api(ws, scene_vars, polling_interval_var, scene_switch_duration_var, event_vars):
    """Main polling loop for Rumble API, runs in a separate thread."""
    global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants
    try:
        while not stop_polling_flag.is_set():
            # Fetch Rumble API data
            data = get_rumble_data()
            if data is None:
                logging.warning("Failed to fetch Rumble API data, skipping this cycle")
                # Sleep in small increments to remain responsive to stop flag
                elapsed = 0
                polling_interval = polling_interval_var.get()
                while elapsed < polling_interval and not stop_polling_flag.is_set():
                    time.sleep(min(SLEEP_INTERVAL, polling_interval - elapsed))
                    elapsed += SLEEP_INTERVAL
                continue

            # Get scene names and settings from GUI
            TARGET_SCENE_FOLLOWER = scene_vars["TARGET_SCENE_FOLLOWER"].get()
            TARGET_SCENE_SUBSCRIBER = scene_vars["TARGET_SCENE_SUBSCRIBER"].get()
            TARGET_SCENE_GIFTED_SUB = scene_vars["TARGET_SCENE_GIFTED_SUB"].get()
            TARGET_SCENE_RANT = scene_vars["TARGET_SCENE_RANT"].get()
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
                switch_scene(ws, TARGET_SCENE_FOLLOWER)
                # Sleep in small increments during scene switch
                elapsed = 0
                while elapsed < scene_switch_duration and not stop_polling_flag.is_set():
                    time.sleep(min(SLEEP_INTERVAL, scene_switch_duration - elapsed))
                    elapsed += SLEEP_INTERVAL
                if not stop_polling_flag.is_set():
                    switch_scene(ws, DEFAULT_SCENE)

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
                switch_scene(ws, TARGET_SCENE_SUBSCRIBER)
                elapsed = 0
                while elapsed < scene_switch_duration and not stop_polling_flag.is_set():
                    time.sleep(min(SLEEP_INTERVAL, scene_switch_duration - elapsed))
                    elapsed += SLEEP_INTERVAL
                if not stop_polling_flag.is_set():
                    switch_scene(ws, DEFAULT_SCENE)

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
                    switch_scene(ws, TARGET_SCENE_GIFTED_SUB)
                    elapsed = 0
                    while elapsed < scene_switch_duration and not stop_polling_flag.is_set():
                        time.sleep(min(SLEEP_INTERVAL, scene_switch_duration - elapsed))
                        elapsed += SLEEP_INTERVAL
                    if not stop_polling_flag.is_set():
                        switch_scene(ws, DEFAULT_SCENE)

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
                    rants = livestream.get("rants", [])
                    seen_rant_ids_in_cycle = set()
                    for rant in rants:
                        if stop_polling_flag.is_set():
                            break
                        username = rant.get("username")
                        amount_dollars = rant.get("amount_dollars")
                        message = rant.get("message")
                        rant_id = f"{username}_{amount_dollars}_{message}"
                        if rant_id not in last_seen_rants and rant_id not in seen_rant_ids_in_cycle:
                            logging.info(f"New rant detected: {username} tipped ${amount_dollars} - {message}")
                            last_seen_rants.add(rant_id)
                            seen_rant_ids_in_cycle.add(rant_id)
                            event_vars["latest_rant"].set(f"Latest Rant: {username} tipped ${amount_dollars}")
                            switch_scene(ws, TARGET_SCENE_RANT)
                            elapsed = 0
                            while elapsed < scene_switch_duration and not stop_polling_flag.is_set():
                                time.sleep(min(SLEEP_INTERVAL, scene_switch_duration - elapsed))
                                elapsed += SLEEP_INTERVAL
                            if not stop_polling_flag.is_set():
                                switch_scene(ws, DEFAULT_SCENE)
                        logging.info(f"Rant: {username} tipped ${amount_dollars} - {message}")

                    # Log chat messages
                    chat_messages = livestream.get("chat_messages", [])
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
        self.root.title("🦦 Otterbot v1.1.3")
        self.root.geometry("600x700")  # Increased height to accommodate new elements

        # Add a custom logging handler to send logs to the GUI
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        handler.emit = log_to_queue_handler
        logging.getLogger().addHandler(handler)

        # Variables to store scene names
        self.scene_vars = {
            "TARGET_SCENE_FOLLOWER": tk.StringVar(),
            "TARGET_SCENE_SUBSCRIBER": tk.StringVar(),
            "TARGET_SCENE_GIFTED_SUB": tk.StringVar(),
            "TARGET_SCENE_RANT": tk.StringVar(),
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
        """Setup the Settings tab with scene name entries, adjustable settings, and buttons."""
        # Scene name entries
        settings_frame = ttkb.LabelFrame(self.settings_tab, text="Scene Configuration", padding=10)
        settings_frame.pack(pady=5, padx=10, fill="x")

        # Follower Scene
        ttkb.Label(settings_frame, text="Follower Scene:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SCENE_FOLLOWER"]).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Subscriber Scene
        ttkb.Label(settings_frame, text="Subscriber Scene:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SCENE_SUBSCRIBER"]).grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Gifted Sub Scene
        ttkb.Label(settings_frame, text="Gifted Sub Scene:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SCENE_GIFTED_SUB"]).grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Rant Scene
        ttkb.Label(settings_frame, text="Rant Scene:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        ttkb.Entry(settings_frame, textvariable=self.scene_vars["TARGET_SCENE_RANT"]).grid(row=3, column=1, padx=5, pady=5, sticky="ew")

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

        # Scene Switch Duration
        ttkb.Label(timing_frame, text="Scene Switch Duration (seconds):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
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
        
        # If polling is active, stop it temporarily
        was_polling = self.is_polling
        if was_polling:
            self.is_polling = False
            stop_polling_flag.set()
            if self.ws:
                self.ws.close()
                self.ws = None
                logging.info("Disconnected from OBS during test event setup")
            self.wait_for_test_event(event_type, was_polling)
        else:
            # If not polling, connect to OBS and simulate the event
            ws = connect_to_obs()
            if not ws:
                logging.error("Failed to connect to OBS for test event")
                return
            self.simulate_test_event(event_type, ws, was_polling)

    def wait_for_test_event(self, event_type, was_polling):
        """Wait for the polling thread to finish before simulating the test event."""
        global polling_thread, stop_polling_flag
        if polling_thread and polling_thread.is_alive():
            self.root.after(100, lambda: self.wait_for_test_event(event_type, was_polling))
        else:
            # Connect to OBS for the test event
            ws = connect_to_obs()
            if not ws:
                logging.error("Failed to connect to OBS for test event")
                if was_polling:
                    # Resume polling if it was active
                    self.is_polling = True
                    self.start_stop_button.configure(text="STOP", bootstyle=DANGER)
                    self.status_var.set("Polling: Active")
                    stop_polling_flag.clear()
                    polling_thread = threading.Thread(target=poll_rumble_api, args=(self.ws, self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var, self.event_vars))
                    polling_thread.daemon = True
                    polling_thread.start()
                return
            self.simulate_test_event(event_type, ws, was_polling)

    def simulate_test_event(self, event_type, ws, was_polling):
        """Simulate the test event using the provided WebSocket connection."""
        global last_follower, last_subscriber, last_seen_gifted_subs, last_seen_rants, polling_thread, stop_polling_flag
        try:
            logging.info(f"Starting test event simulation for {event_type}")
            # Simulate the event
            data = get_rumble_data(test_mode=True, test_event_type=event_type)
            if not data:
                logging.error("Failed to generate test event data")
                return

            # Process the test event
            TARGET_SCENE_FOLLOWER = self.scene_vars["TARGET_SCENE_FOLLOWER"].get()
            TARGET_SCENE_SUBSCRIBER = self.scene_vars["TARGET_SCENE_SUBSCRIBER"].get()
            TARGET_SCENE_GIFTED_SUB = self.scene_vars["TARGET_SCENE_GIFTED_SUB"].get()
            TARGET_SCENE_RANT = self.scene_vars["TARGET_SCENE_RANT"].get()
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
                    switch_scene(ws, TARGET_SCENE_FOLLOWER)
                    time.sleep(scene_switch_duration)
                    switch_scene(ws, DEFAULT_SCENE)
            elif event_type == "subscriber":
                subscribers_data = data.get("subscribers", {})
                latest_subscriber_data = subscribers_data.get("latest_subscriber") or {}
                latest_subscriber = latest_subscriber_data.get("username")
                if latest_subscriber and latest_subscriber != last_subscriber:
                    logging.info(f"New subscriber detected: {latest_subscriber}")
                    last_subscriber = latest_subscriber
                    self.event_vars["latest_subscriber"].set(f"Latest Subscriber: {latest_subscriber}")
                    switch_scene(ws, TARGET_SCENE_SUBSCRIBER)
                    time.sleep(scene_switch_duration)
                    switch_scene(ws, DEFAULT_SCENE)
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
                        switch_scene(ws, TARGET_SCENE_GIFTED_SUB)
                        time.sleep(scene_switch_duration)
                        switch_scene(ws, DEFAULT_SCENE)
            elif event_type == "rant":
                livestreams = data.get("livestreams", [])
                for livestream in livestreams:
                    rants = livestream.get("rants", [])
                    for rant in rants:
                        username = rant.get("username")
                        amount_dollars = rant.get("amount_dollars")
                        message = rant.get("message")
                        rant_id = f"{username}_{amount_dollars}_{message}"
                        if rant_id not in last_seen_rants:
                            logging.info(f"New rant detected: {username} tipped ${amount_dollars} - {message}")
                            last_seen_rants.add(rant_id)
                            self.event_vars["latest_rant"].set(f"Latest Rant: {username} tipped ${amount_dollars}")
                            switch_scene(ws, TARGET_SCENE_RANT)
                            time.sleep(scene_switch_duration)
                            switch_scene(ws, DEFAULT_SCENE)
            logging.info(f"Completed test event simulation for {event_type}")
        except Exception as e:
            logging.error(f"Error during test event simulation: {e}")
        finally:
            # Clean up the temporary WebSocket connection
            if ws:
                ws.close()
                logging.info("Disconnected from OBS after test event")
            # Resume polling if it was active
            if was_polling:
                self.is_polling = True
                self.start_stop_button.configure(text="STOP", bootstyle=DANGER)
                self.status_var.set("Polling: Active")
                stop_polling_flag.clear()
                self.ws = connect_to_obs()
                if self.ws:
                    polling_thread = threading.Thread(target=poll_rumble_api, args=(self.ws, self.scene_vars, self.polling_interval_var, self.scene_switch_duration_var, self.event_vars))
                    polling_thread.daemon = True
                    polling_thread.start()
                else:
                    logging.error("Failed to reconnect to OBS after test event, polling not resumed")
                    self.is_polling = False
                    self.start_stop_button.configure(text="START", bootstyle=SUCCESS)
                    self.status_var.set("Polling: Stopped")

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
