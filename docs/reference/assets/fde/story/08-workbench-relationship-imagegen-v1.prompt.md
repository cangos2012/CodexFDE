# FDE 怎样落到工作台与 FlowERP：ImageGen 生成记录

- 日期：2026-10-04（Asia/Shanghai）。
- 图片：[FDE 怎样落到工作台与 FlowERP](08-workbench-relationship-imagegen-v1.png)。
- 主文：[FDE 与工作台：一个库存问题的图解](../../../FDE与个人AI研发工作台.md)。
- 生成方式：Codex 内置 `image_gen.imagegen`，一次全新生成，无像素编辑或 CLI/API fallback。
- 性质：少字教学故事图，展示业务对象、人的判断和交付关系，不构成真实交付或学习达成证据。
- 原始输出：`C:\Users\Administrator\.codex\generated_images\01a106e8-b279-7c92-a358-8d38d5dcc1d6\exec-6c44b31b-6c73-4476-a3f8-d5fd87733338.png`。
- 尺寸：1672 × 941 像素；文件大小：1395393 字节。
- SHA-256：`8B4A54F416EC67A2F1A93494383F924B1697C8A4102BCF6464CC8A73CE27DC8B`。
- 保存核对：工作区副本与原始输出字节、哈希一致。
- 视觉核对：人和 Codex 先共同建工作台，再由工作台组织 FlowERP 交付；使用反馈回到方法改进；L04 先验收 V0 再首次交付；人与产品责任明确。

## 完整实际提示词

```text
Use case: infographic-diagram
Asset type: 中文FDE图解的第8张少字关系图，说明FDE方法怎样落到工作台及FlowERP。
Primary request: 全新生成高清16:9横向少字教材图，标题逐字“FDE 怎样落到工作台与 FlowERP”。图像主体展示人与Codex共同建造工作台，再由工作台组织持续交付，客户结果反馈回来改进方法。不能变成ERP功能列表或架构术语表。
Style: 浅暖白、深蓝中文大字、青绿主箭头、橙色反馈、轻量等距工具台与文档插画。清楚的3个大主体，功能性人物图标和业务文档，字少图多。Codex用工具卡表现，不用机器人。无实际软件截图或完成印章。
Left subject: 研发负责人和一张清楚标“Codex”的工具卡。人旁边写“人判断与验收”，工具卡下写“Codex 协助实现”。
Center subject: 大的研发工作台，标题“工作台”，三个直观收纳区只写“问题与决定”“执行与检查”“经验与复用”。工作台是组织研发的工具，不是客户经营ERP的业务门户。
Right subject: 独立“FlowERP”客户产品文档与业务人员核对结果的小场景，文档下写“客户使用与业务验收”。
Arrow left to center: “先共同建造”
Arrow center to right: “再组织交付”
Orange feedback right to center: “使用反馈，改进方法”
这三根箭头端点准确，反馈从客户结果回到工作台，不能回到Codex表示自动训练。
Bottom stage line (verbatim): “L04：先验收工作台 V0，再首次交付 FlowERP”
Bottom conclusion (verbatim): “方法由人判断，工作台组织，产品结果检验”
Boundary (verbatim): “教学示意”
Constraints: 只用以上文字，中文与Codex/FlowERP拼写准确，所有文字大且可读。阶段行只是课程换挡点，不假造已验收完成；不画自动发布、模型训练、权重更新、成功印章。不要把三种收纳区分别对应三个独立系统，不画数据库/HTTP/API/哈希等实现细节。背景不透明，无水印。
```
