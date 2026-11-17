# SPE Agentic Harness：材料发现与研究记忆

项目根目录管理共享模型配置、工具接口、知识存储和未来的 RSI。Curator 是当前已实现的文献知识提取模块。根目录 `.env` 的 `LLM_` 配置供各模块共用。

Agentic Curator 将固态聚合物电解质论文中的样品、配方、测试条件与电导率整理为带原文引用的结构化记录。模型根据当前记录和校验结果，选择继续检索、读取指定页面或结束任务，形成可追踪的多轮证据整理流程。

本项目的核心是**让证据缺口驱动下一步行动**：抽取结果中的缺失字段、引用问题和单位问题会反馈给模型，供其决定下一次工具调用。程序保存每轮决策、观察和结果，支持分析补查过程及其成本。

## 工作流

```text
论文正文 + 对应 SI
        ↓
逐页解析与初始检索
        ↓
生成样品记录 → 字段、引用与单位校验
        ↑                  ↓
更新证据 ← search / read_page / finish
                           ↓
                 结构化结果与完整轨迹
```

- `search`：按查询词与页面文本的词项重合程度检索相关页面。
- `read_page`：读取指定来源和页码。
- `finish`：结束抽取，保留当前记录和待核对项。

每个样品及测量条件使用独立记录。字段包括 `sample`、`polymer`、`salt`、`salt_ratio`、`solvent`、`temperature` 和 `conductivity`。已提取字段携带来源 ID、页码和原文引用；未知字段使用 `null`。

## 快速开始

使用 Python 3.10 或以上版本，在 PowerShell 中执行：

