import requests
import telegram
import time
import asyncio
import os
import re
from dotenv import load_dotenv
from telegram.constants import ParseMode
from telegram.error import BadRequest
from playwright.async_api import async_playwright
import jieba
import jieba.analyse
from datetime import datetime, timezone, timedelta # 导入用于处理时间的模块

# --- 配置加载 (保持不变) ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GNEWS_API_KEY]):
    print("错误：配置信息未能完全加载。")
    exit()

# --- 策略与配置 (保持不变) ---
MAX_ARTICLES_TO_SEND = 3
SEND_INTERVAL_SECONDS = 20
UPDATE_INTERVAL_HOURS = 1
SENT_ARTICLES_FILE = 'sent_articles.txt'
SENT_TITLES_FILE = 'sent_titles.txt'
CHANNEL_TOPIC_HEADER = "【全球新闻快讯】"
CONTACT_LINK_TEXT = "联系投稿"
CONTACT_LINK_URL = "https://t.me/VIP33054"
GROUP_LINK_TEXT = "加入讨论群"
GROUP_LINK_URL = "https://t.me/VIP31333"

# --- ★ 新增：时间格式化函数 ★ ---
def format_china_time(time_str: str) -> str:
    """
    将多种格式的时间字符串转换为“年-月-日 时:分”的格式。
    """
    if not time_str:
        return "未知"
    try:
        # 替换掉 'Z' (UTC) 标志，以便 fromisoformat 处理
        if time_str.endswith('Z'):
            time_str = time_str[:-1] + '+00:00'
        
        # 使用 fromisoformat 解析标准时间格式
        dt_object = datetime.fromisoformat(time_str)
        
        # 转换为中国时区 (UTC+8)
        china_tz = timezone(timedelta(hours=8))
        dt_object_china = dt_object.astimezone(china_tz)
        
        # 格式化为易读的中文格式
        return dt_object_china.strftime('%Y年%m月%d日 %H:%M')
    except (ValueError, TypeError):
        # 如果解析失败，则按原样返回，确保程序不会中断
        return time_str.split('T')[0] # 尝试只返回日期部分

# --- 辅助与抓取函数 (保持不变) ---
def load_sent_urls():
    if not os.path.exists(SENT_ARTICLES_FILE): return set()
    with open(SENT_ARTICLES_FILE, 'r', encoding='utf-8') as f: return set(line.strip() for line in f)
def save_sent_url(article_url):
    with open(SENT_ARTICLES_FILE, 'a', encoding='utf-8') as f: f.write(article_url + '\n')
def load_sent_titles():
    if not os.path.exists(SENT_TITLES_FILE): return set()
    with open(SENT_TITLES_FILE, 'r', encoding='utf-8') as f: return set(line.strip() for line in f)
def save_sent_title(article_title):
    with open(SENT_TITLES_FILE, 'a', encoding='utf-8') as f: f.write(article_title + '\n')
def get_gnews_news():
    print("正在从 GNews API 获取最新新闻...")
    url = f"https://gnews.io/api/v4/top-headlines?lang=zh&country=cn&max=10&apikey={GNEWS_API_KEY}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200: return []
        return response.json().get("articles", [])
    except Exception: return []
async def scrape_article_details(page, url: str) -> tuple[str, str]:
    pub_time, summary = "", ""
    try:
        await page.goto(url, timeout=30000, wait_until='domcontentloaded')
        time_selectors = ['meta[property="article:published_time"]','meta[name="publish-date"]','time','.pub_date','.post-time','.time-source .time']
        for selector in time_selectors:
            element = await page.query_selector(selector)
            if element:
                content = await element.get_attribute('content') or await element.get_attribute('datetime') or await element.inner_text()
                if content: pub_time = content.strip(); break
        content_selectors = ['article','.article-content','.post-body','.content','#article_content','#Content','.art-text','#main_content','div[class*="content-main"]','div[class*="article-body"]']
        for selector in content_selectors:
            content_element = await page.query_selector(selector)
            if content_element:
                paragraphs = await content_element.query_selector_all('p')
                summary_parts = [await p.inner_text() for p in paragraphs[:5] if await p.inner_text()]
                if summary_parts:
                    summary = "\n\n".join(summary_parts)
                    if len(paragraphs) > 5: summary += "..."
                    break
        return pub_time, summary
    except Exception: return pub_time, summary

