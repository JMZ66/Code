param(
    [Parameter(Mandatory = $true)][string]$Exe
)
$ErrorActionPreference = "Stop"
$exePath = (Resolve-Path $Exe).Path
$outDir = Split-Path $exePath
$log = Join-Path $outDir "offline-probe.txt"
$selfLog = Join-Path $outDir "selftest.log"
if (Test-Path $selfLog) { Remove-Item $selfLog }
Set-Content -Path $log -Value "exe=$exePath" -Encoding utf8

function Invoke-Exe {
    param([string]$ArgumentLine, [string]$Tag)
    $stdout = Join-Path $outDir "$Tag.stdout.txt"
    $stderr = Join-Path $outDir "$Tag.stderr.txt"
    try {
        $proc = Start-Process -FilePath $exePath -ArgumentList $ArgumentLine -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    } catch {
        Add-Content -Path $log -Value "$Tag START_FAIL $($_)" -Encoding utf8
        return -1
    }
    $code = if ($null -eq $proc.ExitCode) { -1 } else { [int]$proc.ExitCode }
    Add-Content -Path $log -Value "$Tag $code args=$ArgumentLine" -Encoding utf8
    foreach ($path in @($stdout, $stderr)) {
        if (Test-Path $path) {
            Add-Content -Path $log -Value ("--- " + (Split-Path $path -Leaf) + " ---") -Encoding utf8
            Add-Content -Path $log -Value (Get-Content -Path $path -Raw) -Encoding utf8
        }
    }
    return $code
}

$env:QT_QPA_PLATFORM = "offscreen"
$before = Invoke-Exe "--net-probe" "BEFORE"
$rule = "GCMS_KnowledgeBase_BlockOutbound"
netsh advfirewall firewall delete rule name="$rule" | Out-Null
netsh advfirewall firewall add rule name="$rule" dir=out action=block program="$exePath" enable=yes | Out-Null
try {
    $after = Invoke-Exe "--net-probe" "AFTER_BLOCK"
    $self = Invoke-Exe "--self-test --self-test-log `"$selfLog`"" "SELFTEST"
    if (Test-Path $selfLog) {
        Add-Content -Path $log -Value (Get-Content -Path $selfLog -Raw) -Encoding utf8
    } else {
        Add-Content -Path $log -Value "SELFTEST_LOG_MISSING" -Encoding utf8
        exit 1
    }
    $selfText = Get-Content -Path $selfLog -Raw
    if ($self -ne 0 -or $selfText -notmatch "SELF_TEST_OK") {
        Add-Content -Path $log -Value "SELFTEST_FAIL" -Encoding utf8
        exit 1
    }
    if ($before -eq 2 -and $after -eq 0) {
        Add-Content -Path $log -Value "FIREWALL_VERIFIED" -Encoding utf8
        exit 0
    }
    if ($before -eq 2 -and $after -ne 0) {
        Add-Content -Path $log -Value "FIREWALL_DIFF_FAIL before=$before after=$after" -Encoding utf8
        exit 2
    }
    Add-Content -Path $log -Value "FIREWALL_INCONCLUSIVE before=$before after=$after" -Encoding utf8
    exit 0
}
finally {
    netsh advfirewall firewall delete rule name="$rule" | Out-Null
    Write-Host "----- offline-probe.txt -----"
    if (Test-Path $log) { Get-Content -Path $log | Write-Host }
}
