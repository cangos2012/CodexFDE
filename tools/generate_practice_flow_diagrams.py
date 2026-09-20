from __future__ import annotations

from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

LESSONS = {
    3: [
        ("建立本讲目录", "PowerShell", "5 个练习文件"),
        ("回答需求问题", "Codex + 你", "decisions.md"),
        ("写合同并消除歧义", "Codex + 你", "v1 与确认版 Spec"),
        ("抽取通用模板", "练习仓库", "模板与采购迁移稿"),
        ("建设结构解析器", "练习仓库", "解析器与测试"),
        ("用三份合同复验", "PowerShell + 你", "evidence.md"),
    ],
    4: [
        ("准备本讲记录", "PowerShell", "lesson-04-submission"),
        ("调查 V0 缺口", "写作会话 + 你", "Ticket A 合同"),
        ("补齐并自查 V0", "练习仓库", "范围内 Diff"),
        ("独立接受 A", "非执行者", "A 接受记录"),
        ("冻结并提交 B", "控制工作台", "任务与候选"),
        ("独立复验库存导出", "候选目录", "CSV 与报告"),
        ("接受或打回", "审核者", "handoff.md"),
    ],
    5: [
        ("进入自己的工作台", "控制仓库", "L05 会话"),
        ("找出现有绿灯盲区", "你 + Codex", "首次判断"),
        ("完成旧绿、新红对照", "缺陷副本", "两次稳定红灯"),
        ("验证工程范围", "独立练习仓库", "范围证据"),
        ("把检查接入正式候选", "控制工作台", "冻结检查"),
        ("修复并复验", "正式候选", "红转绿证据"),
        ("交给人判断", "工作台页面", "接受或返工"),
        ("排错与迁移", "你", "迁移结论"),
    ],
    6: [
        ("准备自己的候选", "控制仓库", "session.json"),
        ("写首次判断", "你", "个人记录"),
        ("观察失败与假绿", "候选目录", "原始报告"),
        ("先修 Harness 汇总", "候选目录", "可信退出码"),
        ("再修整批导入", "候选目录", "原子导入"),
        ("换七行数据复验", "候选目录", "新报告"),
        ("检查差异并交接", "复验者", "接受或打回"),
        ("中断后继续", "原 session", "续做记录"),
    ],
    7: [
        ("准备环境与起点", "控制仓库", "首次预测"),
        ("观察草稿订单", "客户环境", "业务状态"),
        ("验证适配器输入", "控制仓库", "六类结果"),
        ("建设待审 Hook", "候选目录", "hook_staging"),
        ("交付草稿订单", "控制工作台", "任务与候选"),
        ("触发真实事件", "候选目录", "失败与恢复"),
        ("复验并迁移", "复验者 + 你", "最终结论"),
    ],
    8: [
        ("固定环境与候选", "控制仓库", "共同起点"),
        ("固定业务裁判", "你 + 复验者", "四表预期"),
        ("理解 A/B/C", "本地实验", "证据边界"),
        ("建立个人候选", "控制工作台", "候选与指纹"),
        ("准备 A/B 流程", "候选仓库", "CI 规则"),
        ("完成远程 A/B/C", "远程 CI", "Run 与产物"),
        ("判断是否交接", "复验者", "接受或返工"),
    ],
    9: [
        ("确认位置与起点", "控制仓库", "首次判断"),
        ("观察真实取消", "客户环境", "leak.json"),
        ("检查映射器边界", "控制实验", "映射结果"),
        ("从失败生成草案", "控制仓库", "修复 Spec"),
        ("完成实际交付", "个人候选", "取消修复"),
        ("同伴反证并接受", "复验者", "最终决定"),
    ],
    10: [
        ("固定环境与轮数", "控制仓库", "计数约定"),
        ("运行控制路径", "控制实验", "十二种结果"),
        ("验证发货状态", "客户环境", "合法/非法状态"),
        ("设计自己的 Loop", "你 + Codex", "循环合同"),
        ("实现受控 Loop", "隔离候选", "范围内实现"),
        ("留下收敛与停止", "真实 Loop", "两条轨迹"),
        ("复核并提炼", "同伴 + 你", "流程版本"),
    ],
    11: [
        ("准备项目与判断", "控制仓库", "首次判断"),
        ("运行声明实验", "控制实验", "冲突结果"),
        ("观察采购业务", "客户环境", "采购状态"),
        ("固定两份子任务", "个人候选", "任务合同"),
        ("执行真实并行", "Codex 子代理", "独立产物"),
        ("主任务串行整合", "个人候选", "统一复验"),
        ("复盘并迁移", "你", "协作结论"),
    ],
    12: [
        ("准备独立预期", "控制仓库", "两套状态表"),
        ("观察 Graph 边界", "控制实验", "状态轨迹"),
        ("检验审批与库存", "客户环境", "业务结果"),
        ("建设自己的 Graph", "个人候选", "Graph 实现"),
        ("等待、批准或打回", "审核者", "恢复轨迹"),
        ("统一业务与流程复验", "同一候选", "双重证据"),
        ("提炼并迁移", "你", "流程版本"),
    ],
    13: [
        ("写下接口预期", "控制仓库", "首次判断"),
        ("观察真实 HTTP", "参考实验", "report.json"),
        ("做进程中断恢复", "恢复实验", "恢复证据"),
        ("实现两个最小接口", "个人候选", "提交与查询"),
        ("接回 FlowERP", "同一候选", "Task 与采购对象"),
        ("复验、互评与迁移", "复验者 + 你", "最终结论"),
    ],
    14: [
        ("留下本人判断", "你", "页面问题"),
        ("观察工作台起点", "18114 工作台", "事项状态"),
        ("制造失败并恢复", "浏览器 + 服务", "失败证据"),
        ("形成合同并实现", "对应候选", "页面修复"),
        ("验证业务主路径", "18115 FlowERP", "采购结果"),
        ("核验结果与下载", "两个系统", "一致性证据"),
        ("同伴复验与迁移", "复验者", "接受或打回"),
    ],
    15: [
        ("确认起点", "原 L14 事项", "首次判断"),
        ("导出事实摘要", "控制仓库", "交付摘要"),
        ("采集并审核反馈", "工作台", "反馈记录"),
        ("交付一个小改进", "个人候选", "新 Eval 与结果"),
        ("登记可治理 Memory", "工作台", "来源与状态"),
        ("运行 RAG 反例", "隔离实验", "检索与治理结果"),
        ("由人决定是否采用", "Codex + 你", "采用记录"),
        ("跨事项回收效果", "原反馈者 + 你", "闭环证据"),
    ],
    16: [
        ("冻结实际起点", "原源码", "版本与环境"),
        ("由同伴冷启动", "全新环境", "首次失败与修订"),
        ("抽取未实现需求", "工作台 + 你", "受控 Spec"),
        ("交付并复验", "隔离候选", "真实 Diff 与 Eval"),
        ("检查治理入口", "工作台", "任务与审核"),
        ("恢复、导出与反馈", "双系统", "交付索引"),
        ("答辩与迁移", "你 + 复验者", "最终接受"),
    ],
}

