param(
    [ValidateSet('start', 'stop')]
    [string]$Mode = 'stop',
    [ValidateSet('all', 'frontend', 'backend')]
    [string]$Scope = 'all'
)

$ErrorActionPreference = 'Stop'

try {
    $validator = Join-Path $PSScriptRoot 'validation/run.mts'
    [Console]::In.ReadToEnd() | & node $validator "--$Mode" "--$Scope"
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
