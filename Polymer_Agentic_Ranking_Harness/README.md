# 五窗材料推荐代码索引

要改“下一窗如何产生”，从 `run.py::study` 读起。要改“主控能查什么、交什么”，读 `agent.py::ToolSession` 和 `Agent.decide`。要改“谁应该排在谁前面”，读 `ordinal.py::rank_all`、`evidence_order.py::constrained_tiers` 和 `ranking_policy.py::ranking_record`。安装命令、五窗模块图及结果入口见[仓库首页](../README.md)。

## 1. 从文献得到一个候选材料

这些文件位于 `Polymer_Adoption_Harness/`。当前广域检索覆盖《Polymer Journal》以及膜、涂层、支架等跨领域主题，SPE 主检索和独立检索各有专用查询。

| 文件 | 输入 → 输出及职责 |
| --- | --- |
| [prepare_sources.py](../Polymer_Adoption_Harness/prepare_sources.py) | 用年份、期刊和关键词查询 Crossref 与 Europe PMC，下载或核验 25 份期刊年表、5 份跨域主题快照、5 份 SPE 主检索和 5 份独立 SPE 检索。 |
| [corpus.py](../Polymer_Adoption_Harness/corpus.py) | `raw_paths` 列出每条检索流的输入位置。`papers` 读题录并合并同 DOI 记录，保留截至该窗的发表年份、标题、摘要与检索来源。 |
| [extract.py](../Polymer_Adoption_Harness/extract.py) | `read_interval` 将一个时间段的题录交给 LLM，验证材料名、样品、角色及其对应的标题或摘要原句，生成 `data/intervals/<检索流>/<起年>_<止年>.json`。 |
| [structures.py](../Polymer_Adoption_Harness/structures.py) | `identity` 用材料原名、原文和已登记别名统一身份。`REPEATS` 提供可构图的参考重复单元，决定哪些材料可进入 HPG 计算。 |
| [graph.py](../Polymer_Adoption_Harness/graph.py) | `build` 从抽取记录生成 DOI、材料、样品、角色和三个结构维度的证据关系。`observations` 从 SPE 专项记录中选取实际固态样品或电池中观察到的材料及其角色。 |
| [common.py](../Polymer_Adoption_Harness/common.py) | 定义五个截止年、JSON 工具声明和官方 DeepSeek 请求。`seal` 与 `verified` 封存与核验输入、调用回执和输出。 |

`graph.json` 是当窗的证据快照。每个材料通过 DOI、原文摘句及摘句位置连回发表记录。`first_observed` 表示截止年以前的目标检索尚未观察到采用，`repeat` 表示此前已观察到。两者均保留在全榜中。

## 2. 从结构得到 HPG 电导率

| 文件 | 输入 → 输出及职责 |
| --- | --- |
| [physics.py](../Polymer_Adoption_Harness/physics.py) | `design` 将重复单元、LiTFSI 质量分数、温度组成参考配方。`prepare` 核验权重、调用 CPU 推理器并冻结网格。`dated_predictions` 把结果关联到截止日前可见的材料来源。 |
| [requirements-hpg.txt](../Polymer_Adoption_Harness/requirements-hpg.txt) | HPG 推理所需的 PyTorch、DGL、PyTorch Geometric、RDKit 等依赖。 |
| [hpg_worker.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_worker.py) | 校验质量分数与重复单元连接，构建图和模型输入，加载公开权重。每个配方返回其计算状态，以及成功预测时的 `log10_sigma_S_cm` 和 `sigma_S_cm`。 |
| [hpggat.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/hpggat.py) | HPG 上游图注意力网络实现，包含 `GAT` 和 `GATNet`。预训练参数来自单独取得的 `HPG_GAT.bin`。 |
| [mol2graph.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/mol2graph.py) | 将分子和聚合物转换为模型使用的图，生成原子、化学键和图连接特征。 |
| [polyG.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/polyG.py) | 表示聚合物片段、节点及其连接，按重复单元与连接规则拼接聚合物图。 |
| [smiles_utils.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/smiles_utils.py) | 解析与规范化 SMILES，为原子构造符号、价态、芳香性、杂化等特征。 |
| [harness/common.py](../SPARK_Motif_Transfer_Harness_v4/harness/common.py) | 提供权重路径与指纹、JSON 的原子写入、时间戳、配置和写锁，供上层证据及 HPG 共用。 |
| [harness/__init__.py](../SPARK_Motif_Transfer_Harness_v4/harness/__init__.py)、[hpg_vendor/__init__.py](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/__init__.py)、[LICENSE](../SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/LICENSE) | Python 包入口及上游 HPG 源码的 MIT 许可。 |

