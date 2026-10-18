import pytest
import responses
import json
from licenseflow import (
    LicenseFlowClient,
    RateLimitError,
    InvalidLicenseError,
    ApprovalRequiredError,
    PolicyDeniedError,
)

@pytest.fixture
def client():
    return LicenseFlowClient(
        api_url="https://api.test",
        api_key="test-key",
        jwt_secret="test-secret",
        retries=0
    )

@responses.activate
def test_activate(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/activate-license",
        json={"success": True, "message": "Activated", "proof": "dummy-jwt"},
        status=200
    )
    
    res = client.activate(license_key="TEST-KEY")
    assert res["success"] is True
    assert res["proof"] == "dummy-jwt"

@responses.activate
def test_verify_with_cache(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/verify-license",
        json={"valid": True, "status": "active"},
        status=200
    )
    
    # First call - hits server
    res1 = client.verify(license_key="TEST-KEY")
    assert res1["valid"] is True
    assert len(responses.calls) == 1
    
    # Second call - hits cache
    res2 = client.verify(license_key="TEST-KEY")
    assert res2["valid"] is True
    assert len(responses.calls) == 1

@responses.activate
def test_rate_limit_error(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/verify-license",
        json={"message": "Too many requests"},
        status=429
    )
    
    with pytest.raises(RateLimitError):
        client.verify(license_key="TEST-KEY")

@responses.activate
def test_invalid_license_error(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/verify-license",
        json={"message": "Invalid license"},
        status=400
    )
    
    with pytest.raises(InvalidLicenseError):
        client.verify(license_key="TEST-KEY")

@responses.activate
def test_deactivate(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/deactivate-license",
        json={"success": True},
        status=200
    )
    
    res = client.deactivate(license_key="TEST-KEY")
    assert res["success"] is True

@responses.activate
def test_execute_tool_allowed(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/mcp-gateway",
        json={
            "jsonrpc": "2.0",
            "id": "call-1",
            "result": {
                "content": [{"type": "text", "text": "Results: 42 records"}],
                "isError": False
            }
        },
        status=200
    )

    res = client.execute_tool(
        tool="search_vectors",
        arguments={"query": "test query"},
        agent_id="agent_py_01"
    )

    assert res["allowed"] is True
    assert res["status"] == "executed"
    assert res["result"][0]["text"] == "Results: 42 records"

@responses.activate
def test_execute_tool_denied(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/mcp-gateway",
        json={
            "jsonrpc": "2.0",
            "id": "call-2",
            "error": {
                "code": 40301,
                "message": "Policy denied: destructive drop database forbidden",
                "data": {"decision": "DENY", "reason": "destructive drop database forbidden"}
            }
        },
        status=200
    )

    res = client.execute_tool(
        tool="drop_database",
        arguments={"db": "prod"},
        agent_id="agent_py_01"
    )

    assert res["allowed"] is False
    assert res["decision"] == "DENY"
    assert res["status"] == "denied"
    assert "forbidden" in res["error"]

@responses.activate
def test_execute_tool_approval_required(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/mcp-gateway",
        json={
            "jsonrpc": "2.0",
            "id": "call-3",
            "error": {
                "code": 20201,
                "message": "Tool execution intercepted: pending human approval",
                "data": {"decision": "REQUIRE_APPROVAL", "approval_request_id": "ticket_py_999"}
            }
        },
        status=200
    )

    res = client.execute_tool(
        tool="transfer_funds",
        arguments={"amount": 50000}
    )

    assert res["allowed"] is False
    assert res["decision"] == "REQUIRE_APPROVAL"
    assert res["status"] == "pending_approval"
    assert res["approval_request_id"] == "ticket_py_999"

@responses.activate
def test_list_tools(client):
    responses.add(
        responses.POST,
        "https://api.test/functions/v1/mcp-gateway",
        json={
            "jsonrpc": "2.0",
            "id": "list-1",
            "result": {
                "tools": [{"name": "read_file", "description": "Read local file"}]
            }
        },
        status=200
    )

    res = client.list_tools(agent_id="agent_py_01")
    assert len(res["tools"]) == 1
    assert res["tools"][0]["name"] == "read_file"

@responses.activate
def test_wrap_tool_local_allowed_and_denied(client):
    def auth_callback(request):
        body = json.loads(request.body)
        if body.get("resource") == "tool:dangerous_py_tool":
            return (200, {}, json.dumps({
                "allowed": False,
                "decision": "DENY",
                "code": "POLICY_DENIED",
                "reason": "Forbidden in production"
            }))
        return (200, {}, json.dumps({
            "allowed": True,
            "decision": "ALLOW",
            "code": "PERMITTED"
        }))

    responses.add_callback(
        responses.POST,
        "https://api.test/functions/v1/authorize",
        callback=auth_callback
    )

    # Wrap dangerous tool
    executed = []
    def dangerous_handler(action):
        executed.append(action)
        return "done"

    wrapped_danger = client.wrap_tool("dangerous_py_tool", dangerous_handler)

    with pytest.raises(PolicyDeniedError) as exc_info:
        wrapped_danger(action="delete_all")

    assert "Forbidden in production" in str(exc_info.value)
    assert len(executed) == 0  # CRITICAL: Function was never called!

    # Wrap safe tool using decorator syntax
    @client.wrap_tool("safe_py_tool")
    def safe_handler(query):
        return f"Found: {query}"

    output = safe_handler(query="sample")
    assert output == "Found: sample"

