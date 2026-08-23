#!/usr/bin/env python3
"""Start Eve Chat's adopted upstream UI from a local Python environment."""

from __future__ import annotations

import argparse
import json
import time
import importlib.util
import os
import signal
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from eve_chat_brand_scrub import apply_branding  # noqa: E402


def site_packages_root() -> Path:
    spec = importlib.util.find_spec("open_webui")
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError("open_webui package is not installed in this Python environment")
    package_root = Path(list(spec.submodule_search_locations)[0]).resolve()
    return package_root.parent


def detach_from_launcher() -> None:
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        os.setsid()
    except OSError:
        # Already a process-group leader. Ignoring SIGHUP is the important part.
        pass


def install_eve_chat_followup_routes() -> None:
    """Add Eve-owned routes to the adopted UI without forking the package yet."""
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse

    from open_webui.main import app
    from open_webui.models.chats import Chats

    if getattr(app.state, "eve_chat_followup_routes_installed", False):
        return
    app.state.eve_chat_followup_routes_installed = True

    @app.post("/api/eve-chat/followups/insert")
    async def insert_eve_chat_followup(payload: dict = Body(...)):
        followup = payload.get("followup") if isinstance(payload.get("followup"), dict) else {}
        chat_id = str(payload.get("chat_id") or followup.get("openwebui_chat_id") or "").strip()
        if not chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")

        chat = await Chats.get_chat_by_id(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="chat not found")

        history = (chat.chat or {}).get("history", {})
        messages = history.get("messages", {})
        if not isinstance(messages, dict):
            messages = {}
        current_id = str(history.get("currentId") or "").strip()
        parent_id = str(
            payload.get("parent_message_id")
            or followup.get("openwebui_assistant_message_id")
            or current_id
            or followup.get("openwebui_user_message_id")
            or ""
        ).strip()
        followup_id = str(followup.get("id") or payload.get("followup_id") or "").strip()
        if not followup_id:
            raise HTTPException(status_code=400, detail="followup.id is required")
        message_id = f"eve-followup-{followup_id}"

        if message_id in messages:
            return {
                "ok": True,
                "inserted": False,
                "chat_id": chat_id,
                "message_id": message_id,
                "reason": "already_inserted",
            }

        content = str(followup.get("delivery_text") or followup.get("failure_reason") or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="followup delivery_text is required")

        if parent_id and parent_id in messages:
            parent = dict(messages[parent_id])
            children = [str(item) for item in parent.get("childrenIds", []) if str(item)]
            if message_id not in children:
                children.append(message_id)
            parent["childrenIds"] = children
            messages[parent_id] = parent
        elif not parent_id:
            parent_id = current_id

        messages[message_id] = {
            "id": message_id,
            "parentId": parent_id or None,
            "childrenIds": [],
            "role": "assistant",
            "content": content,
            "done": True,
            "model": "eve",
            "timestamp": int(time.time()),
            "metadata": {
                "source": "eve_chat_followup",
                "followup_id": followup_id,
                "requested_action": followup.get("requested_action") or "",
                "delivery_message_id": followup.get("delivery_message_id") or "",
            },
        }

        updated_chat = dict(chat.chat or {})
        updated_chat["history"] = {
            **history,
            "messages": messages,
            "currentId": message_id,
        }
        if "messages" in updated_chat and isinstance(updated_chat.get("messages"), list):
            updated_chat["messages"] = [
                *updated_chat["messages"],
                {"role": "assistant", "content": content},
            ]

        saved = await Chats.update_chat_by_id(chat_id, updated_chat)
        if not saved:
            raise HTTPException(status_code=500, detail="chat update failed")

        return {
            "ok": True,
            "inserted": True,
            "chat_id": chat_id,
            "message_id": message_id,
            "parent_message_id": parent_id,
        }

    @app.post("/api/eve-chat/ag-ui")
    async def proxy_eve_chat_agui(payload: dict = Body(...)):
        backend_base = os.environ.get("EVE_HOST_BASE_URL") or os.environ.get("EVE_CHAT_BACKEND_BASE_URL") or "http://127.0.0.1:8797"
        backend_base = backend_base.rstrip("/")
        if backend_base.endswith("/v1"):
            backend_base = backend_base[:-3]
        backend_url = f"{backend_base}/api/eve-chat/ag-ui"
        body = json.dumps(payload).encode("utf-8")

        def stream_backend():
            request = urllib.request.Request(
                backend_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    while True:
                        chunk = response.read(4096)
                        if not chunk:
                            break
                        yield chunk
            except Exception as exc:
                message = str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)
                event = {
                    "type": "ERROR",
                    "error": message,
                    "source": "eve_chat_ui_proxy",
                }
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

        return StreamingResponse(stream_backend(), media_type="text/event-stream")

    # OpenWebUI mounts its single-page-app catch-all during import. Routes
    # added after that catch-all can return 405 before FastAPI reaches them, so
    # keep Eve's local API routes ahead of `/{path:path}`.
    routes = app.router.routes
    eve_route_paths = {"/api/eve-chat/followups/insert", "/api/eve-chat/ag-ui"}
    for route in reversed(list(routes)):
        if getattr(route, "path", "") not in eve_route_paths:
            continue
        routes.remove(route)
        routes.insert(0, route)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Eve Chat's local UI adapter without Docker.")
    parser.add_argument("--host", default=os.environ.get("EVE_CHAT_UI_HOST", os.environ.get("EVE_OPENWEBUI_HOST", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EVE_CHAT_UI_PORT", os.environ.get("EVE_OPENWEBUI_PORT", "3000"))))
    parser.add_argument("--brand-name", default=os.environ.get("EVE_WEBUI_BRAND_NAME", "Eve"))
    parser.add_argument("--brand-slug", default=os.environ.get("EVE_WEBUI_BRAND_SLUG", "eve"))
    parser.add_argument("--brand-mode", default=os.environ.get("EVE_CHAT_UI_BRAND_MODE", os.environ.get("EVE_OPENWEBUI_BRAND_MODE", "small-scale-local")))
    args = parser.parse_args()
    detach_from_launcher()

    app_root = site_packages_root()
    report = apply_branding(
        app_root=app_root,
        brand_name=args.brand_name,
        brand_slug=args.brand_slug,
        mode=args.brand_mode,
    )
    print(
        "Eve Chat branding: "
        f"root={app_root} files_changed={report['files_changed']} replacements={report['replacements']}",
        flush=True,
    )

    os.environ["FROM_INIT_PY"] = "true"

    import open_webui.main  # noqa: F401, WPS433
    import uvicorn  # noqa: WPS433

    install_eve_chat_followup_routes()

    uvicorn.run(
        open_webui.main.app,
        host=args.host,
        port=args.port,
        forwarded_allow_ips="*",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