HPG 的对象是一份有明确组分、比例和温度的设计配方。绑定到当年出现的材料后，`query_hpg` 可返回六组条件及计算状态。测量值、后续 SPE 样品，以及该材料假设配方的模型预测各有自己的出处。

## 3. 主控如何调用工具、形成全榜

以下文件位于当前目录 `Polymer_Agentic_Ranking_Harness/`。实验以文献中识别出的材料为候选。骨架、有机阳离子和阴离子分别用于查证，并可追到早期 SPE 样品中的同类角色。

| 文件 | 输入 → 输出及职责 |
| --- | --- |
| [run.py](run.py) | 官方 DeepSeek 五窗入口。`study` 依次登记协议、加载当窗资料、构图、发起提名和排序、冻结排名、揭晓下一窗、更新记忆。 |
| [run_paratera.py](run_paratera.py) | Paratera 版五窗入口，探测原生工具调用能力并登记服务实际返回的模型，使用同一组证据、准入和排序模块。 |
| [paratera.py](paratera.py) | `Paratera` 发送带工具定义的请求，处理限流和暂时性网络错误，保存可供核验的请求与响应。 |
| [resume_paratera.py](resume_paratera.py) | 恢复已完成前四窗、在 2024 年比较阶段遇到数组参数被服务编码成文本的历史运行。一般续跑使用原入口。 |
| [evidence.py](evidence.py) | `Evidence` 合并当时可见的广域文献、既往 SPE 样品及 HPG 配方，按材料生成主控允许读取的证据。 |
| [agent.py](agent.py) | 定义下表的原生工具。`ToolSession` 检查读取范围、DOI 引用和候选覆盖，`Agent.decide` 驱动调用直至收到完整提交，并记录比较依据。 |
| [ordinal.py](ordinal.py) | `screen` 分批覆盖候选以提名。`rank_all` 让 LLM 排列全部候选，小组直接比较，大组用参照材料定位后递归比较，输出保留并列的偏好分组。 |
| [adoption.py](../Polymer_Adoption_Harness/adoption.py) | `qualifies` 核查 HPG 计算状态、日期和阈值。`admit` 将达标材料与有文献依据的 LLM 提名合并，记录每项材料的入池途径。 |
| [evidence_order.py](evidence_order.py) | `constrained_tiers` 用不同 DOI 数与最近发表年份规定必须遵守的相对次序，在当下可选材料中选取 LLM 最优先的一组。 |
| [ranking_policy.py](ranking_policy.py) | 登记 `exposure` 或 `ordinal` 策略。`ranking_record` 将偏好转为正式全榜、池内名次与并列区间，并保存无约束 LLM 对照。 |

| 主控工具 | 它解决的问题 |
| --- | --- |
| `inspect_publications` | 这项材料何时出现？原句描述了哪个样品？近年与较早时段分别有多少篇文献？此前查到过哪些 SPE 用途？ |
| `trace_structural_roles` | 这条骨架、有机阳离子或阴离子的依据分别在哪里？早期 SPE 中有没有同一结构维度的样品可作类比？ |
| `query_hpg` | 某材料在各设计温度和盐含量下的预测电导率是多少？哪些条件达标？ |
| `submit_nominations` | 提交有文献支持的材料及 DOI。HPG 自动入池途径由 `admit` 同时执行。 |
| `submit_order`、`submit_placements` | 提交覆盖整组的偏好顺序，或说明每项材料相对参照材料的位置，保留并列和证据引用。 |
| `read_closed_cases`、`update_memory` | 榜单冻结后读取已核验案例，提交最多三条下一窗的取证问题，每条附案例依据与复核方法。 |

