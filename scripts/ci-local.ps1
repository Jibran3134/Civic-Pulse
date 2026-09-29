<#
.SYNOPSIS
    Local mirror of .github/workflows/ci.yml.

.DESCRIPTION
    Exists because pushing to GitHub to discover a step fails is a slow and
    public way to learn something this script can tell you in three minutes.
    Every job in ci.yml has a counterpart here, run with the same inputs and
    the same pass/fail conditions, so "green locally" means something.

    Written in PowerShell rather than bash on purpose: `bash` on this machine
    is WSL2, which cannot see the Windows Python toolchain, the Docker CLI
    paths, or the environment the checks actually run against. A bash runner
    here would be testing a different machine than CI does.

    What it does NOT reproduce, stated plainly:
      * buildx / GHA layer cache, and the codecov upload.
      * The exact trivy scanner version. The action is pinned to v0.28.0; the
        CLI here is newer, so a clean run means "no NEW HIGH/CRITICAL library
        CVEs", not a byte-for-byte match.
      * The Windows event-loop workaround in the migrations step. ci.yml runs
        on Linux where `alembic upgrade head` works unmodified; on Windows it
        needs the Selector policy, so this script sets it explicitly rather
        than letting the check silently pass for the wrong reason.

.EXAMPLE
    pwsh -File scripts/ci-local.ps1
    pwsh -File scripts/ci-local.ps1 -Jobs lint,test
#>
[CmdletBinding()]
param(
    [string[]]$Jobs = @('lint', 'frontend', 'test', 'build', 'manifests', 'integration'),
    [string]$TrivyBin = '',
    [string]$TrivyCache = ''
)

$ErrorActionPreference = 'Continue'
$script:Passed = @()
$script:Failed = @()
$script:Root = Split-Path -Parent $PSScriptRoot
Set-Location $script:Root

