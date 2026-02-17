import logging
import os
from typing import Any, cast

import typer  # type: ignore
from rich.console import Console  # type: ignore
from rich.table import Table  # type: ignore

# Ensure providers are registered
import orx_search.providers  # noqa: F401
from orx_search.base import SearchResult
from orx_search.registry import get_all_providers, get_provider, list_providers

app = typer.Typer(help="orx-search modular search CLI")
console = Console()

# Configure logging
logging.basicConfig(level=logging.INFO)


@app.command("list")
def list_commands() -> None:
    """List available search providers."""
    providers = list_providers()
    if not providers:
        console.print("[yellow]No providers found.[/yellow]")
        return

    table = Table(title="Available Providers")
    table.add_column("Name", style="cyan")
    table.add_column("Class", style="green")

    all_providers = get_all_providers()
    for name in providers:
        provider_cls = all_providers[name]
        table.add_row(name, provider_cls.__name__)

    console.print(table)


@app.command("search")
def search(
    provider_name: str = typer.Argument(
        ..., help="Name of the provider (e.g., weather, duckduckgo)"
    ),
    query: str = typer.Argument(..., help="Search query"),
    api_key: str | None = typer.Option(
        None, help="API key for providers that require it (e.g., weather)"
    ),
    forecast: bool = typer.Option(
        False, "--forecast", "-f", help="Get forecast (only for weather provider)"
    ),
) -> None:
    """Execute a search with a specific provider."""
    try:
        provider_cls = get_provider(provider_name)
    except ValueError:
        console.print(f"[red]Error:[/red] Provider '{provider_name}' not found.")
        console.print(f"Available: {', '.join(list_providers())}")
        raise typer.Exit(code=1) from None

    # Initialize provider
    if provider_name == "weather":
        resolved_key = api_key or os.environ.get("OPENWEATHERMAP_API_KEY", "")
        if not resolved_key:
            console.print(
                "[red]Error:[/red] Weather provider requires --api-key or OPENWEATHERMAP_API_KEY env var."
            )
            raise typer.Exit(code=1)

    try:
        if provider_name == "weather":
            # Cast to Any because SearchProvider protocol doesn't define api_key in __init__
            provider = cast(Any, provider_cls)(api_key=resolved_key)
        else:
            provider = provider_cls()
    except Exception as e:
        console.print(f"[red]Error initializing provider:[/red] {e}")
        raise typer.Exit(code=1) from e

    results: list[SearchResult] = []
    with console.status(f"Searching {provider_name} for '{query}'..."):
        try:
            if provider_name == "weather" and forecast:
                results = provider.forecast(query)
            else:
                results = provider.search(query)
        except Exception as e:
            console.print(f"[red]Search failed:[/red] {e}")
            raise typer.Exit(code=1) from e

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Results for '{query}' ({len(results)})")
    table.add_column("Title", style="bold cyan")
    table.add_column("Snippet", style="white")
    table.add_column("URL", style="blue underline")

    for res in results:
        snippet = res.snippet[:200] + "..." if len(res.snippet) > 200 else res.snippet
        table.add_row(res.title, snippet, res.url)

    console.print(table)


if __name__ == "__main__":
    app()
