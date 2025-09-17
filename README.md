# GNews 全球新闻机器人 🤖

![GitHub Actions Workflow Status](https://github.com/itl33054/xinwen/actions/workflows/main.yml/badge.svg)

这是一个全自动化的新闻推送机器人。它会定时从 **GNews API** 获取最新的全球中文头条新闻，利用 **Playwright** 深度抓取原文摘要和发布时间，进行智能排版后，自动推送到指定的 **Telegram 频道**。

项目被设计为在 **GitHub Actions** 上以无服务器（Serverless）模式免费、永久地自动化运行，无需您自己准备服务器。

### ✨ 效果演示

机器人会将格式化后的新闻以卡片形式发送到您的 Telegram 频道，如下所示：

*(请在此处替换为您自己机器人发送消息的截图)*
<img src="" width="400">


---

## 🚀 主要特性

*   **全自动运行**: 一次部署，永久自动获取和推送新闻。
*   **深度内容抓取**: 使用 Playwright 模拟浏览器，精准抓取标准新闻网站的发布时间和正文摘要，内容更完整。
*   **智能去重**: 同时记录已发送文章的 URL 和标题，双重保险防止重复推送。
*   **自动生成标签**: 使用 Jieba 对标题进行分词，自动提取关键词作为 Hashtag，方便分类和搜索。
*   **精美排版**: 支持生成包含标题、摘要、发布时间、信息来源、原文链接等多元素的富文本消息。
*   **专为云端设计**: 基于 GitHub Actions 定时任务运行，完美适配免费、无服务器的部署模式。
*   **配置简单**: 所有敏感信息（API Keys, Tokens）均通过环境变量或 GitHub Secrets 配置，安全可靠。

## 🛠️ 技术栈

*   **Python 3.9+**
*   **GNews API**: 获取新闻源
*   **Playwright**: 模拟浏览器抓取网页详细内容
*   **python-telegram-bot**: 与 Telegram API 交互
*   **Jieba**: 中文分词与关键词提取
*   **python-dotenv**: 管理本地环境变量

---

## 📚 部署指南

您可以选择以下两种方式来部署这个机器人。**强烈推荐使用 GitHub Actions 方式**，实现一劳永逸的自动化。

### 方式一：部署到 GitHub Actions (⭐ 推荐)

这是最推荐的方式，可以让您的机器人在云端免费、自动地按时运行。

#### 第1步：Fork 本项目

点击本项目页面右上角的 **Fork** 按钮，将此仓库复制到您自己的 GitHub 账户下。

#### 第2步：获取必要的 API Keys 和 IDs

在配置之前，您需要准备好以下三个关键信息：

1.  **`TELEGRAM_BOT_TOKEN`** (机器人 Token)
    *   在 Telegram 中与 `@BotFather` 对话，输入 `/newbot` 创建一个新的机器人，您会得到一串类似 `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` 的 Token。

2.  **`TELEGRAM_CHAT_ID`** (频道 ID)
    *   创建一个公开或私有频道，并将您的机器人添加为该频道的**管理员** (必须有发布消息的权限)。
    *   **如果频道是公开的**，ID 就是 `@your_channel_name`。
    *   **如果频道是私有的**，将频道内任意消息转发给 `@get_id_bot`，它会返回一串以 `-100` 开头的数字 ID。

3.  **`GNEWS_API_KEY`** (GNews API 密钥)
    *   访问 [gnews.io](https://gnews.io/) 网站，注册一个免费账户，在您的个人资料页面即可找到 API Key。

#### 第3步：在您的 GitHub 仓库中设置 Secrets

1.  进入您 Fork 后的仓库，点击 `Settings` -> `Secrets and variables` -> `Actions`。
2.  点击 `New repository secret` 按钮，逐一添加以下三个 Secret：
    *   **Name**: `TELEGRAM_BOT_TOKEN`, **Secret**: (粘贴您获取的机器人 Token)
    *   **Name**: `TELEGRAM_CHAT_ID`, **Secret**: (粘贴您的频道 ID)
    *   **Name**: `GNEWS_API_KEY`, **Secret**: (粘贴您的 GNews API Key)

#### 第4步：为 Actions 授予写入权限 (非常重要！)

为了让机器人能够保存“已发送列表”以防止重复推送，需要允许 Actions 修改仓库文件。

1.  在您的仓库中，点击 `Settings` -> `Actions` -> `General`。
2.  找到 **Workflow permissions** 部分。
3.  选择 **Read and write permissions** 选项。
4.  点击 **Save**。

#### 第5步：启动机器人！

完成以上步骤后，机器人就已经在待命状态了。它会根据 `.github/workflows/main.yml` 文件中设定的时间（默认为每小时）自动运行。

您也可以手动触发一次来立即测试：
1.  进入仓库的 `Actions` 标签页。
2.  在左侧选择 `GNews Telegram Bot Cron Job`。
3.  点击 `Run workflow` -> `Run workflow`。

---

### 方式二：在您自己的电脑上本地部署 (用于开发和测试)

如果您想在本地进行测试或二次开发，请按以下步骤操作。

#### 第1步：克隆仓库到本地

```bash
git clone https://github.com/itl33054/xinwen.git
cd xinwen
```

#### 第2步：创建并激活虚拟环境

*   **Windows**:

    ```powershell
    python -m venv venv
    .\venv\Scripts\activate
    ```

*   **macOS / Linux**:

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

#### 第3步：安装所有依赖库

```bash
pip install -r requirements.txt
```
#### 第4步：安装 Playwright 的浏览器内核

```bash
playwright install --with-deps
```
### 第5步：创建并配置 .env 文件

在项目根目录下，创建一个名为 .env 的文件。
将以下内容复制到文件中，并替换为您自己的 Keys 和 IDs：
```bash
TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
TELEGRAM_CHAT_ID="-1001234567890"
GNEWS_API_KEY="your_gnews_api_key_here"
```
### 第6步：运行脚本
```bash
python gnews_bot_cn.py
```
您将在终端看到日志输出，同时机器人会将新发现的新闻发送到您的 Telegram 频道。注意，本地脚本只会运行一次便会退出，这符合其为云端定时任务设计的初衷。
### 📂 文件结构说明
```bash
.
├── .github/workflows/main.yml  # GitHub Actions 配置文件，定义了自动化任务
├── .gitignore                  # 定义了 Git 应忽略的文件
├── gnews_bot_cn.py             # 机器人核心逻辑脚本
├── requirements.txt            # Python 依赖库列表
├── sent_articles.txt           # 已发送文章的 URL 记录 (自动生成和更新)
├── sent_titles.txt             # 已发送文章的标题记录 (自动生成和更新)
└── README.md                   # 本说明文件
```
## 🤝 如何贡献
欢迎任何形式的贡献！如果您有好的想法或发现了 Bug，请随时提交 Pull Request 或创建 Issue。
Fork 本仓库
创建您的新分支 (git checkout -b feature/AmazingFeature)
提交您的更改 (git commit -m 'Add some AmazingFeature')
推送到分支 (git push origin feature/AmazingFeature)
创建一个 Pull Request
### 📄 许可证
本项目使用 MIT 许可证。
