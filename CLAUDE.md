# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **snapshot of a live deployment** of the JEV Factorio stream's OBS overlay, not an actively developed source tree. Paths mirror the live filesystem roots: `obs-production/` is the OBS VM (`/etc`, `/opt`, `/home/ubuntu`), `train/` is the Train host (`~completetrain`). The upstream source is `CompleteDotTech/jev-factorio-agent` (`src/jev_factorio/`). Code changes belong there. This repo records what is actually deployed and where it came from.

Keep it byte-faithful to the live system:
- `obs-production/opt/jev-mission-control/jev_factorio/` must be an exact copy of the upstream commit named in `jev_factorio/DEPLOYED_COMMIT` (currently `6424661`). Don't reformat, lint, or "fix" these files.
- `*.before-*` files and `theme-backups/<timestamp>/` are the deployment's own rollback copies. The flat `dashboard.py`/`dashboard_assets/` and `mission_control.py`/`mission_control_web/` at the top of `/opt/jev-mission-control/` are older versions that are still on disk but no longer served. Leave all of them as they are.
- When the live deployment changes, update the snapshot, the systemd unit, `DEPLOYED_COMMIT`, and the README "Source commit" section together. Earlier commits show the pattern: they cite the upstream commit and PRs and note what was not included.

## Redaction rules (required on every capture)

- Replace SRT listener passphrases with `REDACTED` in `STS2.json`, `jev-obs/media.json`, and `jev-obs/factorio-b-media.json`.
- Never commit stream keys, Twitch tokens, browser cookies, recordings, screenshots, runtime status files, or OBS profile backups.
- Never commit Factorio item icons (`/opt/jev-mission-control/icons/`, which is Wube game data). They are served at runtime through `--icon-dir`.

## Generating images (use Codex)

To create new art (textures, slates, backgrounds), call the Codex CLI and let it use its built-in image generation model. The existing `art/` images were made the same way, with the GPT image tool. Codex CLI (`codex`, 0.157.1) is installed, and its `image_generation` feature is on. Run it non-interactively from the repo root:

```
codex exec -C . --sandbox workspace-write "Generate an image with your image generation tool: <prompt>. Save it as art/<name>.png"
```

- Write the prompt as a detailed spec. The `factory-steel.png` prompt in `art/README.md` is the model: say what the asset is for, its size, palette hex values, what to leave out (text, logos, focal points), and how it will be layered.
- Add a section to `art/README.md` for every new image, with its file name, size, purpose, where it's deployed, the date, and the **exact prompt**. The maintenance slate's prompt was never recorded; don't repeat that. Use generated images as they come out, without edits.
- If an image is deployed, commit it in both places: under `art/`, and at its mirrored deploy path (for example `obs-production/.../dashboard_assets/` or `jev-obs/assets/`).

## Running the overlay locally

There's no build step, dependency file, or test suite. The dashboard uses only the Python standard library.

```
cd obs-production/opt/jev-mission-control
python3 -m jev_factorio.dashboard --log-file gameplay.jsonl --supervisor-state supervisor.json --port 8765 [--icon-dir <Factorio>/data/base/graphics/icons]
```

- You must pass exactly one of `--events` (live dashboard-events JSONL) or `--log-file` (legacy gameplay JSONL, which production uses). The file doesn't need to exist yet. Without it the page shows an "awaiting evidence" state.
- Open `http://127.0.0.1:8765/?studio=1` (the 1920x1080 layout OBS uses) or `/?overlay=1`. The server returns 403 unless the `Host` is `127.0.0.1:<port>` or `localhost:<port>`, so use one of those exact hosts.

## Architecture

Data flow, all read-only:
1. **Train host**: `train/factorio-controller-replacement/factorio-production-telemetry.py` (user systemd unit; the session ID is set in the `campaign.conf` drop-in) uses the QEMU guest agent to read `gameplay.jsonl` and `supervisor.json` from the controller run inside the herdr-vm podman container. Every 3 seconds it mirrors them to `/var/lib/jev-mission-control/` on the OBS VM.
2. **OBS VM**: `jev-mission-control.service` runs `python3 -m jev_factorio.dashboard` on `127.0.0.1:8765`, with a hardened unit (`ProtectSystem=strict`, and the data dir mounted read-only).
3. **OBS**: the browser source "JEV Mission Control UI" in scene collection `STS2`, scene **JEV Mission Control**, loads `/?studio=1&v=...`. The native game video is a separate OBS source that shows through the transparent "OBS COMPOSITION" area. OBS Lua scripts in `home/ubuntu/jev-obs/` handle scene switching, the maintenance slate, perf, and audio. Python helpers there handle the broadcast relay and Twitch metadata.

Inside `jev_factorio/`:
- `dashboard.py` has a `Monitor` that tails the JSONL in a thread and builds bounded, redacted snapshots (`SECRET_KEY`/`URL`/`CREDENTIAL` regexes, and `RECORD_KEYS`/`STATE_KEYS` allowlists). `DashboardServer` serves `/api/snapshot`, the SSE stream `/api/events` (a full snapshot every 0.5 s, with a limited number of concurrent clients), `/icons/<name>.png`, and a fixed allowlist of static assets. To add a new asset file, you must also add it to the `names` dict in `do_GET`.
- `dashboard_mission.py` builds the launch-readiness summary. By design, missing, stale, or contradictory evidence must never be displayed as "ready".
- `dashboard_assets/` is vanilla JS with no bundler. `index.html` loads `explain.js`, `mission.js`, and `app.js` (in that order). `app.js` switches layouts with the `studio`/`overlay` query params.

After a deploy, the OBS browser source must be refreshed manually. The server sends `no-store`, but a page that's already open keeps running its old JS.

## Operating the live VM

The OBS VM has no SSH access. Every command goes through the QEMU guest agent from the Train host: `virsh -c qemu:///system` on domain `obs-production`, or `guest_exec` in `train/.../deploy-factorio-broadcast-relay.py`.
- **Keep each guest-exec's output well under 10 MB.** A larger output makes libvirt put the agent in an error state ("QEMU guest agent is not available due to an error"). That also stops the telemetry mirror, which uses the same channel. To recover without sudo, save the `org.qemu.guest_agent.0` `<channel>` XML from `virsh dumpxml`. Then run `virsh detach-device --live` with it, and `attach-device --live` with the output-only `state` attribute removed. The telemetry service resumes on its own.
- **Refreshing the overlay after a deploy.** `~ubuntu/jev-obs/desktop-control.py` sends clicks through the GNOME RemoteDesktop portal and saves a snapshot to `desktop.png`. Run it as ubuntu with `XDG_RUNTIME_DIR=/run/user/1000` and `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`.
  - OBS runs in **Studio Mode**, with Program on *JEV Mission Control* and Preview normally on *JEV - Maintenance*.
  - Single-click the *JEV Mission Control* scene, which changes only the Preview. Never use Transition or double-click, or the maintenance slate goes live on stream.
  - Click **Refresh** in the source toolbar for *JEV Mission Control UI*.
  - Click *JEV - Maintenance* again to restore the Preview.
- **Taking a screenshot of the program output.** As ubuntu, `touch ~ubuntu/jev-obs/screenshot.request`. `jev-factorio.lua` calls `obs_frontend_take_screenshot()` and writes the file's path to `status.json`. The file saves under `/mnt/recordings/sts2/program/`. A request file owned by root can't be read by OBS and silently never fires.
