#!/usr/bin/env python3
"""
Python Backend Engine Server for ED Autopilot.
Provides WebSocket interface for Node.js Dashboard (or Web clients) to control
ED Autopilot, receive real-time telemetry, logs, and live debug screenshots/frames.
"""

import asyncio
import base64
import json
import os
import sys
import threading
import logging
from datetime import datetime

import websockets

# Import EDAutopilot core
try:
    from ED_AP import EDAutopilot
    import cv2
except Exception as e:
    print(f"[Engine Backend] Warning importing EDAutopilot/cv2 dependencies: {e}")
    EDAutopilot = None
    cv2 = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EDAP_Backend")

PORT = int(os.environ.get("EDAP_PORT", 8765))
HOST = os.environ.get("EDAP_HOST", "0.0.0.0")

class EDAPEngineServer:
    def __init__(self):
        self.connected_clients = set()
        self.ed_ap = None
        self.loop = None
        self.latest_telemetry = {
            "status": "Idle",
            "system": "Unknown",
            "jump_info": "Dist: 0ly Jumps: 0/0",
            "ship": "Unknown",
            "fuel": 100,
            "assists": {
                "fsd": False,
                "sc": False,
                "waypoint": False,
                "robigo": False,
                "dss": False,
                "single_waypoint": False,
                "afk_combat": False
            }
        }
        self.debug_stream_active = False

    def ap_callback(self, msg, body=None):
        """Callback received from EDAutopilot instance."""
        asyncio.run_coroutine_threadsafe(self.handle_ap_callback(msg, body), self.loop)

    async def handle_ap_callback(self, msg, body):
        payload = None
        if msg == 'log':
            log_str = str(body) if body else ''
            payload = {"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": log_str}
            logger.info(f"LOG: {log_str}")
        elif msg == 'log+vce':
            log_str = str(body) if body else ''
            payload = {"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": f"[Voice] {log_str}"}
            logger.info(f"LOG+VCE: {log_str}")
        elif msg == 'statusline':
            self.latest_telemetry["status"] = str(body)
            payload = {"type": "telemetry", "data": self.latest_telemetry}
        elif msg == 'jumpcount':
            self.latest_telemetry["jump_info"] = str(body)
            payload = {"type": "telemetry", "data": self.latest_telemetry}
        elif msg.endswith('_start'):
            mode = msg.replace('_start', '')
            if mode in self.latest_telemetry["assists"]:
                self.latest_telemetry["assists"][mode] = True
            payload = {"type": "telemetry", "data": self.latest_telemetry}
        elif msg.endswith('_stop'):
            mode = msg.replace('_stop', '')
            if mode in self.latest_telemetry["assists"]:
                self.latest_telemetry["assists"][mode] = False
            payload = {"type": "telemetry", "data": self.latest_telemetry}
        elif msg == 'stop_all_assists':
            for key in self.latest_telemetry["assists"]:
                self.latest_telemetry["assists"][key] = False
            self.latest_telemetry["status"] = "Idle"
            payload = {"type": "telemetry", "data": self.latest_telemetry}

        if payload:
            await self.broadcast(payload)

    async def broadcast(self, message_dict):
        if not self.connected_clients:
            return
        msg_str = json.dumps(message_dict)
        disconnected = set()
        for ws in self.connected_clients:
            try:
                await ws.send(msg_str)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(ws)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.add(ws)
        self.connected_clients -= disconnected

    def init_engine(self):
        """Initialize EDAutopilot core if available."""
        if EDAutopilot is not None:
            try:
                self.ed_ap = EDAutopilot(cb=self.ap_callback, do_thread=True)
                logger.info("EDAutopilot initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize EDAutopilot core: {e}")
                self.ed_ap = None
        else:
            logger.warning("EDAutopilot class unavailable. Running backend in mock mode.")

    async def periodic_telemetry_and_screenshots(self):
        """Periodically broadcast telemetry and debug frame screenshots."""
        while True:
            try:
                await asyncio.sleep(1.0)
                if self.ed_ap:
                    try:
                        ship_state = self.ed_ap.jn.ship_state()
                        self.latest_telemetry["ship"] = ship_state.get("type", "Unknown") or "Unknown"
                        self.latest_telemetry["system"] = ship_state.get("cur_star_system", "Unknown") or "Unknown"
                        self.latest_telemetry["fuel"] = ship_state.get("fuel_percent", 100)
                    except Exception as e:
                        logger.debug(f"Error updating ship telemetry: {e}")

                await self.broadcast({"type": "telemetry", "data": self.latest_telemetry})

                # Stream debug screenshot frame if enabled and CV/Screen available
                if self.debug_stream_active and self.ed_ap and hasattr(self.ed_ap, "scr"):
                    try:
                        frame = self.ed_ap.scr.get_screen()
                        if frame is not None and cv2 is not None:
                            # Resize for fast streaming over WebSocket
                            h, w = frame.shape[:2]
                            target_w = 640
                            target_h = int(h * (target_w / w))
                            resized = cv2.resize(frame, (target_w, target_h))
                            _, buffer = cv2.imencode('.jpg', resized, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                            b64_str = base64.b64encode(buffer).decode('utf-8')
                            await self.broadcast({"type": "screenshot", "image": f"data:image/jpeg;base64,{b64_str}"})
                    except Exception as err:
                        logger.debug(f"Error capturing debug screenshot frame: {err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in telemetry background task: {e}")

    async def handle_command(self, ws, data):
        """Process command message from client."""
        cmd = data.get("command")
        logger.info(f"Received command: {cmd}")

        if not cmd:
            return

        if cmd == "ping":
            await ws.send(json.dumps({"type": "pong"}))
            return

        if cmd == "start_fsd":
            if self.ed_ap:
                self.ed_ap.set_fsd_assist(True)
            self.latest_telemetry["assists"]["fsd"] = True
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Start FSD Assist"})

        elif cmd == "stop_fsd":
            if self.ed_ap:
                self.ed_ap.set_fsd_assist(False)
            self.latest_telemetry["assists"]["fsd"] = False
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop FSD Assist"})

        elif cmd == "start_sc":
            if self.ed_ap:
                self.ed_ap.set_sc_assist(True)
            self.latest_telemetry["assists"]["sc"] = True
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Start Supercruise Assist"})

        elif cmd == "stop_sc":
            if self.ed_ap:
                self.ed_ap.set_sc_assist(False)
            self.latest_telemetry["assists"]["sc"] = False
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop Supercruise Assist"})

        elif cmd == "start_waypoint":
            if self.ed_ap:
                self.ed_ap.set_waypoint_assist(True)
            self.latest_telemetry["assists"]["waypoint"] = True
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Start Waypoint Assist"})

        elif cmd == "stop_waypoint":
            if self.ed_ap:
                self.ed_ap.set_waypoint_assist(False)
            self.latest_telemetry["assists"]["waypoint"] = False
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop Waypoint Assist"})

        elif cmd == "start_robigo":
            if self.ed_ap:
                self.ed_ap.set_robigo_assist(True)
            self.latest_telemetry["assists"]["robigo"] = True
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Start Robigo Assist"})

        elif cmd == "stop_robigo":
            if self.ed_ap:
                self.ed_ap.set_robigo_assist(False)
            self.latest_telemetry["assists"]["robigo"] = False
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop Robigo Assist"})

        elif cmd == "start_dss":
            if self.ed_ap:
                self.ed_ap.set_dss_assist(True)
            self.latest_telemetry["assists"]["dss"] = True
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Start DSS Assist"})

        elif cmd == "stop_dss":
            if self.ed_ap:
                self.ed_ap.set_dss_assist(False)
            self.latest_telemetry["assists"]["dss"] = False
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop DSS Assist"})

        elif cmd == "stop_all_assists":
            if self.ed_ap:
                self.ed_ap.set_fsd_assist(False)
                self.ed_ap.set_sc_assist(False)
                self.ed_ap.set_waypoint_assist(False)
                self.ed_ap.set_robigo_assist(False)
                self.ed_ap.set_dss_assist(False)
                self.ed_ap.set_afk_combat_assist(False)
                self.ed_ap.set_single_waypoint_assist("", "", False)
            for k in self.latest_telemetry["assists"]:
                self.latest_telemetry["assists"][k] = False
            self.latest_telemetry["status"] = "Idle"
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop All Assists"})

        elif cmd == "load_waypoint_file":
            filepath = data.get("filepath", "")
            if self.ed_ap and hasattr(self.ed_ap, "waypoint") and filepath:
                self.ed_ap.waypoint.load_waypoint_file(filepath)
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": f"Loaded waypoint file: {filepath}"})

        elif cmd == "toggle_debug_stream":
            self.debug_stream_active = bool(data.get("enabled", not self.debug_stream_active))
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": f"Debug frame streaming: {self.debug_stream_active}"})

        await self.broadcast({"type": "telemetry", "data": self.latest_telemetry})

    async def client_handler(self, websocket):
        self.connected_clients.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.connected_clients)}")

        # Send initial state and log message
        await websocket.send(json.dumps({"type": "telemetry", "data": self.latest_telemetry}))
        await websocket.send(json.dumps({
            "type": "log",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": "Connected to ED Autopilot Python Backend Engine"
        }))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_command(websocket, data)
                except json.JSONDecodeError:
                    logger.error("Received non-JSON message from client.")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.remove(websocket)
            logger.info(f"Client disconnected. Total clients: {len(self.connected_clients)}")

    async def main(self):
        self.loop = asyncio.get_running_loop()
        self.init_engine()

        asyncio.create_task(self.periodic_telemetry_and_screenshots())

        logger.info(f"Starting Python Engine WebSocket Server on {HOST}:{PORT}...")
        async with websockets.serve(self.client_handler, HOST, PORT):
            await asyncio.Future()  # run forever

if __name__ == "__main__":
    server = EDAPEngineServer()
    try:
        asyncio.run(server.main())
    except KeyboardInterrupt:
        logger.info("Server shutting down.")
