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
st.set_page_config(page_title="Mikrodrama Studio PL", layout="wide")
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

# --- 2. LOGOWANIE I AI ---
if "messages" not in st.session_state: st.session_state.messages = []
if "auth" not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.markdown("<h1 style='text-align: center; padding-top: 20vh; letter-spacing: 0.3em;'>🎬 MIKRODRAMA STUDIO PL</h1>", unsafe_allow_html=True)
    _, c2, _ = st.columns([1,1,1])
    with c2:
        u = st.text_input("AUTHOR ACCESS:", type="password", placeholder="Imię...")
        if st.button("ENTER STUDIO", use_container_width=True):
            if u.lower() in ["kasia", "julia", "fidel"]:
                st.session_state.auth, st.session_state.user = True, u.capitalize()
                st.rerun()
            else: st.error("Brak dostępu.")
    st.stop()

# Konfiguracja Gemini z wykorzystaniem Secrets
try:
    user_now = st.session_state.user.upper()
    genai.configure(api_key=st.secrets[f"GEMINI_{user_now}"])
    model = genai.GenerativeModel('gemini-3.1-pro-preview')
except Exception as e:
    st.error(f"🚨 BŁĄD: Brak klucza GEMINI_{user_now} w Secrets lub model 3.1 jest zajęty.")
    st.stop()

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
def get_season_arc(ep_str):
    try: ep = int(''.join(filter(str.isdigit, ep_str)))
    except: return "Faza: Pilotażowa."
    if ep <= 5: return "Haczyk: Budowanie uzależnienia widza. Szybkie wprowadzenie konfliktów."
    elif ep <= 20: return "Rozwinięcie: Pierwsze trupy w szafie, zdrady, nagłe zwroty akcji."
    elif ep <= 50: return "Chaos: Każdy odcinek to nowy problem, tempo maksymalne."
    else: return "Endgame: Wielki finał sezonu i brutalny cliffhanger."

def create_fdx(script_text):
    fdx_header = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n<FinalDraft DocumentType="Script" Template="Standard Screenplay" Version="4">\n<Content>\n'
    fdx_footer = '\n</Content>\n</FinalDraft>'
    paragraphs = ""
    for line in script_text.split('\n'):
        clean_line = html.escape(line.strip())
        if not clean_line: continue
        if clean_line.startswith(("INT.", "EXT.", "WIDOK", "WNĘTRZE", "PLENER")): p_type = "Scene Heading"
        elif clean_line.isupper() and len(clean_line) < 30 and not clean_line.startswith(("INT", "EXT")): p_type = "Character"
        elif "(" in clean_line and ")" in clean_line and len(clean_line) < 50: p_type = "Parenthetical"
        else: p_type = "Action" 
        paragraphs += f'<Paragraph Type="{p_type}"><Text>{clean_line}</Text></Paragraph>\n'
    return fdx_header + paragraphs + fdx_footer

# --- 5. INTERFEJS SIDEBAR ---
with st.sidebar:
    st.write(f"Autor: **{st.session_state.user}**")
    proj = st.text_input("Nazwa Projektu:", "Mój Projekt")
    active_p = proj.strip()
    
    agent = st.selectbox("Wybierz Agenta", ["Genesis PL", "Plan Sezonu PL", "Dialogi PL", "Edi PL", "Cliffhanger PL"])
    
    with st.expander("🗄️ ARCHIWUM PROJEKTÓW", expanded=False):
        try:
            all_arch = db.table("archiwum_mikro").select("projekt_nazwa").execute()
            all_names = [row['projekt_nazwa'] for row in all_arch.data] if all_arch.data else []
            unikalne_projekty = sorted(list(set([n.split(" / ")[0] for n in all_names if " / " in n])))
            
            wybrany_proj = st.selectbox("Projekt:", ["-- Wybierz --"] + unikalne_projekty)
            
            if wybrany_proj != "-- Wybierz --":
                pliki_projektu = [n for n in all_names if n.startswith(f"{wybrany_proj} / ")]
                wybrany_plik = st.selectbox("Plik:", ["-- Wybierz... --"] + pliki_projektu)
                
                if wybrany_plik != "-- Wybierz... --":
                    tresc_arch = get_system_data(wybrany_plik)
                    st.text_area("Podgląd:", value=tresc_arch, height=150, disabled=True)
                    st.download_button("⬇️ Pobierz plik (.txt)", data=tresc_arch, file_name=f"{wybrany_plik}.txt", use_container_width=True)
        except:
            st.info("Brak zapisów w bazie.")
            
    st.divider()
    dna_items = {"BIBLIA": "📖", "DRABINKA": "🪜", "MAPA": "🎯", "DOKTRYNA": "⚖️"}
    for d_key, emoji in dna_items.items():
        if get_system_data(f"SYS_{d_key}_{active_p}"):
            st.markdown(f"<div class='dna-box'>{emoji} {d_key}: <b>✅ Aktywna</b></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='dna-box' style='opacity: 0.5;'>{emoji} {d_key}: <b>❌ Brak</b></div>", unsafe_allow_html=True)
            
    with st.expander("📂 IMPORTUJ DOKUMENT (.txt, .pdf, .docx)"):
        uploaded_file = st.file_uploader("Wybierz plik", type=["txt", "pdf", "docx"], label_visibility="collapsed")
        if uploaded_file is not None:
            raw_text = ""
            try:
                if uploaded_file.type == "text/plain": raw_text = uploaded_file.read().decode("utf-8")
                elif uploaded_file.type == "application/pdf":
                    reader = PdfReader(uploaded_file)
                    for page in reader.pages: raw_text += page.extract_text() + "\n"
                elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    doc = Document(uploaded_file)
                    for para in doc.paragraphs: raw_text += para.text + "\n"
                
                if raw_text:
                    st.success(f"Wczytano: {uploaded_file.name}")
                    if st.button("Wgraj do pamięci AI", use_container_width=True):
                        save_system_data(f"SYS_PLIK_{active_p}", raw_text)
                        st.session_state.messages.append({"role": "user", "content": f"Właśnie wgrałem do Twojej pamięci dokument: '{uploaded_file.name}'. Zapoznaj się z nim i powiedz w jednym zdaniu, czy jesteś gotowy do pracy."})
                        st.rerun()
            except Exception as e: st.error(f"Błąd czytania: {e}")

