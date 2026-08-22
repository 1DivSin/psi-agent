$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$statePath = Join-Path $root 'rollback-state.json'

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host '没有可回滚的更新。'
    exit 0
}

$state = $null
try {
    $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $statePath | ConvertFrom-Json
} catch {
    Write-Host '回滚状态文件无法读取，请检查 rollback-state.json。'
    exit 1
}

if (-not $state -or $state.status -notin @('pending', 'done') -or [string]::IsNullOrWhiteSpace($state.last_update)) {
    Write-Host '没有可回滚的更新。'
    exit 0
}

$components = switch ($state.last_update) {
    'app'  { 'app' }
    'msys' { 'msys64' }
    'all'  { 'app', 'msys64' }
    default { $null }
}

if (-not $components) {
    Write-Host '没有可回滚的更新记录。'
    exit 0
}

Write-Host '正在关闭海豚进程...'
$ErrorActionPreference = 'Continue'
& taskkill.exe /F /IM haitun.exe 2>$null | Out-Null
& taskkill.exe /F /T /IM psi-agent.exe 2>$null | Out-Null
Start-Sleep -Milliseconds 500
$ErrorActionPreference = 'Stop'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$restored = @()

foreach ($name in $components) {
    $current = Join-Path $root $name
    $backup = Join-Path $root ($name + '.backup')

    if (-not (Test-Path -LiteralPath $backup)) {
        Write-Warning "$name 没有可用的备份，跳过。"
        continue
    }

    $broken = Join-Path $root ("broken-" + $name + "-" + $stamp)
    try {
        if (Test-Path -LiteralPath $current) {
            Move-Item -LiteralPath $current -Destination $broken -Force
        }
        Move-Item -LiteralPath $backup -Destination $current -Force
        if (Test-Path -LiteralPath $broken) {
            Remove-Item -LiteralPath $broken -Recurse -Force
        }
        $restored += $name
        Write-Host ("已恢复 " + $name)
    } catch {
        if (Test-Path -LiteralPath $broken) {
            Move-Item -LiteralPath $broken -Destination $current -Force -ErrorAction SilentlyContinue
        }
        Write-Host ("回滚失败: " + $name)
        exit 1
    }
}

if ($restored.Count -eq 0) {
    if ($state.status -eq 'pending') {
        $state.last_update = ''
        $state.status = 'none'
        $tmp = $statePath + '.tmp'
        $state | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $tmp
        Move-Item -LiteralPath $tmp -Destination $statePath -Force
        Write-Host '未发现可恢复的备份，已清除未完成的更新状态。'
    } else {
        Write-Host '没有找到可恢复的备份，未做任何修改。'
    }
    exit 0
}

$state.last_update = ''
$state.status = 'rolled_back'
$tmp = $statePath + '.tmp'
$state | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $tmp
Move-Item -LiteralPath $tmp -Destination $statePath -Force

$exe = Join-Path $root 'app\haitun.exe'
if (Test-Path -LiteralPath $exe) {
    Start-Process -FilePath $exe
    Write-Host '海豚已重新启动。'
}

Write-Host '回滚完成。'
