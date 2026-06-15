from typing import List, Dict


class LatexService:
    """LaTeX 表格生成服务"""

    def generate_table(self, data: List[Dict], datasets: List[str], models: List[str], metrics: List[str] = None) -> str:
        """
        生成 LaTeX tabular 代码
        data: [{"model": "", "dataset": "", "metric": "", "value": 0.0}, ...]
        datasets: 数据集列表
        models: 模型列表
        metrics: 指标列表（可选，默认从 data 中提取并排序）
        """
        if not data:
            return ""

        if metrics is None:
            metrics = sorted(set(r['metric'] for r in data))

        col_spec = 'l' + 'r' * len(metrics)

        lines = []
        lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
        lines.append("\\toprule")

        header_row = ["Model"] + metrics
        lines.append(" & ".join(header_row) + " \\\\")
        lines.append("\\midrule")

        for model in models:
            row = [model]
            for metric in metrics:
                value = self._find_value(data, model, datasets, metric)
                row.append(f"{value:.2f}" if value is not None else "-")
            lines.append(" & ".join(row) + " \\\\")

        lines.append("\\bottomrule")
        lines.append("\\end{tabular}")

        return "\n".join(lines)

    def generate_tables_by_benchmark(self, data: List[Dict]) -> str:
        """
        按 benchmark 分块生成 LaTeX tabular，每个 benchmark 一段。
        data 元素需包含 benchmark 字段；缺失时归入 "(未指定)"。
        返回: 由空行分隔的多段 tabular 字符串。
        """
        if not data:
            return ""

        # 按 benchmark 分组
        groups: Dict[str, List[Dict]] = {}
        for r in data:
            key = r.get('benchmark') or '(未指定)'
            groups.setdefault(key, []).append(r)

        models = sorted(set(r['model'] for r in data))
        blocks = []

        for bench in sorted(groups.keys()):
            g = groups[bench]
            datasets = sorted(set(r['dataset'] for r in g))
            metrics = sorted(set(r['metric'] for r in g))
            col_spec = 'l' + 'r' * len(metrics)

            lines = [
                f"% === Benchmark: {bench} ===",
                f"\\begin{{tabular}}{{{col_spec}}}",
                "\\toprule",
                " & ".join(["Model"] + metrics) + r" \\",
                "\\midrule",
            ]
            for model in models:
                row = [model]
                for metric in metrics:
                    value = self._find_value(g, model, datasets, metric)
                    row.append(f"{value:.2f}" if value is not None else "-")
                lines.append(" & ".join(row) + r" \\")
            lines += ["\\bottomrule", "\\end{tabular}"]
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def _find_value(self, data: List[Dict], model: str, datasets: List[str], metric: str) -> float:
        for d in datasets:
            for record in data:
                if (record['model'] == model and
                    record['dataset'] == d and
                    record['metric'] == metric):
                    return record['value']
        return None


latex_service = LatexService()
