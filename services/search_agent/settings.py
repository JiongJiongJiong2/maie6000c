"""Server-only settings; secrets never appear in result objects."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    search_agent_provider: Literal["auto", "deepseek", "ddgs", "brave", "tavily", "searxng"] = (
        "auto"
    )
    search_agent_ddgs_backend: (
        Literal["bing", "duckduckgo", "brave", "google", "yahoo", "yandex", "wikipedia"] | None
    ) = None
    search_agent_domains: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("search_agent_domains")
    @classmethod
    def domain_scope(cls, values):
        import re

        if any(not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}", v) for v in values):
            raise ValueError("Search scope requires lowercase domain names")
        return list(dict.fromkeys(values))

    search_agent_mode: Literal["web", "images"] = "web"
    search_agent_use_model: bool = True
    searxng_url: str = ""
    brave_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    tavily_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    deepseek_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
