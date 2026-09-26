"""Read-only campaign telemetry and an isolated mission-control web server."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


MAX_FILE_BYTES = 2_000_000
ASSETS = Path(__file__).with_name("mission_control_web")


def read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return {}
        data = json.loads(path.read_text(), parse_constant=lambda value: None)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def tail_records(path: Path, limit: int = 30) -> list[dict]:
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = max(0, size - MAX_FILE_BYTES)
            stream.seek(offset)
            data = stream.read(MAX_FILE_BYTES)
        lines = data.split(b"\n")
        if offset:
            lines = lines[1:]
        lines = lines[:-1]
        records = []
        for line in reversed(lines):
            try:
                record = json.loads(line, parse_constant=lambda value: None)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
                if len(records) >= limit:
                    break
        return records
    except OSError:
        return []


def number(value, default=None):
    return value if type(value) in (int, float) and math.isfinite(value) else default


def label(value, limit: int = 160) -> str:
    return value[:limit] if isinstance(value, str) else ""


def quantities(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        label(key, 80): number(amount)
        for key, amount in list(value.items())[:100]
        if isinstance(key, str) and number(amount) is not None
    }


def modified(path: Path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def process_alive(process) -> bool:
    if not isinstance(process, dict) or type(process.get("pid")) is not int:
        return False
    try:
        fields = Path(f"/proc/{process['pid']}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0] not in {"Z", "X"} and fields[19] == str(process.get("identity"))
    except (OSError, IndexError):
        return False


def snapshot(directory: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    checkpoint = read_json(directory / "state.json")
    supervisor = read_json(directory / "supervisor.json")
    session = checkpoint.get("session_id")
    matched = bool(session and supervisor.get("session_id") == session)
    records = tail_records(directory / "gameplay.jsonl")
    records = [
        record for record in records
        if record.get("session_id") == session and session
    ]
    latest = records[0] if records else {}
    game = latest.get("after_state") or latest.get("state") or {}
    if not isinstance(game, dict) or game.get("session_id") != session:
        game = {}
    factory = game.get("factory", {})
    factory = factory if isinstance(factory, dict) else {}
    phase = label(supervisor.get("phase")) if matched else "unavailable"
    alive = process_alive(supervisor.get("process")) if matched else False
    status = phase
    if phase == "gameplay":
        status = label(checkpoint.get("status")) if alive else "stopped"
    if not checkpoint or not matched:
        status = "unavailable"
    plan = checkpoint.get("active_plan") or {}
    pending = checkpoint.get("pending") or {}
    plan = plan if isinstance(plan, dict) else {}
    pending = pending if isinstance(pending, dict) else {}
    entities = factory.get("entities", {})
    machines = []
    for role, entity in list(entities.items())[:60] if isinstance(entities, dict) else []:
        if not isinstance(entity, dict):
            continue
        position = entity.get("position") or {}
        machines.append({
            "role": label(role), "name": label(entity.get("name")),
            "position": {
                "x": number(position.get("x")), "y": number(position.get("y")),
            } if isinstance(position, dict) else {},
            "crafting": entity.get("crafting") is True,
            "status_code": number(entity.get("status")),
            "input": quantities(entity.get("input")),
            "output": quantities(entity.get("output")),
            "fuel": quantities(entity.get("fuel")),
            "fluids": quantities(entity.get("fluids")),
            "products_finished": number(entity.get("products_finished")),
        })
    history = checkpoint.get("history", [])
    history = history if isinstance(history, list) else []
    events = [{
        "kind": label(event.get("kind")), "tick": number(event.get("tick")),
        "action": label(event.get("action")),
        "plan": label(event.get("plan"), 240),
    } for event in history[-20:] if isinstance(event, dict)]
    repair_events = [{
        "event": label(event.get("event")), "at": number(event.get("at")),
        "attempt": number(event.get("attempt")),
        "accepted": event.get("accepted") if type(event.get("accepted")) is bool else None,
        "phase": label(event.get("phase")),
    } for event in tail_records(directory / "events.jsonl", 100)
        if event.get("event") in {
            "repair_finished", "repair_required", "gameplay_stopped",
            "root_repair_verified", "root_operational_takeover_verified",
            "root_observation_repair_verified",
        }][:12]
    return {
        "schema_version": 1, "generated_at": now,
        "checkpoint_at": modified(directory / "state.json"),
        "telemetry_at": modified(directory / "gameplay.jsonl") if game else None,
        "session_id": label(session), "run": directory.name,
        "status": status, "phase": phase, "process_alive": alive,
        "repair_required": supervisor.get("repair_required") is True,
        "repair_attempt": number(supervisor.get("attempt"), 0),
        "started_at": number(supervisor.get("started_at")),
        "cutoff": number(supervisor.get("cutoff")),
        "tick": number(game.get("tick"), number(checkpoint.get("last_tick"))),
        "controller": label(checkpoint.get("status")),
        "target": label(checkpoint.get("target")),
        "active_goal": label(checkpoint.get("active_goal")),
        "completed_goals": quantities(checkpoint.get("completed_goals")),
        "plan": {
            "id": label(plan.get("id"), 240),
            "description": label(plan.get("description"), 240),
            "step": number(checkpoint.get("step_index"), 0),
            "pending_action": label(pending.get("action")),
            "dispatch": label(pending.get("dispatch")),
            "polls": number(pending.get("polls"), 0),
            "started_tick": number(pending.get("started_tick")),
        },
        "research": {
            "name": label(factory.get("research")),
            "progress": number(factory.get("research_progress")),
            "completed": [
                label(item) for item in (game.get("researched") or [])[:100]
                if isinstance(item, str)
            ] if isinstance(game.get("researched"), list) else [],
        },
        "inventory": quantities(game.get("inventory")),
        "machines": machines,
        "rockets_launched": number(factory.get("rockets_launched")),
        "model": {
            "requested": label(latest.get("requested_model")),
            "resolved": label(latest.get("resolved_model")),
            "policy": label(latest.get("policy")),
        },
        "events": events, "repairs": repair_events,
        "retained_failures": sum(quantities(checkpoint.get("failures")).values()),
    }


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".snapshot-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, allow_nan=False)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def handler(snapshot_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/status":
                data = read_json(snapshot_path)
                body = json.dumps(data, allow_nan=False).encode()
                content_type = "application/json"
                status = 200 if data else 503
            elif path in {"/", "/app.js", "/style.css"}:
                filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
                body = (ASSETS / filename).read_bytes()
                content_type = {
                    "/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8",
                    "/style.css": "text/css; charset=utf-8",
                }[path]
                status = 200
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; "
                "base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return Handler


def publish_guest(data: dict, ssh_host: str, domain: str, uuid: str) -> None:
    payload = base64.b64encode(json.dumps(data, allow_nan=False).encode()).decode()
    program = (
        "import base64,os,pathlib,tempfile;"
        f"assert pathlib.Path('/sys/class/dmi/id/product_uuid').read_text().strip()=={uuid!r};"
        "root=pathlib.Path('/var/lib/jev-mission-control');"
        "descriptor,temporary=tempfile.mkstemp(dir=root,prefix='.snapshot-');"
        f"os.write(descriptor,base64.b64decode({payload!r}));os.close(descriptor);"
        "os.chmod(temporary,0o644);os.replace(temporary,root/'status.json')"
    )

    def request(arguments):
        command = shlex.join([
            "virsh", "-c", "qemu:///system", "qemu-agent-command", domain,
            json.dumps(arguments),
        ])
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_host, command],
            check=True, capture_output=True, text=True, timeout=15,
        )
        return json.loads(result.stdout)["return"]

    process = request({"execute": "guest-exec", "arguments": {
        "path": "/usr/bin/python3", "arg": ["-c", program], "capture-output": True,
    }})
    for attempt in range(15):
        result = request({"execute": "guest-exec-status", "arguments": {"pid": process["pid"]}})
        if result.get("exited"):
            if result.get("exitcode") != 0:
                raise RuntimeError("Guest snapshot delivery failed")
            return
        time.sleep(0.2)
    raise TimeoutError("Guest snapshot delivery did not finish")


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--snapshot", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    export = commands.add_parser("export")
    export.add_argument("--run-dir", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--interval", type=float, default=5)
    export.add_argument("--once", action="store_true")
    export.add_argument("--ssh-host")
    export.add_argument("--guest-domain")
    export.add_argument("--guest-uuid")
    arguments = parser.parse_args()
    if arguments.command == "serve":
        ThreadingHTTPServer((arguments.host, arguments.port), handler(arguments.snapshot)).serve_forever()
        return
    if not math.isfinite(arguments.interval) or arguments.interval < 1:
        parser.error("--interval must be finite and at least one second")
    transport = (arguments.ssh_host, arguments.guest_domain, arguments.guest_uuid)
    if any(transport) and not all(transport):
        parser.error("Guest publishing requires --ssh-host, --guest-domain and --guest-uuid")
    while True:
        try:
            data = snapshot(arguments.run_dir)
            atomic_write(arguments.output, data)
            if all(transport):
                publish_guest(data, *transport)
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as error:
            print(f"{datetime.now(timezone.utc).isoformat()} export failed: {type(error).__name__}",
                  flush=True)
            if arguments.once:
                raise
        if arguments.once:
            break
        time.sleep(arguments.interval)


if __name__ == "__main__":
    cli()
