# Changelog

All notable changes to the LicenseFlow Python SDK will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-10-13

### Changed
- Core calls (verify, activate, deactivate, checkout, lease status, offline, usage, entitlements, authorize) use the new canonical API addresses on api.licenseflow.dev, e.g. `/v1/licenses/verify`.
- If the gateway does not recognise a new address it falls back once to the legacy path. Self-hosted and direct backend URLs keep using legacy paths.
- Legacy paths remain supported indefinitely; no code changes are required.

## [2.1.0] - 2026-04-06

### Added - Phase 5 Enterprise Finalization
- **Entitlements**: `has_feature()` and `get_entitlement()` methods.
- **Release Management**: `check_for_updates()` and `download_artifact()`.
- **Usage Credits**: `consume_credits()` and `get_credits_balance()`.
- **Offline Licensing**: `verify_offline_license()` with Ed25519 support.

## [2.0.0] - 2025-01-20

### Added - Phase 5 Enterprise Features
- Initial support for Phase 5 enterprise endpoints.
- JWT-based offline proof validation.

## [1.0.0] - 2024-12-05

### Added
- Initial release with core license activation and verification.
- Local hardware fingerprinting for Windows, macOS, and Linux.
- Automatic caching.
