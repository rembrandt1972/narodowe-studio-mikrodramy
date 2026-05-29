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
h1 { font-size: 1.8rem !important; margin-bottom: 1.5rem !important; letter-spacing: 0.1em; }
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
def get_season_arc(ep_str):
    try: ep = int(''.join(filter(str.isdigit, str(ep_str))))
    except: return "Faza: Pilotażowa."
    if ep <= 10: return "Faza 1-10: Premise ignition (Haczyk startowy)."
    elif ep <= 30: return "Faza 11-30: Binge lock & Pierwszy wielki zwrot."
    elif ep <= 50: return "Faza 31-50: Bohater przejął inicjatywę & Midpoint explosion."
    elif ep <= 80: return "Faza 51-80: Deeper layer & Darkest stretch."
    else: return "Faza 81+: Final collision & Payoff."

def create_fdx(script_text):
    fdx_header = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n<FinalDraft DocumentType="Script" Template="Standard Screenplay" Version="4">\n<Content>\n'
    fdx_footer = '\n</Content>\n</FinalDraft>'
    paragraphs = ""
    for line in script_text.split('\n'):
        clean_line = html.escape(line.strip())
        if not clean_line: continue
        if clean_line.startswith(("INT.", "EXT.", "WIDOK", "WNĘTRZE", "PLENER", "WN.", "PL.")): p_type = "Scene Heading"
        elif clean_line.isupper() and len(clean_line) < 30 and not clean_line.startswith(("INT", "EXT")): p_type = "Character"
        elif "(" in clean_line and ")" in clean_line and len(clean_line) < 50: p_type = "Parenthetical"
        else: p_type = "Action" 
        paragraphs += f'<Paragraph Type="{p_type}"><Text>{clean_line}</Text></Paragraph>\n'
    return fdx_header + paragraphs + fdx_footer

# --- 5. INTERFEJS SIDEBAR ---
with st.sidebar:
    st.write(f"Autor: **{st.session_state.user}**")
    
    try:
        all_arch_side = db.table("archiwum_mikro").select("projekt_nazwa").execute()
        all_names_side = [row['projekt_nazwa'] for row in all_arch_side.data if not str(row['projekt_nazwa']).startswith("SYS_")]
        projekty_side = sorted(list(set([n.split(" / ")[0] for n in all_names_side if " / " in n])))
        pliki_inne = [n for n in all_names_side if " / " not in n]
    except:
        projekty_side = []
        all_names_side = []
        pliki_inne = []

    wyb_proj = st.selectbox("Nazwa Projektu:", ["-- Nowy Projekt --"] + projekty_side)
    if wyb_proj == "-- Nowy Projekt --":
        proj = st.text_input("Wpisz nazwę nowego projektu:", "Mój Projekt")
    else:
        proj = wyb_proj
        
    active_p = proj.strip()
    
    agent = st.selectbox("Wybierz Agenta", [
        "Genesis PL", 
        "Plan Sezonu PL", 
        "Plan Odcinka PL", 
        "Odcinki PL", 
        "Dialogi PL", 
        "Edi PL", 
        "Cliffhanger PL"
    ], index=3)
    
    if agent == "Plan Odcinka PL":
        st.caption("📐 **Plan Odcinka:** Tworzy mapę bitów (drabinkę) z dokładnym czasem i bada emocje.")
    elif agent == "Odcinki PL":
        st.caption("🎬 **Odcinki:** Pisze gotowy scenariusz na bazie drabinki (Format Hollywood FDX).")
    
    with st.expander("🗄️ ARCHIWUM PROJEKTÓW", expanded=False):
        lista_archiwum = projekty_side.copy()
        if pliki_inne:
            lista_archiwum.append("📦 INNE (Stare pliki)")
            
        if lista_archiwum:
            wybrany_proj = st.selectbox("Projekt:", ["-- Wybierz --"] + lista_archiwum)
            if wybrany_proj != "-- Wybierz --":
                if wybrany_proj == "📦 INNE (Stare pliki)":
                    pliki_projektu = pliki_inne
                else:
                    pliki_projektu = [n for n in all_names_side if n.startswith(f"{wybrany_proj} / ")]
                
                wybrany_plik = st.selectbox("Plik:", ["-- Wybierz... --"] + sorted(pliki_projektu))
                if wybrany_plik != "-- Wybierz... --":
                    tresc_arch = get_system_data(wybrany_plik)
                    st.text_area("Podgląd:", value=tresc_arch, height=150, disabled=True)
                    if st.button("💉 Wstrzyknij do czatu", use_container_width=True):
                        st.session_state.messages.append({"role": "user", "content": f"Oto przywrócony tekst z archiwum ({wybrany_plik}), pracujmy na nim dalej:\n\n{tresc_arch}"})
                        save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
                        st.rerun()
                    bezpieczna_nazwa = wybrany_plik.replace("/", "_")
                    st.download_button("⬇️ Pobierz plik (.txt)", data=tresc_arch, file_name=f"{bezpieczna_nazwa}.txt", use_container_width=True)
        else:
            st.info("Brak zapisów w bazie.")
            
    st.divider()
    dna_items = {"BIBLIA": "📖", "DRABINKA": "🪜", "MAPA": "🎯", "DOKTRYNA": "⚖️", "STYL": "🗣️"}
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
                        save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
                        st.rerun()
            except Exception as e: st.error(f"Błąd czytania: {e}")

