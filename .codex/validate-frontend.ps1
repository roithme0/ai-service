param(
    [ValidateSet('start', 'stop')]
    [string]$Mode = 'stop'
)

$ErrorActionPreference = 'Stop'

try {
    $validator = Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend/scripts/validate-frontend.mts'
    [Console]::In.ReadToEnd() | & node $validator "--$Mode"
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
