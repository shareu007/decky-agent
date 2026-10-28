"""Generate PCM WAV samples without accessing a real microphone."""
import signal
import sys
import time
import wave

if "--fail" in sys.argv:
    raise SystemExit(3)
stopped = False


def stop(*_):
    global stopped
    stopped = True


signal.signal(signal.SIGINT, stop)
with open(sys.argv[-1], "wb", buffering=0) as handle, wave.open(handle, "wb") as audio:
    audio.setnchannels(1)
    audio.setsampwidth(2)
    audio.setframerate(16000)
    audio.writeframes(b"" if "--empty" in sys.argv else b"\0\0" * 3200)
    while not stopped:
        if "--empty" not in sys.argv:
            audio.writeframes(b"\0\0" * 320)
        if "--exit-early" in sys.argv:
            break
        time.sleep(.02)
if "--truncate" in sys.argv:
    with open(sys.argv[-1], "r+b") as handle:
        handle.truncate(54)
if "--exit-one" in sys.argv:
    raise SystemExit(1)
