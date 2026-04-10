@echo off
REM UAC -> elevated PowerShell -> register_version_digest_task.ps1 (VersionDigest daily 09:40)
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0'; Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path (Get-Location) 'register_version_digest_task.ps1')"