# --- ★★★ 核心改动：发送函数，采用更新后的排版 ★★★ ---
# --- ★★★ 核心改动：发送函数，增加详细错误日志 ★★★ ---
async def send_single_article(bot, article, pub_time: str, summary: str):
    title, url, image_url = article.get('title'), article.get('url'), article.get('image')
    source_name = article.get('source', {}).get('name', '未知来源')
    if not title or not url: return False
    
    # (此部分代码保持不变...)
    display_time = format_china_time(pub_time) # 假设您已使用我上次提供的带时间格式化的版本
    tags = jieba.analyse.extract_tags(title, topK=3)
    filtered_tags = [tag for tag in tags if not tag.isdigit()]
    hashtags = " ".join([f"#{tag}" for tag in filtered_tags]) if filtered_tags else ""
    summary_text = summary if summary else article.get('description', '')
    if summary_text and title in summary_text: 
        summary_text = ""
    if not summary_text:
        summary_text = f"如需摘要，请<a href='{url}'>点击此处</a>阅览。"

    caption_parts = [
        f"{CHANNEL_TOPIC_HEADER} {hashtags}\n",
        f"<b>{title}</b>\n",
        summary_text,
        "", 
        f"详细信息：<a href='{url}'>点击阅读原文</a>",
        f"发布时间：{display_time}",
        f"信息来源：<a href='{url}'>{source_name}</a>",
        f"投稿联系：<a href='{CONTACT_LINK_URL}'>{CONTACT_LINK_TEXT}</a>",
        f"💬 欢迎加入交流群讨论：<a href='{GROUP_LINK_URL}'>{GROUP_LINK_TEXT}</a>"
    ]
    caption = "\n".join(part for part in caption_parts if part.strip() or part == "")

    if len(caption) > 1024:
        oversize = len(caption) - 1024
        if "点击此处" not in summary_text:
             summary_text = summary_text[:-(oversize + 5)] + "..."
             caption_parts[2] = summary_text
             caption = "\n".join(part for part in caption_parts if part.strip() or part == "")
        else:
             caption = caption[:1020] + "..."

    # ★ 发送逻辑的关键改动在这里 ★
    try:
        if image_url:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Exception as e:
        # 打印第一次发送失败的详细原因
        print(f"!!! 发送带图片的版本失败，错误原因: {e}")
        try:
            # 尝试以降级模式（不带图片）发送
            print("--- 正在尝试发送纯文本版本... ---")
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except Exception as fallback_e:
            # 如果降级模式也失败了，打印最终的错误原因
            print(f"!!! 发送纯文本版本也失败了，最终错误原因: {fallback_e}")
            return False

# --- “永动机”主程序 (保持不变) ---
async def main():
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    print("GNews【终极完美排版版】新闻机器人服务已启动！")
    load_sent_articles = load_sent_urls
    save_sent_article = save_sent_url
    while True:
        try:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- 开始新一轮新闻检查 ---")
            sent_urls = load_sent_articles()
            sent_titles = load_sent_titles()
            news_articles = get_gnews_news()
            if not news_articles:
                print("未能从API获取到新闻。")
            else:
                new_articles_found = [article for article in reversed(news_articles) if article.get('url') not in sent_urls and article.get('title') not in sent_titles]
                if not new_articles_found:
                    print("没有发现新新闻。")
                else:
                    print(f"发现 {len(new_articles_found)} 条新新闻，准备处理...")
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        page = await browser.new_page()
                        articles_sent_count, sent_titles_this_run = 0, set()
                        for article in new_articles_found:
                            if articles_sent_count >= MAX_ARTICLES_TO_SEND:
                                print(f"本轮发送上限 ({MAX_ARTICLES_TO_SEND} 条)已到。")
                                break
                            current_title = article.get('title')
                            if current_title in sent_titles_this_run:
                                print(f"标题重复，跳过: {current_title}")
                                save_sent_article(article.get('url'))
                                continue
                            print(f"正在处理: {current_title}")
                            publication_time, summary = await scrape_article_details(page, article.get('url'))
                            if await send_single_article(bot, article, publication_time, summary):
                                save_sent_article(article.get('url'))
                                save_sent_title(article.get('title'))
                                sent_titles_this_run.add(article.get('title'))
                                articles_sent_count += 1
                                print(f"发送成功 (本轮已发送 {articles_sent_count}/{MAX_ARTICLES_TO_SEND} 条)。")
                                if articles_sent_count < MAX_ARTICLES_TO_SEND and articles_sent_count < len(new_articles_found):
                                    await asyncio.sleep(SEND_INTERVAL_SECONDS)
                            else:
                                print(f"发送失败: {current_title}")
                        await browser.close()
            
            sleep_seconds = UPDATE_INTERVAL_HOURS * 3600
            print(f"--- 本轮任务完成，休眠 {UPDATE_INTERVAL_HOURS} 小时... ---")
            await asyncio.sleep(sleep_seconds)
        except KeyboardInterrupt:
            print("\n服务被手动停止。")
            break
        except Exception as e:
            print(f"!!! 发生未知严重错误: {e} !!!")
            print("将在 15 分钟后重试...")
            await asyncio.sleep(900)

if __name__ == '__main__':
    jieba.initialize()
    asyncio.run(main())