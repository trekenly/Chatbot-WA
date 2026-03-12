# =============================================================
#  ChatBot V11 — Step 1: Upload project to Ubuntu server
#  Run this from PowerShell on your Windows machine
# =============================================================

$LOCAL_PROJECT = "C:\Users\Pc\Desktop\ChatBot_Assets\ChatBot_V11_react\ChatBot_V11"
$SERVER        = "ubuntu@13.250.220.109"
$REMOTE_HOME   = "/home/ubuntu"

Write-Host "=== Building React frontend before upload ===" -ForegroundColor Cyan
Set-Location "$LOCAL_PROJECT\frontend-web"
npm install
npm run build
Set-Location $LOCAL_PROJECT

Write-Host "`n=== Creating remote project directory ===" -ForegroundColor Cyan
ssh $SERVER "mkdir -p $REMOTE_HOME/chatbot"

Write-Host "`n=== Uploading project files (excluding node_modules & __pycache__) ===" -ForegroundColor Cyan
# Use rsync-style exclusions via scp with tar pipe (works with OpenSSH on Windows 10+)
# We exclude node_modules and __pycache__ to keep transfer small
ssh $SERVER "mkdir -p $REMOTE_HOME/chatbot"

$tarCmd = "tar -czf - --exclude='./frontend-web/node_modules' --exclude='./__pycache__' --exclude='./app/__pycache__' --exclude='./app/*/\`__pycache__\`' -C `"$LOCAL_PROJECT\..`" ChatBot_V11"

Write-Host "Compressing and uploading via SSH..." -ForegroundColor Yellow
& cmd /c "tar -czf - --exclude=frontend-web/node_modules --exclude=__pycache__ -C `"$LOCAL_PROJECT\..`" ChatBot_V11 | ssh $SERVER `"cd $REMOTE_HOME/chatbot && tar -xzf - --strip-components=1`""

Write-Host "`n=== Upload complete! ===" -ForegroundColor Green
Write-Host "Next: SSH into your server and run:  bash ~/chatbot/2_server_setup.sh" -ForegroundColor Yellow
Write-Host "  ssh $SERVER" -ForegroundColor White
