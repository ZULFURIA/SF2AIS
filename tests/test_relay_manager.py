import os
import unittest
from unittest.mock import patch

import relay_manager


class CloudflareTunnelManagerTests(unittest.TestCase):
    def test_missing_token_keeps_relay_disabled(self):
        manager = relay_manager.CloudflareTunnelManager()
        with patch.dict(os.environ, {"SF2AIS_CLOUDFLARED_TOKEN": ""}):
            result = manager.start()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["state"], "disabled")

    def test_missing_cloudflared_binary_is_reported_without_starting_process(self):
        manager = relay_manager.CloudflareTunnelManager()
        with patch.dict(os.environ, {"SF2AIS_CLOUDFLARED_TOKEN": "test-token"}), \
             patch.object(manager, "_executable", return_value=None):
            result = manager.start()
        self.assertTrue(result["enabled"])
        self.assertFalse(result["available"])
        self.assertEqual(result["state"], "unavailable")

    def test_tunnel_token_is_redacted_from_recent_logs(self):
        manager = relay_manager.CloudflareTunnelManager()
        with patch.dict(os.environ, {"SF2AIS_CLOUDFLARED_TOKEN": "sensitive-token"}):
            manager._record_log("cloudflared connected with sensitive-token")
        self.assertNotIn("sensitive-token", manager.status()["recent_logs"][0])
        self.assertIn("[redacted]", manager.status()["recent_logs"][0])


if __name__ == "__main__":
    unittest.main()
