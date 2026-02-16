#!/bin/bash
# Format the codebase using ruff and fix exception syntax
# Usage: ./scripts/format.sh

set -e

echo "Running ruff formatter..."
uv run ruff format .

echo "Fixing exception syntax (ruff/black bug workaround)..."
# Fix two-exception cases: except Exception1, Exception2: → except (Exception1, Exception2):
find src/signal_bot_orx -name "*.py" -exec sed -i 's/except \([A-Za-z_][A-Za-z0-9_.]*\), \([A-Za-z_][A-Za-z0-9_.]*\):/except (\1, \2):/g' {} \;

# Fix three-exception cases: except Exception1, Exception2, Exception3: → except (Exception1, Exception2, Exception3):
find src/signal_bot_orx -name "*.py" -exec sed -i 's/except \([A-Za-z_][A-Za-z0-9_.]*\), \([A-Za-z_][A-Za-z0-9_.]*\), \([A-Za-z_][A-Za-z0-9_.]*\):/except (\1, \2, \3):/g' {} \;

echo "✅ Formatting complete!"
