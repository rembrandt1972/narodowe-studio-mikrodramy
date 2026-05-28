import streamlit as st
import google.generativeai as genai
from supabase import create_client
import html
import pandas as pd
import json
import re
from PyPDF2 import PdfReader
from docx import Document
import io

# --- 1. KONFIGURACJA I UI ---
st.set_page_config(page_title="Mikrodrama Studio PL (Wersja PRO)", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'Helvetica Neue', sans-serif; font-weight: 300; background: #fff; }
h1, h2, h3 { font-weight: 300 !important; color: #1a1a1a !important; }
h1 { font-size: 1.8rem !important; margin-bottom: 1.5rem !important; }
h2 { font-size: 1.3rem !important; border-bottom: 1px solid #eee; padding-bottom: 0.5rem; margin-top: 2rem !important; }
h3 { font-size: 0.9rem !important; text-transform: uppercase; letter-spacing: 0.12em; color: #999; margin-top: 1.5rem !important; }
.stButton>button { border: 1px solid #e0e0e0 !important; background: #fff !important; color: #444 !important; font-weight: 300; border-radius: 2px; transition: 0.2s; padding: 0.4rem 1rem; width: 100%; }
.stButton>button:hover { border-color: #000 !important; color: #000 !important; background: #f8f8f8 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.stDownloadButton>button { background: #1a1a1a !important; color: #fff !important; border: none !important; margin-top: 10px; }
.stDownloadButton>button:hover { background: #333 !important; }
.stTextArea textarea { font-family: 'Georgia', serif !important; font-size: 1rem !important; border: 1px solid #f0f0f0 !important; }
.tip-text { font-size: 0.75rem; color: #aaa; padding: 10px; border-left: 2px solid #f0f0f0; margin-bottom: 15px; background: #fafafa; }
.dna-box { font-size: 0.8rem; padding: 8px; border-radius: 4px; margin-bottom: 8px; border: 1px solid #e0e0e0; background: #f9f9f9; color: #333; }
pre, code, .stMarkdown p { white-space: pre-wrap !important; word-wrap: break-word !important; }
</style>
""", unsafe_allow_html=True)

# --- 2. SESJA I LOGOWANIE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "auth" not in st.session_state: st.session_state.auth = False
if "active_file" not in st.session_state: st.session_state.active_file = "1"
if "n_final" not in st.session_state: st.session_state.n_final = "Odcinek 1"

if not st.session_state.auth:
    st.markdown("<h1 style='text-align: center; padding-top: 20vh; letter-spacing: 0.3em;'>🎬 MIKRODRAMA STUDIO PL</h1>", unsafe_allow_html=True)
    _, c2, _ = st.columns([1,1,1])
    with c2:
        u = st.text_input("AUTHOR ACCESS:", type="password", placeholder="Imię...")
        if st.button("ENTER STUDIO", use_container_width=True):
            # POPRAWKA: .strip() usuwa przypadkowe spacje, .lower() normalizuje wielkość
            if u.strip().lower() in ["kasia", "julia", "fidel"]:
                st.session_state.auth, st.session_state.user = True, u.strip().capitalize()
                st.rerun()
            else: st.error("Brak dostępu. Sprawdź imię.")
    st.stop()

# Konfiguracja Gemini
try:
    user_now = st.session_state.user.upper()
    genai.configure(api_key=st.secrets[f"GEMINI_{user_now}"])
    model = genai.GenerativeModel('gemini-3.1-pro-preview')
except Exception as e:
    st.error(f"🚨 BŁĄD: Brak klucza GEMINI_{user_now} w Secrets lub problem z API.")
    st.stop()

safe_config = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
db = init_db()

# --- 3. BAZA DANYCH (_MIKRO) ---
def get_system_data(key):
    try:
        res = db.table("archiwum_mikro").select("tresc").eq("projekt_nazwa", key).execute()
        return res.data[0]["tresc"] if res.data else ""
    except: return ""

def save_system_data(key, content):
    if not content.strip(): return
    try:
        db.table("archiwum_mikro").delete().eq("projekt_nazwa", key).execute()
        db.table("archiwum_mikro").insert({"projekt_nazwa": key, "tresc": content.replace('\x00', ''), "agent": "System"}).execute()
    except: pass

def get_db_data(table, project):
    table_name = f"{table}_mikro"
    try:
        res = db.table(table_name).select("*").eq("projekt_nazwa", project).execute()
        return res.data
    except: return []

# --- 4. STRUKTURA SEZONU MIKRODRAMY ---
def get
