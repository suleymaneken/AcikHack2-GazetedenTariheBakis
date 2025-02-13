#!/usr/bin/env python
# coding: utf-8

import os
import json
import pickle
import requests
import configparser
from queue import Queue
from threading import Thread


from tqdm import tqdm
from bs4 import BeautifulSoup

from db_handler import DB_Handler
from ocr_handler import OCR_Handler
from ner_handler import NER_Handler
from solr_handler import Solr_Handler

config = configparser.ConfigParser()
config.read('settings.ini')
DATASET_URL = config["DEFAULT"]["dataset_url"]

db_gazete = DB_Handler("gazete")
db_page = DB_Handler("page")
ner = NER_Handler()
#solr = Solr_Handler()

# Queue for multithreading
row_queue = Queue()

def createDirectory(dirPath):
    if not os.path.isdir(dirPath):
        os.mkdir(dirPath)

def write_to_text(paper_json,paper_name):
    dirPath = './Papers'
    filePath = '{}/{}.txt'.format(dirPath,paper_name)
    createDirectory(dirPath)
    with open(filePath, 'w') as f:
        json.dump(paper_json, f)
    print(filePath)

def date_formatter(date):
    date_modern = date
    date_table = {
        "ikinci kanun": "01",
        "Kanunu Sani": "01",
        "şubat": "02",
        "mart": "03",
        "nisan": "04",
        "mayıs": "05",
        "haziran": "06",
        "temmuz": "07",
        "ağustos": "08",
        "eylül": "09",
        "birinci teşrin": "10",
        "teşrin-i evvel": "10",
        "ikinci teşrin": "11",
        "teşrin-i sani": "11",
        "birinci kanun": "12",
        "kanunu rvvel": "12"
    }
    for k,v in date_table.items():
        date_modern = date_modern.lower().replace(k, v)

    date_return = date_modern.split(" ")
    date_return.reverse()
    return "_".join(date_return)

def paper_download(url):
    r = requests.get(url)
    return r.content

def parallel_process():
    while True:
        row = row_queue.get()
        date = date_formatter(row.find('td').text)
        url = row.find('a')['href']
        pdf = paper_download(url)
        paper_json = {}
        paper_json['name'] = paper_name
        paper_json['date'] = date
        paper_json['url'] = url
        db_gazete.save(paper_json, pdf, "application/pdf")
        ocr = OCR_Handler(pdf)
        ocr.run()
        for i, text in enumerate(ocr.text):
            paper_json["ner"] = ner.run(text)
            paper_json["page"] = i + 1
            paper_json["text"] = text
            img_tmp = ocr.pages[i]
            db_page.save(paper_json, img_tmp, "image/png")
            #TODO: 404 Error
            #solr.index(paper_json)

        row_queue.task_done()

def paper_to_db(paper,paper_name):    
    tables = paper.findAll("div", {"class":"content"})
    print("## Processing " + paper_name)
    
    workers = [
        Thread(target=parallel_process, daemon=True)
        for _ in range(1)
    ]

    for table in tables: #gazetenin yılları
        table_body = table.find('table')
        rows = table_body.find_all('tr')
        del rows[0] #tablonun sütun adları silinir
        for row in rows: #pdfs
            row_queue.put(row)

    print("#### Running jobs for " + paper_name)
    for w in workers:
        w.start()

    for w in tqdm(workers):
        w.join()
            
    
if __name__ == '__main__':
    r = requests.get(DATASET_URL)
    soup = BeautifulSoup(r.content,"html.parser")
    divs = soup.findAll("div", {"class": "col-6 col-sm-6 col-md-4 mb-4 mb-lg-0 col-lg-2"})

    for div in divs: #tüm gazeteler
        sub_url = div.find('a')['href']
        papers_url = DATASET_URL+sub_url
        r = requests.get(papers_url)
        paper = BeautifulSoup(r.content,"html.parser")
        paper_name = str(papers_url).split("=")[1]
        paper_to_db(paper,paper_name)