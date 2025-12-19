# licenseflow-python

Official Python SDK for LicenseFlow.

## Installation

```bash
pip install licenseflow-python
```

## Quick Start

```python
from licenseflow import LicenseFlowClient, RateLimitError, InvalidLicenseError

client = LicenseFlowClient(
    api_url='https://your-project.supabase.co',
    api_key='your-api-key',
    jwt_secret='your-jwt-secret' # Required for offline validation
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

## License

MIT