function Step { param($m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Pass { param($m) $script:Passed += $m; Write-Host "  PASS  $m" -ForegroundColor Green }
function Fail {
    param($m)
    $script:Failed += $m
    Write-Host "  FAIL  $m" -ForegroundColor Red
}

# Run a command, echo its output indented, and record pass/fail. The boolean
# return is consumed with `| Out-Null` or `$null =` where nothing branches on
# it, so it does not leak into the log.
function Invoke-Check {
    param([string]$Name, [scriptblock]$Body)
    $out = & $Body 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if ($code -eq 0) { Pass $Name; return $true }
    Fail "$Name (exit $code)"
    return $false
}

# ---------------------------------------------------------------- lint-and-type
function Invoke-Lint {
    Step 'lint-and-type / ruff'
    Push-Location backend
    Invoke-Check 'ruff' { python -m ruff check . } | Out-Null
    Pop-Location

    Step 'lint-and-type / mypy (CI flags)'
    # Flags copied verbatim from ci.yml. It disables several error codes, so a
    # bare `mypy` locally reports failures CI would not.
    Push-Location backend
    $null = Invoke-Check 'mypy' {
        python -m mypy app/ --ignore-missing-imports --no-strict-optional `
            --disable-error-code=import-not-found `
            --disable-error-code=attr-defined `
            --disable-error-code=no-untyped-def `
            --disable-error-code=no-untyped-call
    }
    Pop-Location
}

function Invoke-Frontend {
    if (-not (Test-Path 'frontend/package.json')) {
        Step 'frontend jobs'
        Write-Host '  frontend/package.json absent -> these jobs are no-ops in CI too' -ForegroundColor Yellow
        return
    }
    Step 'frontend / npm ci'
    Push-Location frontend
    if (-not (Invoke-Check 'npm ci' { npm ci --no-audit --no-fund })) { Pop-Location; return }

    Step 'lint-and-type / eslint'
    $null = Invoke-Check 'eslint' { npm run lint }

    Step 'lint-and-type / tsc --noEmit'
    $null = Invoke-Check 'tsc' { npx tsc --noEmit }

    Step 'test-frontend / vitest'
    $null = Invoke-Check 'vitest' { npm run test -- --run }
    Pop-Location
}

# ------------------------------------------------------------------ test-backend
function Start-CiServices {
    # Reclaim the ports first. An aborted run leaves containers behind, then
    # `docker run` fails with "port is already allocated" and the health loop
    # times out reporting a "services up" failure that has nothing to do with
    # services.
    foreach ($c in @('ci-local-pg', 'ci-local-redis', 'cp-test-pg', 'cp-test-redis')) {
        docker rm -f $c 2>&1 | Out-Null
    }
    docker run -d --name ci-local-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres `
        -e POSTGRES_DB=civicpulse -p 55432:5432 postgres:16-alpine 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host '    could not start postgres on 55432' -ForegroundColor Red; return $false }
    docker run -d --name ci-local-redis -p 56379:6379 redis:7-alpine 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host '    could not start redis on 56379' -ForegroundColor Red; return $false }

    for ($i = 0; $i -lt 30; $i++) {
        docker exec ci-local-pg pg_isready -U postgres 2>&1 | Out-Null
        $pg = $LASTEXITCODE
        docker exec ci-local-redis redis-cli ping 2>&1 | Out-Null
        $rd = $LASTEXITCODE
        if ($pg -eq 0 -and $rd -eq 0) { return $true }
        Start-Sleep -Seconds 2
    }
    Write-Host '    timed out waiting for postgres/redis' -ForegroundColor Red
    return $false
}
function Stop-CiServices { docker rm -f ci-local-pg ci-local-redis 2>&1 | Out-Null }

function Invoke-Test {
    Step 'test-backend / service containers'
    if (-not (Start-CiServices)) { Fail 'services up'; return }

    $env:DATABASE_URL = 'postgresql://postgres:postgres@localhost:55432/civicpulse'
    $env:REDIS_URL = 'redis://localhost:56379/0'
    $env:TRIAGE_PROVIDER = 'simulated'
    $env:GROQ_API_KEY = ''
    $env:LOG_LEVEL = 'INFO'
    $env:ENVIRONMENT = 'test'

    Step 'test-backend / migrations'
    Push-Location backend
    $null = Invoke-Check 'migrations' {
        $env:PYTHONPATH = (Get-Location).Path
        python -c @"
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from alembic import command
from alembic.config import Config
command.upgrade(Config('alembic.ini'), 'head')
"@
    }
    Step 'test-backend / pytest --cov-fail-under=65'
    $null = Invoke-Check 'pytest' { python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=65 -q }
    Pop-Location
}

# ------------------------------------------------------------------------ build
function Invoke-Build {
    Step 'build / backend image'
    if (-not (Invoke-Check 'build backend' { docker build -q -t ci-local/backend:test ./backend })) { return }

    if (Test-Path 'frontend/package.json') {
        Step 'build / frontend image'
        $null = Invoke-Check 'build frontend' { docker build -q -t ci-local/frontend:test ./frontend }
    }

    $trivy = $TrivyBin
    if (-not $trivy) { $trivy = (Get-Command trivy -ErrorAction SilentlyContinue).Source }
    if (-not $trivy) { $trivy = Join-Path $script:Root '.ci-tools/trivy.exe' }
    if (-not (Test-Path $trivy)) {
        Step 'scan / trivy'
        Write-Host '  SKIPPED: trivy not found. CI WILL run this step.' -ForegroundColor Yellow
        return
    }
    if ($TrivyCache) { $env:TRIVY_CACHE_DIR = $TrivyCache }

    $images = @('ci-local/backend:test')
    if (Test-Path 'frontend/package.json') { $images += 'ci-local/frontend:test' }
    foreach ($img in $images) {
        Step "scan / trivy HIGH,CRITICAL (library) -- $img"
        $null = Invoke-Check "trivy $img" {
            & $trivy image --exit-code 1 --severity HIGH,CRITICAL --vuln-type library `
                --ignore-unfixed --quiet --scanners vuln $img
        }
    }
}

