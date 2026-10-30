param(
    [Parameter(Mandatory=$true)][string]$Source
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$sourcePath = (Resolve-Path $Source).Path
# Accept upstream source directory or the extracted portable dist\DLSS5VideoConverter directory.
if (Test-Path (Join-Path $sourcePath 'dist\DLSS5VideoConverter\bin')) {
    $sourcePath = Join-Path $sourcePath 'dist\DLSS5VideoConverter'
}
$files = @{
    'bin\runtime\nvngx.dll' = 'runtime\nvngx.dll';
    'bin\runtime\nvngx_dlssnr.dll' = 'runtime\nvngx_dlssnr.dll';
    'bin\ffmpeg\bin\ffmpeg.exe' = 'bin\ffmpeg\bin\ffmpeg.exe';
    'bin\ffmpeg\bin\ffprobe.exe' = 'bin\ffmpeg\bin\ffprobe.exe';
    'preview\dlssnr-image.exe' = 'preview\dlssnr-image.exe';
    'preview\caller\nvngx.dll' = 'preview\caller\nvngx.dll';
}
foreach ($pair in $files.GetEnumerator()) {
    $inputFile = Join-Path $sourcePath $pair.Key
    $targetFile = Join-Path $root $pair.Value
    if (Test-Path $inputFile) {
        New-Item -ItemType Directory -Force -Path (Split-Path $targetFile) | Out-Null
        Copy-Item -Force $inputFile $targetFile
        Write-Host "OK  $($pair.Value)"
    } else {
        Write-Warning "NOT FOUND: $inputFile"
    }
}
Write-Host 'Done. Review the vendor binary trust/license before execution.'
