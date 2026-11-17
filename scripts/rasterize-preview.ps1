param([string]$WorkspaceRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$cacheRoot = Join-Path $WorkspaceRoot 'out\.preview-cache'
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$roots = @((Join-Path $WorkspaceRoot 'out\sidecar'), (Join-Path $WorkspaceRoot 'out\word-import-20261116\results')) |
    Where-Object { Test-Path -LiteralPath $_ }
$files = @(Get-ChildItem -LiteralPath $roots -Recurse -File | Where-Object { $_.Extension -in @('.wmf','.emf') })
$map = @{}
$errors = New-Object 'System.Collections.Generic.List[object]'
foreach ($file in $files) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($map.ContainsKey($hash)) { continue }
    $image = $null
    $bitmap = $null
    $graphics = $null
    try {
        $image = [Drawing.Imaging.Metafile]::new($file.FullName)
        $header = $image.GetMetafileHeader()
        $dpiX = if ($header.DpiX -gt 0) { $header.DpiX } else { 96 }
        $dpiY = if ($header.DpiY -gt 0) { $header.DpiY } else { 96 }
        $width = [math]::Max(8, [math]::Round($image.Width / $dpiX * 96))
        $height = [math]::Max(8, [math]::Round($image.Height / $dpiY * 96))
        $scale = [math]::Min(1, [math]::Min(1200 / $width, 1600 / $height))
        $width = [int][math]::Ceiling($width * $scale)
        $height = [int][math]::Ceiling($height * $scale)
        $png = Join-Path $cacheRoot ($hash + '.png')
        if (-not (Test-Path -LiteralPath $png)) {
            $bitmap = [Drawing.Bitmap]::new($width * 2, $height * 2)
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            $graphics.Clear([Drawing.Color]::White)
            $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
            $graphics.DrawImage($image, [Drawing.Rectangle]::new(0,0,$bitmap.Width,$bitmap.Height))
            $bitmap.Save($png, [Drawing.Imaging.ImageFormat]::Png)
        }
        $map[$hash] = @{ path=$png; width=$width; height=$height }
    } catch {
        $errors.Add(@{source=$file.FullName; error=$_.Exception.Message})
    } finally {
        if ($graphics) { $graphics.Dispose() }
        if ($bitmap) { $bitmap.Dispose() }
        if ($image) { $image.Dispose() }
    }
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $cacheRoot 'raster-map.json'), (ConvertTo-Json -InputObject $map -Depth 5), $utf8)
[IO.File]::WriteAllText((Join-Path $cacheRoot 'raster-errors.json'), (ConvertTo-Json -InputObject @($errors.ToArray()) -Depth 4), $utf8)
Write-Output ('Rasterized {0} unique vector images; {1} failures.' -f $map.Count,$errors.Count)
