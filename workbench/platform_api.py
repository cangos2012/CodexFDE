from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
import threading
from urllib.parse import parse_qs

from .agent_roster import (
    assert_boss_actor,
    build_agent_critique,
    list_employees,
    resolve,
)
from .automation import DeliveryAutomation
from .agent_loop import AgentLoop, AgentLoopConfig
from .course_mainline import LESSONS, lesson_contract, validate_mainline
from .delivery_pipeline import pipeline_payload
from .delivery_view import DeliveryViewService
from .evolution import EvolutionStore
from .feedback import add_feedback, review_feedback, summary as feedback_summary
from .initiative import InitiativeStore
from .project_runner import ProjectEvalRunner, ProjectExecutionRunner
from .project_store import ProjectStore
from .plugin_runtime import PluginRuntimeError, PluginSupervisor
from .providers import HarnessProviders
from .runtime_store import HarnessRuntimeStore
from .task_store import TaskStore
from .tool_registry import ToolRegistry
from .session_context import derive_messages
from .session_export import export_session_bundle
from .session_graph import session_delivery_graph
from .tools import register_default_tools
from .mutation_receipts import MutationReceipts, MutationPending


@dataclass
class PlatformResponse:
    status: int
    body: object
    headers: dict[str, str] = field(default_factory=dict)


