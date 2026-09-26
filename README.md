# JEV Factorio Mission Control: OBS overlay

The live broadcast overlay for the JEV AI Factorio stream, captured exactly as
deployed on 2026-09-26 and traced back to its source.

![Offline / maintenance slate](art/jev-factorio-maintenance-v1.png)

## Where it came from

| Layer | Location on the live system | In this repo |
| --- | --- | --- |
| Overlay web app (`dashboard.py` + `dashboard_assets/`) | `obs-production` VM, `/opt/jev-mission-control/` | `obs-production/opt/jev-mission-control/` |
| Overlay service (`127.0.0.1:8765`) | `/etc/systemd/system/jev-mission-control.service` | `obs-production/etc/systemd/system/` |
| OBS scene collection `STS2`, scene **JEV Mission Control** | `~ubuntu/.config/obs-studio/basic/scenes/STS2.json` | `obs-production/home/ubuntu/.config/...` (SRT passphrases redacted) |
| OBS Lua scripts, media sources, relay, maintenance art | `~ubuntu/jev-obs/` | `obs-production/home/ubuntu/jev-obs/` |
| Telemetry mirror (controller to OBS VM, every 3 s) | Train host, `~completetrain/factorio-controller-replacement/` + user systemd unit | `train/` |
| Generated art | see above | [`art/`](art/) |

The OBS browser source loads `http://127.0.0.1:8765/?studio=1&v=d02486c`.
OBS draws that page over the native game video source, which sits under the
transparent **OBS COMPOSITION** area.

### Source commit

The overlay app is built from
[`CompleteDotTech/jev-factorio-agent`](https://github.com/CompleteDotTech/jev-factorio-agent)
(`src/jev_factorio/dashboard.py` and `dashboard_assets/`). Each deployed file
was hashed and matched to that repo's history:

- `dashboard.py`, `app.js`, `index.html` and `factory-steel.png` are
  byte-identical to commit
  [`d02486c`](https://github.com/CompleteDotTech/jev-factorio-agent/commit/d02486c3612381927bd77c443c49f3bd8d3f5231)
  ("Hide scrollbar chrome in OBS dashboard compositions", 2026-09-23).
- `styles.css` has the same rules as `d02486c`, but the scrollbar-hiding block
  is appended at the end of the file instead of sitting mid-file. It was
  hot-patched before that commit.
- `*.before-studio-*` and `theme-backups/` are the deployment's own rollback
  copies. They match earlier upstream commits: PR #25 `ba9d71a`, `1545b62`,
  `b3cd8a6` and `00b1c97`.
- `mission_control.py` and `mission_control_web/` are the original PR #25
  Mission Control app. They are still on disk but no longer serve the stream.

Later upstream work, such as PR #68's launch-readiness panel and
`mission.js`/`mission.css`, is **not** in this deployment.

## Data flow

```
herdr-vm: podman session-home-complete-tech
  /workspace/jev-factorio-agent/.../runs/controller-production-*/{gameplay.jsonl,supervisor.json}
      |  (Train: factorio-production-telemetry.service, read-only, QEMU guest agent)
      v
obs-production VM: /var/lib/jev-mission-control/{gameplay.jsonl,supervisor.json}
      |  (jev-mission-control.service -> dashboard.py :8765)
      v
OBS browser source "JEV Mission Control UI" -> Twitch
```

The dashboard is read-only. It redacts credential-like keys and values before
rendering, and it doesn't call models or control the game.

## Running the overlay locally

```
python3 obs-production/opt/jev-mission-control/dashboard.py \
  --log-file gameplay.jsonl --supervisor-state supervisor.json --port 8765
```

Open `http://127.0.0.1:8765/?studio=1` (1920x1080 studio layout) or `/?overlay=1`.
A missing log file is fine; the page shows its "awaiting evidence" state.

## Redactions

The SRT listener passphrases in `STS2.json`, `jev-obs/media.json` and
`jev-obs/factorio-b-media.json` are replaced with `REDACTED`. None of these files
contains a stream key or Twitch token. The relay and metadata scripts read those
at runtime from the live OBS profile and browser cookie store. Recordings,
screenshots, runtime status files and backups of the OBS profile are not included.

Factorio is a trademark of Wube Software. This project isn't affiliated with Wube.
