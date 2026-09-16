@echo off
cd /d "%~dp0"
echo AVA Vercel deployment
where npx >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm was not found. Install Node.js first, then run this file again.
  pause
  exit /b 1
)
echo.
echo If you have not logged in before, Vercel will open a browser/login flow.
echo.
npx vercel login
if errorlevel 1 (
  echo Vercel login failed.
  pause
  exit /b 1
)
npx vercel --prod
if errorlevel 1 (
  echo Vercel deployment failed. Keep this window open and copy the error into ChatGPT.
  pause
  exit /b 1
)
echo.
echo Deployment finished. Copy the public URL shown above.
pause