```powershell
Set-Location 'E:\学习\研究生\研一秋\To-ljh\spe_agentic_harness'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 1. 检查论文解析结果

选择一篇材料实验论文，将示例路径替换为实际路径：

```powershell
.\.venv\Scripts\python.exe curator.py --pdf 'E:\正文.pdf' 'E:\对应SI.pdf' --out outputs\paper01_index --index-only
```

此步骤在本地生成 `index.json`，无需 API。检查其中是否包含目标样品及性能数据。输入应为可提取文字的 PDF；当前读取文本层，每页最多提供 16000 个字符。扫描件和图像中的数据需先通过 OCR 或人工转录处理。

### 2. 配置模型接口

在项目根目录 `.env` 中填写配置（已创建模板）：

```dotenv
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
OPENALEX_API_KEY=
```

`curator.py` 和 `online.py` 启动时自动读取该文件，与终端所在目录无关。保存后重新运行程序即可。`.env` 已被 Git 忽略，分享配置请使用不含密钥的 `.env.example`。

格式为 `KEY=value`，支持整行注释及成对引号；值按字面读取，不展开变量，也不解析行尾注释。已有环境变量优先，命令行 `--model` 和 `--base-url` 再覆盖环境变量。

也可以在终端临时覆盖：

```powershell
$env:LLM_API_KEY = '你的密钥'
$env:LLM_BASE_URL = 'https://你的服务地址/v1'
$env:LLM_MODEL = '服务提供的模型ID'
```

接口需支持 `/chat/completions`、文本 JSON 响应，以及 `temperature` 和 `max_tokens` 参数。`LLM_BASE_URL` 填写供应商提供的 API 前缀，程序自动追加 `/chat/completions`。接口实现位于 `curator.py` 的 `Client` 类中。

### 3. 运行多轮抽取

```powershell
.\.venv\Scripts\python.exe curator.py --pdf 'E:\正文.pdf' 'E:\对应SI.pdf' --out outputs\paper01_agentic --max-calls 6 --max-output-tokens 5000
```

每次运行传入同一篇论文及其补充材料，并使用新的空输出目录。正文没有 SI 时，传入一个 PDF 即可。

| 参数 | 含义 | 默认值 |
|---|---|---|
| `--pdf` | 正文及对应 SI 的路径 | 必填 |
| `--out` | 本次运行的输出目录 | 必填 |
| `--max-calls` | 最多模型请求次数 | 6 |
| `--max-output-tokens` | 每次请求的生成长度上限 | 5000 |
| `--mode` | `agentic` 多轮决策或 `single` 单次抽取 | `agentic` |
| `--index-only` | 本地解析并导出页面文本 | 关闭 |
| `--model` | 模型 ID，可覆盖环境变量 | `LLM_MODEL` |
| `--base-url` | API 前缀，可覆盖环境变量 | `LLM_BASE_URL` |

模型请求会将论文文本发送给配置的服务。调用次数与输出长度控制计算规模，实际费用按供应商计费；请求用量保存在结果中。接口故障时程序报错，保留已写出的请求与轨迹，便于定位后重跑。

## 读取结果

| 文件 | 内容 | 用途 |
|---|---|---|
| `result.json` | 样品记录、归一化数值、校验问题、终止状态和用量 | 检查抽取结果 |
| `trace.json` | 每轮响应、动作、校验结果和用量 | 分析决策与补查过程 |
| `request_XX.json` | 每轮调用前的完整状态 | 回溯模型当时获得的证据 |

以下为字段结构示意，实际 `quote` 应逐字摘自对应页面：

```json
{
  "id": "sample-A-25C",
  "conductivity": {
    "value": 0.2,
    "unit": "mS/cm",
    "evidence": [
      {"source": "S1", "page": 3, "quote": "原文中的完整证据片段"}
    ]
  }
}
```

程序将电导率归一化为 `S/cm`，将温度归一化为摄氏度，保留原始值及单位。支持的电导率单位为 `S/cm`、`mS/cm`、`uS/cm`、`µS/cm`、`S/m`；温度单位为 `°C`、`C`、`degC`、`K`。

校验结果与记录一同保存：

- `finished`：模型结束任务，规则检查未发现问题。
- `finished_with_issues`：模型结束任务，并保留待补充或核对项。
- `budget_exhausted`：达到请求次数上限。
- `single_pass_complete`：完成单次抽取。

规则校验覆盖字段格式、原文引用存在性和单位转换。样品关联及引用对数值的语义支持通过人工标注或独立评测检查。`solvent: null` 表示溶剂信息未知。

## 对照实验

使用相同论文、模型及初始检索，运行单次抽取：

```powershell
.\.venv\Scripts\python.exe curator.py --pdf 'E:\正文.pdf' 'E:\对应SI.pdf' --out outputs\paper01_single --mode single
```

`single` 与 `agentic` 共用记录格式，便于比较多轮补查带来的变化。实验重点可设为样品—温度—电导率配对准确率、证据支持率、记录完整率，以及调用次数和 token 用量。两种模式的实际调用预算应随结果一起报告。

原始 SPARK 3R 作为独立基线运行。本目录集中提供文本证据抽取与轨迹记录；固定补查对照和样品级金标准评测是后续实验接入点。性能结论以实际测试集评测为依据。

## 文件与测试

```text
spe_agentic_harness/
├── curator.py          # PDF 解析、模型接口、工具、校验与决策循环
├── test_curator.py     # 本地行为测试
├── requirements.txt    # 运行依赖
├── README.md
└── outputs/            # 按运行分别保存结果
```

运行本地测试：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_curator.py
```

测试使用临时 PDF 和确定性模拟模型，覆盖检索反馈与停止、调用预算、单位转换、引用校验及异常记录处理。真实接口连通性和抽取质量通过配置模型后的论文运行验证。

## 在线发现：限定范围的跨领域检索

`online.py` 将主题检索、范围筛选、公开 PDF 获取和逐篇 Curator 抽取串联起来。默认检索范围定义在 `scope.json`，目标是为锂电池寻找具有可迁移离子输运机制的聚合物线索。

```text
限定主题 → OpenAlex 元数据 → 聚合物 + 传导证据或结构物性线索
                                      ↓
                         获取公开 PDF → 逐篇 Curator
```

默认查询覆盖已有 SPE 体系，以及配位基团、链段运动、玻璃化转变、自由体积和两性离子等结构物性线索。纳入有两条路径：

