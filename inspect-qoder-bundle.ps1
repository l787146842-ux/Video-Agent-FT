$path = 'C:\Program Files\Qoder\resources\app\out\vs\workbench\workbench.desktop.main.js'
$s = [IO.File]::ReadAllText($path)
$needles = @('aicoding.questTaskListSnapshot','ownerAccountId','session/load','session/attach','chatSessionService.loadHistory','chat/listAllSessions','chat/getSessionById')
foreach ($n in $needles) {
  $p = 0
  $c = 0
  while (($p = $s.IndexOf($n,$p,[StringComparison]::Ordinal)) -ge 0 -and $c -lt 5) {
    Write-Output "`n### $n @$p"
    $start = [Math]::Max(0,$p-900)
    $len = [Math]::Min(2600,$s.Length-$start)
    Write-Output $s.Substring($start,$len)
    $p += $n.Length
    $c++
  }
}
