# Privacy Policy

XXAR is a desktop application that runs entirely on the user's computer.

**XXAR collects no personal data.** There are no user accounts, no registration, no analytics, no telemetry, no crash reporting, and no usage tracking of any kind. Nothing about the user, their files, or their activity is transmitted to the maintainer of this project or to any third party.

## Network connections

XXAR makes network requests only in the situations listed below. All of them are plain HTTPS `GET` requests that carry no user data — as with any HTTP request, the contacted host necessarily observes the user's IP address and the request's user agent.

| When | Host | Purpose |
|---|---|---|
| At startup in packaged builds, unless disabled, and whenever "Check for Updates" is used in Settings | `api.github.com` | Reads the latest release metadata to compare version numbers |
| When the user accepts an available update | `github.com` | Downloads the installer for the new version |
| When the audio browser loads sound names | `raw.githubusercontent.com` | Fetches the community sound-name database published in this repository |
| When the user opens the GameBanana page in the app | `gamebanana.com`, `api.gamebanana.com`, `img.youtube.com` | Lists mods, downloads a mod the user selected, and loads preview images |
| When the user starts the tool setup from the application | `gitlab.com`, `github.com` | Downloads Audiokinetic Wwise, FFmpeg and vgmstream into the local tools directory |

Only the update check runs without an explicit user action, once per launch in packaged builds. It can be turned off with **Settings → Updates → Check Automatically at Startup**; the choice is stored as `auto_check_updates` in `settings.json`. Every other request in the table is the direct result of the user opening a page or pressing a button. Running XXAR from source performs no update check at all.

With the automatic check disabled, XXAR works fully offline once the audio tools are installed, except for the features that are by definition online (manual update check, GameBanana browsing, sound-name database).

## Data stored on the user's computer

All application data stays local and is never uploaded:

| Location | Contents |
|---|---|
| `%APPDATA%\XXAR\` | `settings.json` (preferences, game install paths, last-used folders) and the per-game mod libraries |
| `%LOCALAPPDATA%\XXAR\` | Downloaded audio tools, caches, downloaded update archives, and application logs (`logs\xxar.log`) |

Logs contain file paths and diagnostic messages from the local session. They are written to disk only and are never transmitted anywhere. Users who attach a log to a bug report should be aware it contains local paths.

Removing these two directories after uninstalling deletes all data XXAR has stored.

## Changes to game files

XXAR modifies audio archives inside the game directory the user selects. This is the purpose of the application and is described in [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md). It involves no data collection.

## Contact

Questions about this policy: open an issue at [github.com/Entity378/XXAR/issues](https://github.com/Entity378/XXAR/issues).
