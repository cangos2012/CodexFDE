"""Rebuild editable diagrams for the workbench design reading guide."""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
FONT = "Microsoft YaHei"
COLORS = {"service": ("#dae8fc", "#6c8ebf"), "data": ("#d5e8d4", "#82b366"),
          "human": ("#fff2cc", "#d6b656"), "external": ("#f5f5f5", "#666666")}


class Diagram:
    def __init__(self, name, width, height):
        self.file = ET.Element("mxfile", {"host": "drawio", "version": "31.4.4"})
        page = ET.SubElement(self.file, "diagram", {"id": name, "name": name})
        model = ET.SubElement(page, "mxGraphModel", {"dx": "1600", "dy": "1000", "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1", "pageWidth": str(width), "pageHeight": str(height), "math": "0", "shadow": "0", "background": "#ffffff"})
        self.root = ET.SubElement(model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})

    def box(self, id, text, x, y, w, h, role="service", parent="1", extra=""):
        fill, stroke = COLORS[role]
        style = f"rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.5;fontFamily={FONT};fontSize=19;fontColor=#172b4d;spacing=14;{extra}"
        cell = ET.SubElement(self.root, "mxCell", {"id": id, "value": text, "style": style, "vertex": "1", "parent": parent})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})

    def text(self, id, text, x, y, w, h, size=20, bold=False, parent="1", align="left"):
        style = f"text;whiteSpace=wrap;html=1;strokeColor=none;fillColor=none;fontFamily={FONT};fontSize={size};fontColor=#243746;align={align};verticalAlign=middle;spacing=0;fontStyle={1 if bold else 0};"
        cell = ET.SubElement(self.root, "mxCell", {"id": id, "value": text, "style": style, "vertex": "1", "parent": parent})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})

    def group(self, id, text, x, y, w, h, parent="1"):
        cell = ET.SubElement(self.root, "mxCell", {"id": id, "value": text, "style": f"swimlane;startSize=45;horizontal=1;rounded=1;arcSize=4;html=1;container=1;pointerEvents=0;fillColor=#f6f9fd;swimlaneFillColor=#ffffff;strokeColor=#9aafc6;strokeWidth=1.5;fontFamily={FONT};fontColor=#243746;fontSize=20;fontStyle=1;spacingLeft=16;", "vertex": "1", "parent": parent})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})

    def edge(self, id, source, target, text="", ports=(1,.5,0,.5), points=(), dashed=False, x=0, y=0):
        ex, ey, ix, iy = ports
        style = f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeWidth=1.8;strokeColor=#526d82;fontFamily={FONT};fontSize=17;fontColor=#243746;labelBackgroundColor=#ffffff;exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={ix};entryY={iy};entryDx=0;entryDy=0;" + ("dashed=1;dashPattern=6 4;" if dashed else "")
        cell = ET.SubElement(self.root, "mxCell", {"id": id, "value": text, "style": style, "edge": "1", "parent": "1", "source": source, "target": target})
        geom = ET.SubElement(cell, "mxGeometry", {"relative": "1", "x": str(x), "y": str(y), "as": "geometry"})
        if points:
            arr = ET.SubElement(geom, "Array", {"as": "points"})
            for px, py in points:
                ET.SubElement(arr, "mxPoint", {"x": str(px), "y": str(py)})

    def legend(self, x, y, external=True):
        roles = [("human", "具名人的决定"), ("service", "工作台职责"), ("data", "持久化与证据")]
        if external:
            roles.append(("external", "独立项目 / 进程"))
        for index, (role, label) in enumerate(roles):
            self.box("legend-" + role, label, x + index*420, y, 360, 50, role, extra="fontSize=17;spacing=6;")

    def save(self, basename):
        ET.indent(self.file, space="  ")
        ET.ElementTree(self.file).write(OUT / (basename + ".drawio"), encoding="utf-8", xml_declaration=True)


