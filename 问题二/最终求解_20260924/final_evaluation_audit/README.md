# 最终打包评价独立审查

`final_evaluation_audit.py` 只读审查 `finalize_submission.py` 及其已生成结果，不修改最终文件。

结论：**PASS_WITH_SCOPE_WARNINGS**。

- 最终方案：`(22, 65.51851671683666 kWh, 6206.344443443169 s, 0 s)`。
- 档案14套，135条不同候选路线；最终方案确为同一档案按遗憾上界、C、L排序后的选择。
- 冻结扩大评价库候选系数哈希为 `96c73b04ebaeb105368e4298d3bd871ceab92c6734e580a835a9988780dc4058`，与偏好下界文件一致；因此旧LP下界可在同一有限库范围复用。
- 遗憾上下界、偏好上界、Pareto支配关系均独立重算一致；没有档案内支配对。
- 最终方案原始XLSX与GeoTIFF独立核验373项通过，全部14个档案方案也通过。

唯一范围提示：`finalize_submission.py`同时合并旧 `改进搜索_20260924/联合非支配档案.json` 和 `cover_search/combined_archive.json`。这会扩大来源档案，已在 `汇总.json` 的 `source_paths` 中记录；只要发布时明确该来源集合即可。所有下界仍只适用于冻结的有限候选库，不能解释为原题全路线全局下界或全局最优。

详细机器结果见 `summary.json`、`raw_final_verification.json`、`raw_archive_verification.json`、`regret_recheck.json` 与 `route_identity_check.json`。