STEP_DETAILS = dict(LESSONS)
STEP_DETAILS[15] = [
    ("确认起点与首次判断", "原 L14 事项", "首次判断"),
    ("导出事实摘要", "控制仓库", "交付摘要"),
    ("采集实际反馈", "工作台", "反馈三层记录"),
    ("观察审核与晋级", "隔离记录", "边界结果"),
    ("交付一个小改进", "个人候选", "新 Eval 与结果"),
    ("核对产品与摘要", "同一候选", "一致性结论"),
    ("登记 Memory", "工作台", "来源与治理状态"),
    ("运行 RAG 反例", "隔离实验", "检索与治理结果"),
    ("决定是否采用", "Codex + 你", "采用记录"),
    ("回收跨事项效果", "原反馈者 + 你", "闭环证据"),
]


def xml_style(fill: str, stroke: str, size: int = 17, bold: bool = False) -> str:
    return (
        "rounded=1;whiteSpace=wrap;html=1;"
        f"fillColor={fill};strokeColor={stroke};fontSize={size};"
        f"fontStyle={1 if bold else 0};spacing=8;"
    )


def diagram_files(lesson: int, steps: list[tuple[str, str, str]]) -> tuple[str, str]:
    rows = (len(steps) + 1) // 2
    height = 170 + rows * 180
    cells = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
        f'<mxCell id="2" value="L{lesson:02d} 实践路线：按顺序操作，每一步都留下实际结果" style="{xml_style("#17324D", "#17324D", 25, True)}fontColor=#FFFFFF;" vertex="1" parent="1"><mxGeometry x="40" y="30" width="1320" height="70" as="geometry"/></mxCell>',
    ]
    svg_nodes = [
        '<rect width="1400" height="%d" fill="#ffffff"/>' % height,
        '<rect x="40" y="30" width="1320" height="70" rx="16" fill="#17324d"/>',
        f'<text x="700" y="74" text-anchor="middle" class="title">L{lesson:02d} 实践路线：按顺序操作，每一步都留下实际结果</text>',
    ]
    positions: list[tuple[int, int]] = []
    for index, (title, place, output) in enumerate(steps, 1):
        row = (index - 1) // 2
        col = (index - 1) % 2
        x = 170 + col * 650
        y = 140 + row * 180
        positions.append((x, y))
        fill, stroke = ("#FFF2CC", "#D6B656") if "审核" in place or "复验" in title or "判断" in title else ("#DAE8FC", "#6C8EBF")
        if index == len(steps):
            fill, stroke = "#D5E8D4", "#82B366"
        value = escape(f"{index} {title}\n位置：{place}\n产出：{output}").replace("\n", "&#xa;")
        cells.append(f'<mxCell id="n{index}" value="{value}" style="{xml_style(fill, stroke, 17, index == len(steps))}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="410" height="120" as="geometry"/></mxCell>')
        svg_nodes.extend([
            f'<rect x="{x}" y="{y}" width="410" height="120" rx="14" fill="{fill.lower()}" stroke="{stroke.lower()}" stroke-width="2"/>',
            f'<text x="{x + 205}" y="{y + 34}" text-anchor="middle" class="step">{index} {escape(title)}</text>',
            f'<text x="{x + 205}" y="{y + 68}" text-anchor="middle" class="meta">位置：{escape(place)}</text>',
            f'<text x="{x + 205}" y="{y + 96}" text-anchor="middle" class="meta">产出：{escape(output)}</text>',
        ])
    for index in range(1, len(steps)):
        x1, y1 = positions[index - 1]
        x2, y2 = positions[index]
        if y1 == y2:
            path = f"M{x1 + 410} {y1 + 60} H{x2 - 10}"
            style = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"
        else:
            path = f"M{x1 + 205} {y1 + 120} V{y1 + 150} H{x2 + 205} V{y2 - 10}"
            style = "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
        cells.append(f'<mxCell id="e{index}" value="" style="edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;endArrow=block;{style}" edge="1" parent="1" source="n{index}" target="n{index + 1}"><mxGeometry relative="1" as="geometry"/></mxCell>')
        svg_nodes.append(f'<path class="edge" d="{path}"/>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="drawio" version="26.0.0"><diagram name="实践路线">'
        f'<mxGraphModel page="1" pageScale="1" pageWidth="1400" pageHeight="{height}"><root>'
        + "".join(cells)
        + '</root></mxGraphModel></diagram></mxfile>\n'
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="{height}" viewBox="0 0 1400 {height}">'
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#35556f"/></marker>'
        '<style>.title{font:700 26px Microsoft YaHei,PingFang SC,sans-serif;fill:#fff}.step{font:700 18px Microsoft YaHei,PingFang SC,sans-serif;fill:#17324d}.meta{font:15px Microsoft YaHei,PingFang SC,sans-serif;fill:#3f5567}.edge{fill:none;stroke:#35556f;stroke-width:3;marker-end:url(#arrow)}</style></defs>'
        + "".join(svg_nodes)
        + '</svg>\n'
    )
    return xml, svg


