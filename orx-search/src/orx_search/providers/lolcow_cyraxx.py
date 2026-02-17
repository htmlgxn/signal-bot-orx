"""Cyraxx wiki search provider."""

from __future__ import annotations

from orx_search.providers.lolcow import LolcowProvider
from orx_search.registry import register


@register
class LolcowCyraxxProvider(LolcowProvider):
    name = "lolcow_cyraxx"
    source = "Cyraxx Wiki"
    base_url = "https://wiki.lolcow.city/cyraxx/api.php"
