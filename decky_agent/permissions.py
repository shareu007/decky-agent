"""Translate the selected Codex permission mode into native protocol policy."""

MODES = {
    "ask": ("on-request", "user", "workspace-write"),
    "auto": ("on-request", "auto_review", "workspace-write"),
    "full": ("never", "user", "danger-full-access"),
}


def codex_permissions(settings: dict) -> tuple[dict, dict]:
    mode = settings.get("permission_mode", "ask")
    if mode not in MODES:
        raise ValueError("未知权限模式，请重新选择")
    approval, reviewer, sandbox = MODES[mode]
    policy = {"approvalPolicy": approval, "approvalsReviewer": reviewer}
    turn_sandbox = {"type": "dangerFullAccess"} if mode == "full" else {
        "type": "workspaceWrite", "writableRoots": [settings["workspace"]],
        "networkAccess": settings["network_access"],
    }
    return {**policy, "sandbox": sandbox}, {**policy, "sandboxPolicy": turn_sandbox}
