#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a local virtual environment using approved package source defaults.
# - Uses official PyPI index by default (https://pypi.org/simple).
# - Uses --no-build-isolation to avoid transient build-env dependency fetch issues.

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: python interpreter not found: $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

# Keep bootstrap resilient in restricted environments: only ensure pip is present
# and avoid forced upgrades that may require network access.
python -m ensurepip --upgrade >/dev/null 2>&1 || true

# Install project runtime + test dependencies from approved source.
python -m pip install -e '.[test]' --no-build-isolation --index-url "$PIP_INDEX_URL"

python - <<'PY'
import fastapi, requests, yaml, pytest
print('setup-check: fastapi', fastapi.__version__)
print('setup-check: requests', requests.__version__)
print('setup-check: pyyaml', yaml.__version__)
print('setup-check: pytest', pytest.__version__)
PY

echo "setup complete: activate with 'source $VENV_DIR/bin/activate'"
