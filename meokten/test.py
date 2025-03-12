import streamlit as st
import sqlite3
import requests


db_url = "https://github.com/jinucho/Meokten/blob/main/meokten/meokten.db"

response = requests.get(db_url)

with open("meokten.db", "wb") as file:
    file.write(response.content)

db = sqlite3.connect("meokten.db")

cursor = db.cursor()

query = st.text_input("쿼리를 입력하세요.")

cursor.execute(query)

results = cursor.fetchall()

st.write(results)
