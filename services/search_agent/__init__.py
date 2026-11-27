"""Bounded web discovery, independent of the UI and business database."""

from .core import search_web
from .models import SearchBudget, SearchResult

__all__ = ["search_web", "SearchBudget", "SearchResult"]
