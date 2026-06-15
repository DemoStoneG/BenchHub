"""LLM 抽取服务：单表抽取。

输入：Django TableChunk（bbox_json 中的 HTML 表格）
输出：List[{"benchmark", "model", "dataset", "metric", "value"}] + tags
"""
import json
import logging
import re
import time
from typing import List, Dict

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _strip_html_table(html: str) -> str:
    """去掉 HTML 表格中的 class/style 等样式属性，保留结构标签和文本。"""
    if not html:
        return ""
    html = re.sub(r'\s+class="[^"]*"', '', html)
    html = re.sub(r'\s+style="[^"]*"', '', html)
    html = re.sub(r'\n\s*', '', html)
    return html.strip()


SINGLE_TABLE_HTML_PROMPT = """你是一个学术论文实验数据提取助手。

输入是论文中**一张**表格（HTML 格式，含 caption 和 <table>...</table> 块）。
请以 JSON 对象格式输出，包含 records、tags、is_experimental、filter_reason 四个字段。

输出格式：
{
  "records": [{"benchmark": "任务名", "model": "模型名", "dataset": "数据集名", "metric": "指标名", "value": 数值}],
  "tags": {"datasets": ["数据集1", "数据集2"], "tasks": ["任务名1", "任务名2"]},
  "is_experimental": true,
  "filter_reason": ""
}

records 规则：
1. **benchmark**：从 caption 推断高层任务/基准名。如果表格内有多个紫色段标题（如 <th>UDA</th>、<th>DG</th>），每个段标题代表不同的实验设置，**该段内的行 benchmark 应该用段标题名**（如 UDA → "UDA"，DG → "DG"）。如果 caption 明确说 "on XXX benchmark"，XXX 就是主要 benchmark。如果没有段标题，从 caption 推断（如 "Action Recognition"）；不要写成 "Action Recognition on XXX" 的完整形式
2. **model**：Method / Setting 列中的行名。有 <br> 换行时取第一行方法名
3. **dataset**：从列头推断（"EPIC-KITCHENS-100" → "EPIC-KITCHENS"）
4. **metric**：从列头推断，归一化（"Top-1 Accuracy" → "Acc"）
5. **value**：float，无百分号；如出现 "(▲ +0.5)" 增量格式只取主结果
6. 一行多个数字 → 多条 record
7. 跳过纯占位符行（仅含 "-", "✓" 等）和空行
8. Verb / Noun / Action 等 sub-task 名词不进 metric 字段，作为 dataset 后缀区分

tags 规则：
1. **datasets**：从 caption 和列头中识别所有数据集名，去重放入数组
2. **tasks**：从 caption 和列头中识别基准任务名，去重放入数组

is_experimental 规则（重要！）：
- **true**：表格包含模型/方法的实验对比数据（不同行是不同方法/模型，列是不同指标）
- **false**：表格是数据集统计信息（如 "Dataset / Dur / Clips / Texts"）、消融实验说明、参数量/架构对比、或者没有数值数据的说明性表格
- 只要表格里有可以排名的实验数字（不同方法在某指标上的得分），就是 true

filter_reason 规则：
- 当 is_experimental=false 时，用中文简短说明原因（10字以内），如："数据集统计信息"、"非实验对比表格"、"无模型对比数据"
- 当 is_experimental=true 时，置空字符串 ""

表格 HTML：
"""


def _normalize_benchmark(name: str) -> str:
    """归一化 benchmark 名称。"""
    if not name:
        return ''

    # 去掉 "on XXX" 数据集后缀
    name = re.sub(r'\s+on\s+[\w\-\s,]+$', '', name, flags=re.IGNORECASE)
    name = name.strip()

    # 已知别名映射
    ALIASES = {
        'multi-instance retrieval': 'Multi-Instance Retrieval',
        'moment queries': 'Moment Query',
        'natural language queries': 'NLQ',
        'action recog': 'Action Recognition',
        'action classification': 'Action Recognition',
        'ablation study': 'Action Recognition',
        'intra-domain': 'Action Recognition',
        'multi-modal': 'Action Recognition',
        'egtea': 'Action Recognition',
        'video-text retrieval': 'Video-Text Retrieval',
        'video text retrieval': 'Video-Text Retrieval',
        'epic-kitchens-100': 'Action Recognition',
        'epic-kitchens': 'Action Recognition',
        'seqdg': 'Action Recognition',
    }
    return ALIASES.get(name.lower(), name)


