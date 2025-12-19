import pytest
import responses
import json
from licenseflow import LicenseFlowClient, RateLimitError, InvalidLicenseError

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
