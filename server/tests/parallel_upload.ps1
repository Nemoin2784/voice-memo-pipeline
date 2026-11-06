# 并发上传测试：同时用 curl 上传多个文件，打印每个请求的 JSON 响应
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File tests\parallel_upload.ps1
#       默认用 ..\audio\ 下的示例音频；也可以设 VOICE_TEST_FILES（分号分隔）指定自己的文件
$ErrorActionPreference = 'Stop'

if ($env:VOICE_TEST_FILES) {
    $files = $env:VOICE_TEST_FILES -split ';' | Where-Object { $_ }
} else {
    $files = @('..\audio\jldx_60s.wav', '..\audio\deo_16k.wav', '..\audio\sample_zh.wav')
}
$files = @($files | Where-Object { Test-Path $_ })
if ($files.Count -eq 0) {
    Write-Host "跳过：找不到测试音频（先用 scripts\make_sample.py 生成，或设 VOICE_TEST_FILES）"
    exit 0
}

$tmp = @()
foreach ($f in $files) { $tmp += [System.IO.Path]::GetTempFileName() }

$procs = @()
for ($i = 0; $i -lt $files.Count; $i++) {
    $args = @('-s', '-X', 'POST', 'http://127.0.0.1:8765/api/upload',
              '-F', "file=@$($files[$i])", '-F', "client=parallel-$i")
    $procs += Start-Process -FilePath 'curl.exe' -ArgumentList $args `
        -RedirectStandardOutput $tmp[$i] -PassThru -NoNewWindow
}
foreach ($p in $procs) { $p.WaitForExit() }

for ($i = 0; $i -lt $files.Count; $i++) {
    "--- $($files[$i])"
    (Get-Content -Raw -Encoding UTF8 -Path $tmp[$i]).Trim()
}
