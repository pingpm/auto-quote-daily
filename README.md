# Auto-Quote Daily

独立的汽车托运 DMS 自动报价分析 skill，包含数据采集、指标计算、日报和周报看板、异常价差复核，以及 AI 运营分析提示词。运行时不依赖原来的 `order_analysis` 项目。

## 安装

需要 Python 3.10 或以上版本。私有仓库需要先使用有仓库访问权限的 GitHub 账号登录；仓库链接本身不会授予访问权限。

```bash
gh repo clone pingpm/auto-quote-daily
cd auto-quote-daily
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python scripts/install_skill.py
```

最后一个命令把 skill 安装到 `${CODEX_HOME:-~/.codex}/skills/auto-quote-daily`。已有同名 skill 时会停止，避免覆盖本地修改。其他 agent 支持 skill 时，可通过 `--skills-dir /path/to/skills` 指定目录；新会话才能发现新安装的 skill。使用 CLI 时需激活上述虚拟环境。

也可以让 Codex 的 `skill-installer` 从 GitHub 仓库根目录安装本 skill，然后在 Python 虚拟环境中运行 `python -m pip install /path/to/installed/auto-quote-daily`。安装 skill 指令与安装 Python 运行依赖是两个步骤。

Release 中的 ZIP 包可解压后按相同步骤安装；wheel 可用 `python -m pip install /path/to/auto_quote_daily-1.0.0-py3-none-any.whl` 安装 CLI，但仍需安装 ZIP 中的 skill 指令和 references。

## 本地授权

由有权限的用户在本机配置 `DMS_ACCESS_TOKEN` 环境变量，或写入用户专用的 `~/.config/auto-quote-daily/.env`。自定义 `XDG_CONFIG_HOME` 时使用其下的 `auto-quote-daily/.env`。配置文件权限设为 `600`，其中可以包含 `DMS_ACCESS_TOKEN` 和可选的 `DMS_BASE_URL`。

不要把真实 token 写入仓库、命令参数或报告。安装包不附带 token，也不自动获取登录凭据。首次拉数前执行：

```bash
auto-quote auth-check
```

## 使用

`--workspace` 写在子命令之前，指定数据与报告的保存目录。默认使用 `AUTO_QUOTE_WORKSPACE` 环境变量，未配置时使用当前目录。

```bash
auto-quote --workspace /path/to/local-analysis daily --date 2026-10-09
auto-quote --workspace /path/to/local-analysis weekly --start 2026-10-05 --end 2026-10-11
auto-quote --workspace /path/to/local-analysis query --date 2026-10-09 --group-by channel
auto-quote --workspace /path/to/local-analysis ask --date 2026-10-09 --question "哪个渠道的自动报价率最低？"
```

`daily` 和 `weekly` 会重新调用接口。日报输出到工作目录下的 `outputs/MMDD_api_analysis/`，线路维护快照在 `outputs/MMDD_auto_bid_line_updates/`，周期看板在 `outputs/YYYYMMDD_YYYYMMDD_weekly_analysis/`。一天的周期输出到 `outputs/YYYYMMDD_daily_dashboard/`。日期目录保留现有模板格式，跨年请使用不同工作目录，以免同一月日的 HTML 互相覆盖。

页面修改或 AI 分析完成后，用本地快照重建，以下命令不请求接口：

```bash
auto-quote --workspace /path/to/local-analysis rebuild --date 2026-10-09
auto-quote --workspace /path/to/local-analysis rebuild-weekly --start 2026-10-05 --end 2026-10-11
```

需要为异常价差补充订单日志、查价详情和线路价格证据时，执行 `auto-quote --workspace /path/to/local-analysis diagnose --date 2026-10-09`，该命令会读取接口并重建日报。诊断失败逐单记入 `errors`，不会替代原始价格事实。

日报看板保留五个业务 Tab、顶部全自动报价率、成单贡献率、默认展开明细、差价绝对值筛选、筛选后 CSV 导出及滚动固定表头。周报按经营趋势、渠道利润和专项跟进组织。[模板说明](references/dashboard.md)记录完整展示要求。

## AI 运营分析

CLI 负责确定性计算、生成证据数据包和校验展示，不自行调用模型。执行任务的 AI 按 [运营分析提示词](references/operational-analysis.md)，读取 `operational_analysis_context_YYYYMMDD.json`，生成 `operational_analysis_YYYYMMDD.json`，再执行 `rebuild`。数据指纹不匹配的旧分析会被拒绝；没有有效分析时显示待生成状态。

阅读 [SKILL.md](SKILL.md)、[指标定义](references/metrics.md)、[接口约定](references/dms-api.md)及[本地数据保护要求](references/security.md)。此安装包提供日报和周/区间分析，不包含原项目的月报采集流程。

## 验证

```bash
python -m pip install '.[test]'
python -m unittest discover -s tests -v
```

测试使用合成订单，不访问真实 DMS。真实数据、生成报告、token 和用户配置均不随源码或安装包分发。看板图表当前引用 ECharts CDN，离线分发需另行内联或提供本地资源。

常规 API 分析不需要 Excel 依赖。保留的旧线路表读取辅助函数需要额外安装 `python -m pip install '.[spreadsheets]'`；它不用于当前全量价格对比展示。
