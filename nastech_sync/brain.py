"""
NasTech Brain — AI intelligence layer.

Supports:
  • OpenAI (GPT-4o / Codex) via OPENAI_API_KEY
  • Ollama Cloud (api.ollama.com) via OLLAMA_API_KEY  — OpenAI-compatible /v1 endpoint
  • Self-hosted Ollama via native /api/chat endpoint

The brain can:
  • Answer questions about the codebase / NasTech-Agent
  • Summarise new upstream commits in NasTech language
  • Generate changelog entries
  • Explain diffs
"""

import os
import json
import logging
import httpx
from typing import Optional, AsyncGenerator

logger = logging.getLogger("nastech_sync.brain")

SYSTEM_PROMPT = """You are the NasTech AI Brain — the intelligence core of NasTech-Agent, built under the NasTech Research umbrella.

Your knowledge base:
• NasTech-Agent is a branded fork maintained by NasTech Research, kept in sync with an upstream open-weight language model project.
• The upstream source provides a family of open-weight language models based on Mistral and Llama architectures, fine-tuned for function calling, reasoning, and agent tasks.
• NasTech Research is the NasTech organisation's AI research arm. NasTech-Agent represents their frontier model capabilities.
• You know the full commit history, model architecture, training philosophy, and tooling of NasTech-Agent.
• NasTech brand values: cutting-edge, open, community-first, transparent.

When answering:
• Always speak as NasTech — refer to the product as "NasTech-Agent" or "NasTech".
• You may reference the upstream source for technical context, but frame it as "the upstream source".
• Be concise and direct. No fluff.
• For code/diff questions, focus on practical impact.
• For commit summaries, write in active voice: "Adds X", "Fixes Y", "Improves Z"."""


class BrainProvider:
    name: str = "base"

    async def chat(self, messages: list[dict], stream: bool = False) -> str:
        raise NotImplementedError

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        raise NotImplementedError

    def available(self) -> bool:
        return False


