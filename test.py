import os
from openai import OpenAI

# 1. 初始化客户端
# 它会自动从环境变量 DEEPSEEK_API_KEY 中读取密钥
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"  # 指定 DeepSeek 的 API 地址[reference:9][reference:10]
)

# 2. 发送请求
response = client.chat.completions.create(
    model="deepseek-v4-pro",  # 使用的模型[reference:11][reference:12]
    messages=[
        {"role": "system", "content": "You are a helpful assistant."}, # 系统提示词
        {"role": "user", "content": "请问我该如何使用你来帮我写代码？"}          # 用户消息
    ],
    stream=False,              # 非流式输出，一次返回完整结果[reference:13][reference:14]
    reasoning_effort="high",   # 启用高级推理模式[reference:15][reference:16]
    extra_body={               # 通过 extra_body 开启思考模式[reference:17][reference:18]
        "thinking": {"type": "enabled"}
    }
)

# 3. 打印回复内容
print(response.choices[0].message.content)