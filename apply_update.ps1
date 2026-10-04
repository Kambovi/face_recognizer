# Apply fix-update.bundle to the branch you are on, then push it.
#
# Brings in everything you don't have yet: HR chatbot + salary + leave,
# fixed entry time + detection log, dashboard Day/Month fix, sortable /
# filterable staff + unknown-faces tables, full settings JSON.
# Works on feature/hr-chatbot or feature/product-v2. dev.db and .env are
# not touched; the database updates itself when the backend starts.
#
# Run in PowerShell (stop the backend first):
#     cd "D:\DS PROJECTS\face-attendance"
#     powershell -ExecutionPolicy Bypass -File .\apply_update.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".\fix-update.bundle")) { throw "fix-update.bundle not found in this folder." }
if (git status --porcelain --untracked-files=no) {
    git status --short --untracked-files=no
    throw "Uncommitted changes above. If it is only .env.example, run: git restore .env.example  -- then run this again."
}
$branch = git branch --show-current
Write-Host "1/4 Updating branch $branch"
git fetch .\fix-update.bundle feature/product-v2:refs/remotes/bundle/latest
if ($LASTEXITCODE -ne 0) { throw "fetch failed -- send me: git log --oneline -3" }
# merge (not fast-forward only): your own commits on this branch are kept and
# nothing already pushed gets rewritten
git merge --no-edit bundle/latest
if ($LASTEXITCODE -ne 0) { git merge --abort; throw "merge failed (conflict) -- nothing changed. Send me: git log --oneline -5" }
git log --oneline -3

Write-Host "2/4 Python packages"
$py = ".\backend\.venv\Scripts\python.exe"
if (Test-Path $py) { & $py -m pip install --quiet pypdf==4.3.1 python-docx==1.1.2 }
else { Write-Host "   backend\.venv not found -- run: pip install -r backend\requirements.txt" }

Write-Host "3/4 Policy folder"
New-Item -ItemType Directory -Force .\backend\data\policy | Out-Null
if (-not (Get-ChildItem .\backend\data\policy -File -ErrorAction SilentlyContinue)) {
    Copy-Item .\docs\sample_policy\company_policy.md .\backend\data\policy\
}

Write-Host "4/4 Pushing $branch to GitHub"
git push -u origin $branch

Write-Host ""
Write-Host "Done. Start backend + frontend. You can delete fix-update.bundle and this script."
