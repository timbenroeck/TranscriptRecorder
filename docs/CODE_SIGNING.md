# Code Signing & Notarization Guide

This document covers how Transcript Recorder is signed and notarized for macOS distribution. It applies to both local development builds and automated GitHub Actions releases.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Concepts](#concepts)
4. [Project Files](#project-files)
5. [Local Signing (Development)](#local-signing-development)
6. [Local Release Build (Sign + Notarize)](#local-release-build-sign--notarize)
7. [GitHub Actions (Automated Releases)](#github-actions-automated-releases)
8. [Setting Up GitHub Secrets](#setting-up-github-secrets)
9. [Verification Commands](#verification-commands)
10. [Troubleshooting](#troubleshooting)
11. [Entitlements Reference](#entitlements-reference)

---

## Overview

### Why Sign & Notarize?

| | Unsigned | Signed | Signed + Notarized |
|---|---|---|---|
| Gatekeeper | Blocks the app; user must manually allow via System Settings | Opens with a warning on first launch | Opens cleanly with no warning |
| Accessibility permissions | Reset on every rebuild (different code identity each time) | **Persist across rebuilds** (stable identity) | Persist across rebuilds |
| Distribution to others | Requires manual workaround steps | Users see a warning dialog | Clean install experience |

- **Code Signing** gives the app a stable identity so macOS recognizes it across rebuilds.
- **Notarization** is an Apple service that scans the signed app and issues a trust ticket. Only needed when distributing to other people.

### When to Use Each

| Scenario | Sign | Notarize |
|---|---|---|
| Day-to-day local development | Yes | No |
| Testing before a release | Yes | Optional |
| Distributing via GitHub Releases | Yes | Yes |

---

## Prerequisites

- **Apple Developer Program** membership ([developer.apple.com/programs](https://developer.apple.com/programs/))
- **Xcode Command Line Tools** installed (`xcode-select --install`)
- **Developer ID Application** certificate installed in your Keychain
- **Notarization credentials** stored in Keychain (for notarization only)

### One-Time Certificate Setup

1. Open **Xcode > Settings > Accounts** and sign in with your Apple ID
2. Select your team and click **Manage Certificates...**
3. Click **+** and create a **Developer ID Application** certificate
4. Verify it's installed:

```bash
security find-identity -v -p codesigning
```

You should see a line like:

```
XXXXXXXX... "Developer ID Application: Your Name (TEAMID)"
```

### One-Time Notarization Credentials Setup

Store your credentials in the macOS Keychain so scripts can authenticate without passwords in plaintext:

```bash
xcrun notarytool store-credentials "TranscriptRecorder" \
  --apple-id "YOUR_APPLE_ID_EMAIL" \
  --team-id "YOUR_TEAM_ID" \
  --password "YOUR_APP_SPECIFIC_PASSWORD"
```

- **Apple ID**: Your Apple ID email address.
- **Team ID**: Found at [Apple Developer > Membership](https://developer.apple.com/account#MembershipDetailsCard).
- **App-Specific Password**: Generated at [appleid.apple.com](https://appleid.apple.com/) > Sign-In and Security > App-Specific Passwords. This is NOT your Apple ID password.

The profile name `"TranscriptRecorder"` is referenced by the notarization scripts.

---

## Concepts

### Signing Order

macOS code signing requires a **bottom-up** approach. Inner components must be signed before the outer bundle:

1. `.so` files (Python extensions)
2. `.dylib` files (dynamic libraries)
3. Embedded frameworks (`Contents/Frameworks/*.framework`)
4. Main executable (`Contents/MacOS/gui_app`)
5. The `.app` bundle itself

The `sign_app.sh` script handles this automatically.

### Hardened Runtime

Notarization requires the **hardened runtime** (`--options runtime`), which restricts what the app can do at runtime. Since Transcript Recorder is a Python app bundled with py2app, certain entitlements are needed to allow the bundled Python runtime and extensions to function. These are declared in `entitlements.plist`.

### SourceBuild vs. Release

| | SourceBuild | Release |
|---|---|---|
| App name | `Transcript Recorder SourceBuild` | `Transcript Recorder` |
| Bundle ID | `com.transcriptrecorder.sourcebuild` | `com.transcriptrecorder.app` |
| Built by | `build_local.sh` / `full_rebuild_local.sh` | `build_release_local.sh` / GitHub Actions |
| Purpose | Local development & testing | Distribution to users |

The separate bundle IDs prevent accessibility permission conflicts between your local dev copy and the installed release version.

---

## Project Files

### Files That Get Committed

| File | Purpose |
|---|---|
| `entitlements.plist` | Runtime entitlements required for py2app builds (see [reference](#entitlements-reference)) |
| `scripts/sign_app.sh` | Signs a `.app` bundle (bottom-up, hardened runtime) |
| `scripts/notarize_app.sh` | Submits a signed `.app` or `.dmg` to Apple for notarization |
| `scripts/build_release_local.sh` | Full local release pipeline: build > sign > DMG > sign DMG > notarize |
| `scripts/build_local.sh` | Development build with optional signing (no notarization) |
| `scripts/full_rebuild_local.sh` | Clean development build with optional signing (no notarization) |
| `.github/workflows/build-release.yml` | Automated CI pipeline: build > sign > DMG > sign DMG > notarize > release |

### Files That Must NOT Be Committed

These are covered by `.gitignore`:

| Pattern | What It Protects |
|---|---|
| `*.p12` | Exported certificates with private keys |
| `*.cer` | Certificate files |
| `*.certSigningRequest` | Certificate signing requests |
| `certificate_base64.txt` | Base64-encoded certificate for CI setup |
| `build.keychain` / `build.keychain-db` | Temporary keychains |
| `temp/` | Temporary working files |

---

## Local Signing (Development)

This is the day-to-day workflow. Signing alone fixes the accessibility permission problem and takes about 30 seconds.

### Using the Build Script

```bash
scripts/build_local.sh
```

When it finishes building, it will prompt:

```
Would you like to code sign the app? (y/n):
```

Say **y**. The first time, macOS will pop up a Keychain dialog asking for your **Mac login password** to authorize `codesign` to use your certificate's private key. Click **Always Allow** so it doesn't ask again.

### Signing an Existing Build

If you already have a built `.app` and just want to sign it:

```bash
scripts/sign_app.sh "dist/Transcript Recorder SourceBuild.app"
```

The script defaults to the SourceBuild app path and your Developer ID identity. You can override both:

```bash
scripts/sign_app.sh "dist/Some Other.app" "Developer ID Application: Other Name (TEAMID)"
```

---

## Local Release Build (Sign + Notarize)

Use this to validate the full release pipeline locally before pushing a tag.

```bash
scripts/build_release_local.sh
```

This mirrors exactly what GitHub Actions does:

1. **Clean** build artifacts
2. **Build** as "Transcript Recorder" (release variant, not SourceBuild)
3. **Sign** the `.app` bundle
4. **Create DMG** with Applications symlink
5. **Sign** the DMG
6. **Prompt** to notarize (optional)

If you choose to notarize, the script calls `notarize_app.sh`, which:
- Submits the DMG to Apple's notary service
- Waits for Apple to scan and approve it (typically 2-10 minutes)
- Staples the notarization ticket to the DMG
- Verifies everything

### Notarizing Separately

You can also notarize any signed artifact on its own:

```bash
# Notarize a .app
scripts/notarize_app.sh "dist/Transcript Recorder SourceBuild.app"

# Notarize a .dmg
scripts/notarize_app.sh "dist/TranscriptRecorder-1.2.3.dmg"
```

If submitting a `.app`, the script automatically creates a temporary zip (required by `notarytool`), submits it, and cleans up.

---

## GitHub Actions (Automated Releases)

The `.github/workflows/build-release.yml` workflow runs automatically when you push a version tag (`v*`).

### What the Workflow Does

1. **Checkout** and **install dependencies**
2. **Import certificate** from GitHub Secrets into a temporary keychain
3. **Build** the app with py2app
4. **Sign** the `.app` bundle (all inner components, then the bundle)
5. **Create** and **sign** the DMG
6. **Notarize** the DMG via Apple's notary service and staple the ticket
7. **Clean up** the temporary keychain (runs even if the build fails)
8. **Upload** the DMG as a build artifact
9. **Create a GitHub Release** with the DMG attached (tag pushes only)

### The Release Flow

```bash
# 1. Bump version
python bump_version.py patch   # or minor/major

# 2. Commit
git add version.py
git commit -m "Bump version to $(python -c 'from version import __version__; print(__version__)')"

# 3. Tag
git tag -a "v$(python -c 'from version import __version__; print(__version__)')" \
  -m "Release v$(python -c 'from version import __version__; print(__version__)')"

# 4. Push — GitHub Actions handles the rest
git push origin main --tags
```

---

## Setting Up GitHub Secrets

The workflow requires 6 repository secrets. Go to **Settings > Secrets and variables > Actions** in your GitHub repository to add them.

| Secret | Description | How to Get It |
|---|---|---|
| `MACOS_CERTIFICATE` | Base64-encoded `.p12` export of your Developer ID Application certificate | Export from Keychain Access (see below) |
| `MACOS_CERTIFICATE_PWD` | Password set when exporting the `.p12` file | You choose this during export |
| `KEYCHAIN_PWD` | Random password for the temporary CI keychain | Generate with `openssl rand -base64 24` |
| `APPLE_ID` | Your Apple ID email | Your Apple Developer account email |
| `APPLE_ID_PASSWORD` | App-specific password for notarization | Generate at [appleid.apple.com](https://appleid.apple.com/) > App-Specific Passwords |
| `APPLE_TEAM_ID` | Your 10-character Team ID | [Developer Portal > Membership](https://developer.apple.com/account#MembershipDetailsCard) |

### Exporting the Certificate

1. Open **Keychain Access**
2. Go to **My Certificates** in the **login** keychain
3. Find your **Developer ID Application** certificate
4. Expand it to verify the private key is attached (disclosure triangle)
5. Right-click the certificate > **Export...** > format **Personal Information Exchange (.p12)**
6. Set a password (this becomes `MACOS_CERTIFICATE_PWD`)
7. Save, then convert to base64:

```bash
base64 -i certificate.p12 | pbcopy
```

8. Paste the clipboard contents as the `MACOS_CERTIFICATE` secret value
9. **Delete the `.p12` file** from your machine

### Security Notes

- GitHub encrypts secrets at rest and only exposes them to workflows at runtime
- Secrets are NOT available in pull requests from forks
- Secrets are masked in workflow logs
- The temporary keychain is deleted in an `if: always()` step, even on build failure

---

## Verification Commands

### Check a Signed App

```bash
# Verify the signature is valid
codesign --verify --deep --strict --verbose=2 "dist/Transcript Recorder SourceBuild.app"

# View signature details (identity, team ID, entitlements hash)
codesign -dv --verbose=4 "dist/Transcript Recorder SourceBuild.app"

# View entitlements
codesign -d --entitlements - "dist/Transcript Recorder SourceBuild.app"

# Check Gatekeeper assessment (will say "rejected" until notarized — that's expected)
spctl --assess --type execute --verbose=2 "dist/Transcript Recorder SourceBuild.app"
```

### Check a Notarized DMG

```bash
# Check the stapled ticket
stapler validate "dist/TranscriptRecorder-1.2.3.dmg"

# Gatekeeper assessment (should say "accepted" with "source=Notarized Developer ID")
spctl --assess --type open --context context:primary-signature --verbose=2 "dist/TranscriptRecorder-1.2.3.dmg"
```

---

## Troubleshooting

### Keychain password prompt during signing

When `codesign` first accesses your certificate's private key, macOS shows a Keychain dialog asking for your **Mac login password**. Click **Always Allow** so it remembers the authorization.

### "errSecInternalComponent" during codesign

The keychain is locked or `codesign` can't access the private key.

```bash
# Unlock the keychain
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

### "The signature is invalid" after signing

Usually means components were signed in the wrong order (parent before children). Re-run the signing script — it handles the correct bottom-up order:

```bash
scripts/sign_app.sh "dist/Transcript Recorder SourceBuild.app"
```

### Accessibility permissions still resetting

Verify the app is actually signed:

```bash
codesign -dv "dist/Transcript Recorder SourceBuild.app" 2>&1 | grep "Authority"
```

You should see your Developer ID in the Authority lines. If it says `"ad-hoc"` or shows no Authority, the signing didn't work.

### Notarization fails

Check the detailed log from Apple:

```bash
xcrun notarytool log <submission-id> --keychain-profile "TranscriptRecorder"
```

The submission ID is printed in the notarization output. Common issues:

| Error | Fix |
|---|---|
| "not signed with a valid Developer ID certificate" | Make sure you used `Developer ID Application` (not `Mac Developer` or `Apple Distribution`) |
| "does not include a secure timestamp" | The `--timestamp` flag is missing from codesign. The scripts include this. |
| "hardened runtime is not enabled" | The `--options runtime` flag is missing. The scripts include this. |
| "uses an SDK older than the 10.9 SDK" | A bundled `.so`/`.dylib` was compiled against a very old SDK. Update the dependency. |

### "Developer ID Application" certificate not found in CI

- Verify you exported the certificate **with the private key** (expand in Keychain Access to confirm)
- Verify the base64 encoding has no extra newlines: `base64 -i certificate.p12 | tr -d '\n' | pbcopy`
- Verify the `MACOS_CERTIFICATE_PWD` secret matches the password you set during export

### App works but accessibility permissions reset after first signed release

Expected one-time event. Signing changes the app's code identity, so macOS treats it as a "new" app compared to the unsigned version. Grant accessibility once and it will persist for all future signed builds.

---

## Entitlements Reference

The `entitlements.plist` file declares runtime exceptions needed by py2app-bundled Python applications:

| Entitlement | Why Needed |
|---|---|
| `cs.allow-unsigned-executable-memory` | Python runtime uses `mmap` with executable memory |
| `cs.disable-library-validation` | py2app bundles `.so` extensions not signed by Apple |
| `automation.apple-events` | Transcript Recorder uses Apple Events for macOS integration |
| `cs.allow-jit` | Python's `ctypes` and C extensions need JIT compilation |
| `cs.allow-dyld-environment-variables` | py2app sets `DYLD_LIBRARY_PATH` to locate bundled libraries |

These entitlements do **not** disable the hardened runtime. They declare specific, narrow exceptions that Apple's notarization service reviews and permits for legitimate use cases. All py2app-based macOS apps need similar entitlements.
