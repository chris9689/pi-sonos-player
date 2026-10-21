# Sync the local working copy to the Raspberry Pi over SSH (alternative to git pull on the Pi).
# Usage: .\sync_to_pi.ps1 -PiHost 192.168.1.50 [-User pi] [-RemoteDir pi-sonos-player] [-Deploy]
param(
    [Parameter(Mandatory = $true)][string]$PiHost,
    [string]$User = $env:PI_USER,
    [string]$RemoteDir = "pi-sonos-player",
    [switch]$Deploy
)

$ErrorActionPreference = "Stop"
if (-not $User) { $User = "pi" }
$target = "$User@$PiHost"

# Only ship tracked files (no venv, .env or caches)
$archive = Join-Path $env:TEMP "pi-sonos-player.tar"
git -C $PSScriptRoot archive --format=tar -o $archive HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }

try {
    Write-Host "Copying to ${target}:~/$RemoteDir ..."
    scp $archive "${target}:/tmp/pi-sonos-player.tar"
    ssh $target "mkdir -p ~/$RemoteDir && tar -xf /tmp/pi-sonos-player.tar -C ~/$RemoteDir && rm /tmp/pi-sonos-player.tar"

    if ($Deploy) {
        ssh -t $target "bash ~/$RemoteDir/deploy/deploy.sh"
    }
    Write-Host "Sync completed."
}
finally {
    Remove-Item $archive -ErrorAction SilentlyContinue
}
