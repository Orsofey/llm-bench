$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$android = Join-Path $root "android"
$pythonExe = (& python -c "import sys; print(sys.executable)").Trim().Replace("\", "/")
Push-Location $android
try {
    & ".\gradlew.bat" "-PllmBenchPython=$pythonExe" assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "Сборка APK завершилась ошибкой" }
} finally {
    Pop-Location
}
New-Item -ItemType Directory -Force (Join-Path $root "dist") | Out-Null
Copy-Item -Force (Join-Path $android "app\build\outputs\apk\debug\app-debug.apk") (Join-Path $root "dist\LLM-Bench-Android.apk")
Write-Host "`nГотово: $root\dist\LLM-Bench-Android.apk" -ForegroundColor Green
