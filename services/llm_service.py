"""LLM 抽取服务：单表抽取（升级自'整篇 PDF 文本抽取'）。

输入：TableChunk（md_parser 产出的单张表片段）
输出：List[{"benchmark", "model", "dataset", "metric", "value"}]
"""
import json
import logging
import re
import time
from typing import List, Dict

import requests
from django.conf import settings

from services.md_parser import TableChunk

logger = logging.getLogger(__name__)


SINGLE_TABLE_PROMPT = """你是一个学术论文实验数据提取助手。

输入是论文中**一张**实验结果表格（Markdown 格式，含 caption 和 |...|...| 表格块）。
请提取该表所有**有数据**的 cell，输出 JSON 数组。

输出格式：
[{"benchmark": "任务名", "model": "模型名", "dataset": "数据集名", "metric": "指标名", "value": 数值}]

规则：
1. **benchmark**：从 caption 推断高层任务/基准名（如 "Action Recognition on X" → "Action Recognition"）；若 caption 没有可识别的任务名，置空字符串 ""
2. **model**：Method / Setting 列中的行名。
   - **Method 列常见结构**：第一行是方法名（如 "Source Only", "SeqDG"），第二行是 Backbone 名（如 "TBN-TRN"），**只用第一行的方法名**作为 model；Backbone 行不另起 model
   - 例：行 "Source Only<br>TBN-TRN" → model = "Source Only"；行 "SeqDG<br>TBN-TRN" → model = "SeqDG"
3. **dataset**：从列头推断（"EPIC-KITCHENS-100" → "EPIC-KITCHENS"，"EGTEA" → "EGTEA"）
4. **metric**：从列头推断，归一化（"Top-1 Accuracy" → "Acc"，"Top-5 Accuracy" → "Acc@5"，"Mean Class Accuracy" → "mAcc"）
5. **value**：float，无百分号；如出现 "(▲ +0.5)" 这种"主结果 + 增量"格式，**只取主结果**（如 34.0），不要增量
6. 一行多个数字 → 多条 record（每个 cell 一条）
7. 跳过纯占位符行（仅含 "-", "✓" 等）和空行
8. 忽略 Markdown 加粗标记 **...** 和 <br> 换行
9. 表格中"主模型"行（通常加粗、含 ▲ 增量、或在 caption 标注的方法）**全部保留**，与其他 baseline 一视同仁——人工筛选是用户的事
10. Verb / Noun / Action 等 sub-task 名词**不要进 metric 字段**（它们是 dataset 维度）；如果表格里 Verb/Noun/Action 各是一列，**为每个 sub-task 各生成一条 record**，metric 统一为该列的 metric 名（"Acc"），dataset 用 "EPIC-KITCHENS-Verb" / "EPIC-KITCHENS-Noun" / "EPIC-KITCHENS-Action" 这种后缀区分

表格 Markdown：
"""