## 4. 排名冻结后怎样核验和学习

| 文件 | 输入 → 输出及职责 |
| --- | --- |
| [memory.py](memory.py) | `closed_cases` 为本窗观察到的首次采用材料，选取文献篇数接近、此前排位靠前但本次未观察到的材料作比较。`reflect` 让 LLM 查阅案例，形成带截止日期的下一窗记忆。 |
| [evaluate.py](evaluate.py) | 五窗完成后打开独立 SPE 检索、剔除重叠 DOI，计算支持并列的 AP、前十命中数和前 20% 召回率。输出 `metrics.csv`、全榜、推荐池及核验 DOI。 |
| [audit.py](audit.py) | 从协议、图谱、调用回执和比较树重建结果，检查时间顺序、候选覆盖、HPG 达标准入和独立检索的隔离。`--check-only` 只读核验。 |
| [progress.py](progress.py) | 将已经冻结的窗口和已揭晓的结果导出，可在运行中途由 `rank-audit --available` 使用。 |
| [explain.py](explain.py) | 按年份查看推荐池或追踪某一材料的证据、入池理由和名次形成过程。 |
| [report.py](report.py) | 用结果目录中的 CSV、摘要和可用审计记录生成 `results/五窗排序对照.md`。 |
| [test_ordinal.py](test_ordinal.py) | 测试候选完整覆盖、并列、正式排序、HPG 入池以及先冻结后反馈的顺序。 |
| [test_adoption.py](../Polymer_Adoption_Harness/test_adoption.py)、[test_prepare_sources.py](../Polymer_Adoption_Harness/test_prepare_sources.py) | 测试截止年、准入、材料与证据身份、检索快照清单和分页完整性。 |

沿着一个材料读代码时，打开 `<年份>/forecast.json` 查看 `route`、`qualifying_recipes` 和 `rank_min/rank_max`，再用 `rank-explain --material` 查看具体比较和证据。要看当年排名是否命中，在 `results/observed_first_use_ranks.csv` 按材料与年份筛选 `verification_dois`。这条路径把当时可用的预测依据与后来报道的样品连接起来。

## 5. 历史实现与归档工具

| 位置 | 在本版本中的作用 |
| --- | --- |
| [history/ordinal/](history/ordinal/) | 保存自由 LLM 排序版本的六份代码快照。`run.py` 是旧主循环，`agent.py` 是工具协议，`evidence.py` 是证据视图，`ordinal.py` 是排序，`evidence_order.py` 是文献约束对照，`memory.py` 是复盘。历史协议按对应版本核验指纹。 |
| [inspect_original.py](inspect_original.py) | 使用单独提供的 SPARK 合作者归档核对其排序计算。当前五窗预测使用上文所列的公开文献输入。 |
| [Adoption/run.py](../Polymer_Adoption_Harness/run.py)、[controller.py](../Polymer_Adoption_Harness/controller.py) | `run.py` 默认转到当前排序入口，`--legacy` 选择较早的加分排序。`controller.py` 是该对照的 LLM 调用与分批决策。 |
| [Adoption/results.py](../Polymer_Adoption_Harness/results.py)、[verify_run.py](../Polymer_Adoption_Harness/verify_run.py) | 分别导出和核验早期对照。有同一批候选的旧运行时，当前评估器可加载其归档分数，与当前正式排序比较。 |
| [根目录 run.py](../run.py)、[配置加载器](../spe_agentic_harness/config.py) | 分发命令并为正式运行读取仓库根目录的 `.env`。`test-ranking` 分别运行数据层和排序层的离线测试。 |
| [早期仓库说明](../README-temporal.md) | 保留早期双窗版的目录、命令和输入格式，便于继续使用历史项目。 |
