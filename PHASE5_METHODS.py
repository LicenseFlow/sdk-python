# Phase 5 SDK Methods - Python Implementation

"""
Add these methods to the LicenseFlowClient class in licenseflow/client.py
"""

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.backends import default_backend
import base64
import json
from datetime import datetime

class LicenseFlowClient:
    # ... existing methods ...
    
    def has_feature(self, verification: dict, feature_code: str) -> bool:
        """
        Phase 5: Check if license has a feature enabled
        
        Args:
            verification: Response from verify() method
            feature_code: Feature code to check (e.g., 'ai_features')
            
        Returns:
            True if feature is enabled
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return False
        
        ent = verification['entitlements'].get(feature_code)
        if not ent:
            return False
        
        # Handle different value formats
        if isinstance(ent, bool):
            return ent
        if isinstance(ent, dict):
            return ent.get('enabled') is True or ent.get('value') is True
        return ent is True
    
    def get_entitlement(self, verification: dict, feature_code: str):
        """
        Phase 5: Get entitlement value
        
        Args:
            verification: Response from verify() method
            feature_code: Feature code to retrieve
            
        Returns:
            Entitlement value or None
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return None
        return verification['entitlements'].get(feature_code)
    
    def check_for_updates(
        self, 
        current_version: str, 
        product_id: str, 
        channel: str = 'stable'
    ) -> dict | None:
        """
        Phase 5: Check for software updates
        
        Args:
            current_version: Current version string (e.g., 'v1.0.0')
            product_id: Product UUID
            channel: Release channel ('stable', 'beta', 'alpha', 'nightly')
            
        Returns:
            Update info dict if newer version available, None otherwise
        """
        response = self._session.get(
            f'{self.base_url}/functions/v1/release-management/latest',
            params={
                'product_id': product_id,
                'channel': channel
            }
        )
        response.raise_for_status()
        data = response.json()
        
        if not data or data.get('version') == current_version:
            return None
        
        return {
            'id': data['id'],
            'version': data['version'],
            'changelog': data.get('changelog'),
            'published_at': data['published_at']
        }
    
    def download_artifact(
        self,
        license_key: str,
        release_id: str = None,
        artifact_id: str = None,
        platform: str = None,
        architecture: str = None
    ) -> dict:
        """
        Phase 5: Download artifact with license verification
        
        Args:
            license_key: License key for authorization
            release_id: Release UUID (optional if artifact_id provided)
            artifact_id: Artifact UUID (optional if release_id provided)
            platform: Platform name (e.g., 'windows', 'macos', 'linux')
            architecture: Architecture (e.g., 'x64', 'arm64')
            
        Returns:
            Dict with download URL and metadata
        """
        payload = {
            'license_key': license_key,
            'release_id': release_id,
            'artifact_id': artifact_id,
            'platform': platform,
            'architecture': architecture
        }
        
        response = self._session.post(
            f'{self.base_url}/functions/v1/artifact-download',
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def verify_offline_license(self, license_file: str, public_key: str) -> dict:
        """
        Phase 5: Verify offline license signature
        
        Args:
            license_file: JSON string of .lic file contents
            public_key: Organization's Ed25519 public key (hex string)
            
        Returns:
            Verified license data dict
            
        Raises:
            ValueError: If signature is invalid or license is expired
        """
        try:
            data = json.loads(license_file)
            
            if 'license' not in data or 'signature' not in data:
                raise ValueError('Invalid offline license format')
            
            # Prepare message and signature
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
            valid_until = datetime.fromisoformat(valid_until_str.replace('Z', '+00:00'))
            
            if valid_until < datetime.now(valid_until.tzinfo):
                raise ValueError('Offline license has expired')
            
            return data['license']
            
        except json.JSONDecodeError:
            raise ValueError('Invalid JSON format in license file')
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f'Failed to verify offline license: {str(e)}')


# Dependencies to add to requirements.txt:
# cryptography>=41.0.0
