@echo off
title Instalador TradingAgents B3
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Payload "%~dp0payload.zip"
