"""Role-checked BizPulse video handoff. Signing keys never leave the backend."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

import frappe
from frappe import _

ROLE = "BizPulse Meeting Host"
def _bridge_config(cfg):
    """Return validated bridge settings from an administrator-owned source."""
    if not isinstance(cfg, dict):
        return None
    url, key = cfg.get("public_url"), cfg.get("bridge_key")
    if not isinstance(url, str) or not isinstance(key, str) or len(key) != 96:
        return None
    if any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in ("", "/")
            or "?" in url or "#" in url or "%" in parts.netloc
            or (parts.port is not None and not 1 <= parts.port <= 65535)
            or len(bytes.fromhex(key)) != 48
        ):
            return None
    except ValueError:
        return None
    return {"public_url": url.rstrip("/"), "bridge_key": key}


def setup():
    """Bench-only, idempotent setup; grants no user roles or document permissions."""
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"role": ROLE, "users_assigned": 0}


def configure(config_path):
    """Bench-only: consume a private bridge export without printing its key."""
    path = Path(config_path)
    stat = path.stat()
    if not path.is_file() or stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
        raise ValueError("Bridge file must be owned by the bench user with permissions 600.")
    config = _bridge_config(json.loads(path.read_text()))
    if not config:
        raise ValueError("Unexpected bridge configuration")
    site_config = Path(frappe.get_site_path("site_config.json"))
    source = json.loads(site_config.read_text())
    source["bizpulse_jitsi"] = config
    temporary = site_config.with_name("site_config.json.jitsi-new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(source, out, indent=2)
    os.replace(temporary, site_config)
    frappe.conf["bizpulse_jitsi"] = source["bizpulse_jitsi"]
    setup()
    return {"configured": True, "public_url": config["public_url"], "secret_displayed": False}


def _configuration():
    cfg = _bridge_config(frappe.conf.get("bizpulse_jitsi"))
    if not cfg:
        frappe.throw(_("BizPulse video is not configured. Ask your administrator."))
    return cfg

def _access(meeting):
    user = frappe.session.user
    if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
        frappe.throw(_("Please sign in with an enabled ERPNext account."), frappe.PermissionError)
    doc = frappe.get_doc("Pulse Meeting", meeting)
    doc.check_permission("read")
    return doc


def _room(doc, cfg):
    identity = str(frappe.local.site) + "\x00" + doc.name
    return "pulse-" + hmac.new(cfg["bridge_key"].encode(), identity.encode(), hashlib.sha256).hexdigest()[:32]


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _ticket(claims, key):
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    message = header + "." + payload
    return message + "." + _b64(hmac.new(key.encode(), message.encode(), hashlib.sha256).digest())


@frappe.whitelist()
def get_video_access(meeting):
    doc = _access(meeting)
    cfg = _bridge_config(frappe.conf.get("bizpulse_jitsi"))
    if not cfg:
        return {"configured": False}
    return {"guest_url": cfg["public_url"] + "/" + _room(doc, cfg),
            "can_host": ROLE in frappe.get_roles(frappe.session.user)
                        and doc.status in ("Scheduled", "In Progress")}


@frappe.whitelist(methods=["POST"])
def launch_video(meeting):
    doc = _access(meeting)
    if ROLE not in frappe.get_roles(frappe.session.user):
        frappe.throw(_("The BizPulse Meeting Host role is required."), frappe.PermissionError)
    if doc.status not in ("Scheduled", "In Progress"):
        frappe.throw(_("Video hosting is available for scheduled or in-progress meetings."))
    cfg = _configuration()
    user = frappe.session.user
    display = frappe.db.get_value("User", user, "full_name") or user
    now = int(time.time())
    claims = {"iss": "bizpulse-erp", "aud": "bizpulse-bridge", "iat": now,
              "nbf": now - 5, "exp": now + 60, "jti": secrets.token_urlsafe(24),
              "room": _room(doc, cfg), "name": str(display)[:120],
              "uid": hashlib.sha256((str(frappe.local.site) + "\x00" + user).encode()).hexdigest()}
    # Never store host tickets in documents, comments or guest invitation fields.
    return {"endpoint": cfg["public_url"] + "/host/erp-join", "ticket": _ticket(claims, cfg["bridge_key"])}