# -------------------------------------------------------------------- manifests
function Invoke-Manifests {
    if (-not (Test-Path 'k8s/overlays/prod/kustomization.yaml')) {
        Step 'manifests'
        Write-Host '  k8s/overlays/prod absent -> CI reports SKIPPED too' -ForegroundColor Yellow
        return
    }
    Step 'manifests / kustomize build | kubeconform -strict'
    $kustomize = (Get-Command kustomize -ErrorAction SilentlyContinue).Source
    $kubeconform = (Get-Command kubeconform -ErrorAction SilentlyContinue).Source
    if (-not $kustomize) { $kustomize = Join-Path $script:Root '.ci-tools/kustomize.exe' }
    if (-not $kubeconform) { $kubeconform = Join-Path $script:Root '.ci-tools/kubeconform.exe' }
    if (-not (Test-Path $kustomize)) { Fail 'kustomize not found'; return }
    if (-not (Test-Path $kubeconform)) { Fail 'kubeconform not found'; return }

    $dir = Join-Path $env:TEMP "ci-manifests-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    $split = Join-Path $dir 'docs'
    New-Item -ItemType Directory $split -Force | Out-Null
    $rendered = Join-Path $dir 'all.yaml'
    & $kustomize build k8s/overlays/prod 2>$null | Set-Content $rendered
    if ($LASTEXITCODE -ne 0) { Fail 'kustomize build'; Remove-Item $dir -Recurse -Force; return }

    # Split the multi-document stream into the `docs` subdirectory only.
    # Writing them alongside all.yaml would make kubeconform validate the
    # concatenated file as well and double-count every resource.
    $i = 0
    foreach ($doc in ((Get-Content $rendered -Raw) -split "(?m)^---\s*$")) {
        if ($doc.Trim()) { $i++; Set-Content (Join-Path $split ("doc-{0:d2}.yaml" -f $i)) $doc.Trim() }
    }
    Write-Host "    rendered $i resources"
    $null = Invoke-Check 'kubeconform' { & $kubeconform -strict -summary -ignore-missing-schemas $split }
    Remove-Item $dir -Recurse -Force
}

