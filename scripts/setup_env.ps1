param(
    [string]$PythonBin = "py",
    [string]$PythonArgs = "-3",
    [string]$VenvDir = ".venv",
    [string]$PipIndexUrl = "https://pypi.org/simple"
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param([string]$Code)
    & $PythonBin $PythonArgs -c $Code
}

try {
    & $PythonBin $PythonArgs --version | Out-Null
} catch {
    throw "error: python interpreter not found: $PythonBin $PythonArgs"
}

Invoke-Python @"
import sys
if sys.version_info < (3, 11):
    raise SystemExit(
        f\"error: Python 3.11+ required, got {sys.version.split()[0]}. Use -PythonArgs '-3.11'\"
    )
"@

& $PythonBin $PythonArgs -m venv $VenvDir

$venvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "error: venv python not found at $venvPython"
}

& $venvPython -m ensurepip --upgrade | Out-Null
# Python 3.12+ venvs ship without setuptools, which --no-build-isolation needs.
& $venvPython -m pip install --disable-pip-version-check "setuptools>=68" wheel --index-url $PipIndexUrl
if ($LASTEXITCODE -ne 0) { throw "error: installing setuptools/wheel failed" }
& $venvPython -m pip install --disable-pip-version-check -e '.[test]' --no-build-isolation --index-url $PipIndexUrl
if ($LASTEXITCODE -ne 0) { throw "error: installing project dependencies failed" }

& $venvPython -c "import fastapi, requests, yaml, pytest, lupa; print('setup-check: fastapi', fastapi.__version__); print('setup-check: requests', requests.__version__); print('setup-check: pyyaml', yaml.__version__); print('setup-check: pytest', pytest.__version__); print('setup-check: lupa', lupa.__version__)"

Write-Host "setup complete: activate with '.\\$VenvDir\\Scripts\\Activate.ps1'"
