import logging
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
import os  # 用于读取环境变量
import base64  # 用于 Base64 编码解码
import json  # 用于解析JSON格式的账号信息
from threading import Thread  # 多线程处理

# 设置中国北京时间时区
tz = pytz.timezone('Asia/Shanghai')

# 配置日志记录，添加时间戳，并将时间转换为北京时间
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# 将时间格式转换为北京时间
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

def mask_account(account):
    """
    对账号进行打码处理，根据账号长度动态决定保留的字符数量。

    规则：
    - 账号长度 <= 2: 全部替换为 '*'
    - 账号长度 3-5: 保留首尾字符，中间部分用 '*' 替换
    - 账号长度 6-10: 保留首尾各2个字符，中间部分用 '*' 替换
    - 账号长度 > 10: 保留首尾各3个字符，中间部分用 '*' 替换
    """
    length = len(account)
    
    if length <= 2:
        return '*' * length
    elif length <= 5:
        return account[0] + '*' * (length - 2) + account[-1]
    elif length <= 10:
        return account[:2] + '*' * (length - 4) + account[-2:]
    else:
        return account[:3] + '*' * (length - 6) + account[-3:]

class LinuxDoBrowser(Thread):
    def __init__(self, username, password):
        """
        初始化浏览器、日志信息以及统计变量。

        参数:
        - username: 登录账号
        - password: 登录密码
        """
        super().__init__()
        self.username = username
        self.password = password
        self.masked_username = mask_account(username)  # 将账号打码

        options = webdriver.ChromeOptions()

        # 使用 fake_useragent 随机生成 macOS + Google Chrome 的 User-Agent
        ua = UserAgent()

        # 生成随机的 Chrome User-Agent，并确保它来自 macOS
        user_agent = ua.random
        while "Macintosh" not in user_agent or "Chrome" not in user_agent:
            user_agent = ua.random

        options.add_argument(f'user-agent={user_agent}')

        # 其他Chrome配置
        options.add_argument('--headless')  # 无头模式
        options.add_argument('--disable-gpu')  # 禁用 GPU 加速
        options.add_argument('--no-sandbox')  # 取消沙箱模式
        options.add_argument('--disable-dev-shm-usage')  # 共享内存问题

        # 启动浏览器
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.total_topics_visited = 0  # 记录访问的主题数量
        self.total_posts_visited = 0   # 记录访问的帖子数量
        self.start_time = time.time()  # 记录程序开始时间
        logging.info(f"[{self.masked_username}] 程序启动并打开主页，使用的 User-Agent: {user_agent}")

        # Base64 编码后的URL
        HOME_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby8="
        self.HOME_URL = base64.b64decode(HOME_URL_ENCODED).decode('utf-8')

        self.driver.get(self.HOME_URL)

    def login(self):
        """
        执行登录操作，输入用户名和密码，并确认登录成功。
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

        # 提交登录
        self.driver.find_element(By.ID, "login-button").click()

        # 确认登录成功
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "current-user"))
        )
        logging.info(f"[{self.masked_username}] 登录成功")

    def fetch_rss_links(self):
        """
        请求并解析RSS数据，返回主题链接及其对应的帖子数量。

        返回:
        - 一个包含元组的列表，每个元组包含一个主题链接和帖子数量
        """
        logging.info(f"[{self.masked_username}] 请求并解析RSS数据")

        # Base64 编码后的URL
        RSS_URL_ENCODED = "aHR0cHM6Ly9saW51eC5kby9sYXRlc3QucnNz"
        RSS_URL = base64.b64decode(RSS_URL_ENCODED).decode('utf-8')

        response = requests.get(RSS_URL)
        response.raise_for_status()

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
        - link: 主题链接
        - num_posts: 主题中的帖子数量
        - index: 当前主题的索引
        - total: 主题总数量
        """
        max_retries = 3  # 设置最大重试次数
        retries = 0
        while retries < max_retries:
            try:
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
        访问主题下的帖子部分，包含重试机制。

        参数:
        - link: 主题链接
        - num_posts: 主题中的帖子数量
        """
        max_retries = 3  # 设置最大重试次数
        for i in range(2, num_posts + 1):
            sub_topic_url = f"{link}/{i}"
            retries = 0
            while retries < max_retries:
                try:
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
                logging.error(f"[{self.masked_username}] 多次尝试后依然无法访问: {sub_topic_url}，跳过此楼层")

    def run(self):
        """
        线程运行的主要逻辑，包括登录、获取RSS数据、以及逐个访问主题和帖子。
        """
        try:
            self.login()  # 登录操作
            links = self.fetch_rss_links()  # 获取RSS数据

            # 逐个访问每个主题
            for index, (link, num_posts) in enumerate(links, start=1):
                self.visit_topic(link, num_posts, index, len(links))

        finally:
            self.close()  # 关闭浏览器，并记录日志信息

    def close(self):
        """
        关闭浏览器，并输出统计日志。
        """
        elapsed_time = time.time() - self.start_time
        logging.info(f"[{self.masked_username}] 程序结束，共访问 {self.total_topics_visited} 个主题，{self.total_posts_visited} 个帖子，耗时 {elapsed_time:.2f} 秒")
        self.driver.quit()  # 关闭浏览器

def load_accounts():
    """
    从环境变量中读取并解析账号信息。

    返回:
    - 账号信息的列表，每个元素是包含用户名和密码的字典。
    """
    accounts_json = os.getenv("ACCOUNTS_JSON")
    return json.loads(accounts_json)

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
