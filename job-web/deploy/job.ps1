#Requires -Version 5.1
<#
.SYNOPSIS
    求职系统 · 一键启停控制台

.DESCRIPTION
    一条命令管理求职系统的全部组件：
      MySQL(3306) / Redis(6379) / Ollama(11434) / Python Agent(8000) / Java(8080) / nginx(81)

    .\job.ps1            交互菜单（双击 启动.bat 也是走这里）
    .\job.ps1 start      一键启动
    .\job.ps1 stop       一键停止
    .\job.ps1 restart    重启
    .\job.ps1 status     只看状态

.NOTES
    * 本文件必须保存为 **UTF-8 with BOM**：本机是 Windows PowerShell 5.1，
      读无 BOM 的 UTF-8 会按 GBK 解释，中文乱码后连结尾引号都会被吃掉。
    * 全程兼容 PowerShell 5.1（不用 ??、?.、三元运算符）。
    * **端口冲突是这个脚本要处理的头号问题**：本机的「边坡监测系统」也用
      8080 和 8000。脚本会识别出"端口被谁占着"，并在动手前问清楚，
      绝不静默失败 —— 旧版 bat 就是静默失败，很难发现。
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('menu', 'start', 'stop', 'restart', 'status', 'token')]
    [string]$Action = 'menu',
    # 端口被边坡系统占用时自动停掉它，不再交互询问（供脚本调用）
    [switch]$Force
)

$ErrorActionPreference = 'Continue'

# ══════════════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════════════

$DeployDir = $PSScriptRoot
$WebDir    = Split-Path -Parent $DeployDir         # job-web
$Root      = Split-Path -Parent $WebDir            # Find_job
$LogDir    = Join-Path $Root 'logs'

$JavaDir   = Join-Path $Root 'job-platform'
$AgentDir  = Join-Path $Root 'job-agent'
$JarPath   = Join-Path $JavaDir 'job-server\target\job-server-1.0-SNAPSHOT.jar'
$NginxConf = Join-Path $DeployDir 'nginx.conf'

# 边坡系统（端口冲突的来源）的停止脚本
$SlopeStop = 'C:\Users\Lenovo\Desktop\new_rag\slope-web\deploy\slope.ps1'

$NginxHome = $env:JOB_NGINX_HOME
$RedisHome = $env:JOB_REDIS_HOME

$Ports = [ordered]@{
    MySQL  = 3306
    Redis  = 6379
    Ollama = 11434
    Agent  = 8000
    Java   = 8080
    Nginx  = 81
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ══════════════════════════════════════════════════════════════════
#  输出helper
# ══════════════════════════════════════════════════════════════════

function Write-Title($text) {
    Write-Host ''
    Write-Host ('═' * 60) -ForegroundColor DarkCyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ('═' * 60) -ForegroundColor DarkCyan
}
function Write-Step($t) { Write-Host "  → $t" -ForegroundColor Gray }
function Write-Ok($t)   { Write-Host "  ✅ $t" -ForegroundColor Green }
function Write-Warn2($t){ Write-Host "  ⚠️  $t" -ForegroundColor Yellow }
function Write-Bad($t)  { Write-Host "  ❌ $t" -ForegroundColor Red }
function Write-Info($t) { Write-Host "     $t" -ForegroundColor DarkGray }

# ══════════════════════════════════════════════════════════════════
#  端口与进程
# ══════════════════════════════════════════════════════════════════

function Test-PortOpen {
    param([int]$Port, [string]$TargetHost = '127.0.0.1', [int]$TimeoutMs = 800)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        $done = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($done -and $client.Connected) { $client.EndConnect($iar); return $true }
        return $false
    } catch { return $false } finally { try { $client.Close() } catch { } }
}

function Get-PortOwner {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
         Select-Object -First 1
    if (-not $c) { return $null }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    $cmd = ''
    if ($p -and $p.CommandLine) { $cmd = [string]$p.CommandLine }
    return @{ PID = $c.OwningProcess; Name = $(if ($p) { $p.Name } else { '?' }); Cmd = $cmd }
}

<#
.SYNOPSIS 分类端口占用者。
.OUTPUTS
    'free'   端口空闲
    'self'   是我们自己（求职系统）的组件，已在运行
    'other'  被另一个项目占用（目前只有边坡系统）
    'alien'  被不认识的进程占用
