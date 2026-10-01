# Full pipeline run, clean warehouse. Used for the overnight rebuild and to
# prove the whole thing reproduces from scratch.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$py = ".\.venv\Scripts\python.exe"

function Run-Stage($name, $scriptblock) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Write-Host "=== $name ===" -ForegroundColor Cyan
    & $scriptblock 2>&1 | Select-String -NotMatch "CategoryInfo|FullyQualifiedErrorId|^\s*\+|At line:|\+ " |
        Out-String | Write-Host
    $code = $LASTEXITCODE
    Write-Host "$name exit=$code elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,0))s" -ForegroundColor Yellow
    return $code
}

$failed = @()

if ($args -contains "-clean") {
    Write-Host "removing warehouse" -ForegroundColor Magenta
    Remove-Item warehouse\dwm.duckdb*, warehouse\tmp -Recurse -Force -ErrorAction SilentlyContinue
}

$c = Run-Stage "ingest"   { & $py -m dwm ingest }
if ($c -ne 0) { $failed += "ingest" }

$c = Run-Stage "etl"      { & $py -m dwm etl }
if ($c -ne 0) { $failed += "etl" }

$c = Run-Stage "features" { & $py -m dwm features }
if ($c -ne 0) { $failed += "features" }

$c = Run-Stage "build"    { & $py -m dwm build }
if ($c -ne 0) { $failed += "build" }

Write-Host "=== tables ===" -ForegroundColor Cyan
& $py -m dwm tables 2>&1 | Select-String -NotMatch "CategoryInfo|FullyQualifiedErrorId|^\s*\+|At line:|\+ " |
    Out-String | Write-Host

if ($failed.Count -gt 0) {
    Write-Host "FAILED STAGES: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "ALL STAGES OK" -ForegroundColor Green
exit 0