class HarnessPlatformAPI:
    """Standalone, project-neutral API for the personal delivery Harness."""

    def __init__(self, runtime_dir: str | Path = ".harness-runtime",
                 repository_root: str | Path | None = None, *, tasks=None, projects=None,
                 runtime_store=None, initiatives=None, delivery_runtime=None) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.repository_root = Path(repository_root or Path.cwd()).resolve()
        self.projects = projects or ProjectStore(self.runtime_dir / "platform.db")
        self.runtime = runtime_store or HarnessRuntimeStore(self.runtime_dir / "platform.db")
        self.tasks = tasks or TaskStore(self.runtime_dir / "tasks.db")
        self.initiatives = initiatives or InitiativeStore(self.runtime_dir / "platform.db")
        self.delivery_runtime = delivery_runtime
        self.mutations = MutationReceipts(self.tasks) if delivery_runtime else None
        self._initiative_promotion_lock = threading.Lock()
        self.evolutions = EvolutionStore(self.tasks.path)
        self.delivery_views = DeliveryViewService(self.tasks, self.evolutions)
        self.providers = HarnessProviders(self.runtime, self.projects, self.runtime_dir, self.repository_root)
        self.tools = ToolRegistry(self.runtime)
        register_default_tools(self.tools, self.tasks, self.providers)
        if self.delivery_runtime is not None:
            self.delivery_runtime.tool_executor = self._invoke_runtime_tool
        self.plugin_supervisor = PluginSupervisor(
            self.providers.plugin_contracts(self.tools),
            event_sink=self.runtime.record_plugin_event,
        )
        catalog = {item["id"]: item for item in self.runtime.plugins()}
        for profile in self.runtime.profiles():
            desired = [
                plugin_id for plugin_id in profile["plugin_ids"]
                if plugin_id in catalog and catalog[plugin_id]["enabled"]
            ]
            self.plugin_supervisor.ensure(profile["id"], desired)
        self.providers.attach_plugin_supervisor(self.plugin_supervisor)
        self.runtime.set_profile_change_handler(self.plugin_supervisor.reconcile)
        self.runtime.set_runtime_status_handler(self.plugin_supervisor.status)
        self.agent_loop = AgentLoop(self.tools, self.runtime, self.tasks, self.providers, AgentLoopConfig())
        self.automation = None
        if self.delivery_runtime is None:
            self.automation = DeliveryAutomation(
                self.tasks, self.runtime_dir,
                suite_runner=self.providers._eval_runner,
                execution_runner=ProjectExecutionRunner(self.projects, self.runtime_dir),
                agent_runner=self._run_agent_loop,
            )
        # Recovery belongs to the caller holding the service lease. Constructing
        # an API must never start an old code task.
        self._install_persist_hook()

    def shutdown(self) -> None:
        """Reverse all live plugin effects before the host process exits."""
        self.runtime.set_after_append(None)
        self.runtime.set_profile_change_handler(None)
        self.runtime.set_runtime_status_handler(None)
        self.plugin_supervisor.shutdown()

    def _install_persist_hook(self) -> None:
        def after_append(session_id: str, event: dict) -> None:
            session = self.runtime.get_session(session_id)
            profile_id = str(session.get("profile_id") or "PROFILE-DEFAULT")
            persist = self.providers.persist_jsonl(profile_id)
            if persist is not None:
                persist.append_event(session_id, event)

        self.runtime.set_after_append(after_append)
    def _run_agent_loop(self, task_id: str, actor: str) -> dict:
        if self.delivery_runtime:
            raise ValueError('共享工作台运行须经事项冻结方案授权；不能从旧 AgentLoop 另起执行')
        session = self.runtime.session_for_task(task_id)
        if not session:
            from .workflow import run_task
            suite_runner = ProjectEvalRunner(self.projects, self.runtime_dir)
            return run_task(
                self.tasks, task_id, actor=actor,
                suite_runner=suite_runner.for_task(self.tasks.get(task_id)),
                execution_runner=ProjectExecutionRunner(self.projects, self.runtime_dir),
            )
        return self.agent_loop.run(session["id"], task_id, actor)

    def _invoke_runtime_tool(self, initiative_id, payload, actor):
        from .delivery_runtime import CandidateProjectRegistry, RuntimeShellProvider
        task = self.tasks.get(payload['task_id'])
        binding = self.delivery_runtime.task_context(task['id'])
        if binding['initiative_id'] != initiative_id:
            raise ValueError('授权调用事项不一致')
        run = self.delivery_runtime.view(initiative_id)
        context = {'task': task, 'initiative_id': initiative_id, 'session_id': run['session_id'],
                   'profile_id': run['profile_id'], 'actor': actor,
                   'projects': CandidateProjectRegistry(self.projects, task, binding['workspace']),
                   'repository_root': binding['workspace'], 'fs': self.providers.fs_provider(run['profile_id']),
                   'shell': self.providers.shell_provider(run['profile_id']),
                   'mcp': self.providers.mcp_provider(run['profile_id']),
                   'allowed_actions': self._task_allowed_actions(task), 'auto_approve': False,
                   'approval_gate': self.delivery_runtime.authorize_tool}
        from .shell_provider import LocalShellProvider
        if isinstance(context['shell'], LocalShellProvider):
            context['shell'] = RuntimeShellProvider(self.delivery_runtime.events.setdefault(initiative_id, threading.Event()))
        if payload['tool_id'].startswith('mcp.'):
            context['allowed_actions'].append('call_mcp')
        return self.tools.invoke(payload['tool_id'], context, payload['args'],
                                 session_id=run['session_id'], actor=actor, call_id=payload['call_id'])

    def _idempotent(self, operation, key, payload, producer):
        if self.mutations:
            return self.mutations.run('harness:' + operation, key, payload, producer)
        return self.projects.idempotent(operation, key, payload, producer)

    def _configuration_sha256(self):
        from .delivery_runtime import _digest
        return _digest({'profiles': self.runtime.profiles(), 'plugins': self.runtime.plugins()})

    def _configure(self, data, producer):
        if not self.delivery_runtime:
            return producer()
        with self.delivery_runtime.lock:
            if data.get('expected_configuration_sha256') != self._configuration_sha256():
                raise ValueError('Harness配置版本已变化或未核对，请重新读取configuration_sha256')
            if self.delivery_runtime.busy():
                raise ValueError('仍有活动运行或工具调用，请结束后再调整Profile或插件')
            return producer()

    def _session_status(self, session_id, data, actor):
        if not self.delivery_runtime:
            return self.runtime.set_status(session_id, str(data.get('status', '')), actor)
        session = self.runtime.get_session(session_id)
        binding = self.delivery_runtime.task_context(session.get('task_id'))
        run = self.delivery_runtime.view(binding['initiative_id'])
        if run['session_id'] != session_id:
            raise ValueError('旧Session不能控制当前事项运行，请读取当前Session与运行版本')
        action = {'paused': 'pause', 'closed': 'cancel', 'active': 'resume'}.get(data.get('status'))
        if not action:
            raise ValueError('Session状态必须是active、paused或closed')
        view = self.delivery_runtime.control(binding['initiative_id'], action, actor,
                    data.get('expected_revision'), data.get('candidate_sha256', ''),
                    run_id=data.get('run_id'), session_id=data.get('session_id'),
                    control_revision=data.get('control_revision'))
        return {**self.runtime.get_session(session_id), 'runtime': view}

    def _shared_tool(self, session_id, task_id, tool_id, context, data, actor, call_id):
        if not self.delivery_runtime:
            return self.tools.invoke(tool_id, context, dict(data.get('args') or {}),
                                     session_id=session_id, actor=actor, call_id=call_id)
        with self.delivery_runtime.lock:
            binding = self.delivery_runtime.task_context(task_id)
            run = self.delivery_runtime._load(binding['initiative_id'])
            if run['revision'] != data.get('expected_revision'):
                raise ValueError('工具请求缺少当前运行版本，或运行已变化，请刷新后重试')
            if run['session_id'] != session_id or context['profile_id'] != run['profile_id']:
                raise ValueError('工具请求的Session、任务或Profile与当前运行不一致')
            from .delivery_runtime import _profile_fingerprint
            if _profile_fingerprint(self.runtime.composition(run['profile_id'])) != run.get('profile_sha256'):
                raise ValueError('冻结Profile已变化，请重新确认运行后再调用工具')
            if data.get('initiative_id') and data['initiative_id'] != binding['initiative_id']:
                raise ValueError('工具调用与事项绑定不一致')
            if tool_id in {'codex.exec', 'eval.blocking'}:
                raise ValueError('编码与项目Eval由同一事项运行推进；请使用事项执行或复验入口')
            context.update(initiative_id=binding['initiative_id'], approval_gate=self.delivery_runtime.authorize_tool,
                           repository_root=binding['workspace'])
            if binding.get('workspace'):
                from .delivery_runtime import CandidateProjectRegistry
                context['projects'] = CandidateProjectRegistry(self.projects, context['task'], binding['workspace'])
            if tool_id.startswith('mcp.'):
                context['allowed_actions'].append('call_mcp')
            return self.tools.invoke(tool_id, context, dict(data.get('args') or {}),
                                     session_id=session_id, actor=actor, call_id=call_id)

    def dispatch(self, method: str, raw_path: str, headers: dict[str, str], body: object) -> PlatformResponse:
        headers = {k.lower(): v for k, v in headers.items()}
        path, _, query_string = raw_path.partition("?")
        path = path.rstrip("/") or "/"
        query = {key: values[-1] for key, values in parse_qs(query_string).items()}
        data = body if isinstance(body, dict) else {}
        try:
            if method == 'POST' and self.delivery_runtime:
                if data.get('actor') and headers.get('x-workbench-actor') and data['actor'] != headers['x-workbench-actor']:
                    raise ValueError('请求署名与X-Workbench-Actor不一致')
                headers.setdefault('x-workbench-actor', str(data.get('actor') or ''))
                headers.setdefault('idempotency-key', str(data.get('submission_key') or ''))
                actor, _ = self._write_identity(headers)
                data = {**data, 'actor': assert_boss_actor(actor)}
            if path == "/api/v1/health" and method == "GET":
                return PlatformResponse(200, {
                    "status": "ok", "product": "Harness Workbench",
                    "runtime_dir": str(self.runtime_dir),
                    "repository_root": str(self.repository_root),
                    "project_count": len(self.projects.list()),
                })
            if path == "/api/v1/flowerp/status" and method == "GET":
                from .managed_flowerp import is_flowerp_live
                host = str(query.get("host") or "127.0.0.1")
                port = int(query.get("port") or "8000")
                live = is_flowerp_live(host, port, timeout=0.4)
                url = f"http://{host}:{port}"
                return PlatformResponse(200, {
                    "live": live,
                    "url": url,
                    "service": "flowerp" if live else None,
                    "pages": [
                        {"id": "dashboard", "label": "经营驾驶舱", "href": f"{url}/#dashboard"},
                        {"id": "sales", "label": "销售订单", "href": f"{url}/#sales"},
                        {"id": "inventory", "label": "库存管理", "href": f"{url}/#inventory"},
                        {"id": "purchases", "label": "采购管理", "href": f"{url}/#purchases"},
                        {"id": "finance", "label": "财务中心", "href": f"{url}/#finance"},
                    ],
                })
            if path == "/api/v1/capabilities" and method == "GET":
                return PlatformResponse(200, {
                    **self.providers.capabilities(),
                    "composition": self.runtime.composition(),
                    "tools": self.tools.list_tools(),
                    "opc": {
                        "mode": "super_individual",
                        "employees": list_employees(),
                        "multi_user_accounts": False,
                    },
                })
            if path == "/api/v1/employees" and method == "GET":
                return PlatformResponse(200, {
                    "items": list_employees(),
                    "mode": "opc",
                    "boss_role": "human_operator",
                    "note": "员工是 Agent，不是多用户账号；老板用 X-Workbench-Actor 具名终审。",
                })
            if path == "/api/v1/tools" and method == "GET":
                return PlatformResponse(200, {"items": self.tools.list_tools()})
            if path.startswith("/api/v1/tools/") and method == "GET":
                tool_id = path.rsplit("/", 1)[-1]
                spec = self.tools.get(tool_id)
                return PlatformResponse(200, {
                    "id": spec.id,
                    "name": spec.name,
                    "description": spec.description,
                    "permissions": sorted(spec.permissions),
                })
            if path == "/api/v1/plugins" and method == "GET":
                return PlatformResponse(200, {"items": self.runtime.plugins(), 'configuration_sha256': self._configuration_sha256()})
            if path == "/api/v1/plugin-events" and method == "GET":
                return PlatformResponse(200, {"items": self.runtime.plugin_events(
                    query.get("profile_id"), int(query.get("limit", "100")),
                )})
            if path == "/api/v1/profiles" and method == "GET":
                return PlatformResponse(200, {"items": self.runtime.profiles(), 'configuration_sha256': self._configuration_sha256()})
            if path.startswith("/api/v1/profiles/") and path.endswith("/runtime") and method == "GET":
                return PlatformResponse(200, self.plugin_supervisor.status(path.split("/")[4]))
            if path.startswith("/api/v1/profiles/") and path.endswith("/composition") and method == "GET":
                return PlatformResponse(200, self.runtime.composition(path.split("/")[4]))
            if path.startswith("/api/v1/profiles/") and path.endswith("/activate") and method == "POST":
                parts = path.split("/")
                profile_id = parts[4]
                actor, key = self._write_identity(headers)
                plugin_id = str(data.get("plugin_id", ""))
                payload = {**data, "profile_id": profile_id, "plugin_id": plugin_id, "actor": actor}
                result = self._idempotent(
                    "profile-activate", key, payload,
                    lambda: self._configure(data, lambda: self.runtime.activate_plugin(profile_id, plugin_id)),
                )
                return PlatformResponse(200, result)
            if path.startswith("/api/v1/plugins/") and path.endswith("/enabled") and method == "POST":
                plugin_id = path.split("/")[4]
                actor, key = self._write_identity(headers)
                if self.delivery_runtime and type(data.get('enabled')) is not bool:
                    raise ValueError('enabled必须是JSON布尔值')
                enabled = bool(data.get("enabled", True))
                payload = {**data, "plugin_id": plugin_id, "actor": actor}
                result = self._idempotent(
                    "plugin-enabled", key, payload,
                    lambda: self._configure(data, lambda: self.runtime.set_plugin_enabled(plugin_id, enabled)),
                )
                return PlatformResponse(200, result)
            if path == "/api/v1/sessions":
                if method == "GET": return PlatformResponse(200, {"items": self.runtime.sessions(int(query.get("limit", "100")))})
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    self.projects.get(str(data.get("project_id", "")))
                    result = self._idempotent("session-create", key, data, lambda: self.runtime.create_session(
                        str(data.get("project_id", "")), str(data.get("title", "")), actor,
                        str(data.get("profile_id", "PROFILE-DEFAULT")),
                    ))
                    return PlatformResponse(HTTPStatus.CREATED, result)
            if path == "/api/v1/dump-config" and method == "GET":
                profile_id = query.get("profile_id", "PROFILE-DEFAULT")
                return PlatformResponse(200, self.runtime.dump_config(profile_id))
            if path.startswith("/api/v1/sessions/") and method == "GET":
                parts = path.split("/")
                session_id = parts[4] if len(parts) > 4 else ""
                if len(parts) == 6 and parts[5] == "messages":
                    session = self.runtime.get_session(session_id)
                    return PlatformResponse(200, {
                        "session_id": session_id,
                        "messages": derive_messages(session),
                    })
                if len(parts) == 6 and parts[5] == "export":
                    session = self.runtime.get_session(session_id)
                    task = self.tasks.get(session["task_id"]) if session.get("task_id") else None
                    return PlatformResponse(200, export_session_bundle(
                        self.runtime, session_id, task=task,
                        delivery_view=self.delivery_views.get(task["id"]) if task else None,
                        repository_root=self.repository_root,
                    ))
                if len(parts) == 6 and parts[5] == "graph":
                    session = self.runtime.get_session(session_id)
                    task = self.tasks.get(session["task_id"]) if session.get("task_id") else None
                    return PlatformResponse(200, session_delivery_graph(session, task))
                if len(parts) == 6 and parts[5] == "agent":
                    return PlatformResponse(200, self.agent_loop.status(session_id))
                session = self.runtime.get_session(session_id)
                if session.get("task_id"):
                    session = self.runtime.sync_task(session["id"], self.tasks.get(session["task_id"]))
                return PlatformResponse(200, session)
            if path.startswith("/api/v1/sessions/") and method == "POST":
                parts = path.split("/")
                session_id = parts[4] if len(parts) > 4 else ""
                actor, key = self._write_identity(headers)
                payload = {**data, "session_id": session_id, "actor": actor}
                if len(parts) == 6 and parts[5] == "fork":
                    result = self._idempotent(
                        "session-fork", key, payload,
                        lambda: self.runtime.fork(session_id, str(data.get("title", "")), actor),
                    )
                    return PlatformResponse(HTTPStatus.CREATED, result)
                if len(parts) == 6 and parts[5] == "status":
                    result = self._idempotent(
                        "session-status", key, payload,
                        lambda: self._session_status(session_id, data, actor),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 6 and parts[5] == "prompt":
                    result = self._idempotent(
                        "session-prompt", key, payload,
                        lambda: self._session_prompt(session_id, actor, data),
                    )
                    return PlatformResponse(HTTPStatus.ACCEPTED, result)
                if len(parts) == 7 and parts[5] == "employees" and parts[6] == "assign":
                    result = self._idempotent(
                        "employees-assign", key, payload,
                        lambda: self._assign_employees(session_id, actor, data),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 7 and parts[5] == "agent" and parts[6] == "start":
                    if self.delivery_runtime:
                        raise ValueError('请从事项的运行与分工面板授权执行，不另起 AgentLoop')
                    task_id = str(data.get("task_id") or self.runtime.get_session(session_id).get("task_id") or "")
                    if not task_id:
                        raise ValueError("agent/start 需要 task_id 或 Session 已绑定 Task")
                    result = self._idempotent(
                        "agent-start", key, payload,
                        lambda: self.agent_loop.run(session_id, task_id, actor),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 7 and parts[5] == "agent" and parts[6] == "step":
                    if self.delivery_runtime:
                        raise ValueError('请从事项运行控制恢复或继续，不另起 AgentLoop')
                    task_id = str(data.get("task_id") or self.runtime.get_session(session_id).get("task_id") or "")
                    if not task_id:
                        raise ValueError("agent/step 需要 task_id 或 Session 已绑定 Task")
                    round_no = int(data.get("round", 0)) or (
                        self.agent_loop.status(session_id)["turns_completed"] + 1
                    )
                    result = self._idempotent(
                        "agent-step", key, {**payload, "round": round_no},
                        lambda: self.agent_loop.run_round(session_id, task_id, actor, round_no=round_no),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 7 and parts[5] == "tools" and method == "POST":
                    tool_id = parts[6]
                    task_id = str(data.get("task_id") or self.runtime.get_session(session_id).get("task_id") or "")
                    if not task_id:
                        raise ValueError("tool invoke 需要 task_id 或 Session 已绑定 Task")
                    task = self.tasks.get(task_id)
                    call_id = str(data.get("call_id") or key)
                    session = self.runtime.get_session(session_id)
                    profile_id = str(session.get("profile_id") or "PROFILE-DEFAULT")
                    context = {
                        "task": task,
                        "session_id": session_id,
                        "actor": actor,
                        "profile_id": profile_id,
                        "projects": self.projects,
                        "repository_root": self.repository_root,
                        "fs": self.providers.fs_provider(profile_id),
                        "shell": self.providers.shell_provider(profile_id),
                        "mcp": self.providers.mcp_provider(profile_id),
                        "allowed_actions": self._task_allowed_actions(task),
                        "auto_approve": False,
                        "approved_tools": [],
                    }
                    result = self._idempotent(
                        f"tool-{tool_id}", key, payload,
                        lambda: self._shared_tool(session_id, task_id, tool_id, context, data, actor, call_id),
                    )
                    return PlatformResponse(200, result)
            if path == "/api/v1/projects":
                if method == "GET": return PlatformResponse(200, {"items": self.projects.list()})
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    result = self._idempotent("project-create", key, data, lambda: self.projects.create(
                        str(data.get("name", "")), str(data.get("root_path", "")),
                        list(data.get("eval_command") or []), str(data.get("id", "")),
                    ))
                    result["registered_by"] = actor
                    return PlatformResponse(HTTPStatus.CREATED, result)
            if path.startswith("/api/v1/projects/") and method == "GET":
                return PlatformResponse(200, self.projects.get(path.rsplit("/", 1)[-1]))
            if path == "/api/v1/delivery/views" and method == "GET":
                return PlatformResponse(200, self.delivery_views.list(int(query.get("limit", "100"))))
            if path.startswith("/api/v1/delivery/views/") and method == "GET":
                return PlatformResponse(200, self.delivery_views.get(path.rsplit("/", 1)[-1]))
            if path == "/api/v1/initiatives":
                if method == "GET":
                    return PlatformResponse(200, {
                        "items": self.initiatives.list(int(query.get("limit", "100"))),
                        "decision_options": ["build", "experiment", "defer", "reject", "stop"],
                    })
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "actor": actor}
                    result = self._idempotent(
                        "initiative-create", key, payload,
                        lambda: self.initiatives.create(data, actor),
                    )
                    return PlatformResponse(HTTPStatus.CREATED, result)
            if path.startswith("/api/v1/initiatives/"):
                parts = path.split("/")
                initiative_id = parts[4] if len(parts) > 4 else ""
                if len(parts) == 5 and method == "GET":
                    return PlatformResponse(200, self.initiatives.get(initiative_id))
                if len(parts) == 6 and parts[5] == "revise" and method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "initiative_id": initiative_id, "actor": actor}
                    result = self._idempotent(
                        "initiative-revise", key, payload,
                        lambda: self.initiatives.revise(
                            initiative_id, data, actor, int(data.get("expected_version", 0)),
                        ),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 6 and parts[5] == "decision" and method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "initiative_id": initiative_id, "actor": actor}
                    result = self._idempotent(
                        "initiative-decision", key, payload,
                        lambda: self.initiatives.decide(
                            initiative_id, str(data.get("decision", "")), actor,
                            str(data.get("rationale", "")), int(data.get("expected_version", 0)),
                            review_trigger=str(data.get("review_trigger", "")),
                            reviewer=str(data.get("reviewer", "")),
                            success_metric=str(data.get("success_metric", "")),
                            stop_condition=str(data.get("stop_condition", "")),
                        ),
                    )
                    return PlatformResponse(200, result)
                if len(parts) == 6 and parts[5] == "delivery" and method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "initiative_id": initiative_id, "actor": actor}
                    result = self._idempotent(
                        "initiative-delivery", key, payload,
                        lambda: self._promote_initiative(initiative_id, data, actor),
                    )
                    return PlatformResponse(HTTPStatus.ACCEPTED, result)
            if path == "/api/v1/tasks":
                if method == "GET":
                    return PlatformResponse(200, {"items": self.tasks.list(int(query.get("limit", "100")))})
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    result = self._idempotent(
                        "task-submit", key, data, lambda: self._submit_project_task(data, actor),
                    )
                    return PlatformResponse(HTTPStatus.ACCEPTED, result)
            if path.startswith("/api/v1/tasks/"):
                parts = path.split("/")
                task_id = parts[4] if len(parts) > 4 else ""
                if len(parts) == 5 and method == "GET":
                    return PlatformResponse(200, self.tasks.get(task_id))
                if len(parts) == 6 and parts[5] == "review" and method == "POST":
                    if self.delivery_runtime:
                        raise ValueError('本次交付必须由事项指定验收人通过事项验收入口接受')
                    actor, key = self._write_identity(headers)
                    boss = assert_boss_actor(actor)
                    payload = {**data, "task_id": task_id, "actor": boss}
                    result = self._idempotent("task-review", key, payload, lambda: self.tasks.review(
                        task_id, boss, str(data.get("decision", "")), str(data.get("note", "")),
                    ))
                    return PlatformResponse(200, result)
                if len(parts) == 6 and parts[5] == "agent-critique" and method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "task_id": task_id, "actor": actor}
                    result = self._idempotent(
                        "task-agent-critique", key, payload,
                        lambda: self._record_agent_critique(task_id, actor, data),
                    )
                    return PlatformResponse(200, result)
            if path == "/api/v1/feedback":
                if method == "GET": return PlatformResponse(200, feedback_summary(self.tasks.path))
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    result = self._idempotent("feedback-create", key, data, lambda: add_feedback(
                        str(data.get("task_id", "")), str(data.get("source", "")),
                        str(data.get("conclusion", "")), str(data.get("next_step", "")), self.tasks.path,
                    ))
                    result["recorded_by"] = actor
                    return PlatformResponse(HTTPStatus.CREATED, result)
            if path.startswith("/api/v1/feedback/"):
                parts = path.split("/"); feedback_id = parts[4] if len(parts) > 4 else ""
                if len(parts) == 6 and parts[5] == "review" and method == "POST":
                    actor, key = self._write_identity(headers)
                    payload = {**data, "feedback_id": feedback_id, "actor": actor}
                    result = self._idempotent("feedback-review", key, payload, lambda: review_feedback(
                        feedback_id, actor, str(data.get("decision", "")),
                        str(data.get("note", "")), self.tasks.path,
                    ))
                    return PlatformResponse(200, result)
            if path == "/api/v1/evolutions":
                if method == "GET": return PlatformResponse(200, self.evolutions.summary(int(query.get("limit", "100"))))
                if method == "POST":
                    actor, key = self._write_identity(headers)
                    result = self._idempotent("evolution-create", key, data, lambda: self.evolutions.create(
                        str(data.get("feedback_id", "")), str(data.get("failure_signature", "")),
                        str(data.get("classification", "")), list(data.get("business_refs") or []) or None, actor,
                    ))
                    return PlatformResponse(HTTPStatus.CREATED, result)
            if path.startswith("/api/v1/evolutions/"):
                parts = path.split("/"); evolution_id = parts[4] if len(parts) > 4 else ""
                if len(parts) == 5 and method == "GET": return PlatformResponse(200, self.evolutions.get(evolution_id))
                if len(parts) == 6 and method == "POST":
                    actor, key = self._write_identity(headers)
                    operation = parts[5]; payload = {**data, "evolution_id": evolution_id, "actor": actor}
                    if operation == "review": producer = lambda: self.evolutions.review(evolution_id, actor, str(data.get("decision", "")), str(data.get("note", "")))
                    elif operation == "assets": producer = lambda: self.evolutions.record_assets(evolution_id, list(data.get("asset_changes") or []), actor)
                    elif operation == "verify": producer = lambda: self.evolutions.verify(evolution_id, str(data.get("candidate_task_id", "")), str(data.get("blocking_report", "")), actor)
                    else: return PlatformResponse(404, {"error": "not_found"})
                    return PlatformResponse(200, self._idempotent(f"evolution-{operation}", key, payload, producer))
            if path == "/api/v1/course/status" and method == "GET":
                return PlatformResponse(200, validate_mainline(self.repository_root))
            if path == "/api/v1/course/lessons" and method == "GET":
                return PlatformResponse(200, {"items": [item.as_dict() for item in LESSONS]})
            if path.startswith("/api/v1/course/lessons/") and method == "GET":
                return PlatformResponse(200, lesson_contract(int(path.rsplit("/", 1)[-1])).as_dict())
            return PlatformResponse(404, {"error": "not_found", "message": "Harness API 路径不存在"})
        except PermissionError as exc:
            return PlatformResponse(HTTPStatus.FORBIDDEN, {'error': 'permission_denied', 'message': str(exc)})
        except KeyError as exc:
            return PlatformResponse(404, {"error": "not_found", "message": str(exc)})
        except MutationPending as exc:
            return PlatformResponse(409, {'error': 'mutation_pending', 'message': str(exc)})
        except PluginRuntimeError as exc:
            return PlatformResponse(409, {"error": "plugin_runtime_conflict", "message": str(exc)})
        except (TypeError, ValueError) as exc:
            return PlatformResponse(422, {"error": "invalid_request", "message": str(exc)})

    _BUSY_TASK_STATUSES = frozenset({
        "queued", "spec_ready", "executing", "evaluating", "rework",
    })

    def _submit_project_task(self, data: dict, actor: str) -> dict:
        if self.delivery_runtime:
            raise ValueError('共享运行视图的需求须从工作台首页事项开始；请确认方案后授权执行')
        project_id = str(data.get("project_id", ""))
        self.projects.get(project_id)
        refs = [f"PROJECT:{project_id}", *list(data.get("business_refs") or [])]
        task = self.automation.submit(
            str(data.get("request", "")), str(data.get("requirement_id", "")), refs, actor,
            "codex" if data.get("execute_code") else "verify",
            list(data.get("write_scope") or []), int(data.get("execution_timeout_seconds", 900)),
            auto_start=False,
        )
        session = self.runtime.create_session(
            project_id, str(data.get("request", ""))[:120], actor,
            str(data.get("profile_id", "PROFILE-DEFAULT")), task["id"],
        )
        self.runtime.append(session["id"], "user/message", actor, {"request": data.get("request")})
        self.runtime.append(
            session["id"], "task/created", "harness", {"task_id": task["id"], "status": task["status"]},
        )
        self.runtime.append(
            session["id"], "pipeline/stage", "harness",
            {**pipeline_payload(str(task.get("status") or "queued")), "task_id": task["id"]},
            source_key=f"pipeline-stage:created:{task['id']}",
        )
        self.automation.start(task["id"], actor="automation")
        return {**task, "session_id": session["id"]}

    def _promote_initiative(self, initiative_id: str, data: dict, actor: str) -> dict:
        # The Web host is threaded. Serialize promotion so two different idempotency
        # keys cannot create two Tasks for one approved initiative.
        with self._initiative_promotion_lock:
            initiative = self.initiatives.get(initiative_id)
            if initiative.get("linked_task_id"):
                task = self.tasks.get(str(initiative["linked_task_id"]))
                session = self.runtime.session_for_task(task["id"])
                return {"initiative": initiative, "task": task, "session_id": (session or {}).get("id")}
            expected_version = int(data.get("expected_version", 0))
            if initiative.get("decision") != "build" or initiative.get("status") != "approved_for_delivery":
                raise ValueError("只有已批准的 Build 事项可以进入交付")
            if int(initiative["version"]) != expected_version:
                raise ValueError(f"事项版本已变化：期望 {expected_version}，实际 {initiative['version']}")
            project_id = str(initiative.get("project_id") or "")
            self.projects.get(project_id)
            task = self._submit_project_task({
                "project_id": project_id,
                "request": self.initiatives.delivery_request(initiative),
                "requirement_id": initiative.get("requirement_id") or "",
                "business_refs": [f"INITIATIVE:{initiative_id}"],
                "execute_code": bool(data.get("execute_code", False)),
                "write_scope": list(data.get("write_scope") or []),
                "execution_timeout_seconds": int(data.get("execution_timeout_seconds", 900)),
                "profile_id": str(data.get("profile_id", "PROFILE-DEFAULT")),
            }, actor)
            linked = self.initiatives.link_delivery(initiative_id, task["id"], actor, expected_version)
            return {"initiative": linked, "task": task, "session_id": task.get("session_id")}

    def _assign_employees(self, session_id: str, actor: str, data: dict) -> dict:
        assert_boss_actor(actor)
        session = self.runtime.get_session(session_id)
        mapping = data.get("duty_by_stage") or data.get("overrides") or {}
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("需要 duty_by_stage 映射")
        cleaned = {}
        for stage, agent_id in mapping.items():
            employee = resolve(str(agent_id))
            cleaned[str(stage)] = employee.id
        coder = cleaned.get("code") or cleaned.get("eval") or "agent:coder"
        reviewer = cleaned.get("human") or "agent:reviewer"
        from .agent_roster import assert_coder_reviewer_sod
        assert_coder_reviewer_sod(coder, reviewer)
        event = self.runtime.append(
            session_id,
            "employees/assign",
            actor,
            {
                "duty_by_stage": cleaned,
                "employees": list_employees(),
                "note": "本会话值班覆盖（仍禁止 coder=reviewer）",
            },
        )
        return {
            "session_id": session_id,
            "duty_by_stage": cleaned,
            "event": event,
            "effective": {**{"request": "agent:spec", "spec": "agent:spec", "code": "agent:coder",
                             "eval": "agent:coder", "human": "agent:reviewer"}, **cleaned},
        }

    def _record_agent_critique(self, task_id: str, actor: str, data: dict) -> dict:
        task = self.tasks.get(task_id)
        reviewer_id = str(data.get("reviewer_id") or "agent:reviewer")
        # Allow boss to trigger critique, or the reviewer agent id itself.
        if actor != reviewer_id and not str(actor).startswith("agent:"):
            # human boss triggering is fine
            pass
        elif str(actor).startswith("agent:") and actor != reviewer_id:
            raise ValueError("只有测试本人或老板可记录测试意见")
        critique = build_agent_critique(task, reviewer_id=reviewer_id)
        if data.get("note"):
            critique["note"] = str(data.get("note")).strip() or critique["note"]
        if data.get("suggested_decision") in {"approve", "reject"}:
            critique["suggested_decision"] = str(data.get("suggested_decision"))
        session = self.runtime.session_for_task(task_id)
        event = None
        if session:
            event = self.runtime.append(
                session["id"],
                "agent/critique",
                reviewer_id,
                {**critique, "task_id": task_id, "visible_to_model": True, "triggered_by": actor},
                source_key=f"agent-critique:{task_id}:{actor}",
            )
        return {"task_id": task_id, "critique": critique, "event": event, "session_id": (session or {}).get("id")}

    def _session_prompt(self, session_id: str, actor: str, data: dict) -> dict:
        if self.delivery_runtime:
            raise ValueError('请在工作台事项讨论中提出后续需求，再确认并授权新一轮交付')
        """Append a user message and start (or continue) delivery inside one Session."""
        session = self.runtime.get_session(session_id)
        if session.get("status") == "closed":
            raise ValueError("已关闭 Session 不可发送；请 fork 新会话")
        if session.get("status") == "paused":
            raise ValueError("已暂停 Session 不可发送；请先恢复为 active")
        request = str(data.get("request", "")).strip()
        if not request:
            raise ValueError("prompt 需要非空 request")
        project_id = str(session.get("project_id") or "")
        self.projects.get(project_id)
        if session.get("task_id"):
            existing = self.tasks.get(session["task_id"])
            if existing.get("status") in self._BUSY_TASK_STATUSES:
                raise ValueError(f"Session 当前任务仍在进行：{existing['status']}")
        refs = [f"PROJECT:{project_id}", *list(data.get("business_refs") or [])]
        task = self.automation.submit(
            request,
            str(data.get("requirement_id", "")),
            refs,
            actor,
            "codex" if data.get("execute_code") else "verify",
            list(data.get("write_scope") or []),
            int(data.get("execution_timeout_seconds", 900)),
            auto_start=False,
        )
        title = request[:120]
        if not session.get("task_id") or session.get("title") in {"", "新会话", "Untitled Session", "New Session"}:
            self.runtime.bind_task(session_id, task["id"], actor, title=title)
        else:
            self.runtime.bind_task(session_id, task["id"], actor)
        self.runtime.append(session_id, "user/message", actor, {"request": request})
        self.runtime.append(
            session_id,
            "task/created",
            "harness",
            {"task_id": task["id"], "status": task["status"]},
        )
        self.runtime.append(
            session_id,
            "pipeline/stage",
            "harness",
            {**pipeline_payload(str(task.get("status") or "queued")), "task_id": task["id"]},
            source_key=f"pipeline-stage:created:{task['id']}",
        )
        self.automation.start(task["id"], actor="automation")
        return {**task, "session_id": session_id}

    @staticmethod
    def _task_allowed_actions(task: dict) -> list[str]:
        allowed = ["read_spec", "read_workspace", "run_blocking_eval", "run_workspace_shell"]
        if task.get("execution_mode") == "codex":
            allowed.append("write_code_in_task_scope")
        return allowed

    @staticmethod
    def _write_identity(headers: dict[str, str]) -> tuple[str, str]:
        actor = headers.get("x-workbench-actor", "").strip()
        key = headers.get("idempotency-key", "").strip()
        if not actor:
            raise ValueError("写操作必须提供 X-Workbench-Actor 具名操作者")
        if not key:
            raise ValueError("写操作必须提供 Idempotency-Key")
        return actor, key
