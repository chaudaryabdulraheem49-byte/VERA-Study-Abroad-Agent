<#
.SYNOPSIS
    One day's upkeep: check for a new CRICOS release, then spend the day's
    embedding allowance on courses that still have no vector.

.DESCRIPTION
    Written to be run unattended by Task Scheduler just after UTC midnight,
    when the free-tier allowance resets. Both steps are safe to repeat: the
    sync downloads nothing when the published release is unchanged, and the
    backfill embeds only courses Qdrant does not already hold.

    Nothing here needs the run to succeed for the next one to work. A failed
    day costs a day, not the progress already made.

.PARAMETER SkipSync
    Only run the embedding backfill. Useful when the register is known to be
    current and the allowance is the only thing worth spending.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\daily_maintenance.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [int]$KeepLogDays = 30
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
$LogDir = Join-Path $RepoRoot 'logs'
$LogFile = Join-Path $LogDir ("daily_maintenance_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "{0} {1,-5} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line
    # Written through .NET rather than Add-Content. Windows PowerShell writes
    # UTF-16 by default, which makes the log unreadable to grep, tail and
    # every other ordinary tool - and `-Encoding UTF8` was not honoured when
    # appending to a file that already existed. This is unambiguous.
    [System.IO.File]::AppendAllText(
        $LogFile, $line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false)
    )
}

function Invoke-Step {
    <#
      Runs one step and reports its exit code without throwing. A failing sync
      must not stop the backfill: they are independent, and the allowance is
      the perishable resource - it is gone at midnight whether or not the
      catalogue check worked.
    #>
    param([string]$Name, [string[]]$Arguments)

    Write-Log "--- $Name ---"
    # Streamed rather than captured. Collecting the output and writing it at
    # the end means a step that takes twelve minutes logs nothing for twelve
    # minutes, and there is no way to tell a slow run from a hung one.
    # ErrorActionPreference must be 'Continue' during native command stderr
    # redirection (2>&1), otherwise Python warnings (e.g. rate limit retries)
    # trigger a terminating NativeCommandError in PowerShell.
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Python @Arguments 2>&1 | ForEach-Object { Write-Log "    $_" }
    }
    finally {
        $ErrorActionPreference = $savedEAP
    }
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Log "$Name exited $code" 'WARN'
    }
    return $code
}

Write-Log "Daily maintenance starting (UTC $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')))"

if (-not (Test-Path $Python)) {
    Write-Log "No interpreter at $Python - was the venv moved?" 'ERROR'
    exit 1
}

# The databases live in Docker. Without them every step fails with a
# connection error that looks like a bug, so it is named plainly instead.
$compose = & docker compose -f (Join-Path $RepoRoot 'docker-compose.yml') ps --format '{{.Service}} {{.State}}' 2>&1
if ($LASTEXITCODE -ne 0 -or -not ($compose -match 'running')) {
    Write-Log "Postgres/Qdrant are not running - start them with 'docker compose up -d'." 'ERROR'
    Write-Log ("docker reported: {0}" -f ($compose -join '; ')) 'ERROR'
    exit 1
}

$failures = 0

if (-not $SkipSync) {
    # --no-embed: the sync can embed what it just ingested, but then the
    # backfill below would be a second run of the same work under a different
    # heading, and the day's allowance would be spent inside a step named
    # "CRICOS sync". One step owns embedding.
    $failures += [int]((Invoke-Step 'CRICOS sync' @(
        (Join-Path $RepoRoot 'scripts\sync_cricos.py'), '--no-embed'
    )) -ne 0)
}

# Always attempted, even if the sync failed: the allowance resets daily and is
# lost if unspent, while a missed sync simply waits for tomorrow.
# Retried rather than run once.
#
# Three scheduled runs in a row died 50-70 seconds in, after one or two
# batches, with no crash, no traceback and nothing in any event log - while
# every manual run completed all eighteen. The deaths land when the machine has
# just booted, resumed or restarted, which is when the 12:30 slot tends to
# catch it. The cause is still unproven.
#
# Waiting for the cause costs 800 embeddings a day, and the allowance is
# perishable. Relaunching is safe without knowing it: the checkpoint makes the
# backfill resumable and idempotent, so a fresh process starts at the next
# unembedded course and never repeats one.
#
# The loop stops when the day's allowance is spent, or when an attempt adds
# nothing - which separates "killed again, try once more" from "genuinely
# broken, stop hammering it".
$backfill = Join-Path $RepoRoot 'scripts\backfill_embeddings.py'
$MaxAttempts = 6
$code = 1

function Get-EmbeddedCount {
    # Read from the checkpoint the backfill maintains. Parsing its stdout would
    # tie this to the exact wording of a progress line.
    $file = Join-Path $RepoRoot 'data\embedding_checkpoint.json'
    if (-not (Test-Path $file)) { return 0 }
    try { return [int]((Get-Content $file -Raw | ConvertFrom-Json).completed_count) }
    catch { return 0 }
}

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $before = Get-EmbeddedCount
    $name = if ($attempt -eq 1) { 'Embedding backfill' }
            else { "Embedding backfill (resume $attempt of $MaxAttempts)" }

    $code = Invoke-Step $name @($backfill)

    $added = (Get-EmbeddedCount) - $before

    # 0 means it finished on its own terms - allowance spent, or nothing left
    # to embed. Either way there is no more work to do today.
    if ($code -eq 0) {
        if ($attempt -gt 1) { Write-Log "Recovered after $attempt attempt(s)." }
        break
    }

    if ($added -le 0) {
        Write-Log "Attempt $attempt added nothing - not retrying." 'WARN'
        break
    }

    Write-Log "Attempt $attempt stopped early after $added course(s); resuming." 'WARN'
}

$failures += [int]($code -ne 0)

Invoke-Step 'Coverage' @(
    (Join-Path $RepoRoot 'scripts\backfill_embeddings.py'), '--status'
) | Out-Null

# Old logs are pruned here rather than by a second scheduled task: one moving
# part is easier to reason about than two.
Get-ChildItem -Path $LogDir -Filter 'daily_maintenance_*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepLogDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Log "Daily maintenance finished with $failures failing step(s)"
exit ([math]::Min($failures, 1))
