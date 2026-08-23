import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


BRIDGE_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_control_bridge.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("eve_control_bridge", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BridgeHandler(BaseHTTPRequestHandler):
    control_payload = None

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/v1/health":
            self.write_json(
                {
                    "app": "eve-runtime-core",
                    "status": "ok",
                    "surfaceRole": "headless_control_plane",
                    "consumerAppRequired": False,
                    "capabilities": ["home-snapshot", "home-control"],
                }
            )
            return
        if self.path == "/v1/home/snapshot":
            self.write_json(
                {
                    "status": "ok",
                    "route": "home_assistant_local",
                    "entityCount": 1,
                    "controllableEntityCount": 1,
                    "entities": [
                        {
                            "entityId": "light.kitchen",
                            "domain": "light",
                            "name": "Kitchen Light",
                            "state": "off",
                            "available": True,
                            "controllable": True,
                            "controlServices": ["turn_on", "turn_off"],
                        }
                    ],
                }
            )
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/home/control":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        BridgeHandler.control_payload = json.loads(data.decode("utf-8"))
        self.write_json(
            {
                "status": "dry_run" if BridgeHandler.control_payload.get("dryRun") else "sent",
                "route": "home_assistant_local",
                "domain": BridgeHandler.control_payload.get("domain", "light"),
                "service": BridgeHandler.control_payload["service"],
                "entityIds": BridgeHandler.control_payload["entityIds"],
            }
        )

    def write_json(self, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class EveControlBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = load_bridge_module()

    def setUp(self):
        BridgeHandler.control_payload = None
        self.server = HTTPServer(("127.0.0.1", 0), BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_status_reads_runtime_health(self):
        payload = self.bridge.request_json(self.base_url, "GET", "/v1/health")
        self.assertEqual("ok", payload["status"])
        self.assertEqual("headless_control_plane", payload["surfaceRole"])
        self.assertFalse(payload["consumerAppRequired"])
        self.assertIn("home-control", payload["capabilities"])

    def test_autostart_only_targets_default_headless_runtime(self):
        self.assertTrue(self.bridge.should_autostart_runtime("http://127.0.0.1:8765"))
        self.assertTrue(self.bridge.should_autostart_runtime("http://localhost:8765"))
        self.assertFalse(self.bridge.should_autostart_runtime(self.base_url))
        self.assertFalse(self.bridge.should_autostart_runtime("https://127.0.0.1:8765"))

    def test_autostart_home_only_targets_default_local_backend(self):
        self.assertTrue(self.bridge.should_autostart_home("http://127.0.0.1:8123"))
        self.assertTrue(self.bridge.should_autostart_home("http://localhost:8123"))
        self.assertFalse(self.bridge.should_autostart_home(self.base_url))
        self.assertFalse(self.bridge.should_autostart_home("https://127.0.0.1:8123"))

    def test_home_status_payload_uses_headless_lifecycle_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "bin" / "run_eve.sh"
            script.parent.mkdir()
            script.write_text("#!/bin/sh\nif [ \"$1\" = status ]; then echo 'running 123'; exit 0; fi\n", encoding="utf-8")
            os.chmod(script, 0o755)

            payload = self.bridge.home_status_payload(self.base_url, root, timeout=1)

        self.assertEqual("eve_home", payload["backend"])
        self.assertEqual("running 123", payload["lifecycleStatus"])
        self.assertTrue(payload["reachable"])
        self.assertFalse(payload["consumerAppRequired"])

    def test_snapshot_reads_home_entities(self):
        payload = self.bridge.request_json(self.base_url, "GET", "/v1/home/snapshot")
        self.assertEqual(1, payload["controllableEntityCount"])
        self.assertEqual("light.kitchen", payload["entities"][0]["entityId"])

    def test_controllable_only_filters_snapshot_json_payload(self):
        payload = {
            "entities": [
                {"entityId": "light.kitchen", "controllable": True},
                {"entityId": "sensor.sun", "controllable": False},
            ]
        }

        filtered = self.bridge.filtered_snapshot_payload(payload, controllable_only=True)

        self.assertEqual(1, filtered["returnedEntityCount"])
        self.assertEqual(["light.kitchen"], [entity["entityId"] for entity in filtered["entities"]])

    def test_control_payload_uses_allowlisted_runtime_endpoint(self):
        payload = self.bridge.build_control_payload(
            ["light.kitchen"],
            "turn_on",
            service_data={"brightness_pct": 55},
            dry_run=True,
        )
        response = self.bridge.request_json(self.base_url, "POST", "/v1/home/control", payload=payload)

        self.assertEqual("dry_run", response["status"])
        self.assertEqual(["light.kitchen"], BridgeHandler.control_payload["entityIds"])
        self.assertEqual("turn_on", BridgeHandler.control_payload["service"])
        self.assertEqual({"brightness_pct": 55}, BridgeHandler.control_payload["serviceData"])
        self.assertTrue(BridgeHandler.control_payload["dryRun"])


if __name__ == "__main__":
    unittest.main()
