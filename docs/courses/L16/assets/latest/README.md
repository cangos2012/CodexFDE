# L16 本轮参考证据

restore-observation.json 来自 examples/restore_lab.py 在全新目录的实际运行；restore-observation.png 是原始字段的可读排版截图，非原生工作台。实验为教学数据，不是客户账本，不代表容器冷启动、生产回滚或人审。原库10件、恢复副本8件；重复恢复拒绝且目标指纹未变，损坏副本拒绝且未建目标库。原备份和失败副本保留在私有实验目录。

## 本机隔离启动

cold-start-observation.json为冷启动本轮实际结果摘要；两张cold-*.png为本机原生页面截图，无补绘。新源码、新虚拟环境、新运行目录仍共享Windows主机与基础Python。首次工作台因缺少Git目录退出；修订后两个首页与健康接口成功，但没有创建ERP组织、没有交付事项，不证明容器运行。私有cold-r1/r2/r3保留失败与修订记录，已停止本轮所启动进程。

## 初始化后的最小业务复验

business-observation.json 来自本机新隔离环境的浏览器自动操作。business-created-product.png 与 business-duplicate-rejected.png 为原生截图，已视觉检查。首次初始化和建档返回201，重复SKU返回409，失败后原记录不变，重新登录可回查。图片不包含密码，不证明人审、新需求交付或容器化完成。
