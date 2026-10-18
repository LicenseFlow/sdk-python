import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Provide lightweight stubs for optional runtime dependencies if not in environment
for mod_name in ['requests', 'requests.exceptions', 'cachetools', 'jose', 'cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.asymmetric', 'cryptography.hazmat.primitives.asymmetric.ed25519']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

class DummySession:
    def __init__(self):
        self.headers = {}
    def post(self, url, *args, **kwargs):
        return MagicMock(status_code=200, json=lambda: {"allowed": True})
    def get(self, url, *args, **kwargs):
        return MagicMock(status_code=200, json=lambda: {"kill_switches": []})
    def request(self, method, url, *args, **kwargs):
        return MagicMock(status_code=200, json=lambda: {"allowed": True})

sys.modules['requests'].Session = DummySession

if not hasattr(sys.modules['cachetools'], 'TTLCache') or isinstance(sys.modules['cachetools'].TTLCache, MagicMock):
    sys.modules['cachetools'].TTLCache = dict

from licenseflow import LicenseFlowClient, PolicyDeniedError
from licenseflow.stream import KillSwitchListener, RevocationEvent


class TestKillSwitchAndRevocationStream(unittest.TestCase):
    def setUp(self):
        self.client = LicenseFlowClient(
            api_url="https://api.licenseflow.dev",
            api_key="lf_live_test_key_123",
            cache_ttl=300,
        )

    def test_instant_local_kill_switch_trip(self):
        self.assertFalse(self.client.is_revoked(subject="agent-rogue-007"))
        
        # Trip kill-switch locally
        self.client.trip_kill_switch_local("subject", "agent-rogue-007", reason="SecOps manual break-glass")
        self.assertTrue(self.client.is_revoked(subject="agent-rogue-007"))
        self.assertFalse(self.client.is_revoked(subject="agent-innocent-001"))

        # Pre-flight check on authorize immediately raises PolicyDeniedError with EMERGENCY_REVOKED
        with self.assertRaises(PolicyDeniedError) as cm:
            self.client.authorize(subject="agent-rogue-007", resource="tools/query_db")
        self.assertEqual(cm.exception.code, "EMERGENCY_REVOKED")

    def test_execute_tool_drops_revoked_subject_without_network(self):
        self.client.trip_kill_switch_local("subject", "agent-blacklisted", reason="Malicious prompt injection")
        
        # execute_tool must abort in < 0.05ms without sending HTTP request
        with patch.object(self.client.session, "post") as mock_post:
            res = self.client.execute_tool(
                tool="bash_exec",
                arguments={"cmd": "rm -rf /"},
                subject="agent-blacklisted",
            )
            mock_post.assert_not_called()
            self.assertFalse(res["allowed"])
            self.assertEqual(res["decision"], "EMERGENCY_REVOKED")
            self.assertEqual(res["status"], "revoked")
            self.assertTrue(res["is_error"])

    def test_wrap_tool_halts_revoked_agent(self):
        self.client.trip_kill_switch_local("tool", "delete_production_database", reason="High risk kill switch")

        underlying_tool = Mock(return_value="Database dropped")
        wrapped = self.client.wrap_tool(
            tool_name="delete_production_database",
            tool_fn=underlying_tool,
            subject="admin-agent",
        )

        with self.assertRaises(PolicyDeniedError) as cm:
            wrapped({"confirm": True})
        
        underlying_tool.assert_not_called()
        self.assertEqual(cm.exception.code, "EMERGENCY_REVOKED")

    def test_protect_agent_swarm_decorator(self):
        self.client.trip_kill_switch_local("subject", "swarm-worker-42", reason="Token exhaustion cutoff")

        swarm_step = Mock(return_value="Step executed")
        protected_step = self.client.protect_agent_swarm(subject="swarm-worker-42")(swarm_step)

        with self.assertRaises(PolicyDeniedError) as cm:
            protected_step()
        
        swarm_step.assert_not_called()
        self.assertEqual(cm.exception.code, "EMERGENCY_REVOKED")

    def test_kill_switch_listener_callback_and_eviction(self):
        received_events = []
        listener = KillSwitchListener(
            client=self.client,
            poll_interval=0.1,
            on_revocation=lambda ev: received_events.append(ev),
        )

        # Process a revocation event
        listener.process_revocation(
            target_type="license",
            target_identifier="LIC-REVOKED-999",
            reason="Non-payment suspension",
            source="sse_stream",
        )

        self.assertTrue(self.client.is_revoked(license_key="LIC-REVOKED-999"))
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].target_type, "license")
        self.assertEqual(received_events[0].target_identifier, "LIC-REVOKED-999")
        self.assertEqual(received_events[0].reason, "Non-payment suspension")


if __name__ == "__main__":
    unittest.main()
