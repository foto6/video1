[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]] $RemainingArgs)
$ErrorActionPreference = "Stop"
$env:CREATOR_R38_NO_NETWORK = "1"
$env:CREATOR_R38_LIVE_AUTHORIZATION = "0"
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
  $python = Get-Command py.exe -ErrorAction Stop
  & $python.Source -3 -m creator_orchestrator.local_fullstack_rehearsal_r38 @RemainingArgs
  exit $LASTEXITCODE
}
& $python.Source -m creator_orchestrator.local_fullstack_rehearsal_r38 @RemainingArgs
exit $LASTEXITCODE
