import unittest
from unittest.mock import Mock, MagicMock, patch
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Provide lightweight stubs for optional runtime dependencies if not in environment
for mod_name in ['requests', 'requests.exceptions', 'cachetools', 'jose', 'cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.asymmetric', 'cryptography.hazmat.primitives.asymmetric.ed25519']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

class DummyRequestException(Exception):
    pass

sys.modules['requests'].exceptions.RequestException = DummyRequestException
if 'requests.exceptions' in sys.modules:
    sys.modules['requests.exceptions'].RequestException = DummyRequestException

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

from licenseflow import (
    LicenseFlowClient,
    RateLimitError,
    InvalidLicenseError,
    ApprovalRequiredError,
    PolicyDeniedError,
)

class TestLicenseFlowClient(unittest.TestCase):
    def setUp(self):
        self.client = LicenseFlowClient(
            api_url="https://api.test",
            api_key="test-key",
            jwt_secret="test-secret",
            retries=0,
        )

    def test_activate(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"success": True, "message": "Activated", "proof": "dummy-jwt"}
            )
            res = self.client.activate(license_key="TEST-KEY")
            self.assertTrue(res["success"])
            self.assertEqual(res["proof"], "dummy-jwt")

    def test_verify_with_cache(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"valid": True, "status": "active"}
            )
            res1 = self.client.verify(license_key="TEST-KEY")
            self.assertTrue(res1["valid"])
            self.assertEqual(mock_post.call_count, 1)

            # Second call - hits cache
            res2 = self.client.verify(license_key="TEST-KEY")
            self.assertTrue(res2["valid"])
            self.assertEqual(mock_post.call_count, 1)

    def test_rate_limit_error(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=429,
                json=lambda: {"message": "Too many requests"}
            )
            with self.assertRaises(RateLimitError):
                self.client.verify(license_key="TEST-KEY")

    def test_invalid_license_error(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=400,
                json=lambda: {"message": "Invalid license"}
            )
            with self.assertRaises(InvalidLicenseError):
                self.client.verify(license_key="TEST-KEY")

    def test_deactivate(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"success": True}
            )
            res = self.client.deactivate(license_key="TEST-KEY")
            self.assertTrue(res["success"])

    def test_execute_tool_allowed(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "result": {
                        "content": [{"type": "text", "text": "Results: 42 records"}],
                        "isError": False
                    }
                }
            )
            res = self.client.execute_tool(
                tool="search_vectors",
                arguments={"query": "test query"},
                agent_id="agent_py_01"
            )
            self.assertTrue(res["allowed"])
            self.assertEqual(res["status"], "executed")
            self.assertEqual(res["result"][0]["text"], "Results: 42 records")

    def test_execute_tool_denied(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "jsonrpc": "2.0",
                    "id": "call-2",
                    "error": {
                        "code": 40301,
                        "message": "Policy denied: destructive drop database forbidden",
                        "data": {"decision": "DENY", "reason": "destructive drop database forbidden"}
                    }
                }
            )
            res = self.client.execute_tool(
                tool="drop_database",
                arguments={"db": "prod"},
                agent_id="agent_py_01"
            )
            self.assertFalse(res["allowed"])
            self.assertEqual(res["decision"], "DENY")
            self.assertEqual(res["status"], "denied")
            self.assertIn("forbidden", res["error"])

    def test_execute_tool_approval_required(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "jsonrpc": "2.0",
                    "id": "call-3",
                    "error": {
                        "code": 20201,
                        "message": "Tool execution intercepted: pending human approval",
                        "data": {"decision": "REQUIRE_APPROVAL", "approval_request_id": "ticket_py_999"}
                    }
                }
            )
            res = self.client.execute_tool(
                tool="transfer_funds",
                arguments={"amount": 50000}
            )
            self.assertFalse(res["allowed"])
            self.assertEqual(res["decision"], "REQUIRE_APPROVAL")
            self.assertEqual(res["status"], "pending_approval")
            self.assertEqual(res["approval_request_id"], "ticket_py_999")

    def test_list_tools(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "jsonrpc": "2.0",
                    "id": "list-1",
                    "result": {
                        "tools": [{"name": "read_file", "description": "Read local file"}]
                    }
                }
            )
            res = self.client.list_tools(agent_id="agent_py_01")
            self.assertEqual(len(res["tools"]), 1)
            self.assertEqual(res["tools"][0]["name"], "read_file")

    def test_wrap_tool_local_allowed_and_denied(self):
        def fake_post(url, *args, **kwargs):
            body = kwargs.get("json", {})
            if body.get("resource") == "tool:dangerous_py_tool":
                return MagicMock(
                    status_code=200,
                    json=lambda: {
                        "allowed": False,
                        "decision": "DENY",
                        "code": "POLICY_DENIED",
                        "reason": "Forbidden in production"
                    }
                )
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "allowed": True,
                    "decision": "ALLOW",
                    "code": "PERMITTED"
                }
            )

        with patch.object(self.client.session, "post", side_effect=fake_post):
            executed = []
            def dangerous_handler(action):
                executed.append(action)
                return "done"

            wrapped_danger = self.client.wrap_tool("dangerous_py_tool", dangerous_handler)

            with self.assertRaises(PolicyDeniedError) as cm:
                wrapped_danger(action="delete_all")

            self.assertIn("Forbidden in production", str(cm.exception))
            self.assertEqual(len(executed), 0)  # Function was never called

            @self.client.wrap_tool("safe_py_tool")
            def safe_handler(query):
                return f"Found: {query}"

            output = safe_handler(query="sample")
            self.assertEqual(output, "Found: sample")


if __name__ == "__main__":
    unittest.main()
