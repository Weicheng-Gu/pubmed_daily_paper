#! usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Wei-cheng Gu
# Date: 2025-11-24


import os
import requests
import xmltodict
import smtplib
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import pandas as pd

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime


info = pd.read_csv('info.txt', sep='\t', quotechar='~')

def fetch_new_papers(keyword, counts):
    """使用 requests 从 PubMed 获取过去 1 天更新的文献"""

    base_esearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_efetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    term = keyword

    print(f"正在搜索关键词: {term} ...")

    # ========== 1) ESearch：获取 PMID 列表 ==========
    try:
        esearch_params = {
            "db": "pubmed",
            "term": term,
            "reldate": 1,          # 最近1天
            "datetype": "pdat",    # 发表日期
            "retmax": counts,
            "retmode": "xml",
        }

        # verify=False 绕过 SSL 证书验证
        r = requests.get(base_esearch, params=esearch_params, verify=False)
        esearch_data = xmltodict.parse(r.text)

        # 取出 Id 字段
        id_field = (
            esearch_data
            .get("eSearchResult", {})
            .get("IdList", {})
            .get("Id", [])
        )

        # 统一转成字符串 list
        id_list = []
        if isinstance(id_field, list):
            for x in id_field:
                if isinstance(x, dict):
                    # 例如 {'#text': '12345678'}
                    id_list.append(x.get("#text", "").strip())
                else:
                    # 例如 '12345678'
                    id_list.append(str(x).strip())
        elif isinstance(id_field, dict):
            id_list.append(id_field.get("#text", "").strip())
        elif isinstance(id_field, str):
            id_list.append(id_field.strip())

        # 去掉空字符串
        id_list = [pmid for pmid in id_list if pmid]

        if not id_list:
            print("未找到新文献。")
            return []

        print(f"找到 {len(id_list)} 篇新文献，正在获取详情...")

    except Exception as e:
        print(f"ESearch 出错: {e}")
        return []

    # ========== 2) EFetch：根据 PMID 获取详情 ==========
    try:
        efetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "xml"
        }

        r = requests.get(base_efetch, params=efetch_params, verify=False)
        data = xmltodict.parse(r.text)

        papers_data = data.get("PubmedArticleSet", {}).get("PubmedArticle", [])
        if isinstance(papers_data, dict):  # 只有一篇文章时
            papers_data = [papers_data]

    except Exception as e:
        print(f"EFetch 出错: {e}")
        return []

    # ========== 3) 解析 PubMed XML ==========
    papers = []

    for article in papers_data:
        try:
            citation = article["MedlineCitation"]
            article_info = citation["Article"]

            # 标题
            title = article_info.get("ArticleTitle", "")

            # 期刊
            journal_info = article_info.get("Journal", {})
            journal_title = journal_info.get("Title", "")

            # 摘要
            abstract_xml = article_info.get("Abstract", {}).get("AbstractText", [])
            if isinstance(abstract_xml, list):
                abstract = " ".join([str(a) for a in abstract_xml])
            else:
                abstract = str(abstract_xml) if abstract_xml else "No Abstract Available."

            # PMID
            pmid = citation["PMID"]["#text"]

            # DOI
            doi = ""
            id_list_xml = article["PubmedData"]["ArticleIdList"]["ArticleId"]
            if isinstance(id_list_xml, dict):
                id_list_xml = [id_list_xml]
            for id_obj in id_list_xml:
                if id_obj.get("@IdType") == "doi":
                    doi = id_obj.get("#text", "")
                    break

            papers.append({
                "title": title,
                "journal": journal_title,
                "abstract": abstract,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "doi": doi
            })

        except Exception as e:
            print(f"解析某篇文章失败: {e}")
            continue

    return papers


