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

# 设置中国北京时间时区
tz = pytz.timezone('Asia/Shanghai')

# 配置日志记录，添加时间戳，并将时间转换为北京时间
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

# 从环境变量中读取用户名和密码
USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')

# 主页URL与RSS URL
HOME_URL = "https://linux.do/"
RSS_URL = "https://linux.do/latest.rss"

class LinuxDoBrowser:
    def __init__(self):
        """初始化浏览器、日志信息以及统计变量"""
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
        logging.info(f"程序启动并打开主页，使用的 User-Agent: {user_agent}")
        self.driver.get(HOME_URL)

    def login(self):
        """执行登录操作"""
        logging.info("点击登录按钮并输入用户名和密码")
        
        # 点击登录按钮
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button .d-button-label"))
        ).click()

        # 输入用户名和密码
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-account-name"))
        ).send_keys(USERNAME)
        self.driver.find_element(By.ID, "login-account-password").send_keys(PASSWORD)

        # 提交登录
        self.driver.find_element(By.ID, "login-button").click()

        # 确认登录成功
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "current-user"))
        )
        logging.info("登录成功")

    def fetch_rss_links(self):
        """请求并解析RSS数据，返回主题链接及其对应的帖子数量"""
        logging.info("请求并解析RSS数据")
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

        logging.info(f"解析完成，共提取 {len(links)} 个主题链接")
        return links

    def visit_topic(self, link, num_posts, index, total):
        """访问单个主题，并处理其帖子"""
        max_retries = 3  # 设置最大重试次数
        retries = 0
        while retries < max_retries:
            try:
                logging.info(f"访问主题链接 ({index}/{total}): {link}")
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
                logging.warning(f"访问主题失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                self.driver.refresh()  # 刷新页面重试
                time.sleep(2)  # 等待2秒再重试

        if retries == max_retries:
            logging.error(f"多次尝试后依然无法访问: {link}，跳过此主题")

    def visit_posts(self, link, num_posts):
        """访问主题下的帖子部分，包含重试机制"""
        max_retries = 3  # 设置最大重试次数
        for i in range(2, num_posts + 1):
            sub_topic_url = f"{link}/{i}"
            retries = 0
            while retries < max_retries:
                try:
                    # 将输出改为显示第几楼，并加上楼层进度
                    logging.info(f"访问第 {i}/{num_posts} 楼")
                    self.driver.get(sub_topic_url)
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                    )
                    self.total_posts_visited += 1
                    time.sleep(3)  # 访问每个部分后延迟3秒
                    break  # 访问成功，跳出重试循环

                except Exception as e:
                    retries += 1
                    logging.warning(f"访问第 {i} 楼失败，正在重试 ({retries}/{max_retries})... 错误信息: {e}")
                    self.driver.refresh()  # 刷新页面重试
                    time.sleep(2)  # 等待2秒再重试

            if retries == max_retries:
                logging.error(f"多次尝试后依然无法访问第 {i} 楼，跳过此帖子")

    def visit_topics(self, links):
        """依次访问主题部分，并计数已访问的帖子数量"""
        total_topics = len(links)
        for index, (link, num_posts) in enumerate(links, start=1):
            self.visit_topic(link, num_posts, index, total_topics)

    def summarize(self):
        """输出运行结果总结"""
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        summary = (
            f"程序运行完成：\n"
            f" - 总耗时: {elapsed_time:.2f} 秒\n"
            f" - 访问的主题数量: {self.total_topics_visited} 个\n"
            f" - 访问的帖子数量: {self.total_posts_visited} 个\n"
        )
        logging.info(summary)

    def run(self):
        """启动浏览器自动化流程"""
        logging.info("程序开始运行")
        self.login()  # 登录失败会直接终止
        links = self.fetch_rss_links()  # RSS解析失败会直接终止
        if links:
            self.visit_topics(links)
        self.summarize()

    def close(self):
        """关闭浏览器"""
        logging.info("关闭浏览器并退出")
        self.driver.quit()


if __name__ == "__main__":
    browser = LinuxDoBrowser()
    try:
        browser.run()
    finally:
        browser.close()
