import requests
import os
from dotenv import load_dotenv

# 加载 .env 文件里的配置
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 我们要测试的Telegram API地址
url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"

print("--- 开始进行网络连通性测试 ---")
print(f"正在尝试访问: {url}")

try:
    # 设置一个15秒的超时
    response = requests.get(url, timeout=15)
    
    # 检查返回的状态码
    if response.status_code == 200:
        print("\n★★★ 测试成功！★★★")
        print("您的网络可以正常连接到Telegram API服务器。")
        print("返回内容:", response.json())
    else:
        print("\n!!! 测试失败 !!!")
        print(f"连接正常，但服务器返回了错误。状态码: {response.status_code}")
        print("返回内容:", response.text)

except requests.exceptions.RequestException as e:
    print("\n!!! 测试失败 !!!")
    print("无法连接到Telegram API服务器。这很可能是网络、防火墙或代理问题。")
    print("详细错误信息:", e)

print("\n--- 测试结束 ---")