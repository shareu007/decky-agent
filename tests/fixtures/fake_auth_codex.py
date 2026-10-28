"""Managed-auth app-server fixture; never contacts OpenAI or handles real tokens."""
import json
import os
import sys
import threading
import uuid
from pathlib import Path

home = Path(os.environ["CODEX_HOME"])
account_file = home / "fixture-account.json"
control_file = home / "fixture-control.json"
finish_file = home / "fixture-finish.json"
output_lock = threading.Lock()
cancelled = threading.Event()
provider = next((s.split("=", 1)[1].strip('"') for s in sys.argv if s.startswith("model_provider=")), "")
(home / "fixture-start.json").write_text(json.dumps({
    "provider": provider, "chat_key_env": bool(os.environ.get("DECKY_AGENT_API_KEY")),
    "openai_key_env": bool(os.environ.get("OPENAI_API_KEY")),
    "custom_provider": any(s.startswith("model_providers.decky.") for s in sys.argv),
    **({"catalog": json.loads(next(s.split("=", 1)[1] for s in sys.argv if s.startswith("model_catalog_json=")))} if any(s.startswith("model_catalog_json=") for s in sys.argv) else {}),
}))


def send(value):
    with output_lock:
        print(json.dumps(value), flush=True)


def complete(login_id, event):
    success = event.get("success", True)
    if success:
        account_file.write_text(json.dumps({"type": "chatgpt", "email": event.get("email", "test@example.com"), "planType": "plus"}))
    send({"method": "account/login/completed", "params": {"loginId": login_id, "success": success, "error": "token-must-not-leak" if not success else None}})


def wait_for_login(login_id):
    while not cancelled.wait(.01):
        if finish_file.exists():
            event = json.loads(finish_file.read_text())
            finish_file.unlink()
            complete(login_id, event)
            return


for line in sys.stdin:
    message = json.loads(line)
    method, params = message.get("method"), message.get("params", {})
    with (home / "fixture-calls.jsonl").open("a") as trace:
        trace.write(json.dumps({"method": method, "params": params}) + "\n")
    result = {}
    if method == "initialize":
        result = {"userAgent": "auth-fixture"}
    elif method == "account/read":
        account = json.loads(account_file.read_text()) if account_file.exists() else None
        result = {"account": account, "requiresOpenaiAuth": True, "accessToken": "never-forward-this-field"}
    elif method == "getAuthStatus":
        result = {"authMethod": "chatgpt", "authToken": "fixture-account-token"}
    elif method == "account/login/start":
        assert params == {"type": "chatgptDeviceCode"}
        login_id = uuid.uuid4().hex
        control = json.loads(control_file.read_text()) if control_file.exists() else {}
        result = {"type": "chatgptDeviceCode", "loginId": login_id,
                  "verificationUrl": "https://auth.openai.com/codex/device" if not control.get("bad_url") else "https://example.com/login",
                  "userCode": "TEST-1234"}
        send({"method": "account/login/completed", "params": {"loginId": "wrong-attempt", "success": True}})
        if control.get("early"):
            complete(login_id, {})
        elif not control.get("bad_url"):
            threading.Thread(target=wait_for_login, args=(login_id,), daemon=True).start()
    elif method == "account/login/cancel":
        cancelled.set()
        result = {"status": "canceled"}
    elif method == "account/logout":
        cancelled.set()
        account_file.unlink(missing_ok=True)
    elif method == "model/list":
        assert params["includeHidden"] is False
        result = {"data": [{"id": "catalog-id", "model": "codex-one", "displayName": "Codex One", "isDefault": True, "internal": "not-for-ui"}], "nextCursor": "page2"} if not params.get("cursor") else {"data": [{"id": "second-id", "model": "codex-two", "displayName": "Codex Two", "isDefault": False}], "nextCursor": None}
    elif method in ("thread/start", "thread/resume"):
        assert params["modelProvider"] == provider
        assert params["approvalPolicy"] == "on-request"
        result = {"thread": {"id": "official-thread"}, "model": params.get("model") or "codex-one"}
    elif method == "turn/start":
        send({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
        send({"method": "item/completed", "params": {"item": {"type": "agentMessage", "id": "answer", "text": "official-provider-ok"}}})
        send({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
        continue
    if "id" in message:
        send({"id": message["id"], "result": result})
