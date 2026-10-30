$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
uv sync --extra dev
uv run nvs doctor
uv run nvs serve
