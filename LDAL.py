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
# 日志格式中的时间转换为北京时间
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

# Base64 编码后的URL
HOME_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby8="
RSS_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby9sYXRlc3QucnNz"

# 解码Base64编码后的URL
HOME_URL = base64.b64decode(HOME_URL_ENCODED).decode('utf-8')
RSS_URL = base64.b64decode(RSS_URL_ENCODED).decode('utf-8')

# 定义浏览器自动化类，并继承自Thread类，以便支持多线程
class LinuxDoBrowser(Thread):
    def __init__(self, username, password):
        """初始化方法，用于设置浏览器配置、登录信息等"""
        super().__init__()
        self.username = username
        self.password = password

        # 初始化浏览器选项
        options = webdriver.ChromeOptions()
        ua = UserAgent()

        # 随机生成 User-Agent 并确保它是 macOS 下的 Chrome
        user_agent = ua.random
        while "Macintosh" not in user_agent or "Chrome" not in user_agent:
            user_agent = ua.random

        options.add_argument(f'user-agent={user_agent}')
        options.add_argument('--headless')  # 无头模式
        options.add_argument('--disable-gpu')  # 禁用 GPU 加速
        options.add_argument('--no-sandbox')  # 取消沙箱模式
        options.add_argument('--disable-dev-shm-usage')  # 解决共享内存问题

        # 启动浏览器并设置隐式等待时间
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.total_topics_visited = 0  # 记录访问的主题数量
        self.total_posts_visited = 0   # 记录访问的帖子数量
        self.start_time = time.time()  # 记录程序启动时间
        logging.info(f"[{self.username}] 程序启动并打开主页，使用的 User-Agent: {user_agent}")
        self.driver.get(HOME_URL)  # 打开主页

    def login(self):
        """执行登录操作"""
        logging.info(f"[{self.username}] 点击登录按钮并输入用户名和密码")
        
        # 等待并点击登录按钮
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button .d-button-label"))
        ).click()

        # 输入用户名
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-account-name"))
        ).send_keys(self.username)
        # 输入密码
        self.driver.find_element(By.ID, "login-account-password").send_keys(self.password)

        # 提交登录表单
        self.driver.find_element(By.ID, "login-button").click()

        # 确认登录成功
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "current-user"))
        )
        logging.info(f"[{self.username}] 登录成功")

    def fetch_rss_links(self):
        """请求并解析RSS数据，返回主题链接及其对应的帖子数量"""
        logging.info(f"[{self.username}] 请求并解析RSS数据")
        
        # 发起HTTP GET请求获取RSS数据
        response = requests.get(RSS_URL)
        response.raise_for_status()  # 如果请求失败，抛出异常

        # 解析RSS XML数据
        root = ET.fromstring(response.content)
        items = root.findall('./channel/item')
        links = []

        # 提取每个项目的链接和帖子数量
        for item in items:
            link = item.find('link').text
            description = item.find('description').text
            num_posts = int(description.split(" 个帖子 - ")[0].split("<small>")[-1].strip())
            links.append((link, num_posts))

        logging.info(f"[{self.username}] 解析完成，共提取 {len(links)} 个主题链接")
        return links

    def visit_topic(self, link, num_posts, index, total):
        """访问单个主题，并处理其帖子"""
        max_retries = 3  # 设置最大重试次数
        retries = 0
        while retries < max_retries:
            try:
                logging.info(f"[{self.username}] 访问主题链接 ({index}/{total}): {link}")
                self.driver.get(link)  # 打开主题链接
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                )
                time.sleep(3)  # 每次访问后等待3秒
                self.total_topics_visited += 1  # 记录已访问的主题数量

                # 访问主题下的帖子部分
                self.visit_posts(link, num_posts)
                break  # 成功访问后跳出重试循环

            except Exception as e:
                retries += 1
                logging.warning(f"[{self.username}] 访问主题失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                self.driver.refresh()  # 刷新页面并重试
                time.sleep(2)  # 等待2秒再重试

        if retries == max_retries:
            logging.error(f"[{self.username}] 多次尝试后依然无法访问: {link}，跳过此主题")

    def visit_posts(self, link, num_posts):
        """访问主题下的帖子部分，包含重试机制"""
        max_retries = 3  # 设置最大重试次数
        for i in range(2, num_posts + 1):
            sub_topic_url = f"{link}/{i}"  # 生成每个帖子的URL
            retries = 0
            while retries < max_retries:
                try:
                    logging.info(f"[{self.username}] 访问第 {i}/{num_posts} 楼")
                    self.driver.get(sub_topic_url)  # 打开帖子链接
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                    )
                    self.total_posts_visited += 1  # 记录已访问的帖子数量
                    time.sleep(3)  # 每次访问后等待3秒
                    break  # 成功访问后跳出重试循环

                except Exception as e:
                    retries += 1
                    logging.warning(f"[{self.username}] 访问第 {i} 楼失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                    self.driver.refresh()  # 刷新页面并重试
                    time.sleep(2)  # 等待2秒再重试

            if retries == max_retries:
                logging.error(f"[{self.username}] 多次尝试后依然无法访问第 {i} 楼，跳过此帖子")

    def visit_topics(self, links):
        """依次访问主题部分，并计数已访问的帖子数量"""
        total_topics = len(links)  # 计算总主题数
        for index, (link, num_posts) in enumerate(links, start=1):
            self.visit_topic(link, num_posts, index, total_topics)  # 访问每个主题

    def summarize(self):
        """输出运行结果总结"""
        end_time = time.time()
        elapsed_time = end_time - self.start_time  # 计算程序总耗时
        summary = (
            f"[{self.username}] 程序运行完成：\n"
            f" - 总耗时: {elapsed_time:.2f} 秒\n"
            f" - 访问的主题数量: {self.total_topics_visited} 个\n"
            f" - 访问的帖子数量: {self.total_posts_visited} 个\n"
        )
        logging.info(summary)

    def run(self):
        """启动浏览器自动化流程"""
        logging.info(f"[{self.username}] 程序开始运行")
        self.login()  # 执行登录操作
        links = self.fetch_rss_links()  # 获取并解析RSS数据
        if links:
            self.visit_topics(links)  # 访问所有提取到的主题
        self.summarize()  # 输出总结

    def close(self):
        """关闭浏览器"""
        logging.info(f"[{self.username}] 关闭浏览器并退出")
        self.driver.quit()  # 关闭浏览器

# 从环境变量加载账号信息的函数
def load_accounts():
    """从环境变量加载账号信息"""
    accounts_json = os.getenv('ACCOUNTS_JSON')  # 获取存储在环境变量中的 JSON 数据
    accounts = json.loads(accounts_json)  # 将 JSON 字符串解析为 Python 字典
    return accounts

# 主程序入口
if __name__ == "__main__":
    accounts = load_accounts()  # 加载账号信息

    browsers = []
    try:
        for account in accounts:
            # 为每个账号启动一个新的浏览器实例，并在独立线程中运行
            browser = LinuxDoBrowser(username=account["username"], password=account["password"])
            browsers.append(browser)
            browser.start()

        for browser in browsers:
            browser.join()  # 等待所有线程完成

    finally:
        for browser in browsers:
            browser.close()  # 关闭所有浏览器实例