- `transport_evidence`：聚合物体系已有离子传导或电解质相关证据。
- `structure_hypothesis`：聚合物结构或物性提供可研究的迁移线索，即使原文没有讨论离子输运也可纳入。

结构命中是待验证假设，不能直接推出电导率或电池适用性。没有命中关键词的聚合物论文进入 `manual_review`，不因缺少离子输运词汇自动排除。综述作为背景保留。水凝胶、质子或钠离子体系还需核查载流子、含水量、盐含量、温度和成膜条件。

`include` 表示进入全文整理。`existing_battery_context` 与 `cross_domain_lead` 区分元数据中的电池背景，`suitability` 和 `novelty` 均保持 `not_assessed`，直到后续独立评价。当前规则是透明的元数据初筛，不是自动科学判定。

### 先检索和查看筛选依据

```powershell
python online.py --discover-spe --limit 5 --search-only --out outputs\spe_search01
```

`--limit` 为每组查询的候选上限。默认九组查询最多返回 45 条去重前记录，实际入选数取决于元数据和筛选条件。`search.json` 保存全部候选、命中词、纳入或排除理由、完整范围配置及检索时间。

OpenAlex 接口支持主题搜索和开放获取位置元数据，可通过 `OPENALEX_API_KEY` 环境变量传入个人服务密钥。接口额度和费用以 [OpenAlex 官方说明](https://help.openalex.org/api/authentication/)为准；程序不会将该密钥写入结果。

### 自动获取并抽取

配置前文的三个 `LLM_` 环境变量后执行：

```powershell
python online.py --discover-spe --limit 5 --max-calls 6 --max-total-calls 30 --out outputs\spe_extract01
```

- `--max-calls` 控制每篇论文的模型调用次数。
- `--max-total-calls` 控制整个批次的模型调用次数，失败请求也计入。
- `--download-only` 执行检索、范围筛选和下载，不调用大模型。
- `--year-from 2020` 将检索起始年份限定为 2020 年。
- `--scope-file 自定义配置.json` 使用独立的主题与范围配置。

每篇论文单独形成 `paper_001/result.json` 等结果，`batch.json` 汇总下载失败、抽取失败、预算耗尽及成功完成的记录。每篇最多尝试三个公开 PDF 地址；下载文件保存 SHA256、原始网址、最终网址与获取时间。模型输出保留文献 DOI 和标题来源。

当前全文获取使用 OpenAlex 返回的公开 PDF 地址。登录页面、网页正文和无法访问的 PDF 会记录原因；不以摘要替代全文抽取。主题批处理获取正文，SI 可通过下面的直接链接入口配对补充。检索到的公开全文集合存在可访问性偏差，评测时应同时报告检索、入选和全文获取数量。

### 自定义主题及直接链接

自定义主题仍经过同一范围筛选：

```powershell
python online.py --topic 'polymerized ionic liquid ion transport decoupling' --limit 10 --out outputs\polyil01
```

正文与 SI 均有直接 PDF 地址时，可作为同一篇论文联合抽取。该入口按用户指定文献执行，不经过主题初筛：

```powershell
python online.py --url 'https://你的文献地址/paper.pdf' 'https://你的文献地址/si.pdf' --out outputs\linked_paper01
```

搜索接口依据：[OpenAlex search](https://help.openalex.org/api/searching/)、[locations](https://help.openalex.org/data/locations/)。`online.py` 的搜索与筛选属于确定性的前置流程；动态工具决策发生在每篇论文的 Curator 抽取阶段。

运行完整本地测试：

```powershell
python -m unittest -v test_curator.py test_online.py
```


## 统一 harness 工具接口

`harness.py` 提供与模型供应商无关的 `ResearchHarness`。上层 planner 决定调用顺序，harness 负责参数校验、工具执行、证据状态、预算和事件记录。

### 简单总控 LLM

`planner.py` 已连接现有工具注册表。每轮将任务、工具定义、历史结果和剩余预算交给 LLM；LLM 返回 JSON action，由 `ResearchHarness.execute()` 执行，再把结果送入下一轮。这里使用 JSON action 协议，尚未采用供应商原生 `tool_calls` 协议。

在 `spe_agentic_harness` 目录运行（每次使用新的输出目录）：

```powershell
python planner.py --task "搜索与固态聚合物电解质相关的论文，筛选后尝试下载并抽取一篇可访问的论文，说明材料信息与缺失字段。遇到403换其他来源或论文。" --out outputs/planner01 --max-steps 12 --max-model-calls 16
```

总控和 Curator 共用 `.env` 的 `LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`；`--max-model-calls` 同时计入总控和内部抽取调用。默认跨次记忆保存在 `outputs/memory/knowledge.sqlite`，用 `--project` 隔离项目，也可通过 `--knowledge-db` 指定数据库。

输出包括 `planner_result.json`（结束状态与总结）、`planner_trace.jsonl`（每轮决策和反馈）、`events.jsonl`（工具执行）、`extraction_*/result.json`（实际抽取结果）。`finished` 表示模型提交了总结，是否完成研究目标仍需检查总结和抽取结果；预算耗尽、步数耗尽和请求失败分别保存独立状态。当前保留完整历史，适合短任务；长任务后续需要上下文压缩。性质工具已注册，实际能力见下文。设计和 RSI 仍是接口设计。

### 直接返回结果的电导率工具

总控可调用 `get_property_capabilities()`、`predict_conductivity(candidate, method, transport)` 和 `query_property_results(text)`。无需新增依赖、修改 `.env` 或安装本地模拟软件。工具执行成功后，计算记录保存到同一个 SQLite 的 `property_results` 表，与文献实测/抽取记录分开，通过项目隔离，保留完整输入和来源。

| method | 当前能力 |
| --- | --- |
| `nernst_einstein` | 已可运行。利用已有扩散系数、各离子摩尔浓度和温度计算电导率，返回 S/cm 和 log10 值。 |
| `remote_ml` | 直接请求远程回归服务的适配器已实现，尚未连接经过确认的聚合物预测服务。默认返回 unavailable，数值为空。 |
| `remote_md` | 共用远程结果接口，尚未连接 PEMD/GROMACS 计算服务。不会在本机安装或启动模拟程序。 |

运行无需 LLM 的公式演示：

```powershell
python run_property_example.py
```

演示输入来自 `examples/transport_example.json`，全部为明确标注的人工测试数据，不能用作材料预测结论。NE 方法忽略离子运动关联，要求提供全部移动离子，并检查电中性。单离子聚合物体系可提供带符号的 `fixed_charge_mol_L`。输入扩散系数必须对应候选温度；来源仅记录，尚未自动核验。不能让 LLM 为得到数值而补造扩散系数。

`candidate` 必须包含 `name`、`temperature_K`、`input_origin` 和非空 `sources`。远程结构预测另外需要 `polymer_repeat_unit_smiles`、`salt`、`salt_concentration`（value/unit/basis）、`additives`。这些只是接口完整性检查，化学结构合法性、模型适用域和力场匹配必须由实际计算服务检查。

Agent 的调用形式：

```python
h.execute('get_property_capabilities', {})
h.execute('predict_conductivity', {
    'candidate': candidate,
    'method': 'remote_ml',
})
h.execute('query_property_results', {'text': candidate['name']})
```

调用者不管理任务队列或计算环境。只有实际部署了服务后，由集成代码向 `ResearchHarness(property_provider=...)` 注入服务客户端。`RemoteConductivityClient(endpoint, token=None)` 使用 HTTPS POST，默认超时 45 秒，无自动重试。endpoint 是我们约定的包装服务地址，不是 PEMD 官方现成 API。当前未部署该服务，也未验证远程计算端到端运行。

后端协议为 `conductivity.v1`：请求包含 `request_id`、`candidate`、`method`。服务直接返回 `status=completed`、原样的 `request_id`、`data_origin`（ml_prediction/md_simulation）、`conductivity`（value/unit/temperature_K）、`model_version`、`calculation_method`、`applicability`（in_domain/out_of_domain/unknown），可选 uncertainty。MD 还必须提供布尔 `converged`。单位支持 S/cm、S/m、mS/cm，入库时统一为 S/cm；uncertainty 原样保留，后端需自带单位、区间定义与校准说明。超时、未完成或结果归属不匹配均不会产生成功预测记录。

远程 MD 长任务后续应由计算服务负责队列、缓存和恢复。当前客户端只接受直接完成的结果，不会把运行中的任务假装成完成。用于高通量即时调用的第一选择是已部署的回归模型；MD 需要单独验证计算时长与服务协议。可参考 PEMD 的真实建模/计算接口：https://github.com/HouGroup/PEMD 。其开源包不自带本项目定义的 HTTP 服务。

### 材料计算工具接口与小测试

`simulation.py` 提供计算任务接口，`harness.py` 已注册为 agent tools。现在已接通项目内独立运行的真实 xTB 引擎，用于 `calculate_coordination(engine="xtb")`。PEMD、GROMACS、LAMMPS、SEAMM、RadonPy、CP2K 和 Matlantis 仍未接通。

#### 已接通的真实 xTB 计算

官方便携版位于 `.runtime/xtb/xtb-6.7.1/bin/xtb.exe`。`harness.py` 自动发现它，无需修改 `.env`、系统 PATH 或激活新环境。执行时以参数列表调用程序，不执行模型生成的 shell 命令；只给计算子进程设置线程数和资源路径。

当前支持中性闭壳层片段（2–64 个原子）与单个 Li+ 的气相 GFN2-xTB 计算，元素限 H/Li/C/N/O/F/P/S/Cl。依次优化片段、计算孤立 Li+、优化复合物，返回电子结合能（kJ/mol）、各部分总能量、优化坐标及 Li 与配位原子的距离。结合能定义为 E(优化复合物) − E(优化片段) − E(Li+)。这个版本没有构象搜索、频率验证或热力学修正，不能把结果当成结合自由能或电导率。

真实测试直接运行：

```powershell
python run_xtb_example.py
```

该脚本构建二甲醚/Li+ 初始几何，通过 agent 工具执行真实计算。结果位于 `outputs/xtb_real_时间/真实计算说明.txt` 和 `result.json`，`xtb_calculations` 保留三个计算的原始输入、命令、输出日志、优化结构和版本信息。结果标记为 `quantum_calculation`，与下文人工测试后端的 `test_fixture` 区分。此示例代表局部醚基模型，不是完整聚合物电解质。

引擎来自官方发布页 https://github.com/grimme-lab/xtb/releases/tag/v6.7.1 ，使用其 Windows 6.7.1pre 便携包，已按官方 SHA256 文件核验，归档 SHA256 为 `043e578da4a7e114a4d584972959a875e3ffb9f2767a86723b95aa6719d28d9c`。下载来源和校验值保存在 `.runtime/xtb/installation.json`。`.runtime` 不纳入版本控制；迁移项目时需要一并复制该目录或使用 `python install_xtb.py` 恢复引擎。

| 工具 | 输入 | 返回 |
| --- | --- | --- |
| `get_simulation_capabilities` | 无 | 各任务/引擎是否连接，是否测试后端 |
| `prepare_simulation_input` | candidate、可选 assumptions | 缺失字段、显式假设、schema_ready/needs_input、record_id |
| `simulate_electrolyte` | prepared_id、engine | 模拟记录、轨迹引用、温度、方法、收敛状态 |
| `analyze_ion_transport` | simulation_id、engine | 电导率/扩散等命名指标、单位和来源 |
| `calculate_coordination` | system、engine | 局部片段与离子的相互作用指标，不直接等同于体相电导率 |
| `calculate_polymer_properties` | prepared_id、engine、properties | 密度、Tg、模量、热容中所请求的性质 |
| `get_simulation_record` | record_id | 本项目保存的输入或计算记录，包括来源和父记录 |

所有工具通过 `h.execute(name, arguments)` 使用。`status=ok` 表示函数调用成功，业务结果还需读取 `data.status`。当前注册工具共 20 个。

准备输入至少包含 `name`、`polymer_repeat_unit_smiles`、`architecture`、`chain_length`、`end_groups:{left,right}`、`salt`、`salt_concentration:{value,unit,basis}`、`temperature_K`、`additives`、`material_state`、`input_origin` 和 `sources`。`chain_length` 为模型聚合度。添加剂格式为 `{name,amount:{value,unit,basis}}`，空列表表示明确不添加，不能代替未知。缺失的链长、端基、材料状态等可通过 `assumptions` 显式补充，每项须有 `{value,reason}`。工具禁止假设覆盖已有值，也不自动猜测聚合物结构。

`schema_ready` 仅表示本接口需要的字段齐全。远程服务仍需验证 SMILES、连接位点、力场适用范围、配方与粒子数换算、材料相态及拓扑。共聚序列、交联网络、填料界面等更复杂信息可作为候选附加字段传递，必须由后端确认支持。当前准备工具不生成原子坐标、力场文件或引擎专有输入文件。

配位接口的 `system.fragment` 和 `system.ion` 分别需要 `symbols`、`positions_angstrom`、`charge`、`multiplicity`。还需 `input_origin`、`sources`。坐标使用同一个参照系，后端负责构建复合物、优化并报告能量定义。不能根据一个结合能直接判定电导率优劣。

无需 API key 或新增依赖的小测试：

```powershell
python run_simulation_smoke.py
python -m unittest discover -p "test_*.py" -v
```

小测试输出到 `outputs/simulation_smoke_时间/测试说明.txt` 和 `results.json`。实际运行输入校验、公式计算和持久化；完整模拟接口通过显式注入的人工测试后端验证。人工结果标为 `test_fixture`，不能用于材料排名，测试后端不会自动进入真实 Planner。

计算服务接入协议（供后续后端实现）为 `simulation.v1`。由集成代码注入 `ResearchHarness(simulation_provider=provider)`，provider 提供 `supported_pairs` 和 `run(request)`。已有 HTTPS 客户端 `RemoteSimulationClient`，接受服务 endpoint、已验证的 task/engine 组合及可选 token，调用者无需安装模拟程序。该协议是本项目接口，不是各工具厂商现成的 API。

请求含 `request_id/task/engine/payload`。完成响应必须原样返回前三项，并包含 `status=completed`、`data_origin`、`engine_version`、`method`、布尔 `converged`。体系模拟还需 `trajectory_ref` 和匹配的 `temperature_K`。性质分析需 `metrics:{指标名:{value,unit}}`，与配方绑定的结果也须匹配温度。所有输入和返回记录以哈希 ID 保存到同一个知识库的 `simulation_records` 表，带 project 和 parent_id，保持与文献记录分离。

未连接服务返回 unavailable，输入不齐返回 needs_input，未收敛模拟不进入输运分析。长任务没有完成时返回 not_completed；当前不提供后台恢复或轮询，不自动重复提交。该接口能直接接收已完成结果，并不承诺长时间 MD 在一次 HTTP 超时窗口内结束。模拟结果仍需独立科学复核，当前统一标记为 unreviewed_computation、eligible_for_ranking=false。

### harness.py 阅读顺序

| 部分 | 职责 |
| --- | --- |
| `spec()` 与 `TOOLS` | 定义工具名称、描述和输入 schema；是模型看到的工具目录。 |
| `check_args()` | 检查参数是否缺失、是否多传以及基础类型；并非完整 JSON Schema 校验器。 |
| `ResearchHarness.__init__()` | 建立输出目录、知识库、范围配置、预算，以及本轮 PDF 和已读证据状态。 |
| `definitions()` | 返回工具定义副本，供总控使用。 |
| `execute()` | 统一入口：检查预算和参数、分发执行、捕获错误、返回结构化结果并追加事件日志。 |
| `_dispatch()` | 将工具名映射到搜索、下载、读取、抽取和知识查询的实际函数；新增工具要同时补定义和分发。 |
| `_dispatch()` 的抽取分支 | 调用 Curator 子循环，统计内部 LLM 调用，并保存知识快照与来源。 |

`corpora` 和 `observed` 是本轮内存状态；SQLite 保存跨次抽取记忆。工具返回 `status=ok` 只表示执行完成，抽取质量需要查看内部 `result.status`、`issues` 和证据。`planner.py` 负责决定下一步，`harness.py` 负责执行与约束。

| 工具 | 输入 | 主要输出 |
|---|---|---|
| `search_literature` | `query`, `limit` | 文献元数据列表 |
| `screen_candidates` | `papers` | 筛选依据、纳入路径、待验证状态 |
| `fetch_pdf` | `url` | 本地 PDF 路径、来源信息 |
| `open_corpus` | `paths`：同一篇正文及 SI | `corpus_id`、来源与页数 |
| `search_evidence` | `corpus_id`, `query` | 页面证据 |
| `read_evidence` | `corpus_id`, `source`, `page` | 指定页面证据 |
| `validate_records` | `corpus_id`, `records` | 校验问题和单位归一化结果 |
| `extract_records` | `corpus_id`, `max_calls` | 完整抽取结果及文件路径 |

在本目录中导入使用：

```python
from harness import ResearchHarness

h = ResearchHarness("outputs/harness01", max_tool_calls=50, max_model_calls=30)
# definitions() 返回 function-calling 风格的工具描述和 JSON Schema。
tool_definitions = h.definitions()

search = h.execute("search_literature", {
    "query": "polymer free volume frustrated packing", "limit": 5
})
if search["status"] == "ok":
    screened = h.execute("screen_candidates", {"papers": search["data"]["papers"]})
    # planner 读取筛选依据，再选择下载、改写查询或保留待核查。
```

调用抽取工具时，通过构造参数传入模型客户端：

```python
import os
from config import load_env
from curator import Client
from harness import ResearchHarness

load_env()
client = Client(os.environ["LLM_MODEL"], os.environ["LLM_BASE_URL"], 5000)
h = ResearchHarness("outputs/harness02", client=client, max_model_calls=30)
opened = h.execute("open_corpus", {"paths": [r"E:\正文.pdf", r"E:\对应SI.pdf"]})
if opened["status"] == "ok":
    result = h.execute("extract_records", {
        "corpus_id": opened["data"]["corpus_id"], "max_calls": 6
    })
```

每个返回值统一包含 `tool`、`status`、`data`、`error`、`usage`。`events.jsonl` 保存输入、输出、错误、耗时及累计调用次数，运行目录保存范围配置快照和抽取产物。失败工具调用也消耗工具预算，失败模型请求消耗模型预算。

上层 planner 可逐个调用检索与读页工具，自行维护抽取记录；也可调用 `extract_records` 委托 Curator 完成内部循环。`validate_records` 使用本 harness 已通过 `search_evidence/read_evidence` 观察的页面；委托抽取有自己的证据与校验轨迹。当前共享预算覆盖工具及 Curator 请求，上层 planner 自身的模型费用由接入方另行统计。CLI `online.py` 和 harness 复用同一组底层函数，CLI 是固定批处理入口，harness 是可编排接口。

完整测试：

```powershell
python -m unittest -v test_curator.py test_online.py test_harness.py
```

## 真实 MD 扩散系数工具

`run_diffusion_benchmark` 通过独立 Python 3.11.9 调用 OpenMM 8.6.1，完成建模、能量最小化、20 ps 平衡、生产轨迹和多时间起点 MSD 分析。当前支持 **300 K 的 LiCl 水溶液基准体系**，用于验证真实计算链路。聚合物候选仍需提供并验证专用结构与力场，不能用此水溶液结果替代。

在项目根目录运行：

```powershell
python spe_agentic_harness/run_diffusion_example.py
```

Agent 调用：`harness.execute('run_diffusion_benchmark', {'production_ps': 100, 'seed': 2026})`。生产长度支持 20–500 ps，使用 CPU 两线程，不调用 LLM、不消耗 API 额度。引擎在子进程中执行，最长 30 分钟；失败保留错误类别、退出码和日志。工具自动使用项目内独立解释器，避免本机 Anaconda 在 OpenMM 创建 Context 时出现的原生崩溃。新机器可先运行 `python spe_agentic_harness/install_openmm.py` 安装项目内运行时。

输出目录保存 `trajectory.npz`（连续坐标 nm、时间 ps、盒长、元素）、`initial.pdb`、`system.xml`、`integrator.xml`、`final_state.xml`、热力学日志，以及 Li/Cl 各自的 MSD CSV。`result.json` 保存拟合区间、斜率、R²、log–log 指数、初步扩散系数和轨迹哈希。工具结果写入 simulation_records，可通过 `get_simulation_record` 取回。

计算使用三维 Einstein 关系 `D = slope(MSD)/6`，同时完成 nm²/ps → m²/s 单位转换。单次短轨迹只返回 `preliminary_D_m2_s`；`accepted_D_m2_s=null`、`converged=false`、`eligible_for_ranking=false`。线性拟合良好不等于采样收敛，正式筛选需要平衡检查、长轨迹及独立重复。

## 持久知识与 RSI 接口

整体设计、数据库结构、跨运行共享示例和 RSI 版本准入流程见 [ARCHITECTURE.md](ARCHITECTURE.md)。harness 的 extract_records 现已自动保存 SQLite 快照，支持 query_knowledge 和 get_knowledge_snapshot。设计、推荐、实验和 RSI 目前为 contracts.py 中的接口定义。

## 下载失败记录

所有 PDF 下载尝试追加到 `downloads/download_events.jsonl`；失败记录包含 `url`、`resolved_url`、`http_status`、`error_category`、`stage`、`retryable`、`next_action` 和时间。`resolved_url` 仅在服务器返回该信息时保存。403 标记为 `access_denied`，不推断具体拒绝原因。

批处理同时在 `batch.json` 的 `attempts` 中保存结构化错误；harness 的 `fetch_pdf` 返回相同错误结构并写入事件日志。直接 `--url` 入口生成 `download_report.json`。只要指定的正文或 SI 有一个下载失败，就以退出码 2 停止，不将缺失 SI 的结果当作完整抽取。

`retryable` 和 `next_action` 是后续处理提示，当前没有新增自动 DOI 替代源搜索或自动重试。403 建议寻找替代来源或人工下载；429、超时及服务器错误可在后续调度中退避重试。文本解析失败与下载失败分别记录。

## 按成功篇数补足候选

```powershell
python online.py --topic 'polymer electrolyte molecular dynamics' --target 3 --limit 5 --max-candidates 30 --max-total-calls 18 --out outputs\target_run01
```

`--target` 为成功处理的目标篇数。失败后保留记录并继续下一篇，候选不足时扩大查询结果窗口，按 DOI/文献 ID 去重；同批次的相同网址只尝试一次，同内容 PDF 不重复计数。除索引提供的多个开放 PDF 地址外，还支持从 arXiv 开放摘要地址构造 PDF 地址。当前仍以 OpenAlex 为检索源，并非全网搜索。

`--download-only` 时，成功表示下载且文本可解析；抽取模式成功要求至少有一条具有聚合物信息、来源引用且通过非缺失项规则检查的记录。缺失电导率不会自动淘汰跨领域材料。成功是工程验收条件，不是人工核验准确率。没有有效记录或有校验问题的结果保留为 `extraction_needs_review`。

达到成功篇数、候选总预算或模型调用预算时停止。`batch.json` 包含 `successful_papers`、`target`、`stop_reason`；无法凑足时如实报告缺口，不保证在开放全文不足时一定达到目标。新运行使用新目录；当前不跨运行自动重用失败缓存。