def summarize_paper(keyword, paper_info):
    """调用 DeepSeek 总结医学文献（优化版）"""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    prompt = f"""
你是一名{keyword}方向的高级科学家，请根据以下 PubMed 文献的标题和摘要，
用**严谨、客观、简洁**的风格，输出一份中文总结。
标题: {paper_info['title']}
摘要: {paper_info['abstract']}

请严格遵守以下格式：

【核心总结】
- 用一两句话浓缩本文最核心的研究发现或贡献。

【期刊信息】
- 期刊：{paper_info['journal']}
- 查询{paper_info['journal']}的最新的影响因子和中科院分区并给出

【研究关键点】
1）研究方法（Methods）
   - 说明研究使用了什么数据/实验/模型/分析方法（不要编造原文没有的信息）。

2）主要结果（Results）
   - 简要的总结最关键的结果和发现（不要编造原文没有的信息）。

3）研究意义（Conclusion）
   - 文章对领域的重要性、潜在影响、临床或生物学意义（不要编造原文没有的信息）。

请严格根据摘要内容，不要进行推测或编造。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一名擅长高质量论文总结的专家。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"AI 总结失败: {e}"

def send_email():
    """发送 HTML 格式邮件"""



    date_str = datetime.now().strftime("%Y-%m-%d")

    for person in set(info['name']):
        # 1. 创建邮件对象
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        
        # 2. 构建 HTML 内容
        html_content = f"<h2>PubMed 文献更新 - {date_str}</h2><hr>"

        info_ind = info[info["name"] == person].copy()
        msg['To'] = info_ind.iloc[0, -1]
        RECEIVER_EMAIL = info_ind.iloc[0, -1]

        paper_counts = 0

        for keyword in info_ind['keywords']:
            counts = info_ind[info_ind['keywords'] == keyword]['counts']
            papers = fetch_new_papers(keyword, counts)

            if not papers:
                print("该关键词未检索到文献。")
                continue

            paper_counts += len(papers)

            html_content += f"""
                    <h2 style="color:#1a73e8; margin-top:30px; margin-bottom:10px; font-family:'Microsoft YaHei', Arial, sans-serif;">
                        📌 关键词：{keyword}
                    </h2>
                    <hr style="border:0; border-top:2px solid #1a73e8; margin-bottom:20px;">
                    """
            for idx, paper in enumerate(papers, 1):
                title = paper.get("title", "")
                abstract = paper.get("abstract", "")

                # 防止 title/abstract 是奇怪类型
                if not isinstance(title, str) or not isinstance(abstract, str):
                    print(f"文献信息格式异常（title/abstract 不是字符串），跳过：{paper.get('url', '')}")
                    continue

                summary = summarize_paper(keyword, paper)

                print(f"正在总结关键词为 {keyword} 的第 {idx} 篇: {title[:30]}...")

                html_content += f"""
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #2c3e50;">{idx}. {title}</h3>
                    <p><b>链接:</b> <a href="{paper['url']}" target="_blank">{paper['url']}</a></p>
                    <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; border-radius: 4px;">
                        <b>AI 总结:</b><br>
                        <pre style="white-space: pre-wrap; font-family: 'Microsoft YaHei', sans-serif; color: #333;">{summary}</pre>
                    </div>
                </div>
                <hr style="border: 0; border-top: 1px solid #eee;">
                """

        # 3. 设置邮件主题
        subject_text = f"PubMed 每日推送: {paper_counts} 篇 ({date_str})"
        msg['Subject'] = Header(subject_text, 'utf-8')
        # 4. 将 HTML 正文添加到邮件中（指定 utf-8 编码）
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        # 5. 发送邮件
        try:
            print("正在连接邮件服务器...")
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            print(f"邮件发送成功！已发送至 {RECEIVER_EMAIL}")
        except Exception as e:
            print(f"邮件发送失败: {e}")

# 配置信息
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465

SENDER_EMAIL = os.getenv("SENDER_EMAIL")  # 发件人邮箱
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") # 邮箱授权码 (非登录密码)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("错误: 未设置 OPENAI_API_KEY")
    else:
        print("开始执行每日抓取任务...")
        send_email()

