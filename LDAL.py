import json
import logging
import os
import time
import requests
import xml.etree.ElementTree as ET
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pytz
from datetime import datetime
from fake_useragent import UserAgent
from threading import Thread
import base64

# 设置中国北京时间时区
tz = pytz.timezone('Asia/Shanghai')

# 配置日志记录，添加时间戳，并将时间转换为北京时间
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

# Base64 编码后的URL
HOME_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby8="
RSS_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby9sYXRlc3QucnNz"

# 解码Base64编码后的URL
HOME_URL = base64.b64decode(HOME_URL_ENCODED).decode('utf-8')
RSS_URL = base64.b64decode(RSS_URL_ENCODED).decode('utf-8')

def mask_account(account):
    """
    对账号进行打码处理，中间部分替换为 '*'。

    如果账号长度小于等于2，则全部替换为 '*'
    否则，仅保留账号的首尾字符，中间部分用 '*' 替换。
    """
    if len(account) <= 2:
        return '*' * len(account)
    return account[0] + '*' * (len(account) - 2) + account[-1]

class LinuxDoBrowser(Thread):
    def __init__(self, username, password):
        """
        初始化浏览器实例，并设置相关变量。

        参数:
        username: 账号名
        password: 密码
        """
        super().__init__()
        self.username = username
        self.password = password
        self.masked_username = mask_account(username)  # 将账号打码

        options = webdriver.ChromeOptions()
        ua = UserAgent()

        # 随机生成符合条件的 User-Agent（macOS + Chrome）
        user_agent = ua.random
        while "Macintosh" not in user_agent or "Chrome" not in user_agent:
            user_agent = ua.random

        # 设置浏览器选项
        options.add_argument(f'user-agent={user_agent}')
        options.add_argument('--headless')  # 无头模式
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        # 启动浏览器
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.total_topics_visited = 0  # 记录访问的主题数量
        self.total_posts_visited = 0   # 记录访问的帖子数量
        self.start_time = time.time()  # 记录程序开始时间

        # 输出启动信息并打开主页
        logging.info(f"[{self.masked_username}] 程序启动并打开主页，使用的 User-Agent: {user_agent}")
        self.driver.get(HOME_URL)

    def login(self):
        """
        执行登录操作。

        通过点击登录按钮，输入账号和密码，最终确认登录成功。
        """
        logging.info(f"[{self.masked_username}] 点击登录按钮并输入用户名和密码")
        
        # 点击登录按钮
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button .d-button-label"))
        ).click()

        # 输入用户名和密码
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-account-name"))
        ).send_keys(self.username)
        self.driver.find_element(By.ID, "login-account-password").send_keys(self.password)

        # 提交登录表单
        self.driver.find_element(By.ID, "login-button").click()

        # 等待确认登录成功
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "current-user"))
        )
        logging.info(f"[{self.masked_username}] 登录成功")

    def fetch_rss_links(self):
        """
        请求并解析RSS数据，提取主题链接及其对应的帖子数量。

        返回:
        包含链接和帖子数量的列表
        """
        logging.info(f"[{self.masked_username}] 请求并解析RSS数据")
        response = requests.get(RSS_URL)
        response.raise_for_status()  # 检查请求是否成功

        # 解析XML格式的RSS数据
        root = ET.fromstring(response.content)
        items = root.findall('./channel/item')
        links = []

        # 遍历RSS中的每个项目，提取链接和帖子数量
        for item in items:
            link = item.find('link').text
            description = item.find('description').text
            num_posts = int(description.split(" 个帖子 - ")[0].split("<small>")[-1].strip())
            links.append((link, num_posts))

        logging.info(f"[{self.masked_username}] 解析完成，共提取 {len(links)} 个主题链接")
        return links

    def visit_topic(self, link, num_posts, index, total):
        """
        访问单个主题，并处理其帖子。

        参数:
        link: 主题链接
        num_posts: 帖子数量
        index: 当前主题索引
        total: 总主题数量
        """
        max_retries = 3  # 设置最大重试次数
        retries = 0
        while retries < max_retries:
            try:
                # 访问主题并等待页面加载完成
                logging.info(f"[{self.masked_username}] 访问主题链接 ({index}/{total}): {link}")
                self.driver.get(link)
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                )
                time.sleep(3)  # 访问每个主题后延迟3秒
                self.total_topics_visited += 1

                # 访问主题下的帖子部分
                self.visit_posts(link, num_posts)
                break  # 访问成功，跳出重试循环

            except Exception as e:
                retries += 1
                logging.warning(f"[{self.masked_username}] 访问主题失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                self.driver.refresh()  # 刷新页面重试
                time.sleep(2)  # 等待2秒再重试

        if retries == max_retries:
            logging.error(f"[{self.masked_username}] 多次尝试后依然无法访问: {link}，跳过此主题")

    def visit_posts(self, link, num_posts):
        """
        访问主题下的帖子部分，并包含重试机制。

        参数:
        link: 主题链接
        num_posts: 帖子数量
        """
        max_retries = 3  # 设置最大重试次数
        for i in range(2, num_posts + 1):
            sub_topic_url = f"{link}/{i}"
            retries = 0
            while retries < max_retries:
                try:
                    # 输出访问的楼层信息，并访问对应链接
                    logging.info(f"[{self.masked_username}] 访问第 {i}/{num_posts} 楼")
                    self.driver.get(sub_topic_url)
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                    )
                    self.total_posts_visited += 1
                    time.sleep(3)  # 访问每个部分后延迟3秒
                    break  # 访问成功，跳出重试循环

                except Exception as e:
                    retries += 1
                    logging.warning(f"[{self.masked_username}] 访问第 {i} 楼失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                    self.driver.refresh()  # 刷新页面重试
                    time.sleep(2)  # 等待2秒再重试

            if retries == max_retries:
                logging.error(f"[{self.masked_username}] 多次尝试后依然无法访问第 {i} 楼，跳过此帖子")

    def visit_topics(self, links):
        """
        依次访问主题部分，并计数已访问的帖子数量。

        参数:
        links: 包含主题链接和帖子数量的列表
        """
        total_topics = len(links)
        for index, (link, num_posts) in enumerate(links, start=1):
            self.visit_topic(link, num_posts, index, total_topics)

    def summarize(self):
        """
        输出运行结果总结，包括总耗时、访问的主题和帖子数量。
        """
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        summary = (
            f"[{self.masked_username}] 程序运行完成：\n"
            f" - 总耗时: {elapsed_time:.2f} 秒\n"
            f" - 访问的主题数量: {self.total_topics_visited} 个\n"
            f" - 访问的帖子数量: {self.total_posts_visited} 个\n"
        )
        logging.info(summary)

    def run(self):
        """
        线程的主运行函数，包括登录、访问主题、总结运行情况等操作。
        """
        logging.info(f"[{self.masked_username}] 程序开始运行")
        self.login()
        links = self.fetch_rss_links()
        if links:
            self.visit_topics(links)
        self.summarize()

    def close(self):
        """
        关闭浏览器并退出程序。
        """
        logging.info(f"[{self.masked_username}] 关闭浏览器并退出")
        self.driver.quit()

def load_accounts():
    """
    从环境变量加载账号信息。

    返回:
    包含账号和密码的列表
    """
    accounts_json = os.getenv('ACCOUNTS_JSON')  # 从环境变量中读取 JSON 格式的账号信息
    accounts = json.loads(accounts_json)  # 将 JSON 字符串转换为 Python 对象
    return accounts

if __name__ == "__main__":
    accounts = load_accounts()  # 加载所有账号

    browsers = []  # 存储浏览器实例
    try:
        for account in accounts:
            # 为每个账号创建独立的浏览器实例，并启动线程
            browser = LinuxDoBrowser(username=account["username"], password=account["password"])
            browsers.append(browser)
            browser.start()

        for browser in browsers:
            # 等待所有线程执行完毕
            browser.join()

    finally:
        for browser in browsers:
            # 确保程序结束时关闭所有浏览器
            browser.close()