def architecture():
    d = Diagram("模块职责与数据归属", 1860, 1440)
    d.text("title", "个人研发工作台：模块职责与数据归属示意", 40, 20, 1740, 55, 30, True)
    d.text("subtitle", "用工作台组织人与 Codex 协同交付；FlowERP 是独立客户项目与验证场。", 40, 85, 1740, 40, 21)
    d.box("human", "人<br>提出需求 · 授权 · 具名审核", 40, 150, 330, 100, "human")
    d.group("workbench", "本仓库：个人研发工作台（默认 :8001，入口 /）", 40, 320, 1080, 800)
    d.box("web", "<b>首页与操作界面</b><br>workbench_web/ · 事项与决策", 50, 70, 960, 100, parent="workbench")
    d.box("server", "<b>HTTP 路由与应用装配</b><br>workbench/workbench_server.py", 50, 220, 960, 100, parent="workbench")
    d.box("learning", "<b>经验与流程</b><br>learning.py / evolution.py<br>来源 · 版本 · 采用 · 失效", 50, 440, 280, 120, parent="workbench")
    d.box("initiative", "<b>事项与决策</b><br>initiative*.py<br>目标 · 调研 · 方案确认", 390, 440, 280, 120, parent="workbench")
    d.box("control", "<b>受控交付</b><br>daily_delivery / workflow<br>execution<br>Spec · 写集 · Eval · 人审", 730, 440, 280, 140, parent="workbench", extra="fontSize=18;")
    d.box("db", "<b>workbench.db</b><br>事项、任务、决定、经验版本<br>记录及绑定；归工作台所有", 50, 650, 450, 110, "data", parent="workbench")
    d.box("evidence", "<b>运行证据文件</b><br>Spec 快照 · Diff · 哈希<br>进程记录 · Eval 报告", 610, 650, 400, 110, "data", parent="workbench")
    d.group("processes", "工作台调用的独立执行进程", 1220, 320, 590, 610)
    d.box("codex", "<b>Codex CLI</b><br>在候选中按确认的写集修改<br>留下实际 Diff、清单与执行结果", 40, 90, 510, 120, "external", parent="processes")
    d.box("candidate-code", "<b>同一隔离候选源码</b><br>写集 · 候选清单 · 哈希 · Diff", 40, 270, 510, 100, "data", parent="processes")
    d.box("eval", "<b>登记项目的阻断 Eval</b><br>按登记入口，在上述候选启动进程<br>检查退出码与报告结论一致", 40, 420, 510, 120, "external", parent="processes")
    d.box("flowerp", "<b>独立 FlowERP 原项目</b><br>源码：flowerp/ 与 web/<br>客户服务 :8000 · 业务库 flowerp.db<br>业务状态与审批由客户项目负责", 1260, 1000, 510, 170, "external")
    d.edge("human-web", "human", "web", "提交事项 / 作出决定", (.5,1,.18,0), [(205,290),(260,290)])
    d.edge("web-server", "web", "server", "HTTP API", (.5,1,.5,0))
    for target, port in (("learning", .15), ("initiative", .5), ("control", .85)):
        d.edge("route-"+target, "server", target, "", (port,1,.5,0))
    d.edge("learning-db", "learning", "db", "", (.5,1,.25,0))
    d.edge("initiative-db", "initiative", "db", "状态与决定", (.5,1,.8,0), [(570,930),(450,930)])
    d.edge("control-evidence", "control", "evidence", "绑定候选与报告", (.5,1,.65,0))
    d.edge("control-codex", "control", "codex", "确认方案与写集", (1,.22,0,.75), [(1170,790),(1170,515)])
    d.edge("control-eval", "control", "eval", "发起检查", (1,.75,0,.4), [(1190,865),(1190,788)])
    d.edge("codex-candidate", "codex", "candidate-code", "修改候选", (.5,1,.5,0))
    d.edge("candidate-eval", "candidate-code", "eval", "验证候选", (.5,1,.5,0))
    d.edge("eval-evidence", "eval", "evidence", "保存检查结果", (0,.85,1,.25), [(1210,842),(1210,998)])
    d.edge("project-eval", "flowerp", "eval", "提供 Eval 入口与运行配置", (.5,0,.5,1))
    d.edge("control-project", "control", "flowerp", "具名接受后，显式集成源码", (0,.9,0,.53), [(740,886),(740,930),(600,930),(600,1190),(1100,1190),(1100,1090)], True)
    d.text("optional", "可选驾驶舱 harness_web/（默认 :8010）不进入必做主线。", 40, 1330, 1080, 30, 19)
    d.text("boundary", "图中箭头表示职责协作、进程调用或证据归属；不等于全部模块依赖已强制单向分层。\n软件审核通过与客户业务审批分别保留证据。", 40, 1250, 1770, 80, 19)
    d.legend(40, 1370)
    d.save("workbench-architecture")


