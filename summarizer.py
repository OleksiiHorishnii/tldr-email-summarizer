import requests
import json
from bs4 import BeautifulSoup
import re

from llm import llm


def html_to_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text()

    # Replace sequences of whitespace characters with a single space or newline
    def replacer(match):
        # if the matched string contains a newline, replace with newline, otherwise replace with space
        return '\n' if '\n' in match.group() else ' '

    text = re.sub(r'[ \t\n]+', replacer, text)

    return text.strip()  # Removing any trailing or leading whitespace


def email_to_prompt(email):
    subject = email.get('header', {}).get('subject', '')
    author = email.get('header', {}).get('author', '')
    body = html_to_text(email.get('body', ''))
    return f"""
Subject: {subject}
Author: {author}

EMAIL BODY BELOW THIS LINE

{body}
"""


def summarize(email):
    threshold = 150
    prompt = email_to_prompt(email)
    result, reason = llm(prompt)
    if not result:
        return None, reason
    summary = result.get('summary', '')
    body = html_to_text(email['body'])
    if len(body) <= threshold:
        result['summary'] = body
        result['is_full_message'] = True
    elif not summary:
        result['summary'] = body[:threshold]
        result['is_uprocessed_summary'] = True
    return result, "Success"
