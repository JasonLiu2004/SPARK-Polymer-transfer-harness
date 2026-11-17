电解质研究 Harness：独立工作目录
2026-11-17

这个目录集中保存文献检索、知识提取、工具调度、研究记忆、性质计算、SPARK任务重建和公开电导率模型测试。原项目保留不动，新实验从这里运行。

从哪里开始
1. 配置统一在本目录根部 .env。当前工作站的配置已复制到这里，继续修改根部 .env 即可。终端中已设置的同名环境变量优先。
2. 在本目录打开终端，使用当前工作站的Python：
   python run.py smoke
   python run.py test
   python run.py hpg
   python run.py scan
   python run.py baseline
3. 总控LLM任务：
   python run.py plan --task "查询SPARK中PEO相关候选，并说明对应文献证据和性质数据"
4. 完整案例与原十篇样例：
   python run.py case
   python run.py batch10
   这两项会使用根部.env中的模型服务；batch10会利用已有缓存。
5. 旧表、归档预测与轨迹后处理：
   python run.py completion

目录
spe_agentic_harness/                  文献搜索、PDF提取、总控、知识记忆和计算工具
spark_agentic_harness/                SPARK适配、应用分类、样例和性质补全
spark_agentic_harness/external_conductivity/
                                     HPG、SCAN、ChemArr数据及新增指纹基线
SPARK_selected3_seed_shareable_20260807/
                                     原SPARK分享包的完整独立副本
To-ljh/                              运行需要的原文献输入、分类标签和旧电导率表
reports/                             合并PPT、整体Harness图、构建及验证记录
verification/                        本独立目录的运行检查

执行与接口
planner.py中的run_planner驱动LLM规划，Harness.definitions()暴露工具，execute(name, arguments)执行并记日志。
ResearchHarness位于spe_agentic_harness/harness.py，SparkHarness位于spark_agentic_harness/spark_harness.py。
知识与计算记录保存在各实验outputs中的SQLite，事件和规划保存在JSONL。文献实测、工具外推和模型预测保留各自来源。
HPG与SCAN当前通过独立脚本执行，统一入口为run.py hpg / scan。它们已完成权重推理测试；总控中的模型路由仍按PPT接入设计实施。

数据与环境
本目录含87份本地PDF副本、WoS工作簿与分类标签、3469行旧电导率CSV、公开模型权重、测试结果和现有Windows OpenMM/xTB运行时。
HPG/DGL/RDKit附加依赖在external_conductivity/.deps，脚本会自行加入搜索路径。本机系统Python的依赖列表见requirements.txt。
目录已移除对原研究目录的活动路径依赖；历史日志里的绝对路径保留为来源记录。local_corpus_inventory.json使用相对路径，原清单保存在.original.json。
这是可在当前Windows工作站独立运行的项目副本。迁移操作系统时需按requirements和各引擎要求重新安装对应平台依赖。

汇报口径
合并PPT前半部分展示成功完成的结果。保留六个有效性质案例，并明确区分五个温度外推与一个25℃实测。
公开模型测试和新增基线放在后半部分，保留各自验证条件。完整历史结果仍在outputs，报告筛选不修改实验记录。

代码整理说明
复制了两个Harness目录的代码、测试、例子、结果、模型及运行时，以及原SPARK分享包。
旧To-ljh约10GB的资料目录只复制了当前代码使用的数据和87份PDF，未复制无关训练中间文件。
根部.env包含你的本地密钥，已加入.gitignore；如需对外分享，使用.env.example替代。
