# 工作台设计解释图与生成记录

这四张图按[主文](../../个人AI研发工作台.md)的阅读顺序组织，分别回答组织思路、系统架构、证据关系和长期复用四个问题。生成方式均为 Codex 内置 `image_gen.imagegen`，未使用 CLI/API fallback。

| 要理解的问题 | 图片 | 精确提示词与生成记录 |
|---|---|---|
| 完整项目怎样落实到长期事项和每轮任务 | [组织思路](workbench-design-mainline-imagegen-v1.png) | [生成记录](workbench-design-mainline-imagegen-v1.prompt.md) |
| 模块怎样协作，研发和业务数据分别属于谁 | [系统架构](workbench-system-architecture-imagegen-v1.png) | [生成记录](workbench-system-architecture-imagegen-v1.prompt.md) |
| 什么变化会使原来的报告与接受依据失效 | [证据与版本](workbench-evidence-binding-imagegen-v1.png) | [生成记录](workbench-evidence-binding-imagegen-v1.prompt.md) |
| Harness、经验与流程怎样支持下一事项 | [交付与复用](workbench-harness-learning-imagegen-v1.png) | [生成记录](workbench-harness-learning-imagegen-v1.prompt.md) |

四图均为 1672 × 941 像素，约 16:9。最终图片保存在本目录，精确生成与修订提示词、原始输出路径、尺寸和 SHA-256 分别保存在同名 `.prompt.md` 中。已查看项目中的 PNG，核对中文、箭头和数据边界；项目文件与内置最终输出的哈希一致，未做像素编辑。

图是设计解释示意。阶段规划由人和 Codex 在项目文档中维护；图中的失败、修复与回流表示设计关系，不能替代真实交付、运行、客户验收或跨事项复用证据。模块关系按当前源码简化，具体约束与取舍见[工作台具体设计](../../工作台具体设计.md)。

已有的[库存经验迁移图](workbench-experience-transfer-imagegen-v1.png)用于展开局部业务例子，[三个视角图](workbench-three-views-imagegen-v1.png)用于补充范围、分工与机制的概念关系。原有 `.drawio`、SVG 和 PNG 继续保留，供需要详细关系图时查阅。