# --- 6. GŁÓWNY WARSZTAT ---
c_left, c_right = st.columns([7, 3])
plik_aktywny = st.session_state.get('akt_plik', "Odcinek 1")

with c_right:
    st.markdown("### 📍 GPS FABUŁY")
    st.markdown(f"<div style='color: #d35400; font-weight: bold;'>{get_season_arc(plik_aktywny)}</div>", unsafe_allow_html=True)
    
    st.markdown("### DETEKTYW WĄTKÓW")
    o_loops = get_system_data(f"SYS_WATKI_{active_p}")
    st.text_area("Pętle", value=o_loops if o_loops else "Brak otwartych pętli.", height=100, disabled=True, label_visibility="collapsed")
    
    st.markdown("### 🧠 PAMIĘĆ SHOWRUNNERA (BRIEF)")
    o_brief = get_system_data(f"SYS_BRIEF_{active_p}")
    new_brief = st.text_area("Kluczowe ustalenia:", value=o_brief, height=150, key="brief_area")
    if st.button("Zapisz Brief", use_container_width=True):
        save_system_data(f"SYS_BRIEF_{active_p}", new_brief)
        st.success("Brief zaktualizowany!")

    st.markdown("### CIĄGŁOŚĆ WIZUALNA")
    o_szafa = get_system_data(f"SYS_SZAFA_{active_p}")
    st.text_area("Ubrania i rekwizyty", value=o_szafa if o_szafa else "Czekam na dane.", height=100, disabled=True, label_visibility="collapsed")
    
    st.markdown("### 🎭 ENCYKLOPEDIA POSTACI")
    p_data = get_db_data("postacie", active_p)
    if p_data:
        for p in p_data[-6:]:
            kolor = "#2ecc71" if p['status_obecny'] == "Aktywny" else "#e74c3c"
            st.markdown(f"**{p['imie']}** <span style='color:{kolor}; font-size:0.8rem;'>● {p['status_obecny']}</span>", unsafe_allow_html=True)
    with st.expander("🛠️ ZARZĄDZAJ OBSADĄ"):
        if p_data:
            df = pd.DataFrame(p_data)
            edited_df = st.data_editor(df[['imie', 'status_obecny', 'sejf_glosu']], use_container_width=True, num_rows="dynamic")
            if st.button("Zapisz zmiany", use_container_width=True):
                for _, row in edited_df.iterrows():
                    db.table("postacie_mikro").update({"status_obecny": row['status_obecny'], "sejf_glosu": row['sejf_glosu']}).eq("projekt_nazwa", active_p).eq("imie", row['imie']).execute()
                st.success("Obsada zaktualizowana!")
                st.rerun()
        else: st.info("Brak postaci.")
        
    st.markdown("### 📝 NOTATNIK AUTORA")
    saved_notes = get_system_data(f"SYS_NOTES_{active_p}")
    user_notes = st.text_area("Luźne zapiski:", value=saved_notes, height=200)
    if st.button("💾 ZAPISZ NOTATKI", use_container_width=True):
        save_system_data(f"SYS_NOTES_{active_p}", user_notes)
        st.success("Zapisano!")