# --- 6. GŁÓWNY WARSZTAT ---
c_left, c_right = st.columns([7, 3])

with c_right:
    st.markdown("### 📍 GPS FABUŁY")
    st.markdown(f"<div style='color: #d35400; font-weight: bold;'>{get_season_arc(st.session_state.n_final)}</div>", unsafe_allow_html=True)
    
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
    
    cl1, cl2, cl3, _ = st.columns([2, 2, 2, 4])
    with cl1:
        if st.button("NOWY CZAT", use_container_width=True):
            st.session_state.messages = []
            save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", "[]")
            st.rerun()
    with cl2:
        if st.button("COFNIJ", use_container_width=True):
            if len(st.session_state.messages) >= 2: 
                st.session_state.messages = st.session_state.messages[:-2]
                save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
            st.rerun()
    with cl3:
        if st.button("PRZYWRÓĆ CZAT", use_container_width=True):
            saved_chat = get_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}")
            if saved_chat and saved_chat != "[]":
                try:
                    st.session_state.messages = json.loads(saved_chat)
                    st.rerun()
                except:
                    st.warning("Błąd przywracania czatu.")
            else:
                st.warning(f"Brak zapisanego czatu dla projektu: '{active_p}'.")
            
    st.divider()
    
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.write(m["content"])
        
    if prompt := st.chat_input("Napisz do agenta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
        st.rerun() 
        
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Przetwarzanie danych..."):
                b_dna = get_system_data(f"SYS_BIBLIA_{active_p}")
                d_dna = get_system_data(f"SYS_DRABINKA_{active_p}")
                m_dna = get_system_data(f"SYS_MAPA_{active_p}")
                dok_dna = get_system_data(f"SYS_DOKTRYNA_{active_p}")
                s_dna = get_system_data(f"SYS_STYL_{active_p}")
                plik_zewnetrzny = get_system_data(f"SYS_PLIK_{active_p}")
                brief_projektu = get_system_data(f"SYS_BRIEF_{active_p}")
                
                p_data_ai = get_db_data("postacie", active_p)
                obsada_ctx = ", ".join([f"{p['imie']} (Status: {p['status_obecny']}, Głos: {p.get('sejf_glosu', 'Standard')})" for p in p_data_ai]) if p_data_ai else "Brak zdefiniowanych postaci w bazie."
                
                akt_zadanie = st.session_state.messages[-1]["content"]
                
                baza_dna = (
                    f"--- DNA PROJEKTU ---\nBiblia: {b_dna}\nDrabinka: {d_dna}\nMapa: {m_dna}\nDoktryna: {dok_dna}\nJęzyk i Styl Postaci: {s_dna}\n"
                    f"AKTYWNA OBSADA: {obsada_ctx}\n"
                    f"USTALENIA Z ROZMOWY (BRIEF): {brief_projektu}\n"
                    f"WGRANY DOKUMENT ZEWNĘTRZNY: {plik_zewnetrzny[:25000]}\n---\n"
                    "=== KRYTYCZNA DOKTRYNA HOOK MAP ===\n"
                    "Każdy Agent MUSI stosować inżynierię zaangażowania widza. Każdy odcinek musi mieć 'hook energy'.\n\n"
                    "1. ANATOMIA ODCINKA (60-90 sekund):\n"
                    "- 0-3 sek.: Opening hook / scroll-stopper.\n"
                    "- 3-15 sek.: Immediate conflict.\n"
                    "- 15-35 sek.: Eskalacja napięcia.\n"
                    "- 35-50 sek.: Twist, reversal lub cios emocjonalny.\n"
                    "- 50-90 sek.: Ending cliffhook.\n\n"
                    "2. ARCHITEKTURA SEZONU (90 Odcinków):\n"
                    "- Odc. 1-10: Premise ignition. 11-20: Binge lock. 21-30: First major reversal. 31-40: Hero becomes active. 41-50: Midpoint explosion.\n"
                    "- Odc. 51-60: Deeper secret layer. 61-70: Darkest stretch. 71-80: Endgame setup. 81-89: Final collision. 90: Payoff + future hook.\n\n"
                    "3. ZASADY JAKOŚCI:\n"
                    "- Używaj inteligentnych hooków: Revelation, Threat, Moral, Status, Desire.\n"
                    "====================================================\n"
                )
                
                # --- INDYWIDUALNE USTAWIENIA AGENTÓW ---
                sp = ""
                agent_temp = 0.5
                agent_kotwica = ""
                
                if agent == "Genesis PL":
                    sp = (
                        "Jesteś Agentem Genesis Mikrodrama PL (Główny Showrunner, Kreator Psychologii i Twój Partner).\n"
                        "TRYB PRACY: Rozmawiasz ze mną krok po kroku. Zadawaj max 2 pytania, proponuj warianty A/B/C i ZAWSZE czekaj na moją decyzję.\n"
                        "OSOBOWOŚĆ: Jesteś doświadczonym twórcą hitowych mikrodram. Twój cel to wielkie emocje, namiętności, zdrady i romanse.\n"
                        "=== ŚCISŁY STANDARD STRUKTURY BIBLII SERIALU ===\n"
                        "1. FUNDAMENTY PROJEKTU: Logline, Format, Teaser.\n"
                        "2. ŚWIAT I BOHATEROWIE: Świat przedstawiony, Profile postaci, Ton i styl.\n"
                        "3. FABUŁA I STRUKTURA: Streszczenie sezonu, Opisy odcinków.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.75
                    agent_kotwica = "KOTWICA WIZJONERA: Bądź kreatywny! Proponuj śmiałe rozwiązania. Masz prawo rzucać pomysłami spoza pudełka, ale zawsze czekaj na akceptację Szefa."
                
                elif agent == "Plan Sezonu PL":
                    sp = (
                        "Jesteś Architektem Fabuły (Season Architect) polskiej mikrodramy aktorskiej.\n"
                        "ZADANIE: Rozpisujesz bloki odcinków precyzyjnie według 'DOKTRYNY HOOK MAP'.\n"
                        "ZASADA DYNAMIKI: Każdy odcinek musi pchać fabułę do przodu. Zawsze podawaj Opening Hook i Ending Cliffhook.\n"
                        f"{baza_dna}\nOtwarte Pętle: {get_system_data(f'SYS_WATKI_{active_p}')}"
                    )
                    agent_temp = 0.5
                    agent_kotwica = "KOTWICA ARCHITEKTA: Pilnuj żelaznej struktury. Każdy odcinek musi wynikać z poprzedniego."
                
                elif agent == "Plan Odcinka PL":
                    sp = (
                        f"Jesteś Architektem Odcinka w Mikrodrama PL.\n"
                        "TWOJE ZADANIE: Tworzysz precyzyjną DRABINKĘ (mapę bitów) jednego, konkretnego odcinka.\n"
                        "=== SYNCHRONIZACJA PSYCHOLOGICZNA (KRYTYCZNE) ===\n"
                        "Zanim napiszesz bity akcji, MUSISZ na samej górze zdefiniować [EMOCJONALNY RDZEŃ ODCINKA]: Czego postacie w tej chwili najbardziej pragną, a czego panicznie się boją? Nie rób z nich zimnych robotów. Mają ludzkie uczucia (słabość, miłość, desperację).\n"
                        "ROZBICIE: Następnie rozbij historię na bity czasowe. Pilnuj punktów zwrotnych.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.45
                    agent_kotwica = "KOTWICA PLANISTY: Bądź precyzyjny. Nie rozpisuj dialogów, twórz twarde ramy akcji. Każda akcja fizyczna musi wynikać z emocji bohatera, a nie tylko z chęci posunięcia fabuły do przodu."
                
                elif agent == "Odcinki PL":
                    sp = (
                        f"Jesteś Scenarzystą Wykonawczym Mikrodrama PL. ODCINEK: {st.session_state.n_final}.\n"
                        "TWOJA ROLA: Dostajesz drabinkę (mapę bitów) i zmieniasz ją w gotowy scenariusz.\n\n"
                        "=== ZASADY FORMATOWANIA SCENARIUSZA (STANDARD HOLLYWOOD / FDX) ===\n"
                        "1. NAGŁÓWKI SCEN: Osobna linia, WIELKIMI LITERAMI (np. INT. KAWIARNIA - DZIEŃ, WN. BIURO - NOC).\n"
                        "2. OPIS AKCJI: Czas teraźniejszy. Pierwsze pojawienie się postaci WIELKIMI LITERAMI z wiekiem (np. VIVIENNE (25)). Ważne rekwizyty i dźwięki ZAWSZE WIELKIMI LITERAMI (np. wyciąga PISTOLET, rozlega się HUK).\n"
                        "3. NAZWY POSTACI: Osobna linijka, WIELKIMI LITERAMI (np. STERLING).\n"
                        "4. DIDASKALIA (Nawiasy): Osobna linijka pod postacią, przed dialogiem. Małe litery w nawiasach (np. (szepta)).\n"
                        "5. DIALOGI: W nowej linijce pod imieniem lub didaskaliami.\n\n"
                        "JĘZYK I STYL: Piszesz w 100% po polsku. Skupiasz się na surowej akcji, interakcjach i napięciu.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.4
                    agent_kotwica = "KOTWICA WYKONAWCY: Jesteś maszyną formatującą. Trzymaj się drabinki, ale priorytetem jest idealne techniczne formatowanie tekstu pod pliki .fdx."
                
                elif agent == "Dialogi PL":
                    sp = (
                        f"Jesteś Elitarnym Scenarzystą Dialogów do formatu Vertical. ODCINEK: {st.session_state.n_final}.\n"
                        "TWOJA MISJA: Pisz gęste, tnące jak brzytwa dialogi. Każda sekunda kosztuje.\n\n"
                        "=== DEKALOG DIALOGU (BEZWZGLĘDNIE PRZESTRZEGAJ KAŻDEGO PUNKTU) ===\n"
                        "I. Dialog-Silnik: Słowo to pchnięcie kulą śnieżną wywołujące lawinę.\n"
                        "II. Słowo jako czyn: Mówienie to atak, obrona, uwodzenie lub ucieczka.\n"
                        "III. Dowcip Sytuacyjny: Napięcie między sytuacją a reakcją, a nie z 'sucharów'.\n"
                        "IV. Fabryka Kultowych Fraz: Szukaj chwytliwych, dziwnych lub trafnych zdań.\n"
                        "V. Zasada Zderzenia: Zestawiaj skrajności (rozmowa o sensie życia w kolejce po kebab).\n"
                        "VI. Chirurgiczna redukcja: Wyrzucaj powitania. Zaczynaj dialog na wysokich emocjach.\n"
                        "VII. Informacja jako oręż: Nigdy nie podawaj faktów za darmo. Wiedza musi być zdobyta.\n"
                        "VIII. Unikalna melodia (Rytm): Każdy ma swój bit. To pojedynek, nie monolog.\n"
                        "IX. Podtekst (Iceberg Theory): To, co ważne, jest pod powierzchnią. Zero mówienia wprost.\n"
                        "X. Puenta jako haczyk: Ostatnia kwestia to cliffhanger. Zostaw widza z pytaniem.\n"
                        "XI. PŁONĄCY LÓD (KRYTYCZNE!): Podtekst to nie to samo co cynizm! Bohaterowie nie mówią o uczuciach wprost, bo są dla nich ZBYT BOLESNE i ZBYT WAŻNE, a nie dlatego, że nic nie czują. Pod ich chłodnymi słowami musi kipieć strach, namiętność, miłość lub rozpacz. Nie pisz scenariuszy o bezdusznych socjopatach.\n\n"
                        "ZASADA JĘZYKOWA: WSZYSTKO (analizy, opisy akcji, dialogi) pisz w 100% po POLSKU.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.5
                    agent_kotwica = "KOTWICA DIALOGISTY: Twoje postacie mają serca, które krwawią, nawet jeśli ich twarze są z kamienia. Słowa mogą być zimne, ale podtekst musi być gorący i pełen ludzkich emocji."
                
                elif agent == "Edi PL":
                    sp = (
                        f"Jesteś Edi, Główny Showrunner, Kontroler Jakości i Strażnik Kanonu. ODCINEK: {st.session_state.n_final}.\n"
                        "ZASADA JĘZYKOWA: Całość komunikacji i scenariuszy zawsze w 100% po POLSKU.\n\n"
                        "=== TWOJE DWA ODDZIELNE TRYBY PRACY (ZALEŻNE OD POLECENIA UŻYTKOWNIKA) ===\n"
                        "Musisz przeanalizować intencję Użytkownika i wejść w JEDEN, konkretny tryb. ZAKAZUJĘ łączyć obu trybów!\n\n"
                        "TRYB 1: AUDYT (Kiedy użytkownik wkleja tekst do oceny, prosi o audyt lub opinię)\n"
                        "- Jesteś surowym inspektorem.\n"
                        "- Wytykaj błędy logiczne, lanie wody i łamanie Doktryny.\n"
                        "- MASZ NOWY PRIORYTET: 'Wykrywacz Cynizmu'. Zwracaj baczną uwagę, czy postacie nie stały się zbyt 'zimne' lub zachowują się jak bezduszne roboty. Jeśli brakuje w nich ludzkiej wrażliwości, miłości czy strachu - bezlitośnie każ to przepisać agentowi od dialogów!\n"
                        "- MASZ ABSOLUTNY ZAKAZ PISANIA SCENARIUSZA! Tylko wypunktuj błędy do poprawy i wydaj instrukcje, np. 'Zanieś to do agenta Dialogi PL'.\n\n"
                        "TRYB 2: FINALIZACJA FDX (TYLKO kiedy użytkownik wyraźnie użyje słów: 'do zapisu', 'do ściągnięcia', 'gotowy tekst', 'formatuj')\n"
                        "- Zmieniasz się w niemą maszynę generującą plik dla Final Draft.\n"
                        "- MASZ ABSOLUTNY ZAKAZ KOMENTOWANIA. Odpowiadasz WYŁĄCZNIE czystym scenariuszem bez ani jednego słowa powitania czy opisu zmian.\n"
                        "- ZASADY FDX: 1. Nagłówki WIELKIMI LITERAMI (np. INT. KAWIARNIA - DZIEŃ). 2. Dźwięki i pierwsze wejście postaci WIELKIMI LITERAMI. 3. Nazwa postaci nad dialogiem WIELKIMI LITERAMI. 4. Didaskalia w nawiasie małymi literami.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.1
                    agent_kotwica = "KOTWICA AUDYTORA: W Trybie 1 pilnuj psychologii (Wykrywacz Cynizmu) i nie pisz scenariuszy. W Trybie 2 oddaj czysty tekst FDX bez słowa wstępu. NIGDY nie łącz tych ról."
                
                elif agent == "Cliffhanger PL":
                    sp = (
                        "Jesteś Bezlitosnym Sędzią Retencji (Hook Validator) na polskiego TikToka/Reels.\n"
                        "TWOJA MISJA: Oceniasz tylko pierwsze 3 sekundy i ostatnie 5 sekund.\n"
                        "FORMAT: Zawsze zaczynaj od werdyktu: [🔥 OCENA X/10] -> [🟢 ZATWIERDZONY] lub [🔴 ODRZUCONY]. Pisz w 100% po polsku.\n"
                        f"{baza_dna}"
                    )
                    agent_temp = 0.2
                    agent_kotwica = "KOTWICA SĘDZIEGO: Taniocha nie przejdzie. Bądź brutalnie szczery w ocenianiu napięcia w ostatnich sekundach odcinka."
                
                else:
                    sp = f"Jesteś asystentem AI. Działaj na polecenie użytkownika. Pisz bezwzględnie w języku polskim.\n{baza_dna}"
                    agent_temp = 0.5
                    agent_kotwica = "KOTWICA: Bądź pomocny i precyzyjny."

                # --- SKŁADANIE POLECEŃ I GENERACJA ---
                zakaz_formy = "\n\nKRYTYCZNA DYREKTYWA: Zwróć WYŁĄCZNIE surowy tekst wynikowy. MASZ ABSOLUTNY ZAKAZ dodawania jakichkolwiek powitań czy komentarzy. TYLKO treść." if agent not in ["Edi PL", "Genesis PL"] else ""
                ostateczny_dopisek = zakaz_formy + "\n\n=== ⚠️ KOTWICA SYSTEMOWA AGENTA ===\n" + agent_kotwica
                
                try:
                    strict_model = genai.GenerativeModel(
                        'gemini-3.1-pro-preview',
                        system_instruction=sp + ostateczny_dopisek
                    )
                    
                    recent_hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-5:-1]])

                    resp = strict_model.generate_content(
                        f"HISTORIA CZATU (ostatnie wiadomości):\n{recent_hist}\n\nZADANIE OD SHOWRUNNERA:\n{akt_zadanie}", 
                        safety_settings=safe_config,
                        generation_config={"temperature": agent_temp}
                    ).text
                    
                    st.session_state.messages.append({"role": "assistant", "content": resp})
                    save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd generacji AI: {e}")

st.divider()

k1, k2, k3 = st.columns([2, 2, 1])
with k1: 
    st.text_input("AKTYWNY PROJEKT:", value=active_p, disabled=True)
with k2: 
    plik = st.text_input("NAZWA PLIKU (np. Odcinek 1):", key="n_final")
with k3: 
    stat = st.selectbox("STATUS", ["Robocze", "Gotowe", "Kanon"])

ostatni_tekst = st.session_state.messages[-1]["content"].replace('\x00', '') if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant" else ""

st.markdown("### 👀 PODGLĄD DO ZAPISU (EDYTUJ PRZED ZAPISEM)")
txt_to_save = st.text_area("Treść do zapisu:", value=ostatni_tekst, height=250, label_visibility="collapsed")

if st.button("💉 WSTRZYKNIJ TEN TEKST DO CZATU"):
    if txt_to_save.strip():
        st.session_state.messages.append({"role": "user", "content": f"Oto zaktualizowany tekst:\n\n{txt_to_save}"})
        save_system_data(f"SYS_AUTOSAVE_CHAT_{active_p}", json.dumps(st.session_state.messages))
        st.rerun()

c1, c2 = st.columns(2)
with c1:
    if st.button("💾 KROK 1: ZAPISZ TEKST", use_container_width=True):
        if txt_to_save.strip():
            try:
                bazowa_nazwa = f"{active_p} / {stat} - {plik}"
                istniejace = db.table("archiwum_mikro").select("projekt_nazwa").like("projekt_nazwa", f"{bazowa_nazwa}%").execute()
                licznik = len(istniejace.data) + 1
                db.table("archiwum_mikro").insert({"projekt_nazwa": f"{bazowa_nazwa} (v{licznik})", "tresc": txt_to_save.replace('\x00', ''), "agent": "System"}).execute()
                st.success(f"Zapisano w bazie jako: wersja v{licznik}!")
            except Exception as e:
                st.error(f"Błąd zapisu do bazy: {e}")
        else: st.warning("Pole tekstu jest puste!")
with c2:
    if st.button("🔍 KROK 2: AKTUALIZUJ PAMIĘĆ AI", use_container_width=True):
        if txt_to_save.strip():
            with st.spinner("Analiza bohaterów i rekwizytów..."):
                try:
                    prompt_petle = f"Wyciągnij otwarte pętle fabularne z tekstu. Krótka lista punktowana w języku polskim. Zero lania wody. Tekst: {txt_to_save}"
                    save_system_data(f"SYS_WATKI_{active_p}", model.generate_content(prompt_petle, safety_settings=safe_config).text)
                    
                    prompt_szafa = f"Wypisz w punktach po polsku, kto w co jest ubrany i jakie trzyma rekwizyty. Krótka lista. Tekst: {txt_to_save}"
                    save_system_data(f"SYS_SZAFA_{active_p}", model.generate_content(prompt_szafa, safety_settings=safe_config).text)
                    
                    p_up = model.generate_content(f"Zwróć TYLKO JSON postaci: imie, status_obecny, sejf_glosu. Tekst: {txt_to_save}", safety_settings=safe_config).text
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
d1, d2, d3, d4, d5 = st.columns(5)
with d1:
    if st.button("📖 BIBLIA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_BIBLIA_{active_p}", txt_to_save); st.rerun()
        else: st.warning("Okno podglądu jest puste!")
with d2:
    if st.button("🪜 DRABINKA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_DRABINKA_{active_p}", txt_to_save); st.rerun()
        else: st.warning("Okno podglądu jest puste!")
with d3:
    if st.button("🎯 MAPA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_MAPA_{active_p}", txt_to_save); st.rerun()
        else: st.warning("Okno podglądu jest puste!")
with d4:
    if st.button("⚖️ DOKTRYNA", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_DOKTRYNA_{active_p}", txt_to_save); st.rerun()
        else: st.warning("Okno podglądu jest puste!")
with d5:
    if st.button("🗣️ STYL", use_container_width=True):
        if txt_to_save.strip(): save_system_data(f"SYS_STYL_{active_p}", txt_to_save); st.rerun()
        else: st.warning("Okno podglądu jest puste!")

if txt_to_save:
    st.divider()
    c_d1, c_d2 = st.columns(2)
    with c_d1: st.download_button("📄 POBIERZ .TXT", data=txt_to_save, file_name=f"{active_p}_{plik}.txt", use_container_width=True)
    with c_d2: st.download_button("🎬 POBIERZ FINAL DRAFT (.fdx)", data=create_fdx(txt_to_save), file_name=f"{active_p}_{plik}.fdx", mime="application/xml", use_container_width=True)
