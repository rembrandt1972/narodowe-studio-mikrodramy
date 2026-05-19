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
    proj = st.text_input("Nazwa Projektu:", "Zdrada na Wilanowie")
    active_p = proj.strip()
    
    agent = st.selectbox("Wybierz Agenta", ["Genesis PL", "Plan Sezonu PL", "Dialogi PL", "Edi PL", "Cliffhanger PL"])
    
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
                    if st.button("Wstrzyknij treść do czatu", use_container_width=True):
                        st.session_state.messages.append({"role": "user", "content": f"WPROWADZAM DOKUMENT EXTERNAL ({uploaded_file.name}):\n\n{raw_text}\n\nPotwierdź odbiór."})
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
        
    # 2. POBIERANIE WIADOMOŚCI Z OKIENKA
    if prompt := st.chat_input("Napisz do agenta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun() # Przeładowujemy, by od razu pokazać wpisany tekst
        
    # 3. MÓZG AI: Reaguje ZAWSZE, gdy ostatnia wiadomość jest od człowieka (Czat LUB Wgrany Plik)
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Przetwarzanie danych..."):
                b_dna = get_system_data(f"SYS_BIBLIA_{active_p}")
                d_dna = get_system_data(f"SYS_DRABINKA_{active_p}")
                m_dna = get_system_data(f"SYS_MAPA_{active_p}")
                dok_dna = get_system_data(f"SYS_DOKTRYNA_{active_p}")
                
                # Pobieramy bieżące zadanie (tekst z okienka LUB treść wgranego pliku)
                akt_zadanie = st.session_state.messages[-1]["content"]
                
                # Do historii bierzemy ostatnie wiadomości, pomijając to najnowsze zadanie
                hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-11:-1]])
                
                baza_dna = (
                    f"--- DNA PROJEKTU ---\nBiblia: {b_dna}\nDrabinka: {d_dna}\nMapa: {m_dna}\nDoktryna: {dok_dna}\n---\n"
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
                
                # --- PROMPTY Z POLSKIMI REALIAMI (Cała Polska, nie tylko Warszawa) ---
                if agent == "Genesis PL":
                    sp = (
                        "Jesteś Agentem Genesis Mikrodrama PL (Główny Showrunner, Kreator Psychologii i Twój Partner).\n"
                        "TRYB PRACY (KRYTYCZNE): Jesteśmy w writers' roomie. Rozmawiasz ze mną krok po kroku. ZAKAZ 'wypluwania' od razu gotowej koncepcji. Zadawaj max 2 pytania, proponuj warianty A/B/C i ZAWSZE czekaj na moją decyzję.\n"
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
                        f"{baza_dna}\nOtwarte Pętle: {o_loops}"
                    )
                elif agent == "Dialogi PL":
                    sp = (
                        "Jesteś elitarnym Polskim Scenarzystą. Format pionowy (9:16), żywi aktorzy.\n"
                        "JĘZYK (Wykrywacz Fałszu): 100% po polsku. Aktorzy mają to mówić naturalnie. Krótkie zdania, przerywanie sobie (używaj '-'), wulgaryzmy tylko z solidnym uzasadnieniem. ZAKAZ 'szeleszczącego papieru' i ZAKAZ ekspozycji (postacie nie mówią rzeczy, o których oboje od dawna wiedzą).\n"
                        "PODTEKST: Polacy są mistrzami pasywnej agresji. Pisz podtekstem. Postacie mają kłamać, unikać odpowiedzi i atakować z ukrycia z uśmiechem na twarzy.\n"
                        "WIZUALIA (9:16): Używaj didaskaliów pod kamerę pionową. Skup się na mikrowyrazach twarzy, drżących dłoniach, spojrzeniach w lusterko samochodowe. To detale budują napięcie w pionie.\n"
                        f"{baza_dna}"
                    )
                elif agent == "Edi PL":
                    sp = (
                        "Jesteś Edi, bezlitosny Redaktor Naczelny i 'Wykrywacz Cringe'u'.\n"
                        "ZADANIE: Skanujesz tekst i miażdżysz go, jeśli:\n"
                        "1. Dialog brzmi jak z taniej telenoweli lub polskiego kabaretu.\n"
                        "2. Bohaterowie mówią o swoich uczuciach wprost zamiast to pokazać (Show, don't tell).\n"
                        "3. Autor zaszalał z budżetem (pościgi) lub zapomniał, że rzecz dzieje się w polskich realiach.\n"
                        "Okrutnie i z polskim sarkazmem wytykaj błędy. JEDNAKŻE: gdy użytkownik pisze 'CZYSTY TEKST' lub 'PODAJ GOTOWE', wyłączasz tryb komentatora i podajesz sam bezbłędny, poprawiony scenariusz.\n"
                        f"{baza_dna}"
                    )
                elif agent == "Cliffhanger PL":
                    sp = (
                        "Jesteś Bezlitosnym Sędzią Retencji (Hook Validator) na polskiego TikToka/Reels.\n"
                        "TWOJA MISJA: Oceniasz tylko pierwsze 3 sekundy (Scroll-stopper) i ostatnie 5 sekund (Cliffhook).\n"
                        "ZASADY ODRZUCANIA: Jeśli hook opiera się na tanim wypadku, chorobie czy upadku ze schodów - ODRZUCASZ GO z obrzydzeniem. Żądasz ciosów psychologicznych: publicznego upokorzenia w małej społeczności, szantażu majątkowego, odkrycia fałszywego aktu notarialnego, zdrady wspólnika.\n"
                        "FORMAT: Zawsze zaczynaj od werdyktu: [🔥 OCENA X/10] -> [🟢 ZATWIERDZONY] lub [🔴 ODRZUCONY]. Następnie daj jedno zdanie brutalnej prawdy i radę ('Prestige Punch-up'), jak podbić napięcie o 100%.\n"
                        f"{baza_dna}"
                    )
                    
                zakaz = "\n\nKRYTYCZNA DYREKTYWA: Zwróć WYŁĄCZNIE surowy tekst wynikowy. MASZ ABSOLUTNY ZAKAZ dodawania jakichkolwiek powitań, komentarzy od siebie typu 'Oto tekst' czy podsumowań. TYLKO treść." if agent != "Edi PL" else ""
                
                try:
                    # Wysyłamy teraz CAŁE zadanie - czy to wpisane z ręki, czy wgrane z pliku!
                    resp = model.generate_content(f"{sp}\nHISTORIA CZATU:\n{hist}\nZADANIE:\n{akt_zadanie}{zakaz}").text
                    st.session_state.messages.append({"role": "assistant", "content": resp})
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd generacji AI: {e}")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.write(m["content"])
        
    if prompt := st.chat_input("Napisz do agenta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.write(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Przetwarzanie danych..."):
                b_dna = get_system_data(f"SYS_BIBLIA_{active_p}")
                d_dna = get_system_data(f"SYS_DRABINKA_{active_p}")
                m_dna = get_system_data(f"SYS_MAPA_{active_p}")
                dok_dna = get_system_data(f"SYS_DOKTRYNA_{active_p}")
                hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-10:]])
                baza_dna = (
                    f"--- DNA PROJEKTU ---\nBiblia: {b_dna}\nDrabinka: {d_dna}\nMapa: {m_dna}\nDoktryna: {dok_dna}\n---\n"
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
                # --- PROMPTY Z POLSKIMI REALIAMI (Cała Polska, nie tylko Warszawa) ---
                if agent == "Genesis PL":
                    sp = (
                        "Jesteś Agentem Genesis Mikrodrama PL (Główny Showrunner, Kreator Psychologii i Twój Partner).\n"
                        "TRYB PRACY (KRYTYCZNE): Jesteśmy w writers' roomie. Rozmawiasz ze mną krok po kroku. ZAKAZ 'wypluwania' od razu gotowej koncepcji. Zadawaj max 2 pytania, proponuj warianty A/B/C i ZAWSZE czekaj na moją decyzję.\n"
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
                        f"{baza_dna}\nOtwarte Pętle: {o_loops}"
                    )
                elif agent == "Dialogi PL":
                    sp = (
                        "Jesteś elitarnym Polskim Scenarzystą. Format pionowy (9:16), żywi aktorzy.\n"
                        "JĘZYK (Wykrywacz Fałszu): 100% po polsku. Aktorzy mają to mówić naturalnie. Krótkie zdania, przerywanie sobie (używaj '-'), wulgaryzmy tylko z solidnym uzasadnieniem. ZAKAZ 'szeleszczącego papieru' i ZAKAZ ekspozycji (postacie nie mówią rzeczy, o których oboje od dawna wiedzą).\n"
                        "PODTEKST: Polacy są mistrzami pasywnej agresji. Pisz podtekstem. Postacie mają kłamać, unikać odpowiedzi i atakować z ukrycia z uśmiechem na twarzy.\n"
                        "WIZUALIA (9:16): Używaj didaskaliów pod kamerę pionową. Skup się na mikrowyrazach twarzy, drżących dłoniach, spojrzeniach w lusterko samochodowe. To detale budują napięcie w pionie.\n"
                        f"{baza_dna}"
                    )
                elif agent == "Edi PL":
                    sp = (
                        "Jesteś Edi, bezlitosny Redaktor Naczelny i 'Wykrywacz Cringe'u'.\n"
                        "ZADANIE: Skanujesz tekst i miażdżysz go, jeśli:\n"
                        "1. Dialog brzmi jak z taniej telenoweli lub polskiego kabaretu.\n"
                        "2. Bohaterowie mówią o swoich uczuciach wprost zamiast to pokazać (Show, don't tell).\n"
                        "3. Autor zaszalał z budżetem (pościgi) lub zapomniał, że rzecz dzieje się w polskich realiach.\n"
                        "Okrutnie i z polskim sarkazmem wytykaj błędy. JEDNAKŻE: gdy użytkownik pisze 'CZYSTY TEKST' lub 'PODAJ GOTOWE', wyłączasz tryb komentatora i podajesz sam bezbłędny, poprawiony scenariusz.\n"
                        f"{baza_dna}"
                    )
                elif agent == "Cliffhanger PL":
                    sp = (
                        "Jesteś Bezlitosnym Sędzią Retencji (Hook Validator) na polskiego TikToka/Reels.\n"
                        "TWOJA MISJA: Oceniasz tylko pierwsze 3 sekundy (Scroll-stopper) i ostatnie 5 sekund (Cliffhook).\n"
                        "ZASADY ODRZUCANIA: Jeśli hook opiera się na tanim wypadku, chorobie czy upadku ze schodów - ODRZUCASZ GO z obrzydzeniem. Żądasz ciosów psychologicznych: publicznego upokorzenia w małej społeczności, szantażu majątkowego, odkrycia fałszywego aktu notarialnego, zdrady wspólnika.\n"
                        "FORMAT: Zawsze zaczynaj od werdyktu: [🔥 OCENA X/10] -> [🟢 ZATWIERDZONY] lub [🔴 ODRZUCONY]. Następnie daj jedno zdanie brutalnej prawdy i radę ('Prestige Punch-up'), jak podbić napięcie o 100%.\n"
                        f"{baza_dna}"
                    )
st.divider()

k1, k2, k3 = st.columns([2, 2, 1])
with k1: 
    plik = st.text_input("NAZWA PLIKU (np. Odcinek 1):", value=plik_aktywny, key="n_final")
    st.session_state.akt_plik = plik
with k2: stat = st.selectbox("STATUS", ["Robocze", "Gotowe", "Kanon"])

ostatni_tekst = st.session_state.messages[-1]["content"].replace('\x00', '') if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant" else ""

st.markdown("### 👀 PODGLĄD DO ZAPISU (EDYTUJ PRZED ZAPISEM)")
txt_to_save = st.text_area("Treść do zapisu:", value=ostatni_tekst, height=250, label_visibility="collapsed")

c1, c2 = st.columns(2)
with c1:
    if st.button("💾 KROK 1: ZAPISZ TEKST", use_container_width=True):
        if txt_to_save.strip():
            bazowa_nazwa = f"{active_p} / {stat} - {plik}"
            istniejace = db.table("archiwum_mikro").select("projekt_nazwa").like("projekt_nazwa", f"{bazowa_nazwa}%").execute()
            licznik = len(istniejace.data) + 1
            db.table("archiwum_mikro").insert({"projekt_nazwa": f"{bazowa_nazwa} (v{licznik})", "tresc": txt_to_save.replace('\x00', ''), "agent": "System"}).execute()
            st.success(f"Zapisano w bazie jako: wersja v{licznik}!")
        else: st.warning("Pole tekstu jest puste!")
        
with c2:
    if st.button("🔍 KROK 2: AKTUALIZUJ PAMIĘĆ AI", use_container_width=True):
        if txt_to_save.strip():
            with st.spinner("Analiza bohaterów i rekwizytów..."):
                try:
                    prompt_petle = f"Wyciągnij otwarte pętle fabularne z tekstu. Krótka lista punktowana. Zero lania wody. Tekst: {txt_to_save}"
                    save_system_data(f"SYS_WATKI_{active_p}", model.generate_content(prompt_petle).text)
                    
                    prompt_szafa = f"Wypisz w punktach kto w co jest ubrany i jakie trzyma rekwizyty. Krótka lista. Tekst: {txt_to_save}"
                    save_system_data(f"SYS_SZAFA_{active_p}", model.generate_content(prompt_szafa).text)
                    
                    p_up = model.generate_content(f"Zwróć TYLKO JSON postaci: imie, status_obecny, sejf_glosu. Tekst: {txt_to_save}").text
                    m = re.search(r'\[.*\]', p_up, re.DOTALL)
                    if m:
                        for p in json.loads(m.group(0)):
                            nm = p.get("imie", "NN")
                            db.table("postacie_mikro").delete().eq("projekt_nazwa", active_p).eq("imie", nm).execute()
                            db.table("postacie_mikro").insert({"projekt_nazwa": active_p, "imie": nm, "status_obecny": p.get("status_obecny", "Aktywny"), "sejf_glosu": p.get("sejf_glosu", "Standard")}).execute()
                    
                    st.success("Pamięć agentów zaktualizowana!")
                    st.rerun()
                except Exception as e: st.warning(f"Błąd analizy: {e}")
        else: st.warning("Brak tekstu do analizy.")

st.markdown("### 🧬 KROK 3: ZARZĄDZANIE KANONEM PROJEKTU")
d1, d2, d3, d4 = st.columns(4)
with d1:
    if st.button("📖 BIBLIA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_BIBLIA_{active_p}", txt_to_save); st.rerun()
with d2:
    if st.button("🪜 DRABINKA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_DRABINKA_{active_p}", txt_to_save); st.rerun()
with d3:
    if st.button("🎯 MAPA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_MAPA_{active_p}", txt_to_save); st.rerun()
with d4:
    if st.button("⚖️ DOKTRYNA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_DOKTRYNA_{active_p}", txt_to_save); st.rerun()

if txt_to_save:
    st.divider()
    c_d1, c_d2 = st.columns(2)
    with c_d1: st.download_button("📄 POBIERZ .TXT", data=txt_to_save, file_name=f"{active_p}_{plik}.txt", use_container_width=True)
    with c_d2: st.download_button("🎬 POBIERZ FINAL DRAFT (.fdx)", data=create_fdx(txt_to_save), file_name=f"{active_p}_{plik}.fdx", mime="application/xml", use_container_width=True)
