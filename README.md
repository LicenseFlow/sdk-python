# LicenseFlow Python SDK

[![PyPI version](https://img.shields.io/pypi/v/licenseflow-python)](https://pypi.org/project/licenseflow-python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://pypi.org/project/licenseflow-python/)

**Stop Building Licensing Infrastructure. Start Shipping Software.**

The official Python SDK for [LicenseFlow](https://licenseflow.dev). Activate, verify, and enforce software entitlements with multi-tier caching, offline grace periods, and zero-friction integration.

## Installation

```bash
pip install licenseflow-python
```

## Quick Start

```python
from licenseflow import LicenseFlowClient

client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',
    api_key='lf_live_xxxxxxxxxxxx',
    cache_ttl=300,          # Cache TTL in seconds (default: 5 min)
    offline_grace=259200    # Offline grace period in seconds (default: 72h)
)

# Activate a license on this device
activation = client.activate(
    license_key='XXXX-YYYY-ZZZZ-AAAA',
    device_name='Production Server'
)
print(f"Activated: {activation['success']}")

# Verify (served from cache when possible)
verification = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')
print(f"Valid: {verification['valid']}")
```

---

## Entitlement Caching

The SDK includes `EntitlementCache` — a multi-tier caching system that dramatically reduces API round-trips and ensures your application keeps running even when offline.

```python
from licenseflow import LicenseFlowClient, EntitlementCache

# Cache is built-in; configure via constructor
client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',
    api_key='lf_live_xxxxxxxxxxxx',
    cache_ttl=300,       # How long cached results are "fresh" (seconds)
    offline_grace=259200 # How long stale cache is used when API is down (seconds)
)

# First call: live API fetch, result cached
result = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')

# Subsequent calls: served from in-memory cache (no network)
result = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')

# During network outage: stale cache is used within grace window
# After grace period expires: OfflineLicenseError is raised
```

**Cache behaviour:**

| Scenario | Behaviour |
|---|---|
| Cache hit within TTL | Returns cached result immediately |
| Cache miss or TTL expired | Fetches from API, updates cache |
| API down, cache within grace | Returns stale result (offline grace) |
| API down, cache expired | Raises `OfflineLicenseError` |

---

## API Reference

### Core Methods

| Method | Description |
|---|---|
| `activate(license_key, device_name, environment_id=None)` | Activate a license on a device |
| `verify(license_key, environment_id=None)` | Verify license status (cached) |
| `deactivate(license_key, device_id=None)` | Deactivate a license from a device |
| `record_usage(license_key, metric_name, value, increment=True)` | Track usage metrics |
| `get_hardware_id()` | Get unique device identifier |

### Entitlements

```python
verification = client.verify(license_key='XXXX-YYYY-ZZZZ-AAAA')

# Feature flags
if client.has_feature(verification, 'ai_features'):
    enable_ai()

# Numeric limits
limit = client.get_entitlement(verification, 'api_rate_limit')
print(f"Rate limit: {limit.get('limit', 1000)} req/hr")
```

### Floating Licenses (Leases)

```python
# Checkout a temporary seat
lease = client.checkout_license(
    license_key='XXXX-XXXX',
    duration_seconds=3600,
    requester_id='ci-runner-1',
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
    print(f"Download URL: {download['url']}")
```

### Offline License Files

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
    NetworkError,
    OfflineLicenseError
)

try:
    client.activate(license_key='XXXX', device_name='Server')
except RateLimitError:
    print("Rate limit exceeded — retry later")
except InvalidLicenseError:
    print("License is invalid or expired")
except NetworkError:
    print("Network error — check connectivity")
except OfflineLicenseError:
    print("Offline grace period expired — reconnect to continue")
```

---

## Configuration Reference

```python
client = LicenseFlowClient(
    api_url='https://api.licenseflow.dev',  # LicenseFlow API endpoint
    api_key='lf_live_xxxxxxxxxxxx',          # API key from dashboard
    jwt_secret='your-jwt-secret',            # For offline license verification
    cache_ttl=300,                           # Cache TTL in seconds (default: 300)
    offline_grace=259200,                    # Offline grace in seconds (default: 72h)
    retries=3                                # Retry count for failed requests
)
```

---

## License

MIT

## Links

- 📖 [Documentation](https://docs.licenseflow.dev)
- 🐛 [Issues](https://github.com/LicenseFlow/sdk-python/issues)
- 🏠 [Homepage](https://licenseflow.dev)