class LLMService:

    def __init__(self):
        self.api_key = settings.MINIMAX_API_KEY
        self.endpoint = settings.MINIMAX_API_ENDPOINT
        self.model = "MiniMax-M2"

    def _call_llm(self, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.0,
            "max_tokens": 4096,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=300)
        if resp.status_code != 200:
            raise Exception(f"LLM API 调用失败: {resp.status_code} - {resp.text[:300]}")
        result = resp.json()
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[]")

    @staticmethod
    def _parse_json(content: str) -> List[Dict]:
        """鲁棒解析 LLM 返回的 JSON 数组。
        兼容：```json ... ``` 包裹、末尾被截断（无 `]`）、前后有解释文字。
        """
        if not content or not content.strip():
            raise Exception("LLM 返回空")

        # 0. 剥掉 markdown 代码块标记
        stripped = re.sub(r'^\s*```(?:json)?\s*', '', content.strip())
        stripped = re.sub(r'\s*```\s*$', '', stripped)

        # 1. 直接解析
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 2. 截断修复：找到最后一个完整的 }, {... 形式
        # 即：从尾部向前扫，匹配到 `,` 或 `[` 之前的最后一个 `}` 之前所有内容 + 补 `]`
        # 启发式：取所有完整对象，用 `[{...},{...},...]` 形式包裹
        last_brace = stripped.rfind('}')
        if last_brace == -1:
            raise Exception(f"LLM 返回中找不到任何完整对象: {content[:200]}")
        # 找到 last_brace 之前最近的 `,` 或 `[`，作为截断点
        # 完整 JSON 是 `[obj1, obj2, ..., objN]`，截断发生在 objN 中
        # 因此从 stripped[:last_brace+1] 就是 `...objN}`，再补 `]`
        # 但需确保 stripped 开头是 `[`
        candidate = stripped[:last_brace + 1]
        if not candidate.lstrip().startswith('['):
            # 前面有 LLM 解释文字，尝试抽出 [ ... ] 段
            m = re.search(r'\[', candidate)
            if m:
                candidate = candidate[m.start():]
        # 补 `]`
        candidate = candidate.rstrip().rstrip(',') + ']'
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # 3. 抽出第一个完整对象
        # 找到所有 `}`，取最后一个 `}` 之前的最近 `,` 切分，组成 list
        objs = []
        depth = 0
        cur_start = None
        for i, ch in enumerate(stripped):
            if ch == '{':
                if depth == 0:
                    cur_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and cur_start is not None:
                    objs.append(stripped[cur_start:i + 1])
                    cur_start = None
        if not objs:
            raise Exception(f"无法从 LLM 返回中提取任何 JSON 对象: {content[:200]}")
        try:
            return [json.loads(o) for o in objs]
        except json.JSONDecodeError as e:
            # 过滤掉解析失败的对象，剩下的算成功
            out = []
            for o in objs:
                try:
                    out.append(json.loads(o))
                except json.JSONDecodeError:
                    pass
            if out:
                return out
            raise Exception(f"LLM 返回中所有对象都解析失败: {e}")

    @staticmethod
    def _normalize_record(rec: Dict) -> Dict:
        """清洗单条 record：value 转 float、字段 trim、空 value 丢弃。

        兼容 LLM 输出的字段别名：
          model   ← 'model' / 'method' / 'Model'
          dataset ← 'dataset' / 'Dataset' / 'subtask' / 'task'
          metric  ← 'metric' / 'Metric'
          value   ← 'value' / 'score'
        """
        try:
            v = float(rec.get('value', 0))
        except (TypeError, ValueError):
            return None

        def _first(*keys: str) -> str:
            for k in keys:
                val = rec.get(k)
                if val is None:
                    continue
                s = str(val).strip()
                if s:
                    return s
            return ''

        return {
            'benchmark': (rec.get('benchmark') or rec.get('Benchmark') or '').strip(),
            'model': _first('model', 'method', 'Model', 'Method'),
            'dataset': _first('dataset', 'subtask', 'task', 'Dataset'),
            'metric': _first('metric', 'Metric'),
            'value': v,
        }

    def extract_from_table_chunk(self, chunk: TableChunk) -> List[Dict]:
        """单表抽取入口。失败时重试 5 次（处理 LLM 偶发空响应/断连）。"""
        user_prompt = SINGLE_TABLE_PROMPT + chunk.markdown_text
        last_err = None
        for attempt in range(5):
            try:
                content = self._call_llm(user_prompt)
                raw = self._parse_json(content)
                out: List[Dict] = []
                for rec in raw:
                    normalized = self._normalize_record(rec)
                    if normalized is None:
                        continue
                    # 丢弃空 model / 空 dataset / 空 metric（噪声）
                    if not (normalized['model'] and normalized['dataset'] and normalized['metric']):
                        continue
                    out.append(normalized)
                return out
            except Exception as e:
                last_err = e
                logger.warning(f"LLM 抽取失败 Table {chunk.table_n} @ p{chunk.page} (attempt {attempt+1}/5): {e}")
                time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s 退避
        logger.error(f"LLM 抽取最终失败 Table {chunk.table_n} @ p{chunk.page}: {last_err}")
        return []

    def extract_table_data(self, text_content: str) -> List[Dict]:
        """旧接口（整篇 PDF 文本抽取），保留以防 fallback，但不再被 tasks.py 主流程调用。"""
        # 截断超长文本
        max_chars = 60000
        if len(text_content) > max_chars:
            text_content = text_content[:max_chars] + "\n\n[... 文本已截断 ...]"

        legacy_prompt = """你是一个学术论文实验数据提取助手。请从以下论文文本中提取所有主要实验结果数据。
任务：
1. 识别论文中的实验对比表格（通常包含 model/dataset/metric/value 列）
2. 提取 Benchmark、Model、Dataset、Metric、Value 五个字段
3. benchmark 字段是高层任务/基准名，若无法区分可与 dataset 相同
4. dataset 归一化（如 "EPIC-KITCHENS-100" -> "EPIC-KITCHENS"，"ImageNet-1K" -> "ImageNet"）
5. metric 归一化（如 "Top-1 Accuracy" -> "Acc"，"Top-5 Accuracy" -> "Acc@5"）
6. 优先保留主模型在主数据集上的主指标
7. 最多返回 30 条记录

只输出 JSON 数组：[{"benchmark", "model", "dataset", "metric", "value"}]
注意：value 必须是 float，无百分号；如无表格返回 []。

论文文本：
""" + text_content

        try:
            content = self._call_llm(legacy_prompt)
            raw = self._parse_json(content)
        except Exception as e:
            logger.warning(f"旧 LLM 抽取失败: {e}")
            return []
        out: List[Dict] = []
        for rec in raw:
            normalized = self._normalize_record(rec)
            if normalized is not None and normalized['model'] and normalized['dataset']:
                out.append(normalized)
        return out


llm_service = LLMService()
