import json
import requests
from django.conf import settings


class LLMService:
    """MiniMax M2 API 调用封装"""

    def __init__(self):
        self.api_key = settings.MINIMAX_API_KEY
        self.endpoint = settings.MINIMAX_API_ENDPOINT
        self.model = "MiniMax-M2"

    def extract_table_data(self, text_content: str) -> list:
        """
        调用 LLM 从论文文本中提取实验数据表格
        返回: [{"model": "", "dataset": "", "metric": "", "value": 0.0}, ...]
        """
        prompt = """你是一个学术论文实验数据提取助手。请从以下论文文本中提取主要实验结果数据。

任务：
1. 找到表格中主要的模型对比数据（忽略 "Source Only" 基线行，优先提取SeqDG、RNA、CIR、TA3N等主要方法）
2. 提取 Model、Dataset、Metric、Value 四个字段
3. dataset 归一化（如 EPIC-KITCHENS-100 -> EPIC-KITCHENS, MMLU, GSM8K 等）
4. metric 归一化（如 Top-1 Accuracy -> Acc, Top-5 Accuracy -> Acc@5, Mean Class accuracy -> mAcc 等）
5. 最多返回 20 条记录（优先保留主要模型的 Action Acc 指标）

只输出 JSON 数组，不要输出任何解释。
格式：[{"model": "模型名", "dataset": "数据集名", "metric": "指标名", "value": 数值}]
如果找不到数据，返回空数组 []。

论文文本：
""" + text_content + """

注意：
- 同一表格中可能有多个指标（Verb, Noun, Action），优先提取 Action 指标
- 数值可能是百分比（如 46.7 表示 46.7%）
"""

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4096
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            self.endpoint,
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code != 200:
            raise Exception(f"LLM API 调用失败: {response.status_code} - {response.text}")

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试修复截断的 JSON
            try:
                # 找到最后一个完整的对象
                last_brace = content.rfind('}')
                last_bracket = content.rfind(']')
                end = max(last_brace, last_bracket)
                if end > 0:
                    fixed = content[:end+1]
                    return json.loads(fixed)
            except:
                pass
            raise Exception(f"LLM 返回格式错误，无法解析 JSON: {content[:500]}")


llm_service = LLMService()
