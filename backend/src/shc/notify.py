"""Desktop notifications for conditions that would otherwise fail silently.

SHC runs unattended on Rob's own Mac, so anything the scheduler discovers is
invisible until he next opens the app. For a broken data source that is exactly
the wrong failure mode: the app keeps serving numbers, they are just old ones.
This module is the push half of that loop.

Desktop banners use macOS `display notification`: no daemon, no credentials. On
the always-on host nobody is looking at the screen, so `send_phone_alert` posts
to the ntfy topic the host job runner (deploy/run-job.sh) already alerts on.
Phone alerts carry check names and counts only, never health data.
Notifications are delivered on a best-effort basis and must never take down
the caller: a notification that fails is logged and swallowed, because the
underlying condition is already being logged by whoever asked us to send it.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# The topic is a shared secret; it lives only on the host, never in the repo.
NTFY_TOPIC_FILE = Path.home() / ".config" / "shc" / "ntfy-topic"

# Passing the payload as argv rather than interpolating it into the AppleScript
# source keeps quotes, newlines and apostrophes in a message from terminating
# the string literal and running as code.
_OSASCRIPT = """on run argv
display notification (item 1 of argv) with title (item 2 of argv) subtitle (item 3 of argv) sound name "Basso"
end run"""

_TIMEOUT_S = 10.0


async def send_desktop_alert(title: str, subtitle: str, message: str) -> bool:
    """Post a macOS notification banner. Returns whether it was delivered.

    Never raises: callers use this to report a problem, and a failure to report
    must not become a second, louder problem.
    """
    if shutil.which("osascript") is None:
        log.warning("osascript unavailable — cannot deliver desktop alert: %s", title)
        return False

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            _OSASCRIPT,
            message,
            title,
            subtitle,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
    except TimeoutError:
        log.warning("desktop alert timed out after %.0fs: %s", _TIMEOUT_S, title)
        return False
    except OSError:
        log.exception("desktop alert failed to launch: %s", title)
        return False

    if proc.returncode != 0:
        log.warning(
            "desktop alert exited %s: %s", proc.returncode, stderr.decode(errors="replace").strip()
        )
        return False
    return True


async def send_phone_alert(title: str, message: str) -> bool:
    """Post a phone notification to the host's ntfy topic. Returns whether it was delivered.

    Never raises. Without a topic file there is no phone channel, and the call
    logs that and returns False. Callers must not pass health data.
    """
    try:
        topic = NTFY_TOPIC_FILE.read_text().strip()
    except OSError:
        log.warning("no ntfy topic at %s, phone alert not sent: %s", NTFY_TOPIC_FILE, title)
        return False
    if not topic:
        log.warning("empty ntfy topic file, phone alert not sent: %s", title)
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                f"https://ntfy.sh/{topic}", content=message.encode(), headers={"Title": title}
            )
        resp.raise_for_status()
    except httpx.HTTPError:
        log.exception("phone alert failed: %s", title)
        return False
    return True
