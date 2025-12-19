from licenseflow import LicenseFlowClient

def main():
    client = LicenseFlowClient(
        api_url='https://api.test',
        api_key='test-api-key'
    )

    print('--- LicenseFlow Python Example ---')

    # 1. Activate
    print('Activating license...')
    activation = client.activate(
        license_key='DEMO-KEY',
        device_name='Python-Bot'
    )
    print(f"Result: {activation}")

    # 2. Verify
    print('Verifying license...')
    verify = client.verify(license_key='DEMO-KEY')
    print(f"Is Valid: {verify['valid']}")

    # 3. Deactivate
    print('Deactivating license...')
    deactivation = client.deactivate(license_key='DEMO-KEY')
    print(f"Result: {deactivation}")

if __name__ == '__main__':
    main()
