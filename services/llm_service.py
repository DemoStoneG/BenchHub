import json
import requests
from django.conf import settings


class LLMService:
    """MiniMax M2.7 API 调用封装"""

    def __init__(self):
        self.api_key = settings.MINIMAX_API_KEY
        self.endpoint = settings.MINIMAX_API_ENDPOINT
        self.model = "MiniMax-M2.7-32K"

    def extract_table_data(self, markdown_content: str) -> list:
        """
        调用 LLM 从 Markdown 表格内容中提取实验数据
        返回: [{"model": "", "dataset": "", "metric": "", "value": 0.0}, ...]
        """
        prompt = f"""你是一个学术论文数据提取助手。请从以下 Markdown 格式的论文表格中提取实验数据。

要求：
1. 只提取主要实验结果表格（通常在实验章节）
2. 识别表格中的 Model/Dataset/Metric/Value 列
3. dataset 归一化为标准名称（如 MMLU, GSM8K, ImageNet 等）
4. metric 归一化为标准缩写（如 Acc, F1, BLEU 等）

只输出 JSON 数组格式，不要输出任何其他内容。
如果表格数据不完整或无法提取，返回空数组 []。

Markdown 内容：
{markdown_content}

输出格式示例：
[{{"model": "GPT-4", "dataset": "MMLU", "metric": "Acc", "value": 86.4}}]
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
            raise Exception(f"LLM 返回格式错误，无法解析 JSON: {content}")


llm_service = LLMService()
