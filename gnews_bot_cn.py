import requests
import telegram
import time
import asyncio
import os
import re
from dotenv import load_dotenv
from telegram.constants import ParseMode
from telegram.error import BadRequest
from playwright.async_api import async_playwright, Playwright, Browser
import jieba
import jieba.analyse
from datetime import datetime, timezone, timedelta

# --- 配置加载 ---
# 在云端环境中，这些变量会由平台的环境变量设置注入
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GNEWS_API_KEY]):
    print("错误：配置信息未能完全加载。请检查环境变量是否已正确设置。")
    exit()

# --- 策略与配置 ---
MAX_ARTICLES_TO_SEND = 3
SEND_INTERVAL_SECONDS = 20 # 在单次运行中发送多条消息的间隔
SENT_ARTICLES_FILE = 'sent_articles.txt'
SENT_TITLES_FILE = 'sent_titles.txt'
CHANNEL_TOPIC_HEADER = "【全球新闻快讯】"
CONTACT_LINK_TEXT = "联系投稿"
CONTACT_LINK_URL = "https://t.me/IE8GB"
GROUP_LINK_TEXT = "加入讨论群"
GROUP_LINK_URL = "https://t.me/DONG8NY"

# --- 时间格式化函数 ---
def format_china_time(time_str: str) -> str:
    if not time_str:
        return "未知"
    try:
        if time_str.endswith('Z'):
            time_str = time_str[:-1] + '+00:00'
        dt_object = datetime.fromisoformat(time_str)
        china_tz = timezone(timedelta(hours=8))
        dt_object_china = dt_object.astimezone(china_tz)
        return dt_object_china.strftime('%Y年%m月%d日 %H:%M')
    except (ValueError, TypeError):
        return time_str.split('T')[0]

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
    except Exception as e:
        print(f"从GNews API获取新闻时出错: {e}")
        return []
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
    except Exception as e:
        print(f"抓取文章详情时出错: {url}, 错误: {e}")
        return pub_time, summary

# --- 发送函数 (包含详细日志和最终排版) ---
async def send_single_article(bot, article, pub_time: str, summary: str):
    title, url, image_url = article.get('title'), article.get('url'), article.get('image')
    source_name = article.get('source', {}).get('name', '未知来源')
    if not title or not url: return False
    
    display_time = format_china_time(pub_time) if pub_time else format_china_time(article.get('publishedAt'))
    
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

    try:
        if image_url:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Exception as e:
        print(f"!!! 发送消息失败，错误原因: {e}")
        try:
            print("--- 正在尝试发送纯文本版本... ---")
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except Exception as fallback_e:
            print(f"!!! 发送纯文本版本也失败了，最终错误原因: {fallback_e}")
            return False

# --- ★★★ 主程序 (已优化为单次运行并确保浏览器关闭) ★★★ ---
async def main():
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    print("GNews Bot Service Started (Single Run for Serverless Environment)")
    
    browser: Browser | None = None
    try:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- Starting new articles check ---")
        sent_urls = load_sent_urls()
        sent_titles = load_sent_titles()
        news_articles = get_gnews_news()

        if not news_articles:
            print("No news received from API.")
        else:
            new_articles_found = [article for article in reversed(news_articles) if article.get('url') not in sent_urls and article.get('title') not in sent_titles]
            if not new_articles_found:
                print("No new articles found.")
            else:
                print(f"Found {len(new_articles_found)} new articles, preparing to process...")
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    
                    articles_sent_count, sent_titles_this_run = 0, set()
                    for article in new_articles_found:
                        if articles_sent_count >= MAX_ARTICLES_TO_SEND:
                            print(f"Reached send limit for this run ({MAX_ARTICLES_TO_SEND}).")
                            break
                        
                        current_title = article.get('title')
                        if current_title in sent_titles_this_run:
                            print(f"Duplicate title in this run, skipping: {current_title}")
                            save_sent_url(article.get('url')) # Still save URL to prevent re-checking
                            continue
                        
                        print(f"Processing: {current_title}")
                        publication_time, summary = await scrape_article_details(page, article.get('url'))
                        
                        if await send_single_article(bot, article, publication_time, summary):
                            save_sent_url(article.get('url'))
                            save_sent_title(article.get('title'))
                            sent_titles_this_run.add(current_title)
                            articles_sent_count += 1
                            print(f"Successfully sent ({articles_sent_count}/{MAX_ARTICLES_TO_SEND} in this run).")
                            if articles_sent_count < MAX_ARTICLES_TO_SEND and articles_sent_count < len(new_articles_found):
                                await asyncio.sleep(SEND_INTERVAL_SECONDS)
                        else:
                            print(f"Failed to send: {current_title}")
        
        print(f"--- Task completed for this run. ---")

    except Exception as e:
        print(f"!!! A critical error occurred in the main function: {e} !!!")
    
    finally:
        # This block will always execute, ensuring the browser is closed.
        if browser:
            print("Closing browser instance...")
            await browser.close()
            print("Browser closed successfully.")
        print("Script execution finished.")

if __name__ == '__main__':
    jieba.initialize()
    asyncio.run(main())


