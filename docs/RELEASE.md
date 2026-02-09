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

## Release Workflow

### Quick Release (Recommended)

```bash
# 1. Make sure all changes are committed
git status

# 2. Bump the version
python bump_version.py patch   # or minor/major

# 3. Commit the version bump
git add version.py
git commit -m "Bump version to $(python -c 'from version import __version__; print(__version__)')"

# 4. Create a version tag
git tag -a "v$(python -c 'from version import __version__; print(__version__)')" -m "Release v$(python -c 'from version import __version__; print(__version__)')"

# 5. Push changes and tag
git push origin main
git push origin --tags
```

### What Happens After Pushing a Tag

When you push a tag starting with `v` (e.g., `v1.0.1`), GitHub Actions will automatically:

1. Build the macOS application using py2app
2. Code-sign the `.app` bundle with your Developer ID certificate
3. Create and sign a DMG installer
4. Notarize the DMG with Apple's notary service and staple the ticket
5. Create a GitHub Release with the signed, notarized DMG attached
6. Generate release notes from commit messages

> See [docs/CODE_SIGNING.md](CODE_SIGNING.md) for full details on the signing and notarization process.

### Manual Build (Without GitHub Actions)

If you need to build locally:

```bash
# Clean previous builds
python setup_py2app.py clean

# Build the application
python setup_py2app.py py2app

# The app will be in dist/Transcript Recorder.app
```

## Configuring Update Checker

For the "Check for Updates" feature to work, update `version.py` with your GitHub repository information:

```python
GITHUB_OWNER = "your-github-username"
GITHUB_REPO = "your-repository-name"
```

## Pre-Release Checklist

Before creating a release, ensure:

- [ ] All new features are tested
- [ ] No linting errors (`python -m py_compile gui_app.py`)
- [ ] App builds successfully (`python setup_py2app.py py2app`)
- [ ] Built app launches and functions correctly
- [ ] Version number in `version.py` is updated
- [ ] GITHUB_OWNER and GITHUB_REPO are set correctly (for update checking)

## Hotfix Process

For urgent bug fixes on a released version:

```bash
# 1. Create a hotfix from the release tag
git checkout -b hotfix/fix-description v1.0.0

# 2. Make your fix and commit
git add .
git commit -m "Fix: description of the fix"

# 3. Bump patch version
python bump_version.py patch

# 4. Commit version bump
git add version.py
git commit -m "Bump version to 1.0.1"

# 5. Merge to main
git checkout main
git merge hotfix/fix-description

# 6. Tag and push
git tag -a "v1.0.1" -m "Hotfix release v1.0.1"
git push origin main --tags

# 7. Clean up
git branch -d hotfix/fix-description
```

## Files Involved in Versioning

| File | Purpose |
|------|---------|
| `version.py` | Single source of truth for version number |
| `bump_version.py` | Script to update version number |
| `gui_app.py` | Imports version for display and update checking |
| `setup_py2app.py` | Imports version for app bundle metadata |
| `.github/workflows/build-release.yml` | Automated build and release workflow |
