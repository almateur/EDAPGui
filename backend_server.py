#!/usr/bin/env python3
"""
Python Backend Engine Server for ED Autopilot.
Provides WebSocket interface for Node.js Dashboard (or Web clients) to control
ED Autopilot, receive real-time telemetry, logs, and live debug screenshots/frames.
"""

import argparse
import asyncio
from contextlib import suppress
import base64
import json
import os
import logging
from datetime import datetime
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed

# Game/OCR dependencies are imported only for a live engine, never for --mock,
# --help, or modules that import the server for protocol tests.
cv2 = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EDAP_Backend")

PORT = int(os.environ.get("EDAP_PORT", 8765))
HOST = os.environ.get("EDAP_HOST", "127.0.0.1")
WAYPOINT_DIR = Path(__file__).resolve().parent / "waypoints"


def resolve_waypoint_file(filepath):
    """Network clients may load only JSON files within the waypoint directory."""
    if not isinstance(filepath, str) or not filepath or len(filepath) > 1024:
        raise ValueError("A waypoint JSON path is required")
    root = WAYPOINT_DIR.resolve()
    candidate = (root.parent / filepath).resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() != ".json":
        raise ValueError("Waypoint files must be JSON files inside waypoints/")
    if not candidate.is_file() or candidate.stat().st_size > 1024 * 1024:
        raise ValueError("Waypoint file is missing or larger than 1 MiB")
    return candidate

class EDAPEngineServer:
    def __init__(self, mock: bool = False):
        self.mock_mode = mock
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
        for ws in tuple(self.connected_clients):
            try:
                await ws.send(msg_str)
            except ConnectionClosed:
                disconnected.add(ws)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.add(ws)
        self.connected_clients -= disconnected

    def init_engine(self):
        """Initialize EDAutopilot core if available."""
        global cv2
        if self.mock_mode:
            self.latest_telemetry["status"] = "Mock mode"
            logger.info("Mock mode requested: skipping game, OCR, and detection model initialization.")
            return
        logger.info("Initializing live autopilot. Keep Elite Dangerous running and visible; OCR/model loading may take time.")
        try:
            from ED_AP import EDAutopilot
            import cv2 as engine_cv2
            cv2 = engine_cv2
            self.ed_ap = EDAutopilot(cb=self.ap_callback, do_thread=True)
            logger.info("EDAutopilot initialized successfully.")
        except Exception as e:
            self.ed_ap = None
            self.mock_mode = True
            self.latest_telemetry["status"] = "Mock mode"
            logger.warning("Live autopilot unavailable; running in mock mode: %s", e)

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
        if not isinstance(data, dict):
            raise ValueError("Command must be a JSON object")
        cmd = data.get("command")
        if not isinstance(cmd, str):
            raise ValueError("Command must be a string")
        logger.info(f"Received command: {cmd}")

        if not cmd:
            return

        if cmd == "ping":
            reply = {"type": "pong"}
            if isinstance(data.get("request_id"), str):
                reply["request_id"] = data["request_id"]
                reply["capabilities"] = ["waypoint_load_result"]
            await ws.send(json.dumps(reply))
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
            self.latest_telemetry["status"] = "Mock mode" if self.mock_mode else "Idle"
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": "Command: Stop All Assists"})

        elif cmd == "load_waypoint_file":
            filepath = str(resolve_waypoint_file(data.get("filepath")))
            if self.ed_ap and hasattr(self.ed_ap, "waypoint") and filepath:
                if not self.ed_ap.waypoint.load_waypoint_file(filepath):
                    raise ValueError("The backend could not load this waypoint file.")
                message = "Waypoint file loaded."
            else:
                message = "Waypoint file validated (mock mode)."
            if isinstance(data.get("request_id"), str):
                await ws.send(json.dumps({"type": "waypoint_load_result", "request_id": data["request_id"],
                                          "success": True, "message": message}))
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": f"{message} {filepath}"})

        elif cmd == "toggle_debug_stream":
            self.debug_stream_active = bool(data.get("enabled", not self.debug_stream_active))
            await self.broadcast({"type": "log", "timestamp": datetime.now().strftime("%H:%M:%S"), "message": f"Debug frame streaming: {self.debug_stream_active}"})

        await self.broadcast({"type": "telemetry", "data": self.latest_telemetry})

    async def client_handler(self, websocket):
        self.connected_clients.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.connected_clients)}")

        try:
            # Initial sends also need cleanup if the client disconnects.
            await websocket.send(json.dumps({"type": "telemetry", "data": self.latest_telemetry}))
            await websocket.send(json.dumps({
                "type": "log",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "message": "Connected to ED Autopilot Python Backend Engine" + (" (mock mode: simulated controls)" if self.mock_mode else "")
            }))

            async for message in websocket:
                data = None
                try:
                    data = json.loads(message)
                    await self.handle_command(websocket, data)
                except json.JSONDecodeError:
                    logger.error("Received non-JSON message from client.")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    if (isinstance(data, dict) and data.get("command") == "load_waypoint_file"
                            and isinstance(data.get("request_id"), str)):
                        await websocket.send(json.dumps({"type": "waypoint_load_result", "request_id": data["request_id"],
                                                         "success": False, "message": str(e)}))
        except ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            logger.info(f"Client disconnected. Total clients: {len(self.connected_clients)}")

    async def main(self):
        if HOST not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("EDAP_HOST must be a loopback address; remote control is unsupported")
        self.loop = asyncio.get_running_loop()
        self.init_engine()

        telemetry_task = asyncio.create_task(self.periodic_telemetry_and_screenshots())
        try:
            logger.info(f"Starting Python Engine WebSocket Server on {HOST}:{PORT}...")
            # Only the local dashboard talks to this socket. Browsers always
            # supply Origin and must use the dashboard's checked WebSocket.
            async with websockets.serve(
                self.client_handler, HOST, PORT, origins=[None],
                max_size=64 * 1024, max_queue=16,
            ):
                await asyncio.Future()  # run forever
        finally:
            telemetry_task.cancel()
            with suppress(asyncio.CancelledError):
                await telemetry_task

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ED Autopilot WebSocket backend")
    parser.add_argument("--mock", action="store_true", help="Run the web UI backend without importing game, OCR, or model dependencies; controls are simulated.")
    args = parser.parse_args()
    server = EDAPEngineServer(mock=args.mock)
    try:
        asyncio.run(server.main())
    except KeyboardInterrupt:
        logger.info("Server shutting down.")
