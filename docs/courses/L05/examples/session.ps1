# Dot-source from the control repository. Keep the returned session file to resume.
param([string]$Resume, [switch]$Latest)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$l05Root = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$l05Pointer = Join-Path $l05Root '.runtime/l05-practice/latest-session.txt'
if ($Latest) {
    if (-not (Test-Path -LiteralPath $l05Pointer)) { throw '尚无会话，请先执行第 1.1 节的初始化命令' }
    $Resume = (Get-Content -LiteralPath $l05Pointer -Raw -Encoding utf8).Trim()
}
$root = $l05Root
$l05LocalPython = Join-Path $root '.venv/Scripts/python.exe'
if ($Resume) {
    $script:l05Session = Get-Content -LiteralPath $Resume -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not $l05Session.control -or -not $l05Session.python) { throw '会话缺少控制目录或解释器，请核对原文件。' }
    if (-not [System.IO.Path]::IsPathRooted($l05Session.control) -or -not [System.IO.Path]::IsPathRooted($l05Session.python)) { throw '会话控制目录和解释器必须是绝对路径。' }
    if ((Resolve-Path -LiteralPath $l05Session.control).Path -ne $l05Root) { throw '会话属于其他控制仓库，请核对来源。' }
    $l05SelectedPython = [System.IO.Path]::GetFullPath($l05Session.python)
} elseif (Test-Path -LiteralPath $l05LocalPython -PathType Leaf) {
    $l05SelectedPython = (Resolve-Path -LiteralPath $l05LocalPython).Path
} elseif ($env:VIRTUAL_ENV -and (Test-Path -LiteralPath (Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe') -PathType Leaf)) {
    $l05SelectedPython = (Resolve-Path -LiteralPath (Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe')).Path
} else {
    throw '控制仓库没有 .venv；请先恢复 L01 原参考虚拟环境，不使用系统 Python。'
}
if (-not (Test-Path -LiteralPath $l05SelectedPython -PathType Leaf)) { throw '原会话的虚拟环境解释器不可用，请核对原参考环境。' }
$l05VerifyPython = @'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
selected = Path(sys.argv[2]).absolute()
if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != selected.parent.parent.resolve():
    sys.exit('所选 Python 不是本次项目虚拟环境，请先恢复原 .venv。')
sys.path.insert(0, str(root))
import workbench
if not Path(workbench.__file__).resolve().is_relative_to(root):
    sys.exit('工作台源码不属于当前控制仓库，请核对环境。')
'@
& $l05SelectedPython -B -X utf8 -c $l05VerifyPython $l05Root $l05SelectedPython
if ($LASTEXITCODE -ne 0) { throw '课程解释器或控制源码核对失败，请先排查原环境。' }
if (-not $Resume) {
    $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $run = Join-Path $root ".runtime/l05-practice/$stamp"
    New-Item -ItemType Directory -Path $run | Out-Null
    $script:l05Session = [pscustomobject]@{
        control=$root; python=$l05SelectedPython; run=$run
        runtime=(Join-Path $root '.runtime/l04-learning'); stamp=$stamp
        actor='L05 teaching run'; gitName='L05 teaching run'; gitEmail='l05@example.invalid'
        identitySource='teaching-default-not-human-review'
    }
    $gitName = & git -C $root config user.name
    $gitEmail = & git -C $root config user.email
    if ($gitName -and $gitEmail) {
        $l05Session.actor = $gitName.Trim()
        $l05Session.gitName = $gitName.Trim()
        $l05Session.gitEmail = $gitEmail.Trim()
        $l05Session.identitySource = 'existing-git-config-not-human-review'
    }
    $script:l05Session | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'session.json') -Encoding utf8
    (Join-Path $run 'session.json') | Set-Content -LiteralPath $l05Pointer -Encoding utf8
}
$l05Control = $l05Session.control
$l05Python = $l05Session.python
$l05Run = $l05Session.run
$l05Runtime = $l05Session.runtime
$l05Actor = $l05Session.actor
$l05Examples = Join-Path $l05Control 'docs/courses/L05/examples'
$l05Fixture = Join-Path $l05Run 'ledger-fixture'
$l05ScopeRepo = Join-Path $l05Run 'scope-repo'
$l05Allow = Join-Path $l05Run 'allowed-files.json'
$l05Check = Join-Path $l05Examples 'receiving_contract_eval.py'
$l05ScopeCheck = Join-Path $l05Examples 'write_scope_eval.py'
$l05ScopeFile = Join-Path $l05ScopeRepo 'flowerp/service.py'
$l05BusinessArgs = @('-m','unittest','tests.test_l05_receiving','-v')
$l05EngineeringArgs = @('-m','unittest','tests.test_l05_scope','-v')
$l05Frozen = Join-Path $l05Run 'frozen-checks.json'
if (Test-Path -LiteralPath (Join-Path $l05Run 'scope-base.txt')) {
    $l05ScopeBase = (Get-Content -LiteralPath (Join-Path $l05Run 'scope-base.txt') -Raw -Encoding utf8).Trim()
    $l05ScopeArgs = @($l05ScopeCheck,'--repo',$l05ScopeRepo,'--base',$l05ScopeBase,'--allow-file',$l05Allow)
}
if (Test-Path -LiteralPath (Join-Path $l05Run 'prepare.json')) {
    $l05Prepare = Get-Content -LiteralPath (Join-Path $l05Run 'prepare.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $l05Candidate = $l05Prepare.path
}
if (Test-Path -LiteralPath (Join-Path $l05Run 'submission.json')) {
    $l05Submission = Get-Content -LiteralPath (Join-Path $l05Run 'submission.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $l05Final = $l05Submission.isolation.path
    $l05Task = $l05Submission.task.id
}
function Invoke-L05 {
    param([string]$Name, [int]$Expected, [string]$Directory, [string[]]$Command)
    $commandFile = Join-Path $l05Run ('command-' + [guid]::NewGuid().ToString('N') + '.json')
    ConvertTo-Json -InputObject @($Command) | Set-Content -LiteralPath $commandFile -Encoding utf8
    $raw = & $l05Python -B -X utf8 (Join-Path $l05Examples 'record_command.py') --cwd $Directory --evidence (Join-Path $l05Run 'evidence') --name $Name --expect $Expected --command-file $commandFile
    $wrapperExit = $LASTEXITCODE
    $record = $raw | ConvertFrom-Json
    Write-Host $record.stdout
    if ($record.stderr) { Write-Host $record.stderr }
    Write-Host "[$Name] exit=$($record.exit_code)；证据：$($record.receipt)"
    if ($wrapperExit -ne 0) { throw "退出码与预期不同；先读证据，不继续下一步：$Name" }
    return $record
}
function Invoke-L05Python {
    param([string]$Name, [int]$Expected, [string]$Directory, [string[]]$Arguments)
    Invoke-L05 $Name $Expected $Directory (@($l05Python, '-B', '-X', 'utf8') + $Arguments)
}
Write-Host "会话文件：$(Join-Path $l05Run 'session.json')"
Write-Host "控制目录：$l05Control；沿用工作台数据：$l05Runtime"
Write-Host "课程解释器：$l05Python"
