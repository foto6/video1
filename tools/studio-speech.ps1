param([Parameter(Mandatory=$true)][string]$TextFile, [Parameter(Mandatory=$true)][string]$OutputFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$studioVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $studioVoice.SelectVoice('Microsoft Irina Desktop')
    $studioVoice.Rate = -1
    $studioVoice.Volume = 100
    $studioText = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
    $studioVoice.SetOutputToWaveFile($OutputFile)
    $studioVoice.Speak($studioText)
} finally {
    $studioVoice.Dispose()
}
