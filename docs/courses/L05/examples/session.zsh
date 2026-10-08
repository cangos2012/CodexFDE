# Source from the control repository in zsh. --latest resumes the saved session.
# A failed step stops the current pasted block; expected failures are recorded.
setopt ERR_RETURN INTERACTIVE_COMMENTS

l05Helper="${${(%):-%N}:A}"
l05Control="${l05Helper:h:h:h:h:h}"
l05ResumeFile=''
if [[ -n "${1:-}" ]]; then
  if [[ "$1" == '--latest' ]]; then
    l05Pointer="$l05Control/.runtime/l05-practice/latest-session.txt"
    [[ -f "$l05Pointer" ]] || { print -u2 '尚无会话，请先执行第 1.1 节的初始化命令。'; return 1; }
    l05ResumeFile="$(cat "$l05Pointer")" || return 1
  else
    l05ResumeFile="${1:A}"
  fi
  [[ -f "$l05ResumeFile" ]] || { print -u2 '原会话文件不存在，请核对路径，不创建新会话。'; return 1; }
fi

# Select a local or already activated course venv; never use system Python.
if [[ -x "$l05Control/.venv/bin/python" ]]; then
  l05Python="$l05Control/.venv/bin/python"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  l05Python="${VIRTUAL_ENV:A}/bin/python"
else
  print -u2 '控制仓库没有 .venv；请先恢复 L01 原参考虚拟环境，不使用系统 Python。'
  return 1
fi
# The available course interpreter only reads metadata here. Resumed commands
# always use the interpreter saved in the original session, even if a new local
# venv has since appeared in the control directory.
if [[ -n "$l05ResumeFile" ]]; then
  l05Python="$("$l05Python" -B -X utf8 - "$l05ResumeFile" "$l05Control" <<'PY'
import json, sys
from pathlib import Path
session = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
if not isinstance(session, dict):
    sys.exit('会话不是 JSON 对象，请核对原文件。')
for key in ('control', 'python'):
    value = session.get(key)
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        sys.exit(f'会话缺少有效的绝对路径：{key}')
if Path(session['control']).resolve() != Path(sys.argv[2]).resolve():
    sys.exit('会话属于其他控制仓库，请核对来源。')
if not Path(session['python']).is_file():
    sys.exit('原会话解释器不存在，请恢复原参考环境，不创建新会话。')
print(session['python'])
PY
  )" || return 1
fi
if [[ ! -x "$l05Python" ]]; then
  print -u2 '原会话的虚拟环境解释器不可用，请核对原参考环境。'
  return 1
fi

l05Session="$("$l05Python" -B -X utf8 - "$l05Control" "$l05ResumeFile" "$l05Python" <<'PY'
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
selected_python = Path(sys.argv[3]).absolute()
if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != selected_python.parent.parent.resolve():
    raise SystemExit('所选 Python 不是本次项目虚拟环境，请先恢复原 .venv。')
sys.path.insert(0, str(root))
import workbench
if not Path(workbench.__file__).resolve().is_relative_to(root):
    raise SystemExit('工作台源码不属于当前控制仓库，请核对环境。')
pointer = root / '.runtime/l05-practice/latest-session.txt'
if mode:
    saved = Path(mode)
    session = json.loads(saved.read_text(encoding='utf-8-sig'))
    if Path(session['control']).resolve() != root.resolve():
        raise SystemExit('会话属于其他控制仓库，请核对来源。')
    if Path(session['python']).absolute() != selected_python:
        raise SystemExit('会话解释器与保存的原环境不一致，请核对原会话。')
else:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    run = root / '.runtime/l05-practice' / stamp
    run.mkdir(parents=True)
    session = dict(control=str(root), python=str(selected_python),
                   run=str(run), runtime=str(root / '.runtime/l04-learning'), stamp=stamp,
                   actor='L05 teaching run', gitName='L05 teaching run',
                   gitEmail='l05@example.invalid', identitySource='teaching-default-not-human-review')
    def git_config(key):
        result = subprocess.run(['git', '-C', str(root), 'config', key],
                                capture_output=True, text=True, encoding='utf-8')
        return result.stdout.strip() if result.returncode == 0 else ''
    name, email = git_config('user.name'), git_config('user.email')
    if name and email:
        session.update(actor=name, gitName=name, gitEmail=email,
                       identitySource='existing-git-config-not-human-review')
    saved = run / 'session.json'
    saved.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding='utf-8')
    pointer.write_text(str(saved) + '\n', encoding='utf-8')
