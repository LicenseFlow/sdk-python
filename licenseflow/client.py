import requests
import uuid
import platform
import socket
from cachetools import TTLCache
from jose import jwt
from .exceptions import LicenseFlowError, NetworkError, RateLimitError, InvalidLicenseError

class LicenseFlowClient:
    def __init__(self, api_url, api_key, jwt_secret=None, cache_ttl=300, retries=3):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.jwt_secret = jwt_secret
        self.cache = TTLCache(maxsize=100, ttl=cache_ttl)
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        })
        
        # Configure simple retry adapter (can be expanded)
        adapter = requests.adapters.HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_hardware_id(self):
        """Generate a unique hardware ID for the current machine."""
        try:
            # Simple unique ID using platform and node (MAC address)
            return str(uuid.getnode())
        except Exception:
            return socket.gethostname()

    def activate(self, license_key, device_id=None, device_name=None, hardware_fingerprint=None, is_test=False):
        """Activate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id,
            "device_name": device_name or socket.gethostname(),
            "hardware_fingerprint": hardware_fingerprint,
            "is_test": is_test
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/activate-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def verify(self, license_key, device_id=None):
        """Verify the license status, using cache if available."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        cache_key = f"verify:{license_key}:{device_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        payload = {
            "license_key": license_key,
            "device_id": device_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/verify-license", json=payload)
            self._handle_response_errors(response)
            data = response.json()
            
            if data.get("valid"):
                self.cache[cache_key] = data
                
            return data
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def record_usage(self, license_key, metric_name, value, increment=False, is_test=False):
        """Record usage metrics for a license."""
        payload = {
            "license_key": license_key,
            "metric_name": metric_name,
            "value": value,
            "increment": increment,
            "is_test": is_test
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/record-usage", json=payload)
            self._handle_response_errors(response)
            return {"success": True, **response.json()}
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def deactivate(self, license_key, device_id=None):
        """Deactivate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/deactivate-license", json=payload)
            self._handle_response_errors(response)
            self.clear_cache()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def validate_proof_offline(self, proof, secret=None):
        """Validate a signed proof token offline."""
        key = secret or self.jwt_secret
        if not key:
            raise ValueError("JWT Secret is required for offline validation")
            
        try:
            payload = jwt.decode(proof, key, algorithms=['HS256'])
            return {
                "valid": True,
                "payload": payload
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e)
            }

    def _handle_response_errors(self, response):
        """Raise appropriate exceptions based on response status code."""
        if response.status_code == 200:
            return
            
        try:
            data = response.json()
            message = data.get("message") or data.get("error") or response.text
        except Exception:
            message = response.text
            
        if response.status_code == 429:
            raise RateLimitError(message)
        elif response.status_code in [400, 404]:
            raise InvalidLicenseError(message)
        elif response.status_code >= 500:
            raise NetworkError(message)
        else:
            raise LicenseFlowError(message, status=response.status_code)

    def clear_cache(self):
        """Clear the internal TTL cache."""
        self.cache.clear()
