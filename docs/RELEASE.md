# Release Guide for Transcript Recorder

This document explains how to manage versions and create releases for Transcript Recorder.

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/) (SemVer): `MAJOR.MINOR.PATCH`

### When to Bump Each Version

| Version | When to Use | Example Changes |
|---------|-------------|-----------------|
| **PATCH** | Bug fixes, minor tweaks that don't add features | Fix a crash, correct a typo, improve performance |
| **MINOR** | New features that are backward compatible | Add a new menu option, new export format, UI improvements |
| **MAJOR** | Breaking changes or major overhauls | Complete UI redesign, change config file format, remove deprecated features |

### Examples

**Patch Release (1.0.0 → 1.0.1)**
- Fixed crash when clicking "Capture Now" without a recording session
- Fixed dark mode text color in meeting notes
- Improved transcript merge accuracy

**Minor Release (1.0.0 → 1.1.0)**
- Added "Check for Updates" feature
- Added version display in status bar
- New keyboard shortcuts for common actions
- Added support for Google Meet

**Major Release (1.0.0 → 2.0.0)**
- Complete redesign of the user interface
- Changed configuration file format (existing configs need migration)
- Dropped support for macOS 11 and earlier
- New plugin architecture for meeting apps

## Version Management

The version is defined in a single file: `version.py`

### Bump Version Script

Use the `bump_version.py` script to update the version:

```bash
# Show current version
python bump_version.py

# Bump patch version (1.0.0 → 1.0.1)
python bump_version.py patch

# Bump minor version (1.0.0 → 1.1.0)
python bump_version.py minor

# Bump major version (1.0.0 → 2.0.0)
python bump_version.py major

# Set a specific version
python bump_version.py set 2.0.0
```
