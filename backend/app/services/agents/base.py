"""Agent base class — LLM call + JSON parse + trace."""

import asyncio
import json
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    agent: str
    data: dict
    duration_ms: int = 0
    error: Optional[str] = None


class AgentBase:
    """Base agent with LLM calling and JSON parsing."""

    def __init__(self, name: str, system_prompt: str, model: str = "qwen-max",
                 api_key: str | None = None, api_provider: str | None = None,
                 api_base_url: str | None = None):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.api_key = api_key
        self.api_provider = api_provider
        self.api_base_url = api_base_url

    async def run(self, **kwargs) -> AgentResult:
        t0 = time.time()
        try:
            prompt = self.system_prompt.format(**kwargs)
            response = await self._call_llm(prompt)
            data = self._parse_json(response)
            return AgentResult(agent=self.name, data=data, duration_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            logger.error(f"[{self.name}] Failed: {e}")
            return AgentResult(agent=self.name, data={}, duration_ms=int((time.time() - t0) * 1000), error=str(e))

    async def _call_llm(self, prompt: str, override_system: str | None = None) -> str:
        from app.services.qwen_client import chat
        system_msg = override_system if override_system else "你只输出JSON，不要加任何markdown标记或解释文字。"
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]
        return await asyncio.to_thread(
            chat, messages, self.model, self.api_key,
            self.api_provider if not self.api_base_url else None,
            base_url=self.api_base_url, temperature=0.3, max_tokens=2048,
        )

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"No JSON found in: {text[:200]}")
