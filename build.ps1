$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot

try {
    $pythonExe = $null
    $pythonPrefix = @()
    $iconPath = Join-Path $projectRoot 'assets\dks-web-favicon.ico'

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonExe = 'python'
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $pythonExe = 'py'
        $pythonPrefix = @('-3')
    }
    else {
        throw 'Python launcher not found. Install Python or ensure `python` / `py` is in PATH.'
    }

    & $pythonExe @pythonPrefix -m pip install --upgrade pip
    & $pythonExe @pythonPrefix -m pip install -r requirements.txt

    if (-not (Test-Path $iconPath)) {
        throw "Build icon not found at '$iconPath'."
    }

    & $pythonExe @pythonPrefix -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name DKSInstaller `
        --icon $iconPath `
        main.py
}
finally {
    Pop-Location
}
