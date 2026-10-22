param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Policy,

    [Parameter(Mandatory = $true, Position = 1)]
    [ValidateSet("dev", "heldout")]
    [string]$Split,

    [Parameter(Mandatory = $true, Position = 2)]
    [string]$KValues,

    [Parameter(Mandatory = $true, Position = 3)]
    [string]$OutDir
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$settingsPath = Join-Path $PSScriptRoot "team_settings.sh"
$settings = @{}

foreach ($line in Get-Content -LiteralPath $settingsPath) {
    if ($line -match '^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=([^\s#]+)') {
        $settings[$Matches[1]] = $Matches[2]
    }
}

$required = "AGENT_MODEL", "REVIEWER", "ATTACK"
foreach ($name in $required) {
    if (-not $settings.ContainsKey($name)) {
        throw "Missing $name in $settingsPath"
    }
}

$venvPython = Join-Path $repoRoot "agentdojo_venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) {
    $venvPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

$splitFiles = @(
    "splits/banking_v1.2.json",
    "splits/slack_v1.2.json",
    "splits/travel_v1.2.json"
)
$ks = @($KValues -split '\s+' | Where-Object { $_ })

Push-Location $repoRoot
try {
    foreach ($splitFile in $splitFiles) {
        $runnerArgs = @(
            "-m", "agent_framework.runner",
            "--provider", "lmstudio",
            "--policy", $Policy,
            "--llm", $settings.AGENT_MODEL,
            "--reviewer", $settings.REVIEWER,
            "--reviewer-model", $settings.AGENT_MODEL,
            "--attack", $settings.ATTACK,
            "--split-file", $splitFile,
            "--split", $Split,
            "--k"
        ) + $ks + @("--outdir", $OutDir)

        & $python @runnerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Runner failed for $splitFile with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}