#>
function Get-PortKind {
    param([int]$Port, [string]$Component)
    $o = Get-PortOwner -Port $Port
    if (-not $o) { return @{ Kind = 'free'; Owner = $null } }
    $cmd = $o.Cmd
    $isSelf = $false
    switch ($Component) {
        'Java'   { if ($cmd -match 'job-server|job-platform') { $isSelf = $true } }
        'Agent'  { if ($cmd -match 'app\.main:app' -or $cmd -match 'job-agent') { $isSelf = $true } }
        'Nginx'  { if ($cmd -match 'nginx') { $isSelf = $true } }
        'Redis'  { if ($cmd -match 'redis-server') { $isSelf = $true } }
        'Ollama' { if ($cmd -match 'ollama') { $isSelf = $true } }
        'MySQL'  { if ($cmd -match 'mysqld') { $isSelf = $true } }
    }
    if ($isSelf) { return @{ Kind = 'self'; Owner = $o } }
    if ($cmd -match 'slope-platform|end_new\.py|new_rag') {
        return @{ Kind = 'other'; Owner = $o }
    }
    return @{ Kind = 'alien'; Owner = $o }
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 120)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Find-ToolHome {
    param([string]$ExeName, [string]$NamePattern, [string[]]$ExtraPaths)
    foreach ($p in $ExtraPaths) {
        if ($p -and (Test-Path (Join-Path $p $ExeName))) { return $p }
    }
    $cmd = Get-Command $ExeName -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path -Parent $cmd.Source) }
    foreach ($drive in (Get-PSDrive -Provider FileSystem).Root) {
        $hit = Get-ChildItem -Path $drive -Directory -Filter $NamePattern `
                   -Recurse -Depth 3 -ErrorAction SilentlyContinue |
               Where-Object { Test-Path (Join-Path $_.FullName $ExeName) } |
               Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

# ══════════════════════════════════════════════════════════════════
#  端口冲突处理（本脚本的重点）
# ══════════════════════════════════════════════════════════════════

<#
.SYNOPSIS 检查 Agent(8000) 与 Java(8080) 是否被边坡系统占用；是则询问是否停掉它。
.OUTPUTS  $true 可以继续启动；$false 应当中止
#>
function Resolve-PortConflicts {
    $conflicts = @()
    foreach ($item in @(
            @{ C = 'Agent'; P = $Ports.Agent; N = 'Python Agent' },
            @{ C = 'Java';  P = $Ports.Java;  N = 'Java 后端'    })) {
        $k = Get-PortKind -Port $item.P -Component $item.C
        if ($k.Kind -eq 'other' -or $k.Kind -eq 'alien') {
            $conflicts += [pscustomobject]@{
                Name = $item.N; Port = $item.P; Kind = $k.Kind; Owner = $k.Owner
            }
        }
    }
    if ($conflicts.Count -eq 0) { return $true }

    Write-Host ''
    Write-Host '  ┌─ 端口冲突 ─────────────────────────────────────' -ForegroundColor Yellow
    foreach ($c in $conflicts) {
        $who = if ($c.Kind -eq 'other') { '边坡监测系统' } else { $c.Owner.Name }
        Write-Host ("  │ {0} 需要 :{1}，但已被【{2}】占用 (PID {3})" -f $c.Name, $c.Port, $who, $c.Owner.PID) -ForegroundColor Yellow
    }
    Write-Host '  └────────────────────────────────────────────────' -ForegroundColor Yellow
    Write-Host ''
    Write-Info '两个项目用的是同一组端口（8080 / 8000），不能同时运行。'

    $allSlope = ($conflicts | Where-Object { $_.Kind -eq 'other' }).Count -eq $conflicts.Count

    if (-not $allSlope) {
        Write-Bad '占用者不是边坡系统，本脚本不会去杀不认识的进程。'
        Write-Info '请先手工释放上面这些端口，再重新启动。'
        return $false
    }

    if (-not $Force) {
        $ans = Read-Host '  要先停掉【边坡监测系统】再继续吗？(Y/n)'
        if ($ans -and $ans -notmatch '^[Yy]') {
            Write-Warn2 '已取消启动。'
            return $false
        }
    } else {
        Write-Step '（-Force）自动停掉边坡系统…'
    }

    if (Test-Path $SlopeStop) {
        Write-Step '调用边坡系统的停止脚本…'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $SlopeStop stop 2>&1 |
            Where-Object { $_ -match '已停止|已释放|仍被占用' } |
            ForEach-Object { Write-Info $_ }
    } else {
        # 找不到对方的脚本时，退化为按命令行精确清理（仍然只杀确定的那些）
        Write-Warn2 "找不到 $SlopeStop，改为按进程命令行清理"
        Get-CimInstance Win32_Process -Filter "Name='java.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like '*slope-platform*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like '*end_new.py*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }

    Start-Sleep -Seconds 2
    $still = @()
    foreach ($p in @($Ports.Agent, $Ports.Java)) {
        if (Test-PortOpen -Port $p) { $still += $p }
    }
    if ($still.Count -gt 0) {
        Write-Bad ("端口仍未释放：{0}" -f ($still -join ', '))
        return $false
    }
    Write-Ok '端口已释放，继续启动'
    return $true
}

# ══════════════════════════════════════════════════════════════════
#  状态
# ══════════════════════════════════════════════════════════════════

function Show-Status {
    Write-Title '求职系统 · 服务状态'
    <#
      排版：不要用 "{0,-20}" 对齐含中文的名字 —— PowerShell 按字符数补空格，
      而中文占两格宽，列必然错位。ASCII 名字放前面负责对齐，中文放最后。
    #>
    $rows = @(
        @{ N = 'MySQL '; P = $Ports.MySQL;  C = 'MySQL';  D = '数据库 (系统服务)' },
        @{ N = 'Redis '; P = $Ports.Redis;  C = 'Redis';  D = '缓存' },
        @{ N = 'Ollama'; P = $Ports.Ollama; C = 'Ollama'; D = '向量模型 (RAG)' },
        @{ N = 'Agent '; P = $Ports.Agent;  C = 'Agent';  D = 'Python AI Agent' },
        @{ N = 'Java  '; P = $Ports.Java;   C = 'Java';   D = 'Spring Boot 业务后端' },
        @{ N = 'nginx '; P = $Ports.Nginx;  C = 'Nginx';  D = '前端入口' }
    )
    $up = 0
    foreach ($r in $rows) {
        $k = Get-PortKind -Port $r.P -Component $r.C
        $isUp = $k.Kind -ne 'free'
        if ($isUp) { $up++ }
        $mark = switch ($k.Kind) {
            'free'  { '未运行' }
            'self'  { '运行中' }
            'other' { '被边坡系统占用' }
            default { '被其它进程占用' }
        }
        $color = switch ($k.Kind) {
            'self'  { 'Green' }
            'free'  { 'DarkGray' }
            default { 'Yellow' }
        }
        Write-Host ("    {0} :{1,-6} {2}   " -f $r.N, $r.P, $mark) -NoNewline -ForegroundColor $color
        Write-Host $r.D -ForegroundColor DarkGray
    }

    Write-Host ''
    Write-Host "    求职系统组件：$up / 6 就绪" -ForegroundColor $(if ($up -eq 6) { 'Green' } else { 'Yellow' })

    if (Test-PortOpen -Port $Ports.Nginx) {
        Write-Host ''
        Write-Host '    访问入口：' -NoNewline -ForegroundColor Gray
        Write-Host "http://127.0.0.1:$($Ports.Nginx)/" -ForegroundColor White
        Write-Host '    管理员账号：' -NoNewline -ForegroundColor Gray
        Write-Host 'admin / 123456' -ForegroundColor White
    }
}

# ══════════════════════════════════════════════════════════════════
#  启动
# ══════════════════════════════════════════════════════════════════

function Start-MySQL {
    $k = Get-PortKind -Port $Ports.MySQL -Component 'MySQL'
    if ($k.Kind -ne 'free') { Write-Ok 'MySQL 已在运行'; return $true }
    # MySQL 是 Windows 服务，net start 需要管理员权限，失败时如实说明
    $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'mysql' } | Select-Object -First 1
    if (-not $svc) { Write-Warn2 '找不到 MySQL 服务'; return $false }
    Write-Step "尝试启动服务 $($svc.Name)…"
    try { Start-Service -Name $svc.Name -ErrorAction Stop } catch {
        Write-Warn2 "启动失败（多半是权限不足，请用管理员身份运行）：$($_.Exception.Message)"
        return $false
    }
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-PortOpen -Port $Ports.MySQL) { Write-Ok 'MySQL 已启动'; return $true }
        Start-Sleep -Milliseconds 800
    }
    Write-Warn2 'MySQL 启动超时'
    return $false
}

function Start-Redis {
    if ((Get-PortKind -Port $Ports.Redis -Component 'Redis').Kind -ne 'free') {
        Write-Ok 'Redis 已在运行'; return $true
    }
    if (-not $RedisHome) {
        $RedisHome = Find-ToolHome -ExeName 'redis-server.exe' -NamePattern 'Redis*' `
            -ExtraPaths @('D:\develop_software\Redis-x64-3.2.100', 'C:\Redis', 'C:\Program Files\Redis')
    }
    if (-not $RedisHome) { Write-Warn2 '找不到 redis-server.exe，跳过'; return $false }
    Start-Process -FilePath (Join-Path $RedisHome 'redis-server.exe') `
        -WorkingDirectory $RedisHome -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'redis.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'redis.err.log')
    for ($i = 0; $i -lt 15; $i++) {
        if (Test-PortOpen -Port $Ports.Redis) { Write-Ok 'Redis 已启动'; return $true }
        Start-Sleep -Milliseconds 700
    }
    Write-Warn2 'Redis 启动超时'
    return $false
}

function Start-Ollama {
    if ((Get-PortKind -Port $Ports.Ollama -Component 'Ollama').Kind -ne 'free') {
        Write-Ok 'Ollama 已在运行'; return $true
    }
    $exe = (Get-Command ollama -ErrorAction SilentlyContinue)
    if (-not $exe) { Write-Warn2 '找不到 ollama，RAG 向量检索会不可用'; return $false }
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    for ($i = 0; $i -lt 25; $i++) {
        if (Test-PortOpen -Port $Ports.Ollama) { Write-Ok 'Ollama 已启动'; return $true }
        Start-Sleep -Seconds 1
    }
    Write-Warn2 'Ollama 启动超时（RAG 可能不可用）'
    return $false
}

function Start-Agent {
    if ((Get-PortKind -Port $Ports.Agent -Component 'Agent').Kind -ne 'free') {
        Write-Ok 'Python Agent 已在运行'; return $true
    }
    if (-not (Test-Path (Join-Path $AgentDir 'app\main.py'))) {
        Write-Bad "找不到 $AgentDir\app\main.py"; return $false
    }
    Start-Process -FilePath 'python' `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', "$($Ports.Agent)" `
        -WorkingDirectory $AgentDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'job-agent.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'job-agent.err.log')

    # 就绪判据用 /agent/... 之外的轻量路径：uvicorn 起来后端口先通，
    # 这里等端口 + 一次 HTTP 探测，避免"端口通了但应用还没就绪"
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-PortOpen -Port $Ports.Agent) {
            Start-Sleep -Seconds 3
            Write-Ok "Python Agent 已就绪 (:$($Ports.Agent))"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Bad 'Agent 启动超时，看 logs\job-agent.err.log'
    return $false
}

