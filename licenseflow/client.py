import requests
import uuid
import platform
import socket
from cachetools import TTLCache
from jose import jwt
from .exceptions import LicenseFlowError, NetworkError, RateLimitError, InvalidLicenseError
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import json
from datetime import datetime

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

    def activate(self, license_key, device_id=None, device_name=None, hardware_fingerprint=None, is_test=False, environment_id=None):
        """Activate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id,
            "device_name": device_name or socket.gethostname(),
            "hardware_fingerprint": hardware_fingerprint,
            "is_test": is_test,
            "environment_id": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/activate-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def verify(self, license_key, device_id=None, environment_id=None):
        """Verify the license status, using cache if available."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        cache_key = f"verify:{license_key}:{device_id}:{environment_id or 'default'}"
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        payload = {
            "licenseKey": license_key,
            "deviceId": device_id,
            "environmentId": environment_id
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

    def record_usage(self, license_key, metric_name, value, increment=False, is_test=False, environment_id=None):
        """Record usage metrics for a license."""
        payload = {
            "license_key": license_key,
            "metric_name": metric_name,
            "value": value,
            "increment": increment,
            "is_test": is_test,
            "environment_id": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/record-usage", json=payload)
            self._handle_response_errors(response)
            return {"success": True, **response.json()}
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def deactivate(self, license_key, device_id=None, environment_id=None):
        """Deactivate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id,
            "environment_id": environment_id
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
            
        # Clear cache on any error to be safe
        self.cache.clear()
            
        message = None
        try:
            data = response.json()
            if isinstance(data, dict):
                message = data.get("message") or data.get("error") or data.get("msg")
        except Exception:
            pass
            
        if not message:
            message = response.text or f"HTTP {response.status_code}"
            
        if response.status_code == 429:
            raise RateLimitError(message)
        elif response.status_code in [400, 404]:
            raise InvalidLicenseError(message)
        elif response.status_code >= 500:
            raise NetworkError(message)
        else:
            raise LicenseFlowError(message, status=response.status_code)

    def has_feature(self, verification, feature_code):
        """
        Phase 5: Check if license has a feature enabled
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return False
        
        ent = verification['entitlements'].get(feature_code)
        if ent is None:
            return False
        
        # Handle different value formats
        if isinstance(ent, bool):
            return ent
        if isinstance(ent, dict):
            return ent.get('enabled') is True or ent.get('value') is True
        return ent is True

    def get_entitlement(self, verification, feature_code):
        """
        Phase 5: Get entitlement value
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return None
        return verification['entitlements'].get(feature_code)

    def check_for_updates(self, current_version, product_id, channel='stable'):
        """
        Phase 5: Check for software updates
        """
        response = self.session.get(
            f'{self.api_url}/functions/v1/release-management/latest',
            params={
                'product_id': product_id,
                'channel': channel
            }
        )
        self._handle_response_errors(response)
        
        # requests.Response.json() might raise if empty, check status first
        # _handle_response_errors checks status, but 404 might raise InvalidLicenseError which we might catch
        # Actually 404 means no update usually? No, endpoint returns 200 with data or null.
        # If product not found, it might 404.
        
        try:
            data = response.json()
        except ValueError:
            return None

        if not data or data.get('version') == current_version:
            return None
        
        return {
            'id': data['id'],
            'version': data['version'],
            'changelog': data.get('changelog'),
            'published_at': data['published_at']
        }

    def download_artifact(self, license_key, release_id=None, artifact_id=None, platform=None, architecture=None):
        """
        Phase 5: Download artifact with license verification
        """
        payload = {
            'license_key': license_key,
            'release_id': release_id,
            'artifact_id': artifact_id,
            'platform': platform,
            'architecture': architecture
        }
        
        try:
            response = self.session.post(
                f'{self.api_url}/functions/v1/artifact-download',
                json=payload
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def verify_offline_license(self, license_file, public_key):
        """
        Phase 5: Verify offline license signature
        """
        try:
            data = json.loads(license_file)
            
            if 'license' not in data or 'signature' not in data:
                raise ValueError('Invalid offline license format')
            
            # Prepare message and signature
            # Use separators to match JS JSON.stringify behavior if needed, usually default is slightly different in Python (spaces)
            # Standard: separators=(',', ':') removes spaces
            message = json.dumps(data['license'], separators=(',', ':')).encode()
            signature = base64.b64decode(data['signature'])
            pub_key_bytes = bytes.fromhex(public_key)
            
            # Verify Ed25519 signature
            public_key_obj = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
            
            try:
                public_key_obj.verify(signature, message)
            except Exception:
                raise ValueError('Invalid offline license signature')
            
            # Check expiration
            valid_until_str = data['license']['valid_until']
            # Simple ISO parsing (python 3.7+ supports fromisoformat, prior needs dateutil)
            # Removing Z for compatibility if needed, but 3.11 supports Z
            if valid_until_str.endswith('Z'):
                valid_until_str = valid_until_str[:-1] + '+00:00'
                
            valid_until = datetime.fromisoformat(valid_until_str)
            
            if valid_until < datetime.now(valid_until.tzinfo):
                raise ValueError('Offline license has expired')
            
            return data['license']
            
        except json.JSONDecodeError:
            raise ValueError('Invalid JSON format in license file')
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f'Failed to verify offline license: {str(e)}')
