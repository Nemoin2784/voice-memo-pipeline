# Remove the inbound BLOCK rules that stop phones from reaching python.exe,
# then add proper ALLOW rules for the transcription server.
# ASCII only on purpose: cmd + PowerShell 5.1 mis-parse UTF-8 .ps1 files here.
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$py = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\.tools\python310\python.exe')).Path
Write-Host "python : $py"

$whatIf = @{}
if ($DryRun) { $whatIf['WhatIf'] = $true; Write-Host '(dry run: nothing will be changed)' }

# --- 1) inbound BLOCK rules for this exact program (path may be stored lowercase) ---
$blocked = @(
    Get-NetFirewallApplicationFilter |
        Where-Object { $_.Program -and $_.Program.TrimEnd('\') -ieq $py } |
        Get-NetFirewallRule |
        Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' -and $_.Enabled -eq 'True' }
)
if ($blocked.Count -gt 0) {
    Write-Host ("found " + $blocked.Count + " inbound block rule(s) for this python:")
    $blocked | ForEach-Object { Write-Host ("  - " + $_.DisplayName + "  [" + $_.Name + "]") }
    $blocked | Remove-NetFirewallRule @whatIf
    if (-not $DryRun) { Write-Host 'removed.' }
} else {
    Write-Host 'no inbound block rules for this python: good'
}

# --- 2) drop our own earlier rules (some were stored with a non-normalized ..\ path) ---
$old = @(Get-NetFirewallRule -DisplayName 'VoiceTranscribe*' -ErrorAction SilentlyContinue)
if ($old.Count -gt 0) {
    Write-Host ("removing " + $old.Count + " old VoiceTranscribe rule(s) to recreate them cleanly")
    $old | Remove-NetFirewallRule @whatIf
}

# --- 3) allow the program and the TCP port ---
if (-not $DryRun) {
    # Profile Any: the xEdge virtual adapter is usually classified as Public,
    # so Domain,Private only would keep the phone out even on the tailnet.
    New-NetFirewallRule -DisplayName 'VoiceTranscribe python' -Direction Inbound -Program $py `
        -Action Allow -Profile Any | Out-Null
    New-NetFirewallRule -DisplayName 'VoiceTranscribe 8765' -Direction Inbound -Protocol TCP `
        -LocalPort 8765 -Action Allow -Profile Any | Out-Null
    Write-Host 'added allow rules for python.exe and TCP 8765 (all profiles)'
}

# --- 4) report the end state ---
Write-Host ''
Write-Host '--- inbound rules mentioning python / VoiceTranscribe ---'
Get-NetFirewallRule -Direction Inbound -Enabled True -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'python|VoiceTranscribe' } |
    Select-Object DisplayName, Action, Profile |
    Format-Table -AutoSize | Out-String | Write-Host
Write-Host 'Expect: NO row with Action=Block.'
