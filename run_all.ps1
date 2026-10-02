# Full pipeline run, clean warehouse. Used for the overnight rebuild and to
# prove the whole thing reproduces from scratch, all the way to report.md.
#
# Pass -skipAnalysis to rebuild only the warehouse. The mining stage takes
# about 90 seconds, most of it clustering, so it is worth being able to skip.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$py = ".\.venv\Scripts\python.exe"
$skipAnalysis = $args -contains "-skipAnalysis"

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

if ($skipAnalysis) {
    Write-Host "SKIPPED: mine, report (-skipAnalysis)" -ForegroundColor DarkGray
} else {
    # `report` exits non-zero when an inference guard fails, by design: a
    # warehouse that cannot support its own claims must not pass silently.
    $c = Run-Stage "mine"   { & $py -m dwm mine }
    if ($c -ne 0) { $failed += "mine" }

    $c = Run-Stage "report" { & $py -m dwm report }
    if ($c -ne 0) { $failed += "report" }

    Write-Host "=== artefacts ===" -ForegroundColor Cyan
    Get-ChildItem reports\*.json, reports\*.md |
        Select-Object Name, @{n="KB";e={[math]::Round($_.Length/1KB,1)}} |
        Format-Table -AutoSize | Out-String | Write-Host
}

if ($failed.Count -gt 0) {
    Write-Host "FAILED STAGES: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "ALL STAGES OK" -ForegroundColor Green
exit 0