def update_manual(lesson: int, steps: list[tuple[str, str, str]]) -> None:
    manual = ROOT / "docs" / "courses" / f"L{lesson:02d}" / "实践操作手册.md"
    body = manual.read_text(encoding="utf-8")
    marker = "### 按图执行的完成标志"
    if marker not in body:
        table = [
            marker,
            "",
            "| 步骤 | 在哪里操作 | 进入下一步前必须留下什么 |",
            "|---|---|---|",
        ]
        for index, (title, place, output) in enumerate(steps, 1):
            table.append(f"| {index}. {title} | {place} | {output} |")
        addition = "\n".join(table) + "\n"
        pattern = rf"(?m)(可编辑源文件：\[l{lesson:02d}-practice-flow\.drawio\]\([^\n]+\)。\n)"
        body, count = re.subn(pattern, rf"\1\n{addition}", body, count=1)
        if count != 1:
            raise RuntimeError(f"L{lesson:02d} 未找到流程图源文件段落")

    details = STEP_DETAILS[lesson]
    for index, (_, place, output) in enumerate(details, 1):
        guide_marker = f"<!-- step-guide-{index} -->"
        if guide_marker in body:
            continue
        next_text = f"完成后进入第 {index + 1} 步。" if index < len(details) else "完成后按本讲提交要求交接。"
        guide = (
            f"\n{guide_marker}\n"
            f"> **本步位置：**{place}\n"
            f"> **完成标志：**已经留下可打开、可复查的“{output}”。\n"
            f"> **异常时：**保留实际输出和退出码，先处理本步问题，不用后一步的成功覆盖它。\n"
            f"> **下一步：**{next_text}\n"
        )
        heading_pattern = rf"(?m)(^##\s+(?:第\s*)?{index}(?:\s*步)?(?:[.．、：:]|\s)[^\n]*\n)"
        body, count = re.subn(heading_pattern, rf"\1{guide}", body, count=1)
        if count != 1:
            raise RuntimeError(f"L{lesson:02d} 未找到第 {index} 步标题")
    body = re.sub(
        r"(?m)^(> \*\*(?:本步位置|完成标志|异常时)：\*\*.*)  $",
        r"\1",
        body,
    )
    manual.write_text(body, encoding="utf-8")


def main() -> None:
    for lesson, steps in LESSONS.items():
        target = ROOT / "docs" / "courses" / f"L{lesson:02d}" / "assets"
        target.mkdir(parents=True, exist_ok=True)
        xml, svg = diagram_files(lesson, steps)
        (target / f"l{lesson:02d}-practice-flow.drawio").write_text(xml, encoding="utf-8")
        (target / f"l{lesson:02d}-practice-flow.svg").write_text(svg, encoding="utf-8")
        update_manual(lesson, steps)


if __name__ == "__main__":
    main()
