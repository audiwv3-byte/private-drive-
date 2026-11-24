# LOCAL QA ONLY. Never commit a Mapbox token to Git.
# Run from the repository root: powershell -NoProfile -File .\ops\setup-local-mapbox.ps1
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$relativePath = 'site_preview/assets/mapbox-local-config.js'
$target = Join-Path $repoRoot $relativePath

if (-not (Test-Path 'site_preview/order-map.html')) {
    throw 'Run from the PRIVATE DRIVE repository containing site_preview/order-map.html.'
}
& git check-ignore -q -- $relativePath
if ($LASTEXITCODE -ne 0) {
    throw 'Safety stop: local Mapbox config is not ignored by Git. Run git pull --ff-only first.'
}
$tracked = & git ls-files -- $relativePath
if ($tracked) {
    throw 'Safety stop: local Mapbox config is tracked by Git.'
}
if (Test-Path $target) {
    $existing = [System.IO.File]::ReadAllText($target)
    if ($existing -match 'window\.PD_MAPBOX_PUBLIC_TOKEN\s*=\s*["''][ ]*pk\.') {
        Write-Host 'Local Mapbox config already contains a public token. No changes made.'
        exit 0
    }
    if ($existing.Trim() -and $existing -notmatch 'window\.PD_MAPBOX_PUBLIC_TOKEN\s*=\s*["'']{2}') {
        throw 'Safety stop: existing local Mapbox config has unexpected content. No changes made.'
    }
}

# Prefer an existing local environment variable; do not print its value.
$token = [Environment]::GetEnvironmentVariable('MAPBOX_WEB_PUBLIC_TOKEN')
if (-not $token) {
    $token = [Environment]::GetEnvironmentVariable('MAPBOX_PUBLIC_TOKEN')
}
if (-not $token) {
    Write-Host 'Enter the existing Mapbox PUBLIC (pk.) token. Input is hidden.'
    $secure = Read-Host -AsSecureString 'Public Mapbox token'
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}
$token = $token.Trim()
if ($token -notmatch '^pk\.[A-Za-z0-9_.-]{8,}$') {
    throw 'Only an existing public Mapbox token beginning with pk. is accepted. No file written.'
}
# Since Mapbox public tokens can be exposed to browsers, this only prevents Git exposure.
$js = 'window.PD_MAPBOX_PUBLIC_TOKEN = ' + (ConvertTo-Json -InputObject $token -Compress) + ';' + [Environment]::NewLine
[System.IO.File]::WriteAllText($target, $js, (New-Object System.Text.UTF8Encoding($false)))
$token = $null
Write-Host 'Local Mapbox config created. Token was not printed and the file is Git-ignored.'
Write-Host 'Open http://localhost:5500/site_preview/order-map.html in Live Server.'
Write-Host 'If tiles do not load, check URL restrictions for http://localhost:5500 on the existing token.'
