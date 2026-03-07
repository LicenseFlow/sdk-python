# LicenseFlow Python SDK

**Stop Building Licensing Infrastructure. Start Shipping Software.**

The official Python SDK for LicenseFlow. Protect your intellectual property, enforce entitlements, and manage software distribution with enterprise-grade security.

## Installation

```bash
pip install licenseflow-python
```

## Quick Start

```python
from licenseflow import LicenseFlowClient, RateLimitError, InvalidLicenseError

client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',
    api_key='lf_live_xxxxxxxxxxxx', # Generated from the SaaS platform
    jwt_secret='your-jwt-secret'    # Required for offline validation
)

try:
    # 1. Activate License
    activation = client.activate(
        license_key='XXXX-YYYY-ZZZZ-AAAA',
        device_name='My Computer'
    )
    print(f"Activated: {activation['success']}")

    # 2. Verify License (Uses internal TTL cache)
    verification = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')
    print(f"Valid: {verification['valid']}")

    # 3. Record Usage
    client.record_usage(
        license_key='XXXX-YYYY-ZZZZ-AAAA',
        metric_name='tokens_used',
        value=150,
        increment=True
    )

except RateLimitError:
    print("Slow down! Rate limit exceeded.")
except InvalidLicenseError:
    print("License is not valid or expired.")
except Exception as e:
    print(f"An error occurred: {e}")
```

## Features

- **Hardware Fingerprinting**: Automatic unique device ID generation.
- **In-memory Caching**: Fast verification with configurable TTL cache.
- **Fault Tolerance**: Automatic retries for network-level failures.
- **Offline Proofs**: Validate signed JWT proofs offline.


## Phase 5: Entitlements

Check feature access based on license tier:

```python
# Check boolean feature
if client.has_feature(verification, 'ai_features'):
    enable_ai()

# Check numeric limit
limit = client.get_entitlement(verification, 'api_rate_limit')
print(f"Your rate limit: {limit.get('limit', 1000)} requests/hour")
```

## Phase 5: Release Management

Check for updates and download new versions:

```python
# Check for updates
update = client.check_for_updates(
    current_version='v1.5.0',
    product_id='your-product-id',
    channel='stable' # or 'beta', 'alpha'
)

if update:
    print(f"New version available: {update['version']}")
    
    # Download with license
    download = client.download_artifact(
        license_key='XXXX-XXXX',
        release_id=update['id'],
        platform='win32', # or 'darwin', 'linux'
        architecture='x64'
    )
    
    print(f"Download URL: {download['url']}")
```

## Phase 5: Offline Licensing

Verify licenses without internet access using Ed25519 signatures:

```python
import json

# Load license file content
with open('license.lic', 'r') as f:
    lic_file_content = f.read()

public_key = 'YOUR_ORG_PUBLIC_KEY_HEX'

try:
    license_data = client.verify_offline_license(lic_file_content, public_key)
    
    print('Offline license valid!')
    print(f"Customer: {license_data.get('customer_name')}")
    print(f"Valid until: {license_data.get('valid_until')}")
    
except Exception as e:
    print(f"Invalid offline license: {e}")
```

## License

MIT
