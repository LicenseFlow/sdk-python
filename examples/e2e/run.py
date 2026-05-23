import os, sys
from licenseflow import LicenseFlowClient

for k in ("LICENSEFLOW_API_URL", "LICENSEFLOW_API_KEY", "LICENSE_KEY", "REVOKED_LICENSE_KEY"):
    if not os.environ.get(k):
        print(f"Missing env: {k}", file=sys.stderr); sys.exit(2)

c = LicenseFlowClient(base_url=os.environ["LICENSEFLOW_API_URL"], api_key=os.environ["LICENSEFLOW_API_KEY"])
lk = os.environ["LICENSE_KEY"]
rk = os.environ["REVOKED_LICENSE_KEY"]

act = c.activate(license_key=lk, device_name="ci-py")
assert act, "activation failed"
assert c.verify(license_key=lk).valid is True, "active must verify"
assert c.verify(license_key=rk).valid is False, "revoked must not verify"
c.deactivate(license_key=lk)
print("Python SDK E2E ✓")