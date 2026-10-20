# Sync local project to Raspberry Pi
$env:SSH_ASKPASS = "C:\Users\chg68\.gemini\antigravity\brain\b8e3a847-0dec-4eb7-be58-7c9ca9f10370\scratch\askpass.exe"
$env:SSH_ASKPASS_REQUIRE = "force"
$env:DISPLAY = "localhost:0.0"

$source = "C:\Users\chg68\.gemini\antigravity\scratch\pi-sonos-player"
$target = "chris@192.168.178.154:/home/chris/"

Write-Host "Creating target folder on Pi..."
& ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile="NUL" chris@192.168.178.154 "mkdir -p /home/chris/pi-sonos-player"

Write-Host "Copying files to Pi..."
& scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile="NUL" "$source\*" "$target/pi-sonos-player/"

Write-Host "Sync completed successfully!"