def learning_cycle():
    d = Diagram("跨事项经验与流程复用", 1830, 1330)
    d.text("title", "能力如何增长：让前一事项的经验接受后一事项检验", 40, 20, 1750, 55, 30, True)
    d.text("subtitle", "Harness 控制交付；记忆保留有边界的经验；工作流从真实轨迹提炼，并经复验和人审后复用。", 40, 85, 1750, 50, 21)
    d.group("a", "事项 A：真实交付产生可核查的来源", 40, 170, 1730, 260)
    d.box("delivery-a", "<b>受控交付、失败与已接受反馈</b><br>保留任务、Spec、Diff、Eval<br>及实际人审或失败轨迹", 30, 80, 370, 130, parent="a", extra="fontSize=18;")
    d.box("candidate", "<b>提炼记忆 / 流程候选</b><br>来源快照 · 项目 · 适用边界<br>排除条件 · 版本与哈希", 460, 80, 390, 130, parent="a")
    d.box("review", "<b>独立审核候选</b><br>审核人须与提炼者分离<br>核查来源与采用边界", 910, 80, 340, 130, "human", parent="a")
    d.box("version", "<b>可召回的版本</b><br>记忆已生效<br>流程经审核可试用", 1310, 80, 380, 130, "data", parent="a")
    d.edge("a-candidate", "delivery-a", "candidate")
    d.edge("candidate-review", "candidate", "review")
    d.edge("review-version", "review", "version")
    d.group("b", "事项 B：显式采用版本，验证是否真的有效", 40, 540, 1730, 440)
    d.box("recall", "<b>按项目与边界召回</b><br>人逐项采用或拒绝<br>保存理由与版本绑定", 30, 70, 370, 130, "human", parent="b")
    d.box("spec", "<b>冻结 Spec 与采用快照</b><br>绑定目标、写集、版本哈希<br>失效版本不可继续沿用", 460, 70, 390, 130, parent="b")
    d.box("execute", "<b>固定四阶段执行</b><br>前置检查 → 实现 → Eval → 人审<br>逐阶段保留实际检查与候选证据", 910, 70, 780, 130, parent="b")
    d.box("outcome", "<b>记录人审及实际采用结果</b><br>通过：具名验收 + 检查证据完整<br>失败：保留失败轨迹与原因", 1100, 270, 590, 130, "data", parent="b")
    d.box("govern", "<b>发布、修订或停用版本</b><br>流程试用通过后，由人具名发布<br>流程复用失败即停用；记忆可由人撤回", 510, 270, 510, 130, "human", parent="b", extra="fontSize=18;")
    d.box("next", "<b>后续事项再次采用</b><br>继续检验适用性与交付效果<br>保留新事项与旧版本的关联", 30, 270, 400, 130, parent="b")
    d.edge("version-recall", "version", "recall", "进入后续独立事项；流程试用须显式选择", (.5,1,.5,0), [(1540,480),(255,480)], x=.1, y=-8)
    d.edge("recall-spec", "recall", "spec")
    d.edge("spec-execute", "spec", "execute")
    d.edge("execute-outcome", "execute", "outcome", "", (.75,1,.5,0))
    d.edge("outcome-govern", "outcome", "govern", "", (0,.5,1,.5))
    d.edge("govern-next", "govern", "next", "", (0,.5,1,.5))
    d.text("accept", "闭环的完成判断：来源真实 → 独立事项采用明确版本 → 执行与人审证据完整 → 复用结果可追溯 → 失败触发修订 / 停用。", 40, 1030, 1730, 70, 20, True)
    d.text("boundary", "来源要求：已验收成功任务可直接作为来源；失败来源须有具名接受反馈与改进提案。\n这是一张设计与代码机制示意图。单次交付、事件持久化或反馈登记不能证明闭环完成；真实工程效果须查看实际记录。\n首版流程只有四个固定阶段；未据此认定通用编排、自动蒸馏或模型训练已经实现。", 40, 1110, 1730, 110, 19)
    d.legend(40, 1260, external=False)
    d.save("workbench-learning-cycle")


if __name__ == "__main__":
    architecture()
    learning_cycle()