function Start-Java {
    if ((Get-PortKind -Port $Ports.Java -Component 'Java').Kind -ne 'free') {
        Write-Ok 'Java 后端已在运行'; return $true
    }
    if (-not (Test-Path $JarPath)) {
        Write-Bad "找不到 jar：$JarPath"
        Write-Info '先构建：cd job-platform && mvn -q -DskipTests install'
        return $false
    }
    # 用 java -jar 而不是 mvn spring-boot:run：后者每次都要走一遍 Maven 生命周期，
    # 启动慢很多（旧脚本就是那样，双击后要等很久）。
    Start-Process -FilePath 'java' -ArgumentList '-jar', "`"$JarPath`"" `
        -WorkingDirectory $JavaDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'job-java.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'job-java.err.log')
    # ⚠️ 就绪探测必须用**后端的真实路径** `/user/stats`，不能写 `/api/user/stats`。
    #    Java 没有 /api 这个 context-path（application.yml 里无 server.servlet.context-path，
    #    控制器就是 @RequestMapping("/user/stats")），/api 只是 nginx 给前端加的前缀。
    #    写错的话后端其实已经起来了，这里却一直 404，误报"启动超时"。
    if (Wait-HttpOk -Url "http://127.0.0.1:$($Ports.Java)/user/stats" -TimeoutSec 150) {
        Write-Ok "Java 后端已就绪 (:$($Ports.Java))"
        return $true
    }
    Write-Bad 'Java 启动超时，看 logs\job-java.err.log'
    return $false
}