class OpenAIProvider(BrainProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    async def chat(self, messages: list[dict], stream: bool = False) -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key)
        resp = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key)
        async with client.chat.completions.stream(
            model=self.model,
            messages=messages,
            temperature=0.3,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk


class OllamaCloudProvider(BrainProvider):
    """
    Ollama Cloud provider — uses the OpenAI-compatible /v1 endpoint.
    Works with api.ollama.com (requires OLLAMA_API_KEY) or any OpenAI-compatible
    Ollama deployment (Fly.io, Render, etc.) that serves /v1/chat/completions.
    """
    name = "ollama"

    def __init__(self, base_url: str = "https://api.ollama.com",
                 model: str = "llama3.1", api_key: str = ""):
        # Normalise: strip /v1 suffix if present — openai SDK appends it
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.model = model
        self.api_key = api_key or "ollama"  # native Ollama ignores the key

    def available(self) -> bool:
        """Quick ping — check /v1/models endpoint."""
        try:
            headers = {}
            if self.api_key and self.api_key != "ollama":
                headers["Authorization"] = f"Bearer {self.api_key}"
            with httpx.Client(timeout=5) as c:
                r = c.get(f"{self.base_url}/v1/models", headers=headers)
                return r.status_code in (200, 401, 403)  # 401/403 = server alive, auth issue
        except Exception:
            return False

    async def chat(self, messages: list[dict], stream: bool = False) -> str:
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=f"{self.base_url}/v1",
        )
        resp = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=f"{self.base_url}/v1",
        )
        async with client.chat.completions.stream(
            model=self.model,
            messages=messages,
            temperature=0.3,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk


class OllamaNativeProvider(BrainProvider):
    """
    Self-hosted Ollama using native /api/chat endpoint.
    Use for local or self-hosted Ollama that does NOT serve /v1.
    """
    name = "ollama_native"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def available(self) -> bool:
        try:
            with httpx.Client(timeout=2) as c:
                r = c.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def chat(self, messages: list[dict], stream: bool = False) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            pass


def _is_cloud_ollama(url: str) -> bool:
    """Return True if this URL should use the OpenAI-compatible /v1 provider."""
    u = url.lower()
    return (
        "api.ollama.com" in u
        or "/v1" in u
        or "fly.dev" in u
        or "render.com" in u
        or "onrender.com" in u
    )


class NasTechBrain:
    """
    Multi-provider AI brain.
    Tries providers in order: OpenAI → Ollama Cloud → Ollama Native → fallback echo.
    """

    def __init__(self, config):
        self.config = config
        self._providers: list[BrainProvider] = []
        self._history: list[dict] = []  # conversation history
        self._build_providers()

    def _build_providers(self):
        openai_key = (
            os.environ.get("OPENAI_API_KEY")
            or getattr(self.config, "openai_api_key", None)
        )
        if openai_key:
            model = getattr(self.config, "openai_model", "gpt-4o")
            self._providers.append(OpenAIProvider(api_key=openai_key, model=model))

        ollama_url = getattr(self.config, "ollama_url", "https://api.ollama.com")
        ollama_model = getattr(self.config, "ollama_model", "llama3.1")
        ollama_api_key = (
            os.environ.get("OLLAMA_API_KEY")
            or getattr(self.config, "ollama_api_key", "")
        )

        if ollama_url:
            if _is_cloud_ollama(ollama_url):
                self._providers.append(OllamaCloudProvider(
                    base_url=ollama_url,
                    model=ollama_model,
                    api_key=ollama_api_key,
                ))
            else:
                self._providers.append(OllamaNativeProvider(
                    base_url=ollama_url,
                    model=ollama_model,
                ))

    def _active_provider(self) -> Optional[BrainProvider]:
        for p in self._providers:
            if p.available():
                return p
        return None

    def provider_status(self) -> dict:
        result = {}
        for p in self._providers:
            result[p.name] = p.available()
        return result

    async def ask(self, question: str, context: str = "") -> str:
        """Ask a question, optionally with extra context (e.g. a diff or commit)."""
        provider = self._active_provider()
        if not provider:
            return (
                "⚠️  No AI provider available. Set OPENAI_API_KEY or OLLAMA_API_KEY.\n"
                f"Your question: {question}"
            )

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Include recent conversation history
        messages.extend(self._history[-6:])

        user_content = question
        if context:
            user_content = f"Context:\n```\n{context}\n```\n\nQuestion: {question}"

        messages.append({"role": "user", "content": user_content})

        try:
            answer = await provider.chat(messages)
            # Save to history
            self._history.append({"role": "user", "content": question})
            self._history.append({"role": "assistant", "content": answer})
            return answer
        except Exception as exc:
            logger.error("Brain error (%s): %s", provider.name, exc)
            # Try next available provider on error
            for fallback in self._providers:
                if fallback is provider:
                    continue
                if fallback.available():
                    try:
                        answer = await fallback.chat(messages)
                        self._history.append({"role": "user", "content": question})
                        self._history.append({"role": "assistant", "content": answer})
                        return answer
                    except Exception as exc2:
                        logger.error("Fallback brain error (%s): %s", fallback.name, exc2)
            return f"⚠️  Error from {provider.name}: {exc}"

    async def stream_ask(self, question: str, context: str = "") -> AsyncGenerator[str, None]:
        """Streaming version of ask()."""
        provider = self._active_provider()
        if not provider:
            yield "⚠️  No AI provider available. Set OPENAI_API_KEY or OLLAMA_API_KEY."
            return

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._history[-6:])

        user_content = question
        if context:
            user_content = f"Context:\n```\n{context}\n```\n\nQuestion: {question}"
        messages.append({"role": "user", "content": user_content})

        full_response = ""
        try:
            async for chunk in provider.stream_chat(messages):
                full_response += chunk
                yield chunk
        except Exception as exc:
            logger.error("Stream brain error (%s): %s", provider.name, exc)
            yield f"\n⚠️  Stream error: {exc}"

        self._history.append({"role": "user", "content": question})
        self._history.append({"role": "assistant", "content": full_response})

    async def summarise_commit(self, commit: dict, diff_text: str = "") -> str:
        """Generate a NasTech-branded commit summary."""
        prompt = (
            f"Upstream commit:\n"
            f"SHA: {commit.get('sha', '')[:12]}\n"
            f"Message: {commit.get('subject', '')}\n"
        )
        if diff_text:
            prompt += f"\nDiff (first 2000 chars):\n{diff_text[:2000]}"
        prompt += (
            "\n\nWrite a 1-3 sentence NasTech-branded release note for this change. "
            "Say what changed, why it matters for NasTech-Agent users. "
            "Frame it as a NasTech-Agent update — do NOT say it comes from an external upstream by name."
        )
        return await self.ask(prompt)

    async def explain_branding(self, original: str, branded: str) -> str:
        """Explain what branding changed and why."""
        prompt = (
            f"Original text:\n{original}\n\n"
            f"After NasTech branding:\n{branded}\n\n"
            "Explain in 2 sentences what was rebranded and what it means for NasTech-Agent."
        )
        return await self.ask(prompt)

    def clear_history(self):
        self._history = []
