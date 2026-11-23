# 用聚合物文献预测固态电解质材料

给定某一年已经发表的聚合物文献，哪些材料最有可能在随后五年首次被报道用于固态聚合物电解质（SPE）？本项目让大语言模型（LLM）查阅当时的文献、分别追踪骨架与离子角色，并查询 HPG 模型的配方电导率预测。每一窗先保存全体材料的排名，再打开后五年的 SPE 文献核验。合作者可以从榜单上的一个材料追到当时的证据、模型的比较和后来报道的实际样品。

**读代码从这里开始。** 仓库根目录的 `run.py` 负责分发命令，五个时间窗的推进、排名冻结和反馈更新都在 `Polymer_Agentic_Ranking_Harness/run.py` 的 `study()`。逐文件索引列出了主控、工具、知识图谱、HPG 推理和评估各自的输入、输出和入口。[命令入口](run.py) · [五窗主循环](Polymer_Agentic_Ranking_Harness/run.py) · [逐文件索引](Polymer_Agentic_Ranking_Harness/README.md)

## 当前版本的模块图

```mermaid
flowchart TD
    broad["跨领域聚合物文献<br/>Crossref 与 Europe PMC"] --> extr["corpus.py · extract.py<br/>按日期抽取材料、样品和原句"]
    extr --> graph["graph.py · evidence.py<br/>更新截至当年的材料知识图谱"]
    recipe["structures.py · physics.py<br/>重复单元、盐含量、温度"] --> hpg["hpg_worker.py<br/>计算配方电导率网格"]
    graph --> agent["agent.py · ordinal.py<br/>LLM 查文献、分轴查证、比较全体候选"]
    hpg -->|query_hpg| agent
    hpg -->|已有文献支持且配方达标| pool["adoption.py<br/>确定推荐池"]
    agent -->|附 DOI 的提名| pool
    agent -->|含并列的偏好顺序| rank["evidence_order.py · ranking_policy.py<br/>形成正式全榜和池内名次"]
    pool --> rank
    rank --> freeze["forecast.json<br/>冻结对后五年的预测"]
    freeze --> reveal["run.py · memory.py<br/>核验采用情况，保存案例和下窗取证问题"]
    spe["后五年的 SPE 主检索<br/>实际固态样品、材料角色与 DOI"] --> reveal
    reveal -->|进入下一窗| agent
    reveal -->|成为已知 SPE 应用| graph
    freeze --> eval["evaluate.py · audit.py<br/>比较基线、重建名次和证据"]
    independent["独立 SPE 检索<br/>五窗冻结后剔除重叠 DOI"] --> eval
```

## 每个时间窗怎样产生一张榜

| 步骤 | 输入 | 代码做什么 | 输出 |
| --- | --- | --- | --- |
| 1. 建立当窗图谱 | 2000–2024 年《Polymer Journal》题录和跨领域膜、涂层、支架等检索记录 | 按首次发表年份整理 DOI，用标题和可获得的摘要抽取材料名称、样品、角色及原句。材料骨架、有机阳离子、阴离子分别登记，可各自缺失 | 可回溯到 DOI 和原句的材料关系，以及当年可排序的全部候选 |
| 2. 计算可能的电导率 | 有登记重复单元的聚合物、LiTFSI 质量分数和温度 | 本地 HPG 图神经网络对干态设计配方推理。每种材料设聚合度 100，考察 10%、20%、30% 盐含量与 25、60 °C 的六种组合 | 配方级预测电导率（S/cm）、温度、盐含量和计算状态。对历史年份使用此公开模型属于回顾性估算 |
| 3. 确定推荐池 | 截至当年的文献、既往 SPE 样品、HPG 结果 | LLM 可凭已返回的 DOI 提名。材料当年已有来源且任一有效配方达到默认阈值 **10⁻⁴ S/cm**，程序即将它纳入推荐池 | 每项材料的入池途径及全部达标配方。未匹配 HPG 模板的材料仍可由文献提名 |
| 4. 排列全部候选 | 候选的文献证据、三个结构角色的历史类比、HPG、上一窗记忆 | LLM 分组比较、允许并列。默认 `exposure` 策略要求某材料在 DOI 篇数和最近发表年份上均不落后、且至少一项严格领先时排在对方前面。其余可选材料由 LLM 的偏好决定 | 无约束 LLM 名次、正式全榜名次、池内名次和比较记录 |
| 5. 验证并学习 | 冻结的榜单与随后五年的 SPE 专项文献 | 查找材料是否实际进入固态电解质样品、以什么角色出现。LLM 比较已观察到的案例和靠前但本次检索未观察到的案例，写下下一窗应查什么、怎样复核 | 带 DOI 的采用事件、复盘记录、跨窗取证记忆 |
| 6. 比较排序方法 | 各窗冻结排名、主检索和独立 SPE 检索 | 独立检索先排除与跨域及主检索重叠的 DOI。在同一候选集合上比较正式排序、自由 LLM、文献分层和频次／近期性基线 | 全榜、推荐池、首次观察到采用的材料、逐窗平均精度（AP）和前十命中指标 |

初始知识截至 **2004 年（含）**，此后依次推进至 **2009、2014、2019、2024 年**。例如，2014 年榜单用 2015–2019 年的 SPE 文献核验，这次核验形成的记忆可进入 2019 年预测。2024 年榜单面向 2025–2029 年，在本协议中保留为前瞻预测。“首次”指在相应检索语料中首次观察到该材料承担电解质样品角色。这里持续更新的是图谱和 LLM 下一窗使用的取证记忆，所用 LLM 和 HPG 权重固定。

## 运行

在仓库根目录执行。以下命令适用于 Python 3.11，PowerShell 中可直接运行。先检查排序、入池和跨窗反馈逻辑，这一步使用 Python 标准库。

