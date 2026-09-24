param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Target
)
$ErrorActionPreference = 'Stop'
$extension = [IO.Path]::GetExtension($Source).ToLowerInvariant()
$application = $null
$document = $null
$ownsApplication = $false
$oldSecurity = $null
$oldAlerts = $null
$startedAt = [DateTime]::UtcNow
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HirakuWindow {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
}
'@
function Record-Instance($App, [bool]$Empty, [string]$ProcessName) {
    $officePid = [uint32]0
    $window = $App.Hwnd
    if ($null -ne $window -and $window -ne 0) {
        [void][HirakuWindow]::GetWindowThreadProcessId([IntPtr]$window, [ref]$officePid)
    } else {
        $createdProcesses = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
            Where-Object { $_.StartTime.ToUniversalTime() -ge $startedAt.AddSeconds(-1) })
        if ($createdProcesses.Count -ne 1) { return $false }
        $officePid = [uint32]$createdProcesses[0].Id
    }
    $officeProcess = Get-Process -Id $officePid
    $created = $officeProcess.StartTime.ToUniversalTime()
    $owned = $Empty -and $created -ge $startedAt.AddSeconds(-1)
    @{pid=$officePid; created_ticks=$created.Ticks; owned=$owned} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path (Split-Path $Target) 'office-worker.json') -Encoding UTF8
    return $owned
}
function Trace-Stage([string]$Stage) { Write-Output ('HIRAKU_STAGE=' + $Stage) }
try {
    Trace-Stage 'create'
    switch ($extension) {
        {$_ -in '.docx','.docm'} {
            $application = New-Object -ComObject Word.Application
            $ownsApplication = Record-Instance $application ($application.Documents.Count -eq 0) 'WINWORD'
            $oldSecurity = $application.AutomationSecurity
            $oldAlerts = $application.DisplayAlerts
            if ($ownsApplication) { $application.Visible = $false }
            $application.DisplayAlerts = 0
            $application.AutomationSecurity = 3
            $document = $application.Documents.Open($Source, $false, $true, $false)
            $document.ExportAsFixedFormat($Target, 17)
        }
        {$_ -in '.xlsx','.xlsm'} {
            $application = New-Object -ComObject Excel.Application
            Trace-Stage 'configure-excel'
            $ownsApplication = Record-Instance $application ($application.Workbooks.Count -eq 0) 'EXCEL'
            $oldSecurity = $application.AutomationSecurity
            $oldAlerts = $application.DisplayAlerts
            if ($ownsApplication) { $application.Visible = $false }
            $application.DisplayAlerts = $false
            $application.AutomationSecurity = 3
            Trace-Stage 'open-excel'
            $document = $application.Workbooks.Open($Source, 0, $true)
            Trace-Stage 'export-excel'
            $document.ExportAsFixedFormat(0, $Target)
            Trace-Stage 'exported-excel'
        }
        {$_ -in '.pptx','.pptm'} {
            $application = New-Object -ComObject PowerPoint.Application
            $ownsApplication = Record-Instance $application ($application.Presentations.Count -eq 0) 'POWERPNT'
            $oldSecurity = $application.AutomationSecurity
            $application.AutomationSecurity = 3
            $document = $application.Presentations.Open($Source, -1, 0, 0)
            $document.SaveAs($Target, 32)
        }
        default { throw 'Unsupported Office format.' }
    }
    if (-not (Test-Path -LiteralPath $Target)) { throw 'Office PDF export failed.' }
} finally {
    Trace-Stage 'close-document'
    try {
        if ($null -ne $document) {
            try {
                if ($extension -in '.pptx','.pptm') { $document.Close() }
                else { $document.Close(0) }
            } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) }
        }
    } finally {
        if ($null -ne $application) {
            Trace-Stage 'quit-application'
            try {
                if ($null -ne $oldSecurity) { $application.AutomationSecurity = $oldSecurity }
                if ($null -ne $oldAlerts) { $application.DisplayAlerts = $oldAlerts }
                if ($ownsApplication) { $application.Quit() }
            }
            finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) }
        }
    }
    [GC]::Collect()
    Trace-Stage 'finalizers'
    [GC]::WaitForPendingFinalizers()
    Trace-Stage 'done'
}
