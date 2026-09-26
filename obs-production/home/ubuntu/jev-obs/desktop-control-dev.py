import json
import sys
import time
from pathlib import Path
import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

DBusGMainLoop(set_as_default=True)
Gst.init(None)
bus = dbus.SessionBus()
remote_service = "org.gnome.Mutter.RemoteDesktop"
capture_service = "org.gnome.Mutter.ScreenCast"
remote_path = bus.get_object(remote_service, "/org/gnome/Mutter/RemoteDesktop").CreateSession(
    dbus_interface=remote_service
)
remote_object = bus.get_object(remote_service, remote_path)
remote = dbus.Interface(remote_object, remote_service + ".Session")
session_id = remote_object.Get(remote_service + ".Session", "SessionId", dbus_interface="org.freedesktop.DBus.Properties")
capture_path = bus.get_object(capture_service, "/org/gnome/Mutter/ScreenCast").CreateSession(
    {"remote-desktop-session-id": session_id}, dbus_interface=capture_service
)
capture = dbus.Interface(bus.get_object(capture_service, capture_path), capture_service + ".Session")
stream_path = capture.RecordMonitor("", {"cursor-mode": dbus.UInt32(0)})
stream = bus.get_object(capture_service, stream_path)
loop = GLib.MainLoop()
pipeline = None


def ready(node):
    global pipeline
    pipeline = Gst.parse_launch(
        f"pipewiresrc path={int(node)} ! videoconvert ! pngenc ! appsink name=snapshot max-buffers=1 drop=true sync=false"
    )
    pipeline.get_bus().add_signal_watch()
    pipeline.get_bus().connect("message", message)
    pipeline.set_state(Gst.State.PLAYING)
    GLib.timeout_add(1800, save_snapshot)


def save_snapshot():
    sample = pipeline.get_by_name("snapshot").emit("try-pull-sample", 0)
    if sample is None:
        return True
    buffer = sample.get_buffer()
    Path("/home/ubuntu/jev-obs/desktop.png").write_bytes(buffer.extract_dup(0, buffer.get_size()))
    loop.quit()
    return False


def message(bus, event):
    if event.type == Gst.MessageType.ERROR:
        print(event.parse_error(), flush=True)
        loop.quit()
    elif event.type == Gst.MessageType.EOS:
        loop.quit()


stream.connect_to_signal("PipeWireStreamAdded", ready, dbus_interface=capture_service + ".Stream")
remote.Start()
actions = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
for action in actions:
    if action[0] == "key":
        for keysym in action[1:]:
            remote.NotifyKeyboardKeysym(dbus.UInt32(keysym), True)
        for keysym in reversed(action[1:]):
            remote.NotifyKeyboardKeysym(dbus.UInt32(keysym), False)
    elif action[0] == "click":
        remote.NotifyPointerMotionAbsolute(str(stream_path), float(action[1]), float(action[2]))
        time.sleep(0.2)
        button = int(action[3]) if len(action) > 3 else 272
        assert button in (272, 273)
        remote.NotifyPointerButton(button, True)
        time.sleep(0.1)
        remote.NotifyPointerButton(button, False)
    elif action[0] == "text":
        for character in action[1]:
            remote.NotifyKeyboardKeysym(dbus.UInt32(ord(character)), True)
            remote.NotifyKeyboardKeysym(dbus.UInt32(ord(character)), False)
            time.sleep(0.01)
    elif action[0] == "wait":
        time.sleep(float(action[1]))
    time.sleep(0.35)
GLib.timeout_add_seconds(15, lambda: loop.quit() or False)
loop.run()
if pipeline:
    pipeline.set_state(Gst.State.NULL)
remote.Stop()
print("desktop snapshot complete")
