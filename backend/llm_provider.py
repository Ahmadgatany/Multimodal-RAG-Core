from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image


class ProviderRequestError(RuntimeError):
    """A sanitized provider failure suitable for logs and API error mapping."""

    def __init__(self, provider: str, message: str, status_code: Optional[int] = None):
        self.provider = provider
        self.status_code = status_code
        prefix = f"{provider} request failed"
        if status_code is not None:
            prefix += f" ({status_code})"
        super().__init__(f"{prefix}: {message[:500]}")


class GeminiProvider:
    """Small provider boundary so the RAG pipeline is independent of an LLM vendor."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=google")

        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(
        self,
        prompt: str,
        image: Optional[Image.Image] = None,
        max_output_tokens: int = 2048,
    ) -> str:
        from google.genai import types

        contents = [prompt]
        if image is not None:
            image_buffer = BytesIO()
            image.save(image_buffer, format=image.format or "PNG")
            contents.append(
                types.Part.from_bytes(
                    data=image_buffer.getvalue(),
                    mime_type=Image.MIME.get(image.format, "image/png"),
                )
            )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                    temperature=0.2,
                ),
            )
        except Exception as error:
            status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
            status_code = status_code if isinstance(status_code, int) else None
            raise ProviderRequestError("Gemini", str(error), status_code) from error
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        if finish_reason is not None and getattr(finish_reason, "name", str(finish_reason)) == "MAX_TOKENS":
            raise RuntimeError("Gemini stopped because it reached the output token limit")
        return text.strip()


class OpenRouterProvider:
    """OpenAI-compatible OpenRouter provider with optional image input."""

    def __init__(self, api_key: str, model: str, site_url: str, app_name: str):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        self.api_key = api_key
        self.model = model
        self.site_url = site_url
        self.app_name = app_name

    def generate(
        self,
        prompt: str,
        image: Optional[Image.Image] = None,
        max_output_tokens: int = 512,
    ) -> str:
        import base64
        import requests

        content = [{"type": "text", "text": prompt}]
        if image is not None:
            image_buffer = BytesIO()
            image.save(image_buffer, format=image.format or "PNG")
            encoded_image = base64.b64encode(image_buffer.getvalue()).decode("ascii")
            mime_type = Image.MIME.get(image.format, "image/png")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                }
            )

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.site_url,
                    "X-Title": self.app_name,
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": max_output_tokens,
                    "temperature": 0.2,
                },
                timeout=120,
            )
        except requests.RequestException as error:
            raise ProviderRequestError("OpenRouter", str(error)) from error
        if not response.ok:
            raise ProviderRequestError("OpenRouter", response.text, response.status_code)
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderRequestError("OpenRouter", "provider returned invalid JSON", response.status_code) from error
        if payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                message = error.get("message") or "Unknown OpenRouter error"
                code = error.get("code")
                raise ProviderRequestError("OpenRouter", f"{code}: {message}", response.status_code)
            raise ProviderRequestError("OpenRouter", str(error), response.status_code)
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderRequestError("OpenRouter", "provider returned an unexpected response", response.status_code) from error
        if not text:
            raise RuntimeError("OpenRouter returned an empty response")
        return text.strip()
