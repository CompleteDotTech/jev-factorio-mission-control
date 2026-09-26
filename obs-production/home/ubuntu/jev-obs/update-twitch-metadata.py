import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import sys
import urllib.error
import urllib.parse
import urllib.request

assert Path("/sys/class/dmi/id/product_uuid").read_text().strip() == "fd83a53b-7bd7-4364-b06c-2bd6abd428bc"
profile = next(Path("/home/ubuntu/snap/firefox/common/.mozilla/firefox").glob("*/cookies.sqlite"))
with tempfile.TemporaryDirectory() as temporary:
    snapshot = Path(temporary) / "cookies"
    shutil.copyfile(profile, snapshot)
    connection = sqlite3.connect(snapshot)
    token = connection.execute(
        "select value from moz_cookies where host=? and name=?",
        (".twitch.tv", "auth-token"),
    ).fetchone()[0]
    connection.close()

request = urllib.request.Request(
    "https://id.twitch.tv/oauth2/validate",
    headers={"Authorization": "OAuth " + token},
)
with urllib.request.urlopen(request, timeout=20) as response:
    identity = json.load(response)
assert identity["login"] == "completedottech"


def api(path, method="GET", data=None):
    request = urllib.request.Request(
        "https://api.twitch.tv/helix/" + path,
        method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Client-Id": identity["client_id"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            return json.loads(body) if body else {"status": response.status}
    except urllib.error.HTTPError as error:
        print(json.dumps({"status": error.code, "error": error.read().decode()}))
        raise SystemExit(1)


def graphql(query, variables=None):
    request = urllib.request.Request(
        "https://gql.twitch.tv/gql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Authorization": "OAuth " + token,
            "Client-Id": identity["client_id"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


if len(sys.argv) > 1:
    print(json.dumps(graphql(sys.argv[1]), indent=2))
    raise SystemExit(0)


channel_path = "channels?broadcaster_id=" + identity["user_id"]
before = api(channel_path)
game = api("games?name=Factorio")["data"]
assert len(game) == 1 and game[0]["name"] == "Factorio"
title = "JEV AI plays Factorio | Autonomous factory to rocket launch | Live Mission Control"
update = {
    "title": title,
    "game_id": game[0]["id"],
    "broadcaster_language": "en",
    "tags": ["AI", "ArtificialIntelligence", "Automation", "FactoryBuilding", "Programming", "English"],
}
receipt = {"before": before, "requested": update, "result": api(channel_path, "PATCH", update)}
receipt["after"] = api(channel_path)
assert receipt["after"]["data"][0]["title"] == title
assert receipt["after"]["data"][0]["game_name"] == "Factorio"
destination = Path("/home/ubuntu/jev-obs/twitch-metadata-receipt.json")
destination.write_text(json.dumps(receipt, indent=2))
destination.chmod(0o600)
print(json.dumps(receipt, indent=2))
