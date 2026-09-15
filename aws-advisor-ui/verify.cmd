@echo off
cd /d "D:\! Sciqus Internship\AWS Agent\aws-advisor-ui"
call .venv\Scripts\python.exe -m pytest tests -q > api-tests.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> api-tests.log
call npm run build > ui-build.log 2>&1
echo BUILD_EXIT=%ERRORLEVEL% >> ui-build.log
node scripts\shots.mjs final > shots-final.log 2>&1
echo SHOTS_EXIT=%ERRORLEVEL% >> shots-final.log
