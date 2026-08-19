[CmdletBinding()]
param(
    [string]$BaseRef
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$scriptPath = Join-Path $repoRoot "scripts/check-repo.py"
$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $python) {
    throw "Python 3 is required to run repository baseline checks."
}

$arguments = @($scriptPath)
if ($BaseRef) {
    $arguments += @("--base-ref", $BaseRef)
}

& $python.Source @arguments
exit $LASTEXITCODE