with c_left:
    st.markdown(f"## {agent}")
    cl1, cl2, _ = st.columns([2, 2, 6])
    with cl1:
        if st.button("NOWY CZAT", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    with cl2:
        if st.button("COFNIJ", use_container_width=True):
            if len(st.session_state.messages) >= 2: st.session_state.messages = st.session_state.messages[:-2]
            st.rerun()
            
    st.divider()
    
    # 1. WYŚWIETLANIE HISTORII WIADOMOŚCI
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.write(m["content"])
        
    # 2. JEDYNE OKIENKO CZATU W APLIKACJI
    if prompt := st.chat_input("Napisz do agenta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun() 
        
    # 3. MÓZG AI: Reaguje ZAWSZE, gdy ostatnia wiadomość jest od człowieka
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Przetwarzanie danych..."):
                b_dna = get_system_data(f"SYS_BIBLIA_{active_p}")
                d_dna = get_system_data(f"SYS_DRABINKA_{active_p}")
                m_dna = get_system_data(f"SYS_MAPA_{active_p}")
                dok_dna = get_system_data(f"SYS_DOKTRYNA_{active_p}")
                plik_zewnetrzny = get_system_data(f"SYS_PLIK_{active_p}")
                brief_projektu = get_system_data(f"SYS_BRIEF_{active_p}")
                
                p_data_ai = get_db_data("postacie", active_p)
                obsada_ctx = ", ".join([f"{p['imie']} (Status: {p['status_obecny']}, Głos: {p.get('sejf_glosu', 'Standard')})" for p in p_data_ai]) if p_data_ai else "Brak zdefiniowanych postaci w bazie."
                
                akt_zadanie = st.session_state.messages[-1]["content"]
                hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-11:-1]])
                
                baza_dna = (
                    f"--- DNA PROJEKTU ---\nBiblia: {b_dna}\nDrabinka: {d_dna}\nMapa: {m_dna}\nDoktryna: {dok_dna}\n"
                    f"AKTYWNA OBSADA: {obsada_ctx}\n"
                    f"USTALENIA Z ROZMOWY (BRIEF): {brief_projektu}\n"
                    f"WGRANY DOKUMENT ZEWNĘTRZNY: {plik_zewnetrzny[:25000]}\n---\n"
                    "=== KRYTYCZNA DOKTRYNA HOOK MAP (SYSTEM VVROOM) ===\n"
                    "Każdy Agent MUSI bezwzględnie stosować poniższą inżynierię uzależnienia widza. Hook to nie tylko odcinek 1, każdy odcinek musi mieć 'hook energy'.\n\n"
                    "1. ANATOMIA ODCINKA (60-90 sekund):\n"
                    "- 0-3 sek.: Opening hook / scroll-stopper (natychmiastowe uderzenie wizualne lub tekstowe).\n"
                    "- 3-15 sek.: Immediate conflict (natychmiastowy konflikt).\n"
                    "- 15-35 sek.: Eskalacja napięcia.\n"
                    "- 35-50 sek.: Twist, odwrócenie ról (reversal) lub cios emocjonalny.\n"
                    "- 50-90 sek.: Ending cliffhook (zmusza do bezwarunkowego kliknięcia w kolejny odcinek).\n\n"
                    "2. ARCHITEKTURA SEZONU (90 Odcinków):\n"
                    "- Odc. 1-10 (Premise ignition): Sprzedaj główną fantazję, ranę, niesprawiedliwość lub nierównowagę sił. Odc. 1 musi mieć najsilniejszy opening hook.\n"
                    "- Odc. 11-20 (Binge lock): Zmień ciekawość w uzależnienie. Rywalizacja, szantaż, fałszywa nadzieja, przerwana bliskość.\n"
                    "- Odc. 21-30 (First major reversal): Pierwsze wielkie odwrócenie sytuacji. Zmiana układu sił, ukryte dowody, zdrada kogoś bliskiego.\n"
                    "- Odc. 31-40 (Hero becomes active): Bohaterka przestaje tylko cierpieć i zaczyna działać (zemsta, uwodzenie, sojusze).\n"
                    "- Odc. 41-50 (Midpoint explosion): Eksplozja w połowie sezonu (np. publiczne ujawnienie, fałszywa śmierć) i jej natychmiastowe konsekwencje.\n"
                    "- Odc. 51-60 (Deeper secret layer): Odkrycie, że widoczny dotąd konflikt to tylko wierzchołek góry lodowej (ukryte pokrewieństwo, stare zbrodnie). Widz musi zacząć reinterpretować wcześniejsze odcinki.\n"
                    "- Odc. 61-70 (Darkest stretch): Maksymalny ból emocjonalny, izolacja, szantaż, utrata pozycji. Ale każdy odcinek wciąż musi pchać akcję do przodu.\n"
                    "- Odc. 71-80 (Endgame setup): Nadzieja wraca, plan wchodzi w życie, ujawnia się ukryty sojusznik.\n"
                    "- Odc. 81-89 (Final collision): Ostateczne zderzenie i spłata wszystkich obietnic (payoff). Ujawnienie prawdy, sprawiedliwość, zemsta.\n"
                    "- Odc. 90 (Payoff + future hook): Emocjonalne domknięcie wątków + nowy hook na przyszłość (np. nowe zagrożenie, ciąża, ukryta wiadomość).\n\n"
                    "3. ZASADY JAKOŚCI I ANTY-POWTÓRZENIA (ZAKAZ TANIOCHY):\n"
                    "- Zakaz leniwego pisania! Masz unikać ciągłych fizycznych uderzeń w twarz, zbyt wielu przerwanych pocałunków, fałszywych ciąż i tanich szoków.\n"
                    "- Używaj inteligentnych, zróżnicowanych hooków: Revelation (Odkrycie np. 'Ona jest twoją córką'), Threat (Groźba np. 'Podpisz to albo stracisz wszystko'), Moral (Dylemat moralny), Status (Społeczna degradacja, wyrzucenie z pracy), Desire (Zakazane pożądanie, zazdrość).\n"
                    "- Hooki mają być emocjonalne, ostre, uzależniające i mocno osadzone w psychologii postaci.\n"
                    "====================================================\n"
                )
                
                # --- PROMPTY Z POLSKIMI REALIAMI ---
                if agent == "Genesis PL":
                    sp = (
                        "Jesteś Agentem Genesis Mikrodrama PL (Główny Showrunner, Kreator Psychologii i Twój Partner).\n"
                        "TRYB PRACY (KRYTYCZNE): Jesteśmy w writers' roomie. Rozmawiasz ze mną krok po kroku. ZAKAZ 'wypluwania' od razu gotowej koncepcji. Zadawaj max 2 pytania, proponuj warianty A/B/C i ZAWSZE czekaj na moją decyzję.\n"
                        "OSOBOWOŚĆ (BARDZO WAŻNE): MASZ ABSOLUTNY ZAKAZ BYCIA POTAKIWACZEM! Jesteś bezlitosnym, doświadczonym polskim twórcą. Jeśli mój pomysł jest nudny, płaski, przewidywalny lub sztampowy – POWIEDZ MI TO WPROST. Kłóć się ze mną, wymagaj głębszej psychologii. Jeśli proponuję banał, skrytykuj to i podsuń o wiele bardziej bezczelną, mroczną i wielowymiarową alternatywę. Broń jakości!\n"
                        "GRUPA DOCELOWA: Kobiety 20-45 lat. Oczekują silnych, psychologicznych emocji, walki o pozycję, toksycznych relacji, trudnych macierzyństw i ukrytych pragnień.\n"
                        "TON I STYL: Konflikty w białych rękawiczkach. Rzecz dzieje się w POLSCE – to mogą być duże miasta, ale też bogate przedmieścia mniejszych miejscowości, układy w lokalnym samorządzie, zamknięte społeczności, rodzinne firmy. ZAKAZ ograniczania się tylko do Warszawy! ZAKAZ patologii, 'wujków z flaszką' i biedy rodem z dokumentów. Ma być duszno od tajemnic, elegancko, ale mrocznie.\n"
                        "BOHATEROWIE: Nikt nie jest idealny. Każda postać musi mieć 'fatal flaw' (skazę), mroczny sekret i ukryty motyw finansowy lub emocjonalny. Twórz gęstą siatkę relacji.\n"
                        f"{baza_dna}"
                    )
                elif agent == "Plan Sezonu PL":
                    sp = (
                        "Jesteś Architektem Fabuły (Season Architect) polskiej mikrodramy aktorskiej.\n"
                        "ZADANIE: Rozpisujesz odcinki precyzyjnie według 'DOKTRYNY HOOK MAP'.\n"
                        "DYREKTYWY PRODUKCYJNE: Każdy odcinek to 60-90 sekund. Żadnej ekspozycji. "
                        "Lokacje muszą być tanie w produkcji, ale efektowne emocjonalnie i typowo polskie (nowoczesny dom pod lasem, wnętrze drogiego SUV-a, zaplecze lokalnego butiku, gabinet notariusza, stół podczas rodzinnego obiadu).\n"
                        "ZASADA DYNAMIKI: Każdy odcinek musi pchać fabułę do przodu i nieodwracalnie zmieniać status quo. ZAKAZ fillerów. "
                        "Zawsze podawaj, co jest Opening Hookiem, a co Ending Cliffhookiem w danym odcinku.\n"
