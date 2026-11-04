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
    param([string[]]$ArgumentList)
    $proc = Start-Process -FilePath $exePath -ArgumentList $ArgumentList -Wait -PassThru -WindowStyle Hidden
    if ($null -eq $proc.ExitCode) { return -1 }
    return [int]$proc.ExitCode
}

$before = Invoke-Exe @("--net-probe")
Add-Content -Path $log -Value "BEFORE $before" -Encoding utf8
$rule = "GCMS_KnowledgeBase_BlockOutbound"
netsh advfirewall firewall delete rule name="$rule" | Out-Null
netsh advfirewall firewall add rule name="$rule" dir=out action=block program="$exePath" enable=yes | Out-Null
try {
    $after = Invoke-Exe @("--net-probe")
    Add-Content -Path $log -Value "AFTER_BLOCK $after" -Encoding utf8
    $self = Invoke-Exe @("--self-test", "--self-test-log", $selfLog)
    Add-Content -Path $log -Value "SELFTEST $self" -Encoding utf8
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
}
