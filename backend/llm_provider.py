from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image


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
        max_output_tokens: int = 512,
    ) -> str:
        contents = [prompt]
        if image is not None:
            image_buffer = BytesIO()
            image.save(image_buffer, format=image.format or "PNG")
            contents.append(
                {
                    "inline_data": {
                        "mime_type": Image.MIME.get(image.format, "image/png"),
                        "data": image_buffer.getvalue(),
                    }
                }
            )

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config={"max_output_tokens": max_output_tokens, "temperature": 0.2},
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
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
        if not response.ok:
            raise RuntimeError(f"OpenRouter request failed ({response.status_code}): {response.text[:500]}")
        payload = response.json()
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("OpenRouter returned an unexpected response") from error
        if not text:
            raise RuntimeError("OpenRouter returned an empty response")
        return text.strip()
