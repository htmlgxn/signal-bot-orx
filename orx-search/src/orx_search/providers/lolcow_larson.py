"""Daniel Larson wiki search provider."""

from __future__ import annotations

from orx_search.providers.lolcow import LolcowProvider
from orx_search.registry import register


@register
class LolcowLarsonProvider(LolcowProvider):
    name = "lolcow_larson"
    source = "Daniel Larson Wiki"
    base_url = "https://wiki.lolcow.city/daniel-larson/api.php"