print(json.dumps(session, ensure_ascii=False))
PY
)" || return 1

# Read JSON without evaluating it as shell code. Dot paths select nested fields.
l05_field() {
  "$l05Python" -B -X utf8 -c '
import json, sys
value = json.loads(sys.argv[1])
for key in sys.argv[2].split("."):
    value = value[key]
print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
' "$1" "$2"
}

l05Run="$(l05_field "$l05Session" run)"
l05Runtime="$(l05_field "$l05Session" runtime)"
l05Actor="$(l05_field "$l05Session" actor)"
l05Stamp="$(l05_field "$l05Session" stamp)"
l05GitName="$(l05_field "$l05Session" gitName)"
l05GitEmail="$(l05_field "$l05Session" gitEmail)"
l05Examples="$l05Control/docs/courses/L05/examples"
l05Fixture="$l05Run/ledger-fixture"
l05ScopeRepo="$l05Run/scope-repo"
l05Allow="$l05Run/allowed-files.json"
l05Check="$l05Examples/receiving_contract_eval.py"
l05ScopeCheck="$l05Examples/write_scope_eval.py"
l05ScopeFile="$l05ScopeRepo/flowerp/service.py"
l05BusinessArgs=(-m unittest tests.test_l05_receiving -v)
l05EngineeringArgs=(-m unittest tests.test_l05_scope -v)
l05Frozen="$l05Run/frozen-checks.json"
if [[ -f "$l05Run/scope-base.txt" ]]; then
  l05ScopeBase="$(cat "$l05Run/scope-base.txt")"
  l05ScopeArgs=("$l05ScopeCheck" --repo "$l05ScopeRepo" --base "$l05ScopeBase" --allow-file "$l05Allow")
fi
if [[ -f "$l05Run/prepare.json" ]]; then
  l05Prepare="$(cat "$l05Run/prepare.json")"
  l05Candidate="$(l05_field "$l05Prepare" path)"
fi
if [[ -f "$l05Run/submission.json" ]]; then
  l05Submission="$(cat "$l05Run/submission.json")"
  l05Final="$(l05_field "$l05Submission" isolation.path)"
  l05Task="$(l05_field "$l05Submission" task.id)"
fi

# stdout is the JSON record; readable output goes to stderr, including on failure.
l05_command() {
  local name="$1" expected="$2" directory="$3" raw wrapperExit
  shift 3
  if raw="$("$l05Python" -B -X utf8 "$l05Examples/record_command.py" \
    --cwd "$directory" --evidence "$l05Run/evidence" --name "$name" --expect "$expected" -- "$@")"; then
    wrapperExit=0
  else
    wrapperExit=$?
  fi
  if [[ -z "$raw" ]]; then
    print -u2 '记录器没有返回结果，请保留终端错误。'
    return 1
  fi
  "$l05Python" -B -X utf8 -c '
import json, sys
r = json.loads(sys.argv[1])
print(r["stdout"], end="", file=sys.stderr)
print(r["stderr"], end="", file=sys.stderr)
print("[{}] exit={}；证据：{}".format(r["name"], r["exit_code"], r["receipt"]), file=sys.stderr)
' "$raw" || return 1
  print -r -- "$raw"
  if (( wrapperExit != 0 )); then
    print -u2 "退出码与预期不同；先读证据，不继续下一步：$name"
    return 1
  fi
}

l05_python() {
  local name="$1" expected="$2" directory="$3"
  shift 3
  l05_command "$name" "$expected" "$directory" "$l05Python" -B -X utf8 "$@"
}

print -u2 "会话文件：$l05Run/session.json"
print -u2 "控制目录：$l05Control；沿用工作台数据：$l05Runtime"
print -u2 "课程解释器：$l05Python"
