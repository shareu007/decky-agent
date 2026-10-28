"""Decky Loader Python entrypoint. Runs without the _root manifest flag."""
import os
import sys
from pathlib import Path

import decky

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT))

from decky_agent.service import AgentService


class Plugin:
    async def _main(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise RuntimeError("Decky Agent 必须以普通用户运行；请移除 _root 标志")
        self.service = AgentService(
            Path(decky.DECKY_PLUGIN_SETTINGS_DIR),
            Path(decky.DECKY_PLUGIN_RUNTIME_DIR),
            PLUGIN_ROOT, Path(decky.DECKY_USER_HOME),
        )
        decky.logger.info("Decky Agent ready")

    async def _unload(self):
        if hasattr(self, "service"):
            await self.service.close()

    async def get_bootstrap(self):
        return self.service.bootstrap()

    async def report_frontend(self, details: dict):
        self.service.report_frontend(details)

    async def save_settings(self, changes: dict):
        return self.service.save_settings(changes)

    async def list_models(self):
        return await self.service.models()

    async def get_model_catalog(self):
        return await self.service.model_catalog()

    async def get_account_status(self):
        return await self.service.account_status()

    async def login_chatgpt(self):
        return await self.service.login_chatgpt()

    async def cancel_chatgpt_login(self, login_id: str):
        return await self.service.cancel_login(login_id)

    async def logout_chatgpt(self):
        return await self.service.logout_chatgpt()

    async def create_session(self):
        return self.service.create_session()

    async def delete_session(self, session_id: str):
        self.service.delete_session(session_id)

    async def get_session(self, session_id: str, revision: int = -1):
        return self.service.snapshot(session_id, revision)

    async def start_task(self, session_id: str, prompt: str):
        return await self.service.start(session_id, prompt)

    async def stop_task(self, session_id: str):
        await self.service.stop(session_id)

    async def respond_request(self, session_id: str, request_id: str, approved: bool, answers: dict):
        self.service.respond(session_id, request_id, approved, answers)

    async def start_recording(self, session_id: str):
        return await self.service.start_recording(session_id)

    async def recording_status(self, recording_id: str):
        return await self.service.speech.status(recording_id)

    async def finish_recording(self, recording_id: str):
        return await self.service.speech.finish(recording_id)

    async def cancel_recording(self, recording_id: str):
        await self.service.speech.cancel(recording_id)
