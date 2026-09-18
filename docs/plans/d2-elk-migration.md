# D2 + ELK 迁移规划

日期：2026-09-10。状态：首版已实施并完成本地验证。下文保留批准时的设计快照（第 10 节为规划时的验证记录）；当前实现与验证结果见 [实施验收记录](../validation/d2-elk.md)，实际命令见 [README](../../README.md)。

## 1. 目标与决策

将日常使用入口切换为 **迁移 SQL + 外键配置 → D2 源文件 → D2 内置 ELK → SVG**。保留 draw.io 导出、关系提取、差异比较以及旧脚本的调用能力，作为显式选择的兼容功能。

推荐首版交付 `.d2 + .svg`：前者适合审查、版本管理和重新生成，后者用于浏览器查看和文档展示。仅生成 `.d2` 时不要求安装 D2 可执行文件；要求渲染时必须成功使用 ELK，失败返回非零，不自动切到 draw.io、Dagre 或旧网格布局。

D2 定义图的内容，ELK 负责布局与连线路由。项目直接调用 D2 CLI 的 `--layout elk`；无需额外搭建 ELK 服务、引入 Java/Node 服务或自行计算一套坐标。本机 D2 0.7.1 的 `d2 layout elk` 已确认 ELK 内置。D2 官方确认 `sql_table` 支持列级连接和 PK/FK/UNQ 标记，ELK 能把连接定位到对应行。[SQL Tables](https://d2lang.com/tour/sql-tables/)、[ELK](https://d2lang.com/tour/elk/)

首版范围：

- 复用当前 Schema、SQL 解析和 YAML 外键能力，新增 D2 输出与 SVG 渲染。
- 修复本次实测发现、会影响两个输出后端的解析兼容问题。
- 保留类型展示、主键、外键、索引说明、自引用和可明确配对的复合外键。
- 新入口默认 D2 + ELK；旧入口继续输出 draw.io。
- 补齐测试、Makefile、依赖版本基线和迁移文档。

后续按实际需要扩展 PNG/PDF、按业务域拆图、主题预设和增量对比。首版不引入通用插件框架、任意 D2 反向解析器或新的完整图模型。

## 2. 当前代码与实测风险

### 2.1 可以复用的结构

| 现有位置 | 当前职责 | 迁移策略 |
| --- | --- | --- |
| `erd_generator/schema.py` | `Schema`、`Table`、`Column`、`ForeignKey`、`Index`，约束说明 | 继续作为共同数据契约，不添加 D2 坐标或样式字段 |
| `erd_generator/sql_parser.py` | 按迁移文件构建 Schema，收集解析失败 | 修复已验证的兼容问题；渲染迁移阶段不重写 SQL 解析器 |
| `erd_generator/fk_config.py` | YAML 外键加载、名称查找、关系注入 | 继续复用；新路径需要能收集配置应用阶段的诊断 |
| `erd_generator/cli.py` | 当前只编排 draw.io 生成 | 提取共同加载步骤，按入口默认值选择后端 |
| `erd_generator/drawio.py` | Schema → draw.io XML | 保留公开函数、输出语义和调用方式 |
| `erd_generator/layout.py` | NetworkX、grid/Graphviz、坐标和备注高度 | 留作 draw.io 专用布局；D2 分支不调用 |
| `erd_generator/drawio_parser.py`、`schema_diff.py` | 解析、比较既有 draw.io 文档 | 保持兼容工具职责，不用于校验 D2 |
| `gen_drawio_erd_table.py` | 旧命令入口 | 保留原命令和参数的默认行为 |

当前没有项目 Makefile、自动测试目录或 CI 配置；`requirements.txt` 的四个直接依赖均未锁版本。

`erd_generator/__init__.py` 虽然声明了延迟加载，但同时直接导入 `cli`、`drawio` 和 `sql_parser`；`cli.py` 又在模块顶层导入 draw.io 和布局。因此只增加一个 `d2.py` 不足以让新路径脱离 NetworkX/draw.io，必须一起调整导入边界。

### 2.2 必须先处理的已复现问题

在仓库外的临时环境中，按现有 `requirements.txt` 安装得到：Python 3.14.0、sqlglot 30.18.0、NetworkX 3.6.1、PyYAML 6.0.3、pydot 4.0.1。运行仓库样例迁移和 `sample_fk_config.yaml`：

- 旧 CLI 退出码为 0，报告 0 条解析失败，成功写出 draw.io。
- 实际 Schema 有 6 张表、26 列、5 个外键、8 个索引。
- `DROP TABLE demo_library.temp_audit` 未生效。
- `DROP COLUMN last_login` 和 `DROP COLUMN order_label` 未生效。
- 已删除的索引仍残留。

独立最小样例也复现了 DROP TABLE、DROP COLUMN、DROP INDEX 无效。进一步检查发现：当前 sqlglot 的 DROP 目标存储已改变，目标不再位于现有实现读取的 `statement.this` / `action.this`；例如 DROP TABLE 的目标位于 `args['tables']`，`this` 为 `None`。

**处理顺序：先写失败测试，适配已验证的 AST 结构，再锁定通过测试的依赖版本。** 不把上述错误结果保存成正确性金标准，也不以“新旧图一致”代替迁移语义正确。修复会同时改善旧 draw.io 和新 D2 的内容，作为独立变更说明。

另外两项既有边界需要纳入测试和真实迁移验收：

- 文件目前按路径字符串排序；`V10` / `V2` 这样的版本名可能顺序错误。若实际输入包含这种命名，应单独明确并修复迁移排序契约。
- YAML 名称匹配会按未限定的表名后缀取第一个结果；多 schema 同名表可能匹配错误。新路径应报告歧义并要求明确表名，不能靠 ELK 解决。

这两项不与布局代码混做一次大重构。

## 3. 最小设计快照

### 3.1 依赖方向

```text
python -m erd_generator            gen_drawio_erd_table.py
    | 默认 D2                         | 默认 draw.io
    +-----------------+---------------+
                      v
              cli.py：参数与编排
                      |
        sql_parser.py + fk_config.py
                      |
               schema.py：Schema
                      |
            +---------+-------------------+
            |                             |
       D2 关系检查                    drawio.py
            |                             |
          d2.py                       layout.py
       纯文本生成                  grid / Graphviz
            |                             |
       schema.d2                    schema.drawio
            |
      d2_renderer.py（仅请求渲染时）
            |
       本地 D2 CLI --layout elk
            |
       schema.svg
```

Schema 和 SQL 解析层不依赖任何输出格式；D2 生成器不依赖 draw.io、NetworkX、Graphviz、文件写入或子进程。文件操作、超时和外部命令集中在编排与渲染边界。

### 3.2 文件与接口

| 位置 | 计划变化 | 依赖/验证重点 |
| --- | --- | --- |
| `erd_generator/__main__.py`，新增 | 提供 `python -m erd_generator`，显式传入 D2 默认后端 | 新入口默认生成 D2；不增加根目录工具脚本 |
| `erd_generator/cli.py` | 共用参数、Schema 加载、后端选择、输出路径检查 | 旧命令默认值、非法参数组合、退出码 |
| `erd_generator/__init__.py` | 实际执行延迟导入；可导出 `build_d2` | 保留现有公开名称；新路径不导入 NetworkX |
| `erd_generator/d2.py`，新增 | Schema → D2 文本、标识符转义、约束展示、稳定排序 | 纯函数，不修改输入 Schema |
| `erd_generator/d2_renderer.py`，新增 | D2 检查、ELK 调用、超时、SVG 输出 | 不处理 SQL 或修改关系 |
| `erd_generator/validation.py`，新增 | 检查图中引用的表/列、复合外键对应关系 | 只依赖 Schema，返回显式诊断 |
| `sql_parser.py`、`fk_config.py` | AST 兼容修复，向新流程显式传递诊断 | 不再让新流程依赖上一轮的全局错误状态 |
| `requirements.txt`、`requirements-dev.txt` | 锁定测试基线；开发依赖加入 pytest/静态检查工具 | 原安装入口仍可获得 draw.io 所需依赖 |
| `Makefile`、`.gitignore` | 统一构建、生成、测试入口，隔离生成物与缓存 | 不删除既有日志或用户文件 |
| `README.md` | 更新首页、安装、使用、结构、限制和回退说明 | 主示例 D2，兼容章节 draw.io |

建议核心接口如下；这是待实现契约：

```python
build_d2(schema: Schema, *, show_types: bool = False,
         direction: str = "right") -> str

render_d2(source_path: Path, output_path: Path,
          config: D2RenderConfig) -> None
```

`D2RenderConfig` 仅包含首版需要的可执行文件路径、渲染超时和展示选项；ELK 是该后端的固定布局要求。不做运行时插件发现或通用 renderer 继承树。

现有 `main()` / `build_parser()` 的默认调用仍保留 draw.io 兼容行为；新模块入口通过显式的入口默认参数启用 D2，避免顺带改变已有 Python 调用者。CLI 对未指定的布局按后端选默认值：D2 为 elk，draw.io 为 grid。新增辅助开发脚本若确有需要，放在 `scripts/`；既有根目录兼容入口保留。

现有 `load_schema_from_migrations()` / `get_last_parse_failures()` 保留为兼容接口。内部增加返回本次 Schema 与诊断的加载结果，新入口直接消费本次结果；旧接口可继续维护历史调用约定。新代码不增加共享可变全局状态。

首轮不搬动现有 draw.io 文件；先拆开导入和编排。未来确有多个新后端时再考虑目录重组。

### 3.3 不变量

- SQL/YAML 决定表、列和关系，ELK 只决定展示位置。
- 两个后端读取同一份解析结果，不互相转换产物。
- 外键方向始终为引用列 → 被引用列；图中的布局方向不能改变语义。
- 相同 Schema、配置、生成器版本产生相同 `.d2` 文本。表/关系稳定排序，列保留 Schema 中的声明顺序。
- 文本中不写入本轮时间戳、临时路径或随机 ID。
- SVG 外观由 D2/ELK 版本、字体、配置共同影响；不承诺跨版本像素不变。
- D2 路径不调用旧布局，不静默补出数据库中不存在的对象。

## 4. D2 内容映射与兼容边界

| Schema 内容 | D2 方案 | 边界 |
| --- | --- | --- |
| 表 | `shape: sql_table` | 首版平铺，用完整限定表名区分 schema |
| 字段和类型 | 每列一行；保留 `--show-types` | 关闭类型时仍保留字段与连线 |
| 主键 / 外键列 | `constraint: primary_key / foreign_key`；重合时用数组 | 复合主键可以标记各参与列，但整体约束保留在说明中 |
| 单列无条件唯一约束 | `constraint: unique` | 不把复合 UNIQUE、条件唯一索引、表达式唯一索引误标为每列独立唯一 |
| 外键 | `"demo_library.loan_requests"."user_id" -> "demo_library.members"."id"` | 按实际列连接，处理去重与自引用 |
| 复合外键 | 按声明顺序逐对连接，并以相同约束标识关联 | 不把多条线描述成多个独立约束；重复声明只画一组 |
| 索引/完整约束说明 | 复用 Schema 的说明能力，放入表 tooltip | 对已有说明缺失的索引名称/方法等字段，直接从 Index 补充，不能从 draw.io XML 回读 |
| 共享静态说明 | SVG 可显式开启 `--force-appendix` | 表下固定备注改为 tooltip/附录，是需要记录的展示变化 |

完整限定名应作为一个被转义的 D2 键，例如 `"demo_library.members"`；裸写 `demo_library.members` 会带入 D2 路径层级语义。标识符和文本值使用专门的 D2 转义函数，覆盖引号、反斜杠、换行、保留字、`${...}`、Unicode 和点号；不能直接拼接 SQL 原文，也不能假设 JSON 转义完全等价于 D2。[Strings](https://d2lang.com/tour/strings/)、[Variables & Substitutions](https://d2lang.com/tour/vars/)

外键的特殊情况：

- 两侧字段明确且数量一致：按 tuple 顺序配对。
- SQL 省略引用列且目标只有一个主键列：可按 SQL 语义解析为该列，并写明诊断/解析规则。
- SQL 省略复合主键的引用列：当前 `primary_key` 是 set，无法可靠恢复声明顺序。首版应明确报不支持，不能排序后猜连线；若实际迁移依赖此语法，先单独增加有序主键元数据及回归测试。
- 引用表/列缺失、字段数量不匹配或表名歧义：新路径返回可定位的错误，生成前阻止隐式创建假节点。旧 draw.io 的历史容错方式保留在兼容入口。
- 本期不承诺乌鸦脚基数：现有模型不足以无歧义表达所有 cardinality，普通字段级箭头最稳妥。

## 5. 布局与产物约定

默认全局 `direction: right`，D2 文件写入 `vars.d2-config.layout-engine: elk`；项目渲染调用仍显式传入 `--layout elk`，防止环境变量覆盖源文件配置。D2 官方说明命令行/环境配置优先于文件变量。[配置优先级](https://d2lang.com/tour/vars/)

ELK 有层次布局约束，也可能产生多余折线；不能承诺任意大图完全没有交叉，或按旧网格的绝对坐标摆放。`--per-row` 与 `--graphviz-*` 仅属于 draw.io，新 D2 分支收到这些参数应报错。[布局限制](https://d2lang.com/tour/layouts/)、[ELK 特性与限制](https://d2lang.com/tour/elk/)

首版先用 D2 已暴露的默认 ELK 配置。若样例需要调距，仅映射固定 D2 版本真实支持的选项。本机 0.7.1 暴露 algorithm、nodeNodeBetweenLayers、padding、edgeNodeBetweenLayers、nodeSelfLoop；不能把 Eclipse ELK 文档中的全部参数直接当作 D2 CLI 支持项。

生成物放在 `generated/`，由命令重新生成；测试金标准放在 `tests/fixtures/`。人工调整应修改 SQL/FK 配置或生成器展示参数，避免手改会被覆盖的生成文件。是否提交团队真实 `.d2` 由其仓库的文档管理方式决定；本项目默认不提交每次运行的 SVG 与日志。

SVG 是首版渲染格式，主要验收环境为浏览器。PNG 需要额外的浏览器运行依赖，PDF 也依赖 PNG 导出流程，因此列为后续功能。[D2 Exports](https://d2lang.com/tour/exports/)

## 6. 计划中的命令与开发入口

以下新命令目前尚未实现。

```bash
# 新主入口：生成 D2 源文件，并通过 ELK 生成同名 SVG
python3 -m erd_generator \
  --migrations ./db/migration \
  --out ./generated/schema.d2 \
  --render svg \
  --show-types \
  --fk-config sample_fk_config.yaml

# 只生成源码：省略 --render；不启动 D2 进程
python3 -m erd_generator \
  --migrations ./db/migration \
  --out ./generated/schema.d2 \
  --fk-config sample_fk_config.yaml

# 兼容入口：旧参数、旧默认输出格式仍然有效
python3 gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./generated/schema.drawio \
  --show-types --layout grid \
  --fk-config sample_fk_config.yaml

# 通用入口显式选择 draw.io
python3 -m erd_generator \
  --format drawio \
  --migrations ./db/migration \
  --out ./generated/schema.drawio
```

参数规则：新入口默认 `--format d2`；`.d2` 为源文件输出，`--render svg` 生成同目录同 stem 的 `.svg`。格式与扩展名矛盾时直接提示，不猜测。`--render` 仅适用于 D2；对 draw.io 指定 `--layout elk` 同样报错。

| 计划命令 | 含义 |
| --- | --- |
| `make build` | 编译/检查 Python 源码可加载；不访问数据库 |
| `make gen` | 使用样例 SQL/YAML 生成 `generated/schema.d2` |
| `make run` | 运行样例 D2 → ELK → SVG 全链路 |
| `make test` | Python 单元测试与快速集成，不要求本地 D2 |
| `make test-integration` | 使用固定版本 D2 做真实 SVG 渲染和旧 CLI 回归 |
| `make lint` / `make format` | 静态检查/格式化，范围在引入时明确 |

无数据库连接和数据库变更，因此不增加 migrate-up/down 或部署命令。

## 7. 失败处理与可观察性

| 情况 | 新 D2 入口行为 | 验证 |
| --- | --- | --- |
| 输入目录不存在/没有可解析表 | 非零退出，说明输入问题 | 临时空目录和不存在路径 |
| 检测到解析失败/非法 YAML/配置引用不明 | 诊断包含阶段、文件位置和对象；不得报告完整成功 | 显式失败样例；已被正确处理的兼容提示不当成失败 |
| 缺少 D2 可执行文件 | 源码模式可用；请求渲染则非零退出，提示依赖 | 隔离 PATH，模拟缺失二进制 |
| 没有 ELK 或版本不匹配 | 预检查失败，不更换布局 | 模拟 layout/version 输出；CI 固定版本 |
| D2 编译错误/超时 | 非零退出，包含版本、阶段、耗时、错误位置；保留可诊断源码 | 子进程失败/超时测试 |
| 输出不可写 | 明确文件写入错误 | 不可写目标测试 |
| SVG 已存在而新渲染失败 | 不覆盖旧 SVG；明确其未更新，不能把旧文件当本次成功结果 | 写入失败与残留文件场景 |
| 只安装核心解析依赖 | D2 生成不应导入旧布局依赖 | 独立进程阻断 NetworkX/pydot 导入 |

先完成 Schema/关系检查，再写入正式源码。渲染先写同目录临时 SVG，成功检查 SVG 文件后原子替换目标。`.d2` 与 `.svg` 是两个文件，不声称两者更新具有跨文件原子性；渲染失败必须清楚报告“源码已更新，图片未更新”，并以非零退出阻止流水线发布陈旧图片。

调用采用参数数组和子进程 timeout，不使用 shell 拼接、不依赖 sleep 同步。默认运行只读取本地文件，不上传到在线 Playground。日志记录后端、D2 版本、表/列/关系数量、耗时和结果；不直接倾倒全部 SQL、YAML 或数据内容。旧日志若保留 SQL 摘要，需要单独审查，不能因这次增加诊断而扩大输出范围。

严格检查只能约束已识别的失败；现有 SQL 子集仍需用明确的预期 Schema 验证，不能把“零诊断”当作完整 PostgreSQL 支持证明。

## 8. 实施顺序与回滚点

| 阶段 | 变更 | 验收出口 | 回滚 |
| --- | --- | --- | --- |
| P0：可信基线 | 为 DROP/ALTER/rename/FK 写测试；修复已复现的 sqlglot AST 兼容；锁定测试依赖；补基本 make 命令 | 样例不再残留被删对象，旧 draw.io 能生成，语义断言通过 | 独立提交；可撤回依赖/解析适配，不与渲染变更绑定 |
| P1：拆开依赖 | 调整 `__init__` 导入；整理公共加载和显式诊断；旧后端保持可用 | 旧入口/API 回归通过；Schema 导入不触发布局依赖 | 仅回滚导入/编排提交 |
| P2：D2 + ELK | 先写 D2/错误路径测试，再实现文本生成、关系检查、D2 运行器和新入口 | `.d2` 可验证，ELK 可渲染，字段与外键正确，失败不产生虚假成功 | 移除新入口/后端提交；旧脚本可继续显式使用 |
| P3：切换日常路径 | README/Makefile 主流程切换，固定 CI 的 D2 版本，做样例和代表性规模验收 | 默认路径为 D2；旧入口仍能运行；文档包含限制与回退 | 回滚默认工作流/文档即可，保留 D2 能力排查 |

各阶段独立验证、提交。流程遵循先拆边界、再适配行为、最后清理文档与无用连线的顺序；不一次性搬动所有文件。draw.io 回退由操作者显式调用兼容入口，符合“保留能力”的要求；程序不自动违反团队的日常输出选择。

依赖策略：先保留现有安装入口兼容，锁定经过测试的版本。D2 以本机已验证的 0.7.1 作为首轮验收候选，记录为测试基线而非宣称最新版；团队若指定其他版本，应重跑渲染验收。Python 支持范围按实际 CI 验证写明，不能仅凭 README 的 Python 3.9+ 声称全部组合受支持。拆分 NetworkX/pydot 为可选安装项可随后独立做。

## 9. 测试与完成条件

单元测试放在被测模块附近，例如 `erd_generator/test_d2.py`、`test_d2_renderer.py`、`test_validation.py`、`test_sql_parser.py`；CLI/真实渲染集成放在 `tests/integration/`，小型显式输入及金标准放在 `tests/fixtures/`。

| 测试组 | 必须覆盖 |
| --- | --- |
| 解析语义 | CREATE/ALTER/DROP、表列重命名、索引删除、FK 随重命名更新；明确断言已删除对象消失 |
| 来源一致性 | 原生 FK、注释 FK、YAML FK；重复声明；未知/歧义配置；确保修改 Schema 时不丢列或约束 |
| D2 输出 | PK/FK 同列、无类型、自引用、循环、孤立表、复合键、无外键表、相同短名的跨 schema 表 |
| 文本边界 | 保留字、点号、空格、引号、反斜杠、`${...}`、非 ASCII 文本、空输入、超长名称 |
| 约束正确性 | 复合 UNIQUE、条件唯一索引、表达式索引不变成错误的单列 UNQ；完整说明保留 |
| 确定性 | 调整 Schema 字典插入顺序不改变 `.d2`；字段顺序保留；不依赖随机/时间信息 |
| 运行器 | 缺二进制、版本/ELK 不符合要求、超时、非零退出、写入失败、已有 SVG 保留 |
| 兼容 | 旧 CLI 参数、`build_drawio()`、公开导入、边提取和 comparator；grid 正常，Graphviz 原行为另行验证 |
| 端到端 | 预期 Schema → D2 文本金标准 → `d2 validate` → `d2 --layout elk` → SVG 有效并核对表/列标签 |

期望结果要来自明确的迁移语义和人工维护的小样本，不是把同一个解析结果在两个函数间来回比较。既有 draw.io comparator 不支持注入 `--fk-config`，不能直接把加了 YAML 关系的图与裸迁移比较后当作新后端验收依据。

布局还需人工检查浏览器展示：连线是否落在正确字段、标签是否被裁切、自引用和复合外键是否可读、tooltip/附录是否能获取索引说明。自动 SVG 有效性检查不能代替这一步。

规模验收先用仓库小样例，再用明确生成的 50/200 表测试输入，记录表数、列数、边数、耗时、峰值内存和输出尺寸；最终补团队代表性迁移样本。无业务规模数据前不承诺固定秒数或任意大图可读；只有实际验证不满足时才推进分域/过滤功能。

每个阶段至少运行 `make build && make test`；影响渲染时加 `make test-integration`，并运行适用的 lint/format 检查。CI 的渲染任务缺少 D2 应失败，不可跳过后仍宣称渲染验收通过。

最终完成条件：

1. 新入口和 README 的默认示例生成 D2 + ELK SVG。
2. 不依赖 draw.io 产物或旧坐标算法即可完成新流程。
3. 已删除对象不残留；表/列/外键/索引说明有明确语义断言。
4. 外键异常、D2 缺失/超时、输出失败均有可定位的失败结果。
5. 原 draw.io 命令、Python API、关系提取和差异比较仍可显式使用。
6. 测试、真实渲染、人工视觉验收和 README 更新全部完成后，才切换团队日常流程。

## 10. 本次规划已验证与未验证事项

已完成：

- 检查当前仓库的入口、模型、解析器、布局、渲染器和文档。
- 检查本机 D2 版本 0.7.1 及内置 ELK 的实际可用参数。
- 临时手写 D2 样例通过 `d2 validate` 并通过 `d2 --layout elk` 输出有效 SVG；覆盖五张表、自引用、两列复合 FK、孤立表、PK/FK 数组、带点号表/列名、保留字列 `shape`、tooltip。
- 解析该 SVG，核对五个表标签、特殊列名和 tooltip 内容存在。
- 在临时 Python 环境运行旧样例 CLI，成功生成 draw.io，并反查表与边数量。
- 对现有 12 个 Python 文件完成语法解析检查。
- 复现并定位新版 sqlglot 下 DROP 目标读取错误；没有修改运行代码。

未完成：新 D2 后端实现、自动回归测试套件、DROP 修复、团队真实迁移验证、大规模布局测量、浏览器视觉验收、PNG/PDF、Windows/其他 Python 版本验证。当前没有可执行的 `make build` / `make test`，不能据此宣称这些检查通过。

本次工作仅新增本规划文档；临时环境和实验产物位于仓库外，不改变项目安装环境或当前默认输出。
