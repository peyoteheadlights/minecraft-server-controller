# Phone apps

Native apps for Android (Kotlin, Jetpack Compose) and iPhone (Swift,
SwiftUI). Every screen is the app's own; nothing of the dashboard is shown
in a web view. Other companies' sites (Tailscale, GitHub's forms) open in
the phone's browser, and the sign-in never goes with them.

The apps talk only to the agent on your PC, over Tailscale, with the same
API as the dashboard. There is no server in between and no account.

## What's where

| Folder | What |
|---|---|
| `shared/` | Generated, never edited: the dashboard's words (`strings.json`, Simple and Technical), themes, server colors, alert names and the app version. Both apps bundle these files. |
| `app-strings.json` | The apps' own words (`mobile.*`), next to the dashboard's. Edit these here. |
| `version.json` | The apps' version and which agent API versions they work with. |
| `api-routes.txt` | Every agent route the apps call. `tests/test_phone_app.py` fails if one disappears, so the agent stays compatible with apps already on phones. |
| `tools/generate.py` | Writes `shared/`. |
| `android/core/` | Everything the Android app decides that doesn't need Android: reading the pairing code, the certificate check, talking to the agent, the wording, the server colors, the Notifications tab and the widget. Plain Kotlin with JUnit tests. |
| `android/app/` | The Android app. |
| `ios/Core/` | The iPhone app's equivalent of `android/core`, a Swift package with tests. |
| `ios/` | The iPhone app and its widget (`project.yml` is the XcodeGen spec). |

## Words and colors

After changing the dashboard's `strings.js`, `feed.js`, `styles.css`,
`colors.js` or the palette in `agent/colors.py`, or `app-strings.json`:

```
python mobile/tools/generate.py
```

It needs Node (it runs the dashboard's own `colors.js` to record how it
tints each color, and the apps' tests check they tint the same way). CI
runs it with `--check`, and so does `tests/test_phone_app.py`.

## Building

**Android:** Android Studio (or JDK 17 and the Android SDK), then:

```
cd mobile/android
./gradlew :core:test :app:assembleDebug
```

Without the Android SDK, `./gradlew -PcoreOnly=true :core:test` runs only
the core tests.

**iPhone:** a Mac with Xcode 16 and [XcodeGen](https://github.com/yonaskolb/XcodeGen):

```
swift test --package-path mobile/ios/Core
xcodegen generate --spec mobile/ios/project.yml
open mobile/ios/ServerController.xcodeproj
```

CI (`.github/workflows/mobile.yml`) does both on every change under
`mobile/`, unsigned. The first build of each app is in CI.

## Lock-screen alerts (Firebase)

Android lock-screen alerts use Google's Firebase Cloud Messaging, sent by
the agent itself. Two files come from your Firebase project (see
`docs/notifications.md` for making it):

- `google-services.json` (for building the app): save its contents as the
  repository secret `GOOGLE_SERVICES_JSON` (**Settings → Secrets and
  variables → Actions**). CI writes it to `android/app/` before building.
  To build on your own PC, put the file there; it is in `.gitignore`.
  Without it the app builds and works, with lock-screen alerts off.
- The service-account key (for the PC that sends): only on that PC, put
  there by `python -m installer.setup_phone_alerts`. Never in the
  repository, `.env` or a secret.

## Keys and signing

Signing keys and store credentials never go in the repository or `.env`:
only in CI secrets (in a protected environment) or on the PC that builds a
release. `android/app/build.gradle.kts` signs a release only when
`ANDROID_KEYSTORE_FILE`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`
and `ANDROID_KEY_PASSWORD` are set. Store releases come in a later step of
Phase 9.

## House rules, in the apps too

- A value the agent didn't measure shows as Unknown, never 0 or a guess,
  and an old reading is never shown as current (the widget and the server
  list turn Unknown when the PC doesn't answer).
- The apps start, stop and restart servers through the same API routes and
  permissions as the dashboard; they can't run anything else on the PC.
- Certificate checks are never switched off. A pairing code names the PC's
  certificate and only that one is accepted; a typed address needs one the
  phone trusts, or the person compares fingerprints.
- Logs and "Copy details for a problem report" never hold the sign-in, a
  password, the PC's address or the certificate fingerprint.