```powershell
python run.py --help
python run.py test-ranking -v
```

**准备文献与 HPG。** `sources` 通过 Crossref 和 Europe PMC 下载题录与可用摘要，按检索式保存 40 份快照。已有快照可直接运行 `--check` 核验。重新向数据库检索会得到运行当日的索引，逐项重放历史实验需要该次保存的快照。

```powershell
python run.py sources
python run.py sources --check
python -m pip install -r Polymer_Adoption_Harness/requirements-hpg.txt
git clone --depth 1 https://github.com/spark8ku/HPG.git spark_agentic_harness/external_conductivity/HPG
python -c "from shutil import copyfile; copyfile('spark_agentic_harness/external_conductivity/HPG/ckpt/HPG_GAT.bin', 'SPARK_Motif_Transfer_Harness_v4/harness/hpg_vendor/HPG_GAT.bin')"
python run.py hpg-grid
```

程序校验两处 `HPG_GAT.bin` 的 SHA-256，然后生成 `Polymer_Adoption_Harness/data/physics/grid.json`。LLM 通过 `query_hpg` 读取当前窗可用的配方与数值。计算细节见[配方定义](Polymer_Adoption_Harness/physics.py)、[图编码与推理](SPARK_Motif_Transfer_Harness_v4/harness/hpg_worker.py)和 [HPG 上游项目](https://github.com/spark8ku/HPG)。

**配置模型并启动正式运行。** 将 `.env.example` 复制为根目录的 `.env`，填写 `LLM_API_KEY`、`LLM_MODEL` 和 `LLM_BASE_URL`。`LLM_MODEL` 填账号可用且支持原生工具调用的部署名。官方 DeepSeek 入口使用 `https://api.deepseek.com`。如采用 Paratera 排序，在同一文件填写 `PARATERA_API_KEY`。首次抽取文献仍会调用官方 DeepSeek，Paratera 负责提名、比较和复盘。已有进程环境变量优先。[配置模板](.env.example) · [配置加载器](spe_agentic_harness/config.py)

```powershell
# 首次建立本机配置
if (!(Test-Path .env)) { Copy-Item .env.example .env }

# 填写 .env 后，以下两种排序入口选一种运行
python run.py rank --ranking exposure --run-id study01 --workers 4
# 或采用 11 月 23 日实验所用服务与部署
python run.py rank-paratera --model DeepSeek-V4-Flash-0731 --workers 4
```

`--workers` 控制并发数。完整运行会调用远程 LLM。官方入口的示例结果写入 `Polymer_Agentic_Ranking_Harness/runs/study01/`。Paratera 入口按部署保存，本例运行标识为 `paratera_20261123/DeepSeek-V4-Flash-0731/exposure_primary`。同一协议可用原命令续跑，程序校验已冻结的文件。历史实验的逐项核验还需要当次抽取、HPG 网格、窗口记录和模型调用回执。

## 合作者怎样读结果

先看 `results/2024_first_adoption.csv` 获取前瞻推荐，再用 `rank-explain` 从材料名追到文献、HPG 和 LLM 比较，最后看 `results/metrics.csv` 比较方法。AP（平均精度）衡量后窗观察到采用的材料在榜单中排得有多靠前。比较时应使用相同的检索来源、预测窗口和候选集合。

```powershell
# 将 study01 换成要查看的运行标识
python run.py rank-explain --run-id study01 --year 2024 --pool
python run.py rank-explain --run-id study01 --year 2009 --material polyethylene
python run.py rank-audit --run-id study01 --check-only
python run.py rank-report --run-id study01
```

| 在一次运行目录中打开 | 可以回答 |
| --- | --- |
| `protocol.json`、`<年份>/graph.json` | 这一窗采用哪套代码、模型、HPG 网格和历史证据？ |
| `<年份>/forecast.json`、`<年份>/comparisons.json`、`<年份>/decisions/` | 材料排第几、为什么入池、LLM 比较过谁、有何依据？ |
| `<年份>/reveal.json` | 随后五年看到哪些真实样品？下一窗继承了哪些取证问题？ |
| `results/rankings.csv`、`results/observed_first_use_ranks.csv` | 每项材料的名次是多少？哪些 DOI 验证了首次采用？ |
| `results/metrics.csv`、`results/五窗排序对照.md` | 两种 SPE 检索下，各排序方法表现如何？ |

## 仓库导航

| 目录或文件 | 职责 |
| --- | --- |
| [Polymer_Agentic_Ranking_Harness/](Polymer_Agentic_Ranking_Harness/README.md) | **当前主流程。** 调度五窗、定义 LLM 工具、提交与冻结排序、跨窗记忆、评估与审计。 |
| [Polymer_Adoption_Harness/](Polymer_Adoption_Harness/) | 提供文献输入、证据抽取、材料识别、图谱、HPG 配方及推荐池准入。也保留早期加分排序作为对照。 |
| [SPARK_Motif_Transfer_Harness_v4/harness/](SPARK_Motif_Transfer_Harness_v4/harness/) | 当前使用的 HPG CPU 推理器、上游图编码器与通用存储工具。 |
| [temporal_harness/](temporal_harness/) | 早期双时间窗实现，通过 `python run.py temporal` 使用。[旧版用法](README-temporal.md) |
| [spe_agentic_harness/](spe_agentic_harness/README.md)、[spark_agentic_harness/](spark_agentic_harness/README.md) | 文献策展、PDF 处理、模拟工具及早期实验。根目录 `run.py` 也保留相应旧命令。 |

公开仓库包含源代码、配置样例、测试和 HPG 上游许可。文献快照、实验输出、模型回执、密钥及权重保存在本地。
