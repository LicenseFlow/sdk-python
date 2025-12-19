from setuptools import setup, find_packages

setup(
    name="licenseflow-python",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
        "cachetools>=5.0.0",
        "pycryptodome>=3.15.0",
        "python-jose[cryptography]>=3.3.0",
    ],
    author="LicenseFlow",
    description="Official Python SDK for LicenseFlow",
    python_requires=">=3.7",
)
