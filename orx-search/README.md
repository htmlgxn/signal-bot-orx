# orx-search

Standalone modular search package extracted from `signal-bot-orx`.

## Installation

```bash
uv sync
```

## Usage

### CLI

```bash
# List available providers
orx-search list

# Search with a provider
orx-search search duckduckgo "Python programming"
orx-search search wikipedia "Alan Turing"
orx-search search weather "London" --api-key YOUR_KEY
```

### Programmatic

```python
from orx_search import get_provider
import orx_search.providers  # registers all providers

DDG = get_provider("duckduckgo")
provider = DDG()
results = provider.search("Python programming")
for r in results:
    print(f"{r.title}: {r.url}")
```

## Providers

| Name | Description |
|------|-------------|
| `duckduckgo` | Web search via DuckDuckGo HTML |
| `wikipedia` | Wikipedia article lookup |
| `weather` | Current weather via OpenWeatherMap |
