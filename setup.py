from setuptools import setup, find_packages

setup(
    name="licenseflow-python",
    version="2.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
        "cachetools>=5.0.0",
        "pycryptodome>=3.15.0",
        "python-jose[cryptography]>=3.3.0",
    ],
    author="LicenseFlow",
    author_email="hello@licenseflow.dev",
    description="Official Python SDK for LicenseFlow — Licensing, activation, entitlements, floating licenses, and distribution.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://licenseflow.dev",
    project_urls={
        "Documentation": "https://docs.licenseflow.dev",
        "Source": "https://github.com/licenseflow/python-sdk",
        "Issues": "https://github.com/licenseflow/python-sdk/issues",
    },
    python_requires=">=3.8",
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries",
    ],
)