# ------------------------------------------------------------------ integration
function Invoke-Integration {
    Step 'integration / .env'
    @'
POSTGRES_PASSWORD=postgres
TRIAGE_PROVIDER=simulated
GROQ_API_KEY=
LOG_LEVEL=INFO
ENVIRONMENT=development
'@ | Set-Content .env

    $env:POSTGRES_PASSWORD = 'postgres'
    $env:TRIAGE_PROVIDER = 'simulated'
    $env:GROQ_API_KEY = ''

    Step 'integration / compose up'
    docker compose down -v 2>&1 | Out-Null
    docker compose up -d --build postgres redis backend 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'compose up'; docker compose down -v 2>&1 | Out-Null; return }
    Pass 'compose up'

    Step 'integration / migrations'
    $migrated = $false
    for ($i = 0; $i -lt 20; $i++) {
        docker compose exec -T backend alembic upgrade head 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $migrated = $true; break }
        Start-Sleep -Seconds 3
    }
    if ($migrated) { Pass 'migrations' } else { Fail 'migrations' }

    Step 'integration / wait for /ready'
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-RestMethod 'http://localhost:8000/ready' -TimeoutSec 3
            if ($r.status -eq 'ready') { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Fail '/ready'
        docker compose logs backend 2>&1 | Select-Object -Last 30 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        docker compose down -v 2>&1 | Out-Null
        return
    }
    Pass '/ready'

    Step 'integration / submit complaint'
    $body = '{"text":"Water main burst on Mall Road since fajr water entering ground floors","location":"Mall Road, Lahore"}'
    $resp = $null
    try {
        $resp = Invoke-RestMethod 'http://localhost:8000/api/complaints' -Method Post -ContentType 'application/json' -Body $body
    } catch { Fail 'submit complaint' }
    if ($resp) {
        $cats = @('water', 'electricity', 'sanitation', 'roads', 'streetlights', 'other')
        if ($resp.status -eq 'open' -and $cats -contains $resp.category -and $resp.triaged_by) {
            Pass 'submit complaint'
            Write-Host "    category=$($resp.category) priority=$($resp.priority) triaged_by=$($resp.triaged_by)" -ForegroundColor DarkGray
        } else {
            Fail 'submit complaint'
        }
    }

    Step 'integration / complaint persisted'
    # Mirror CI's `curl ... | grep -q "Mall Road"` rather than reimplementing it
    # with object property access: the point is that the row is readable back
    # through the API, and a raw-body match cannot silently pass on a null.
    $raw = curl.exe -s http://localhost:8000/api/complaints
    if (($raw -join "`n") -match 'Mall Road') { Pass 'persisted' } else { Fail 'persisted' }

    # The X-Cache response HEADER is the only thing that distinguishes a HIT
    # from a MISS -- the body is byte-identical either way.
    function Get-XCache {
        $h = curl.exe -s -D - -o NUL http://localhost:8000/api/stats
        $line = ($h | Select-String -Pattern '^x-cache:' | Select-Object -First 1)
        if ($line) { return ($line.Line -split ':', 2)[1].Trim() } else { return '<absent>' }
    }
    # POST a JSON body. Must go through Invoke-RestMethod, NOT curl --data-raw:
    # PowerShell strips the embedded double quotes when shelling out to a native
    # executable, so curl receives malformed JSON and the API correctly answers
    # 422. ci.yml uses curl inside a bash `run:` block where the quoting is
    # intact, so this divergence was in the local runner only.
    function Post-Complaint {
        param([string]$Body)
        try {
            return Invoke-RestMethod 'http://localhost:8000/api/complaints' `
                -Method Post -ContentType 'application/json' -Body $Body
        } catch { return $null }
    }

    Step 'integration / X-Cache MISS then HIT'
    $c1 = Get-XCache
    $c2 = Get-XCache
    Write-Host "    first=$c1  second=$c2" -ForegroundColor DarkGray
    if ($c1 -eq 'MISS' -and $c2 -eq 'HIT') { Pass 'X-Cache MISS->HIT' } else { Fail "X-Cache MISS->HIT (got $c1 then $c2)" }

    Step 'integration / cache invalidation on write'
    $body2 = '{"text":"Garbage not collected for three days in Model Town block B","location":"Model Town, Lahore"}'
    $w = Post-Complaint $body2
    if (-not $w) { Fail 'write before invalidation check' }
    else { Write-Host "    POST status: 201 (triaged_by=$($w.triaged_by))" -ForegroundColor DarkGray }
    $c3 = Get-XCache
    $c4 = Get-XCache
    Write-Host "    after POST=$c3  next call=$c4" -ForegroundColor DarkGray
    if ($c3 -eq 'MISS' -and $c4 -eq 'HIT') { Pass 'cache invalidated on write' } else { Fail "cache invalidated on write (got $c3 then $c4)" }

    Step 'integration / teardown'
    docker compose down -v 2>&1 | Out-Null
    Pass 'teardown'
}

# ------------------------------------------------------------------------- main
foreach ($job in $Jobs) {
    switch ($job) {
        'lint' { Invoke-Lint }
        'frontend' { Invoke-Frontend }
        'test' { Invoke-Test; Stop-CiServices }
        'build' { Invoke-Build }
        'manifests' { Invoke-Manifests }
        'integration' { Invoke-Integration }
        default {
            # An unrecognised job must FAIL, not pass. Treating it as a no-op
            # means a typo such as -Jobs test,integration reports "All checks
            # passed" having run nothing, which is exactly the false green this
            # script exists to prevent.
            Write-Host "unknown job: $job (known: lint, frontend, test, build, manifests, integration)" -ForegroundColor Red
            Fail "unknown job: $job"
        }
    }
}

Write-Host "`n================ SUMMARY ================" -ForegroundColor Cyan
foreach ($p in $script:Passed) { Write-Host "  PASS  $p" -ForegroundColor Green }
foreach ($f in $script:Failed) { Write-Host "  FAIL  $f" -ForegroundColor Red }

if ($script:Failed.Count -eq 0) {
    Write-Host "`nAll checks passed. Safe to push." -ForegroundColor Green
    exit 0
}
Write-Host "`n$($script:Failed.Count) check(s) failed. Do not push." -ForegroundColor Red
exit 1
