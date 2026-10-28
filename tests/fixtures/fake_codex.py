"""A subprocess fixture that speaks the public app-server JSON-lines protocol."""
import json
import sys
from pathlib import Path


def send(value):
    print(json.dumps(value), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method in ("thread/start", "thread/resume", "turn/start"):
        Path(method.replace("/", "-") + ".json").write_text(json.dumps(message["params"]))
    if method == "initialize":
        send({"id": message["id"], "result": {"userAgent": "fake-codex"}})
    elif method in ("thread/start", "thread/resume"):
        if message["params"].get("approvalPolicy") not in ("on-request", "never"):
            raise RuntimeError("approval policy missing")
        send({"id": message["id"], "result": {"thread": {"id": "thread-1"}, "approvalsReviewer": message["params"].get("approvalsReviewer")}})
    elif method == "turn/start":
        send({"id": message["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        send({"method": "item/started", "params": {"item": {
            "id": "cmd-1", "type": "commandExecution", "command": "pwd", "status": "inProgress",
        }}})
        send({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {
            "itemId": "cmd-1", "threadId": "thread-1", "turnId": "turn-1", "command": "pwd",
            "availableDecisions": ["accept", "decline"],
        }})
    elif method == "turn/interrupt":
        Path("interrupt.marker").write_text("interrupted")
        send({"id": message["id"], "result": {}})
        send({"method": "serverRequest/resolved", "params": {"threadId": "thread-1", "requestId": "approval-1"}})
        send({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "interrupted"}}})
    elif message.get("id") == "approval-1":
        accepted = message["result"]["decision"] == "accept"
        send({"method": "item/agentMessage/delta", "params": {"itemId": "answer-1", "delta": "hello "}})
        send({"method": "item/agentMessage/delta", "params": {"itemId": "answer-1", "delta": "deck"}})
        send({"method": "item/completed", "params": {"item": {
            "id": "answer-1", "type": "agentMessage", "text": "hello deck" if accepted else "declined",
        }}})
        send({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
