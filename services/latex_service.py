from typing import List, Dict


class LatexService:
    """LaTeX 表格生成服务"""

    def generate_table(self, data: List[Dict], datasets: List[str], models: List[str]) -> str:
        """
        生成 LaTeX tabular 代码
        data: [{"model": "", "dataset": "", "metric": "", "value": 0.0}, ...]
        datasets: 数据集列表
        models: 模型列表
        """
        if not data:
            return ""

        metrics = sorted(set(r['metric'] for r in data))
        num_cols = 1 + len(metrics)
        col_spec = 'l' + 'r' * len(metrics)

        lines = []
        lines.append(f"\\begin{{tabular}}{{@{columnspec}@}}".replace('@{columnspec}@', f"{{{col_spec}}}"))
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

    def _find_value(self, data: List[Dict], model: str, datasets: List[str], metric: str) -> float:
        for d in datasets:
            for record in data:
                if (record['model'] == model and
                    record['dataset'] == d and
                    record['metric'] == metric):
                    return record['value']
        return None


latex_service = LatexService()
