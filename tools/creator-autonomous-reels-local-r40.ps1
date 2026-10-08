[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]] $RemainingArgs)
$ErrorActionPreference = "Stop"
$env:CREATOR_R40_LIVE_SEND = "0"
$env:CREATOR_R40_LIVE_PUBLISH = "0"
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
  $python = Get-Command py.exe -ErrorAction Stop
  & $python.Source -3 -m creator_orchestrator.autonomous_reels_local_r40 @RemainingArgs
  exit $LASTEXITCODE
}
& $python.Source -m creator_orchestrator.autonomous_reels_local_r40 @RemainingArgs
exit $LASTEXITCODE
