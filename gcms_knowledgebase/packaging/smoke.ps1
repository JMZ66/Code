param(
    [Parameter(Mandatory = $true)][string]$Exe
)
$ErrorActionPreference = "Stop"
$exePath = (Resolve-Path $Exe).Path
$outDir = Split-Path $exePath
$log = Join-Path $outDir "offline-probe.txt"
$selfLog = Join-Path $outDir "selftest.log"
Set-Content -Path $log -Value "exe=$exePath" -Encoding utf8

function Invoke-Probe([string]$tag) {
    & $exePath --net-probe
    $code = $LASTEXITCODE
    Add-Content -Path $log -Value "$tag $code" -Encoding utf8
    return $code
}

$before = Invoke-Probe "BEFORE"
$rule = "GCMS_KnowledgeBase_BlockOutbound"
netsh advfirewall firewall delete rule name="$rule" | Out-Null
$added = netsh advfirewall firewall add rule name="$rule" dir=out action=block program="$exePath" enable=yes
Add-Content -Path $log -Value "FIREWALL_ADD $($added -join ' ')" -Encoding utf8
try {
    $after = Invoke-Probe "AFTER_BLOCK"
    & $exePath --self-test --self-test-log $selfLog
    $self = $LASTEXITCODE
    Add-Content -Path $log -Value "SELFTEST $self" -Encoding utf8
    if (Test-Path $selfLog) {
        Add-Content -Path $log -Value (Get-Content -Path $selfLog -Raw) -Encoding utf8
    }
    if ($self -ne 0) { exit 1 }
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