function Start-Nginx {
    if (-not $NginxHome) {
        $NginxHome = Find-ToolHome -ExeName 'nginx.exe' -NamePattern 'nginx*' `
            -ExtraPaths @('D:\develop_software\nginx-1.20.2', 'C:\nginx', 'C:\Program Files\nginx')
    }
    if (-not $NginxHome) {
        Write-Bad '找不到 nginx.exe。可用 $env:JOB_NGINX_HOME 指定目录'
        return $false
    }
    $exe = Join-Path $NginxHome 'nginx.exe'

    # 先做配置检查，配置写错时给明确报错而不是静默失败
    $test = & $exe -p "$NginxHome" -c "$NginxConf" -t 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Bad 'nginx 配置检查未通过：'
        $test | ForEach-Object { Write-Info $_ }
        return $false
    }

    $k = Get-PortKind -Port $Ports.Nginx -Component 'Nginx'
    if ($k.Kind -eq 'self') {
        # 注意：同一个 nginx 主进程可能同时托管多个站点配置，
        # 这里用 -c 指定本项目的配置重载，只影响本文件定义的 server。
        & $exe -p "$NginxHome" -c "$NginxConf" -s reload 2>$null
        Write-Ok "nginx 已重载 (:$($Ports.Nginx))"
        return $true
    }
    if ($k.Kind -ne 'free') {
        Write-Bad "端口 $($Ports.Nginx) 被 $($k.Owner.Name) 占用，无法启动 nginx"
        return $false
    }
    Start-Process -FilePath $exe -ArgumentList '-p', "$NginxHome", '-c', "$NginxConf" `
        -WorkingDirectory "$NginxHome" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    if (Test-PortOpen -Port $Ports.Nginx) { Write-Ok "nginx 已启动 (:$($Ports.Nginx))"; return $true }
    Write-Bad 'nginx 启动失败'
    return $false
}

function Invoke-Start {
    Write-Title '启动求职系统'

    # 先解决端口冲突，再动任何东西 —— 否则后面每步都会因为端口占用而失败，
    # 报错信息还会互相掩盖，排查起来很痛苦。
    if (-not (Resolve-PortConflicts)) {
        Write-Host ''
        Write-Warn2 '启动已中止（端口冲突未解决）'
        return
    }

    Write-Host ''
    Start-MySQL  | Out-Null
    Start-Redis  | Out-Null
    Start-Ollama | Out-Null
    Start-Agent  | Out-Null
    Start-Java   | Out-Null
    Start-Nginx  | Out-Null
    Write-Host ''
    Show-Status
}

# ══════════════════════════════════════════════════════════════════
#  停止
# ══════════════════════════════════════════════════════════════════

function Stop-Nginx {
    if ($NginxHome -and (Test-Path (Join-Path $NginxHome 'nginx.exe'))) {
        & (Join-Path $NginxHome 'nginx.exe') -p "$NginxHome" -c "$NginxConf" -s stop 2>$null
        Start-Sleep -Seconds 2
    }
    if (Test-PortOpen -Port $Ports.Nginx) {
        # 只杀本项目的 nginx（按配置文件路径匹配），不要一刀切杀掉所有 nginx
        Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*$NginxConf*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
    if (Test-PortOpen -Port $Ports.Nginx) { Write-Warn2 "nginx 仍在监听 $($Ports.Nginx)" }
    else { Write-Ok 'nginx 已停止' }
}

function Stop-Java {
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='java.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*job-server*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }
    Start-Sleep -Seconds 1
    Write-Ok "Java 后端已停止（$n 个进程）"
}

function Stop-Agent {
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*app.main:app*' -or $_.CommandLine -like '*job-agent*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }
    Start-Sleep -Seconds 1
    Write-Ok "Python Agent 已停止（$n 个进程）"
}

function Invoke-Stop {
    Write-Title '停止求职系统'
    # 顺序与启动相反：先断入口，再停后端，避免"页面能访问但后端已没了"的空窗
    Stop-Nginx
    Stop-Java
    Stop-Agent
    # Redis / Ollama / MySQL 是**共用基础设施**，边坡系统也在用，默认不停。
    # 想一起停可以手工执行，避免"关一个项目把另一个项目的依赖也关了"。
    Write-Info 'Redis / Ollama / MySQL 为共用依赖，默认保留运行'
    Write-Host ''
    Show-Status
}

# ══════════════════════════════════════════════════════════════════
#  菜单
# ══════════════════════════════════════════════════════════════════

function Show-Menu {
    while ($true) {
        Write-Host ''
        Write-Host ('═' * 60) -ForegroundColor DarkCyan
        Write-Host '   求职系统 · 控制台' -ForegroundColor Cyan
        Write-Host ('═' * 60) -ForegroundColor DarkCyan

        $core = @(
            (Get-PortKind -Port $Ports.Agent -Component 'Agent').Kind -ne 'free'
            (Get-PortKind -Port $Ports.Java  -Component 'Java').Kind  -ne 'free'
            (Get-PortKind -Port $Ports.Nginx -Component 'Nginx').Kind -ne 'free'
        )
        $n = ($core | Where-Object { $_ }).Count
        Write-Host "   核心组件：$n / 3 运行中" -ForegroundColor $(if ($n -eq 3) { 'Green' } elseif ($n -eq 0) { 'DarkGray' } else { 'Yellow' })

        # 端口被边坡系统占着时提前提示，别等用户点了启动才知道
        $c1 = Get-PortKind -Port $Ports.Java -Component 'Java'
        $c2 = Get-PortKind -Port $Ports.Agent -Component 'Agent'
        if ($c1.Kind -eq 'other' -or $c2.Kind -eq 'other') {
            Write-Host '   ⚠️  8080/8000 被【边坡监测系统】占用，启动前会询问是否停掉它' -ForegroundColor Yellow
        }

        Write-Host ''
        Write-Host '   [1] 启动全部服务' -ForegroundColor White
        Write-Host '   [2] 停止全部服务' -ForegroundColor White
        Write-Host '   [3] 重启' -ForegroundColor White
        Write-Host '   [4] 查看状态' -ForegroundColor White
        Write-Host '   [5] 打开前端页面' -ForegroundColor White
        Write-Host '   [6] 触发一次岗位爬取' -ForegroundColor White
        Write-Host '   [7] 生成用户态 Token（供 Postman / curl 调试 AI 用）' -ForegroundColor White
        Write-Host '   [0] 退出' -ForegroundColor DarkGray
        Write-Host ''
        $c = Read-Host '   请选择'
        switch ($c) {
            '1' { Invoke-Start }
            '2' { Invoke-Stop }
            '3' { Invoke-Stop; Start-Sleep -Seconds 2; Invoke-Start }
            '4' { Show-Status }
            '5' { Start-Process "http://127.0.0.1:$($Ports.Nginx)/"; Write-Ok "已打开 http://127.0.0.1:$($Ports.Nginx)/" }
            '6' { Invoke-Crawl }
            '7' { Get-UserToken }
            '0' { return }
            default { Write-Warn2 '请输入 0-7' }
        }
    }
}

<#
.SYNOPSIS 生成一个用户态 JWT，供 Postman / curl 等浏览器之外的工具调试 AI 接口用。

.DESCRIPTION
    页面里点「演示登录」就能生成，本函数是给**浏览器之外**的场景用的。

    为什么需要单独造 token：AI 接口（/user/agent/**）要的是**用户态** token
    （请求头 authentication），而系统唯一的用户登录入口是「微信 code 换 token」，
    浏览器和 Postman 都拿不到 code。管理端的 token 也换不来（后端会 401）。

    密钥推导有个坑（子代理实测确认，我也独立复核过）：
      JwtUtil 用 jjwt 0.9.1 的 signWith(HS256, String)，该重载把字符串**当 Base64 解**，
      而它的解码器**只处理完整的 4 字符组** —— "itcast" 6 个字符，尾部 "st" 被丢弃，
      实际只用了 "itca"，解出 3 字节 8a d7 1a。
      用 UTF-8 直取 "itcast"（6 字节）或标准 Base64（4 字节）签名，后端一律 401。
#>
function Get-UserToken {
    param([int]$UserId = 1, [int]$Hours = 2)

    function ConvertTo-B64Url([byte[]]$bytes) {
        return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    }

    # 复刻 jjwt 的宽松 Base64：只保留完整的 4 字符组
    $secret = 'itcast'
    $keep = $secret.Substring(0, [Math]::Floor($secret.Length / 4) * 4)   # -> "itca"
    $pad = 4 - ($keep.Length % 4)
    if ($pad -eq 4) { $pad = 0 }                                          # 已是 4 的倍数就不用补
    $keyBytes = [Convert]::FromBase64String($keep + ('=' * $pad))
    Write-Step "密钥推导：'$secret' -> jjwt 宽松解码 -> $($keyBytes.Length) 字节 ($([BitConverter]::ToString($keyBytes).Replace('-','').ToLower()))"

    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $header = '{"alg":"HS256"}'
    $payload = '{"userId":' + $UserId + ',"exp":' + ($now + $Hours * 3600) + '}'

    $h = ConvertTo-B64Url ([Text.Encoding]::UTF8.GetBytes($header))
    $p = ConvertTo-B64Url ([Text.Encoding]::UTF8.GetBytes($payload))
    $signingInput = "$h.$p"

    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    $hmac.Key = $keyBytes
    $sig = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($signingInput))
    $token = "$signingInput." + (ConvertTo-B64Url $sig)

    Write-Host ''
    Write-Output $token
    Write-Host ''
    Write-Info "userId=$UserId   有效期 ${Hours} 小时   长度 $($token.Length)"

    # 立刻拿后端自检 —— 自签 token 如果后端不认，就是废纸，
    # 必须先验一次再交给用户，免得让人以为成功了却一直 401。
    if (Test-PortOpen -Port $Ports.Java) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($Ports.Java)/user/agent/history?sessionId=token-check" `
                -Headers @{ authentication = $token } -UseBasicParsing -TimeoutSec 15
            if ($r.StatusCode -eq 200) {
                Write-Ok '后端校验通过（GET /user/agent/history → 200）'
            } else {
                Write-Warn2 "后端返回 $($r.StatusCode)，token 可能无效"
            }
        } catch {
            Write-Warn2 "后端校验失败：$($_.Exception.Message)"
        }
    } else {
        Write-Warn2 "Java 后端未运行，跳过校验（启动后再验一次）"
    }

    Write-Host ''
    Write-Info '用法示例：'
    Write-Info "  curl -H ""authentication: $($token.Substring(0,24))..."" http://127.0.0.1:$($Ports.Java)/user/agent/history?sessionId=demo"
    Write-Info '  或粘贴到 Web 页面的「用户态 Token」输入框里'
}


<#
.SYNOPSIS 触发一次岗位爬取（登录 → 调 /admin/crawl/run）。
.NOTES 耗时 1~3 分钟，所以用 script: 作用域的超时而不是默认值。
#>
function Invoke-Crawl {
    if (-not (Test-PortOpen -Port $Ports.Java)) {
        Write-Bad 'Java 后端未运行，无法触发爬取'
        return
    }
    try {
        $login = Invoke-RestMethod -Uri "http://127.0.0.1:$($Ports.Java)/api/admin/employee/login" `
            -Method Post -ContentType 'application/json' `
            -Body (@{ username = 'admin'; password = '123456' } | ConvertTo-Json) -TimeoutSec 15
        if ($login.code -ne 1) { Write-Bad "登录失败：$($login.msg)"; return }
        $token = $login.data.token
        Write-Step '已登录，开始爬取（1~3 分钟，请稍候）…'
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$($Ports.Java)/api/admin/crawl/run" `
            -Method Post -Headers @{ token = $token } -TimeoutSec 600
        $sw.Stop()
        if ($r.code -eq 1) {
            Write-Ok "爬取完成：新增/更新 $($r.data) 条，耗时 $([int]$sw.Elapsed.TotalSeconds)s"
        } else {
            Write-Bad "爬取失败：$($r.msg)"
        }
    } catch {
        Write-Bad "爬取出错：$($_.Exception.Message)"
    }
}

# ══════════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════════

switch ($Action) {
    'start'   { Invoke-Start }
    'stop'    { Invoke-Stop }
    'restart' { Invoke-Stop; Start-Sleep -Seconds 2; Invoke-Start }
    'status'  { Show-Status }
    'token'   { Get-UserToken }
    default   { Show-Menu }
}
