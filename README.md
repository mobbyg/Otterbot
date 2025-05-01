# 🦦 Otterbot
### The Offical Rumble livestreaming bot of the GREAT Otterman Empire!
  
![image](https://github.com/user-attachments/assets/6cc23934-5aec-4552-946a-481d1296359b)

Required:<br>

+ pycurl<br>
+ websocket<br>
+ ttkbootstrap<br>

Installation:<br>

+ Install required libraries above. 
+ Start with `python3 otterbot_v1_1_3.py`

Upcoming Features:<br>

+ Multiple Channel Support
+ Themes
+ Suggest YOUR ideas

### Should work on Windows and Mac with Python v3.xx installed. ### 

-------------------------------------------

## Version History:
* v1.0.0 (2025-04-28): Initial GUI release with scene configuration, start/stop polling, and real-time log display.
                      Added Clear Log button in the Log tab.
                      Added otter emoji (🦦) to the title bar.
                      Added persistent state saving/loading to prevent re-triggering old events on startup.
                      Fixed state file saving by using absolute path and improved error logging.
                      Improved gifted sub detection to avoid duplicates.
  
* v1.1.0 (2025-04-29): Added saving of scene names to state file.
                      Added Reset State button to clear event tracking.
                      Added Test Mode button to simulate new events.
                      Added status indicator for polling state.
                      Added adjustable polling interval and scene switch duration.
                      Added display of latest event details (follower, subscriber, gifted sub).
                      Fixed global variable declaration issue in test_event method.

* v1.1.1 (2025-04-30): Fixed polling thread termination to be more responsive by breaking sleep into smaller intervals.
                      Made thread joining non-blocking to prevent GUI freeze.

* v1.1.2 (2025-04-30): Fixed test event functionality to work without polling being active.
                      Ensured WebSocket connection is available during test events.
                      Added better logging for test event simulation.

* v1.1.3 (2025-04-30): Added support for detecting and handling new rants (monetary tips) during livestreams.
                      Added scene switching for new rants and test mode simulation for rants.
                      Added display of latest rant in the GUI.
# v1.1.4 (2025-04-29): Replaced scene switching with source visibility toggling for followers, subscribers, gifted subs, and rants.
                      Updated GUI to configure source names instead of scenes.
                      Used SetSceneItemEnabled for OBS WebSocket 5.x to toggle sources.

# v1.1.5 (2025-04-29): Fixed missing sceneItemId in SetSceneItemEnabled requests by adding get_scene_item_id helper.
                      Ensured test mode and polling correctly toggle sources.

# v1.1.6 (2025-04-29): Fixed get_scene_item_id to correctly extract sceneItemId from responseData, resolving test button failure.

# v1.1.7 (2025-04-29): Fixed toggle_source to use sceneItemEnabled instead of enabled in SetSceneItemEnabled requests.

# v1.1.8 (2025-04-29): Improved WebSocket and thread management in test_event and wait_for_test_event to fix test button failure during polling.

# v1.1.9 (2025-04-29): Fixed `watchers_data` typo in simulate_test_event for subscriber events.
                      Improved toggle_source to use threading.Timer for reliable source disabling.
                      Added event queuing to prevent overlapping source toggles.
                      Added WebSocket reconnection logic in poll_rumble_api for robustness.
                      Ensured subscriber events are processed consistently with polling.
# v1.2.0 (2025-04-29): Fixed Queue.Empty error in process_event_queue by using queue.Empty.
                      Simplified event handling by removing event_queue and process_event_queue thread.
                      Ensured sources are disabled after timer by validating WebSocket connection.
                      Added WebSocket reconnection logic in toggle_source for robustness.
                      Improved logging for timer and disable actions.
