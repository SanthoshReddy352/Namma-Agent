"""Cloud providers that speak the OpenAI chat wire: Google Vertex AI and Azure.

* :class:`VertexProvider` — Vertex's OpenAI-compatible endpoint
  (``…/v1/projects/{project}/locations/{region}/endpoints/openapi``) with a
  short-lived token from Application Default Credentials. Needs the optional
  ``google-auth`` package; project/region come from config (``project`` /
  ``region``) or ``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION`` (default
  ``global``). Model ids carry the publisher prefix: ``google/gemini-2.5-flash``.
* :class:`AzureProvider` — Azure OpenAI / AI Foundry. With an ``api_version``
  (config, ``extra.api_version`` or ``AZURE_OPENAI_API_VERSION``) it uses the SDK's
  ``AzureOpenAI`` client against the resource endpoint (model = deployment name);
  without one it targets Foundry's version-less ``…/openai/v1`` route as a plain
  OpenAI-compatible endpoint.
"""
from __future__ import annotations

import os

from .openai_compat import OpenAICompatProvider

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class VertexProvider(OpenAICompatProvider):
    name = "vertex"

    def __init__(self, model: str = "google/gemini-2.5-flash", project: str = "",
                 region: str = "", **kwargs):
        super().__init__(model=model, **kwargs)
        extra = self.extra or {}
        self.project = (project or extra.get("project") or os.environ.get("GOOGLE_CLOUD_PROJECT")
                        or os.environ.get("VERTEX_PROJECT") or "")
        self.region = (region or extra.get("region") or os.environ.get("GOOGLE_CLOUD_LOCATION")
                       or os.environ.get("VERTEX_LOCATION") or "global")
        if not self.base_url and self.project:
            host = ("aiplatform.googleapis.com" if self.region == "global"
                    else f"{self.region}-aiplatform.googleapis.com")
            self.base_url = (f"https://{host}/v1/projects/{self.project}"
                             f"/locations/{self.region}/endpoints/openapi")
        self._key_optional = True
        self._creds = None

    def _default_key_env(self) -> str:
        return "VERTEX_ACCESS_TOKEN"

    def _requires_key(self) -> bool:
        return False

    def _client_importable(self) -> bool:
        try:
            import google.auth  # noqa: F401
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        return bool(self.project) and self._client_importable()

    def unavailable_reason(self) -> str:
        if not self._client_importable():
            return "Google Vertex AI needs google-auth — install it with: pip install google-auth"
        if not self.project:
            return "set GOOGLE_CLOUD_PROJECT (and optionally GOOGLE_CLOUD_LOCATION) for Vertex AI"
        return ""

    def _token(self) -> str:
        import google.auth
        from google.auth.transport.requests import Request

        if self._creds is None:
            self._creds, _ = google.auth.default(scopes=[_SCOPE])
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self._api_key or self._token(), base_url=self.base_url,
                      timeout=self.timeout_s)


class AzureProvider(OpenAICompatProvider):
    name = "azure"

    def __init__(self, model: str = "", api_version: str = "", **kwargs):
        kwargs.setdefault("api_key_env", "AZURE_FOUNDRY_API_KEY")
        super().__init__(model=model, **kwargs)
        self.api_version = (api_version or (self.extra or {}).get("api_version")
                            or os.environ.get("AZURE_OPENAI_API_VERSION") or "")
        self._key_optional = False

    def _default_key_env(self) -> str:
        return "AZURE_FOUNDRY_API_KEY"

    def is_available(self) -> bool:
        return bool(self.base_url) and super().is_available()

    def unavailable_reason(self) -> str:
        if not self.base_url:
            return "set the Azure endpoint (https://<resource>.openai.azure.com/openai/v1)"
        return super().unavailable_reason()

    def _client(self):
        if self.api_version:
            from openai import AzureOpenAI

            endpoint = self.base_url.split("/openai")[0]
            return AzureOpenAI(azure_endpoint=endpoint, api_key=self._api_key,
                               api_version=self.api_version, timeout=self.timeout_s)
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, base_url=self.base_url, timeout=self.timeout_s)


__all__ = ["AzureProvider", "VertexProvider"]
