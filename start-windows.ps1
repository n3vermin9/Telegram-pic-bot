Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required: https://www.docker.com/products/docker-desktop/"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Start Docker Desktop, then run this script again."
}

if (-not (Test-Path ".env")) {
    $secureToken = Read-Host "New Telegram bot token" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plainToken)) {
            throw "Token cannot be empty."
        }
        @(
            "BOT_TOKEN=$plainToken"
            "LOG_LEVEL=INFO"
        ) | Set-Content -Path ".env" -Encoding ascii
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $plainToken = $null
    }
}

docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not start the bot."
}
docker compose ps
Write-Host "Bot is running and will restart automatically with Docker."
