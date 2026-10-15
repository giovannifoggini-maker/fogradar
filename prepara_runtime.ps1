param([switch]$IncludeTunnel)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = $PSScriptRoot
$Tools = Join-Path $Root 'tools'
$Downloads = Join-Path $Tools 'downloads'
$PythonDir = Join-Path $Tools 'python'
$PythonExe = Join-Path $PythonDir 'python.exe'
$CloudflaredExe = Join-Path $Tools 'cloudflared.exe'
New-Item -ItemType Directory -Force -Path $Tools, $Downloads | Out-Null

function Get-VerifiedDownload([string]$Url, [string]$Destination, [string]$ExpectedSha256, [string]$Label) {
    if (Test-Path $Destination) {
        $existing = (Get-FileHash -Algorithm SHA256 -Path $Destination).Hash.ToLowerInvariant()
        if ($existing -eq $ExpectedSha256.ToLowerInvariant()) { return }
        Remove-Item -Force $Destination
    }
    $part = "$Destination.part"
    if (Test-Path $part) { Remove-Item -Force $part }
    Write-Host "Download componente ufficiale: $Label" -ForegroundColor Cyan
    Invoke-WebRequest -Uri $Url -OutFile $part -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 -Path $part).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        Remove-Item -Force $part -ErrorAction SilentlyContinue
        throw "Controllo SHA-256 fallito per $Label. File rimosso; nessun componente e' stato avviato."
    }
    Move-Item -Force $part $Destination
}

# Portable Python 3.13.16 (official embeddable distribution). Extracted only inside this folder.
if (-not (Test-Path $PythonExe)) {
    $pythonZip = Join-Path $Downloads 'python-3.13.16-embeddable-amd64.zip'
    Get-VerifiedDownload `
        'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embeddable-amd64.zip' `
        $pythonZip `
        '589dc1e9d02549ca5f680710307ff9b77f6e3ffc4aa3efccd7fa54eeeafac94b' `
        'Python portatile 3.13.16 x64'
    New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
    Expand-Archive -LiteralPath $pythonZip -DestinationPath $PythonDir -Force
    if (-not (Test-Path $PythonExe)) { throw 'Python portatile non contiene python.exe; estrazione non riuscita.' }
    Write-Host 'Python portatile pronto nella cartella tools\python.' -ForegroundColor Green
}

if ($IncludeTunnel) {
    Get-VerifiedDownload `
        'https://github.com/cloudflare/cloudflared/releases/download/2026.10.0/cloudflared-windows-amd64.exe' `
        $CloudflaredExe `
        '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c' `
        'Cloudflare Tunnel (Windows x64)'
    Write-Host 'Cloudflare Tunnel pronto nella cartella tools. Non e'' stato installato nel sistema.' -ForegroundColor Green
}
Write-Host ''
Write-Host 'Componenti pronti. Sono conservati nella cartella tools del progetto.' -ForegroundColor Green
