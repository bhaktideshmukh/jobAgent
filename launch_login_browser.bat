@echo off
echo ======================================================================
echo Launching Native Google Chrome for Indeed / LinkedIn Login
echo Profile: C:\langgraph\browser_profile
echo ======================================================================
echo Opening Chrome without any automation flags.
echo Please log into your Indeed account.
echo When you are done, simply close the Chrome browser window.
echo ======================================================================
"C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\langgraph\browser_profile" "https://in.indeed.com"

