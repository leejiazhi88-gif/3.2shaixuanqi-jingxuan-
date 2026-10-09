# 3.2 筛选器精选

本项目用于维护飞书《筛选器精选 26.9.24》表格的数据刷新流程。

- 飞书文档：[筛选器精选 26.9.24](https://my.feishu.cn/wiki/UI5Tw4yxSiFsEXk5mkmcgqPWnPc)
- 当前工作表：[2026-10-8（精选）](https://my.feishu.cn/wiki/UI5Tw4yxSiFsEXk5mkmcgqPWnPc?sheet=kyJJbv)
- 最近一次数据口径：2026-10-08 收盘，113 家公司（含宁德时代）；1,909 个更新单元格已逐格回读，9 条条件格式规则保留。
- 刷新脚本：`scripts/refresh_selected.py`（按日期运行）
- `scripts/refresh_selected_20260923.py` 为首次刷新记录，仍依赖历史项目。

## 更新口径

更新市值、PE(TTM)、2026–2028 年预测 PE、交易日、当日及 10/30/60/90/250/360/720/1080 日涨幅、TTM 股息率及 2026 年预估股息率。涨幅沿用原项目的未复权收盘价与交易记录间隔口径，历史不足时明确标注。

年度/季度利润、利润同比、四年均值、锁定预测和行业分类采用源表现有假设。预测 PE 使用当前市值除以表内预测利润；2026 年股息率沿用原分红假设并按市值调整。国电电力仍取“预测利润的 60%”与“每股 0.22 元”两项下限的较高者。

刷新前复制上一次工作表并以目标日期命名，保留历史记录和原生数据条。脚本只写市场相关列，并按原项目阈值重算 PE 字体（<30 绿，>50 红，其余黑）。写入后逐格核对数据、静态字段、原表和全部条件格式规则。

## 运行

Python 3.9+，安装 `requirements.txt`。配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，或设置 `FEISHU_ENV` 指向本地凭据文件；Tushare 使用 `TUSHARE_TOKEN` 或已保存的本机 token。凭据不得提交。

可用 `SELECTED_HISTORY_CACHE` 指定历史日线 CSV 目录，文件名例如 `688981_SH.csv`；未命中则从 Tushare 获取。增量行情、写入前快照、校验结果保存在本项目的 `work/refresh-YYYYMMDD/`，已被 Git 忽略。下一次可使用上一轮该目录内的 `prices/` 作为缓存。

```bash
python scripts/refresh_selected.py prepare --date 2026-10-08 --source rSNcUu --target kyJJbv
python scripts/refresh_selected.py apply --date 2026-10-08 --source rSNcUu --target kyJJbv
```

`prepare` 只读并校验行情日期与股票覆盖；`apply` 在源表和目标副本均未变化时写入。必须在目标日期完整收盘行情和估值到齐后运行；缺数据不会静默改用其他日期。

工作表名称兼容 `2026-10-8（精选）` 和 `2026-10-08（精选）`；名称中的日期必须与 `--date` 一致。
