"""Server-only settings; secrets never appear in result objects."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    search_agent_provider: Literal["auto", "deepseek", "ddgs", "brave", "tavily", "searxng"] = (
        "auto"
    )
    search_agent_mode: Literal["web", "images"] = "web"
    search_agent_use_model: bool = True
    searxng_url: str = ""
    brave_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    tavily_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    deepseek_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
