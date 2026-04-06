# LicenseFlow Python SDK

[![PyPI version](https://img.shields.io/pypi/v/licenseflow-python)](https://pypi.org/project/licenseflow-python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Stop Building Licensing Infrastructure. Start Shipping Software.**

The official Python SDK for [LicenseFlow](https://licenseflow.dev). Protect your intellectual property, enforce entitlements, and manage software distribution with enterprise-grade security.

## Installation

```bash
pip install licenseflow-python
```

## Quick Start

```python
from licenseflow import LicenseFlowClient, RateLimitError, InvalidLicenseError

client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',
    api_key='lf_live_xxxxxxxxxxxx',
    jwt_secret='your-jwt-secret'
)

# Activate
activation = client.activate(
    license_key='XXXX-YYYY-ZZZZ-AAAA',
    device_name='My Computer'
)
print(f"Activated: {activation['success']}")

# Verify (uses internal TTL cache)
verification = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')
print(f"Valid: {verification['valid']}")
```

---

## API Reference

### Core Methods

| Method | Description |
|--------|-------------|
| `activate(license_key, device_name, environment_id=None)` | Activate a license on a device |
| `verify(license_key, environment_id=None)` | Verify license status (cached) |
| `deactivate(license_key, device_id=None)` | Deactivate a license from a device |
| `record_usage(license_key, metric_name, value, increment=True)` | Track usage metrics |
| `get_hardware_id()` | Get unique device identifier |

### Entitlements

```python
if client.has_feature(verification, 'ai_features'):
    enable_ai()

limit = client.get_entitlement(verification, 'api_rate_limit')
print(f"Rate limit: {limit.get('limit', 1000)} req/hr")
```

### Floating Licenses (Leases)

```python
# Checkout a temporary seat
lease = client.checkout_license(
    license_key='XXXX-XXXX',
    duration_seconds=3600,
    requester_id=f"ci-{os.environ['CI_JOB_ID']}",
    requester_type='ci_runner'
)
print(f"Lease: {lease['lease_key']}, expires: {lease['expires_at']}")

# Release early
client.checkin_license(lease['lease_key'])

# Check status
status = client.get_lease_status(lease['lease_key'])
```

### Credits

```python
# Consume credits
result = client.consume_credits(amount=100, description='AI tokens')
print(f"Remaining: {result['remaining']}")

# Check balance
balance = client.get_credits_balance()
print(f"Credits: {balance['balance']}")
```

### Release Management

```python
update = client.check_for_updates(
    product_id='prod_123',
    current_version='v1.5.0',
    channel='stable'
)

if update:
    download = client.download_artifact(
        license_key='XXXX-XXXX',
        release_id=update['id'],
        platform='linux',
        architecture='x64'
    )
    print(f"Download: {download['url']}")
```

### Offline Licensing

```python
with open('license.lic', 'r') as f:
    lic_content = f.read()

license_data = client.verify_offline_license(lic_content, 'ORG_PUBLIC_KEY_HEX')
print(f"Valid until: {license_data['valid_until']}")
```

### Heartbeat

```python
client.start_heartbeat('XXXX-XXXX', interval_seconds=60)
# ... later
client.stop_heartbeat()
```

---

## Error Handling

```python
from licenseflow import (
    LicenseFlowError,
    RateLimitError,
    InvalidLicenseError,
    NetworkError
)

try:
    client.activate(license_key='XXXX', device_name='Server')
except RateLimitError:
    print("Rate limit exceeded, retry later")
except InvalidLicenseError:
    print("License is invalid or expired")
except NetworkError:
    print("Network error — check connectivity")
```

## Configuration

```python
client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',
    api_key='lf_live_xxxxxxxxxxxx',
    jwt_secret='your-jwt-secret',
    cache_ttl=300,    # Cache duration in seconds (default 5 min)
    retries=3         # Retry count for failed requests
)
```

## License

MIT

## Links

- 📖 [Documentation](https://docs.licenseflow.dev)
- 🐛 [Issues](https://github.com/licenseflow/python-sdk/issues)
- 🏠 [Homepage](https://licenseflow.dev)
