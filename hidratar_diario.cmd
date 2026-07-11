@echo off
rem Corrida diaria del backfill SoT por-jugador (Task Scheduler, 7:30 PM Lima).
rem La cuota de API-Football Free resetea a las 00:00 UTC = 7:00 PM Lima; si la
rem ventana ya se uso, el script aborta con gracia (ApiFootballError) sin
rem corromper sot_backfill_progreso. Log: hidratar_diario.log (gitignored).
cd /d %~dp0
echo ===== %date% %time% hidratar diario ===== >> hidratar_diario.log
python download_sot_jugador.py hidratar >> hidratar_diario.log 2>&1
echo. >> hidratar_diario.log