def _normalize_dataset(name: str) -> str:
    """归一化 dataset 名称：合并子任务和变体到主数据集。"""
    if not name:
        return ''

    # EPIC-KITCHENS 所有变体统一归一化
    if re.match(r'^EPIC[- ]KITCHENS', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    if re.match(r'^EPICKITCHENS', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    # EPIC-KITCHENS 的常见缩写
    if re.match(r'^(EK|EK100)$', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    # 纸 10/11 单独 "Test-Action" 等
    if re.match(r'^(Test|Val)[- ](Action|Noun|Verb)$', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    if re.match(r'^Validation$', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    if re.match(r'^CharadesEgo$', name, re.IGNORECASE):
        return 'Charades-Ego'

    # SeqDG-Action → EPIC-KITCHENS（DG 论文的 table 1 子行）
    if re.match(r'^SeqDG[- ](Action|Noun|Verb)$', name, re.IGNORECASE):
        return 'EPIC-KITCHENS'

    # Ego4D → EPIC-KITCHENS（EgoVideo 论文混合测试）
    if re.match(r'^Ego4[Dd]$', name):
        return 'EPIC-KITCHENS'

    # 去掉泛化后缀
    name = re.sub(r'[- ](test|val|validation)$', '', name, flags=re.IGNORECASE)

    # "val (Backbone)" → 去掉括号里的模型名
    m = re.match(r'^(.+)\s*\([^)]+\)$', name)
    if m:
        inner = m.group(1).strip()
        if inner.lower() in ('val', 'test', 'validation'):
            return name
        return inner

    return name.strip()


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
    def _parse_json_response(content: str) -> Dict:
        """解析 LLM 返回的 JSON 对象。
        Fallback：若返回的是裸数组，当作 records 处理。
        """
        if not content or not content.strip():
            return {'records': [], 'tags': {}, 'is_experimental': True, 'filter_reason': ''}
        stripped = re.sub(r'^\s*```(?:json)?\s*', '', content.strip())
        stripped = re.sub(r'\s*```\s*$', '', stripped)

        # 尝试作为对象解析
        try:
            result = json.loads(stripped)
            if isinstance(result, dict) and 'records' in result:
                return result
        except json.JSONDecodeError:
            pass
        try:
            result = json.loads(content)
            if isinstance(result, dict) and 'records' in result:
                return result
        except json.JSONDecodeError:
            pass

        # Fallback：裸数组
        records = LLMService._parse_json(content)
        return {'records': records, 'tags': {}, 'is_experimental': True, 'filter_reason': ''}

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

    def extract_from_table_chunk(self, chunk) -> tuple:
        """从 Django TableChunk 中提取结构化数据 + 标签 + 过滤信息。
        返回: (records, tags, is_experimental, filter_reason)
        """
        bbox = chunk.bbox_json if isinstance(chunk.bbox_json, dict) else {}
        raw_html = bbox.get('html', chunk.markdown_text)
        clean_html = _strip_html_table(raw_html)

        caption_line = f"Caption: {chunk.caption}\n\n" if chunk.caption else ""
        user_prompt = SINGLE_TABLE_HTML_PROMPT + caption_line + clean_html

        last_err = None
        for attempt in range(5):
            try:
                content = self._call_llm(user_prompt)
                parsed = self._parse_json_response(content)
                records = []
                for rec in parsed.get('records', []):
                    normalized = self._normalize_record(rec)
                    if normalized is None:
                        continue
                    if not (normalized['model'] and normalized['dataset'] and normalized['metric']):
                        continue
                    # 归一化 benchmark
                    normalized['benchmark'] = _normalize_benchmark(normalized['benchmark'])
                    records.append(normalized)
                tags = parsed.get('tags', {'datasets': [], 'tasks': []})
                if not isinstance(tags, dict):
                    tags = {'datasets': [], 'tasks': []}
                tags.setdefault('datasets', [])
                tags.setdefault('tasks', [])
                is_experimental = parsed.get('is_experimental', True)
                if not isinstance(is_experimental, bool):
                    is_experimental = True
                filter_reason = parsed.get('filter_reason', '') if not is_experimental else ''
                return records, tags, is_experimental, filter_reason
            except Exception as e:
                last_err = e
                logger.warning(f"LLM 抽取失败 Table {chunk.table_n} @ p{chunk.page} (attempt {attempt+1}/5): {e}")
                time.sleep(2 ** attempt)
        logger.error(f"LLM 抽取最终失败 Table {chunk.table_n} @ p{chunk.page}: {last_err}")
        return [], {'datasets': [], 'tasks': []}, True, ''

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
