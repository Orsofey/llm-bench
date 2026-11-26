$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать .venv" }
}
& $python -m pip install -r (Join-Path $root "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить build-зависимости" }
& $python (Join-Path $root "tools\make_icons.py")
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать иконку" }
& $python (Join-Path $root "build_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Сборка EXE завершилась ошибкой" }
Write-Host "`nГотово: $root\dist\LLM Bench.exe" -ForegroundColor Green
