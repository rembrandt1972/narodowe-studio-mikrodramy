import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import html
import pandas as pd

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="Mikrodrama Studio PL", layout="wide")

# --- 2. LOGOWANIE ---
if "user" not in st.session_state:
    st.markdown("<h1 style='text-align: center;'>🎬 MIKRODRAMA STUDIO PL</h1>", unsafe_allow_html=True)
    pwd = st.text_input("AUTHOR ACCESS:", type="password")
    if pwd.lower() in ["kasia", "julia", "fidel"]:
        st.session_state.user = pwd.capitalize()
        st.rerun()
    st.stop()

# --- 3. BAZA DANYCH (TABELE _MIKRO) ---
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
db = init_db()

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

# --- 5. EKSPORT DO FINAL DRAFT ---
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

# --- 6. AGENCI (POLSKI FORMAT PIONOWY) ---
AGENTS = {
    "Genesis PL": "Jesteś Agentem Genesis Mikrodrama PL. Tworzysz historie do krótkiego formatu pionowego (TikTok/Reels). DYREKTYWA: Piszemy dla żywych aktorów w Polsce. Lokacje realistyczne i niskobudżetowe (mieszkania, kawiarnie, ulice, biura). STYL: Mocne, polskie konflikty – rodzina, zdrada, pieniądze. Żadnego 'amerykańskiego snu', stawiamy na polską krew, realizm i skrajne emocje.",
    "Plan Sezonu PL": "Jesteś Architektem polskiej mikrodramy. Rozpisujesz strukturę na odcinki. Pamiętaj: każdy odcinek ma tylko 60-90 sekund! Tempo musi być błyskawiczne, nie ma czasu na długie wstępy. Liczy się natychmiastowa akcja.",
    "Dialogi PL": "Jesteś Scenarzystą Mikrodram. ODCINEK: 60-90 sekund. ZASADA JĘZYKOWA: 100% PO POLSKU. Dialogi muszą być ostre, krótkie i naturalne. Unikaj literackiego języka, pisz potoczną, współczesną polszczyzną. Opisy akcji dynamiczne, dostosowane pod kamerę telefonu (format pionowy 9:16).",
    "Edi PL": "Jesteś Edi, bezlitosny polski redaktor naczelny. Wytykasz błędy, pilnujesz realizmu budżetowego i dynamiki scen. Jeśli dialog brzmi sztucznie – poprawiasz. Gdy użytkownik prosi o 'czysty tekst do zapisu', wyłączasz komentarze i podajesz sam scenariusz.",
    "Cliffhanger PL": "Jesteś Sędzią Mikrodram. Oceniasz tylko jedno: czy widz przescrolluje dalej? Pierwsze 3 sekundy odcinka muszą być 'wybuchem'. Koniec odcinka to brutalne, nagłe zawieszenie akcji, które wymusza odpalenie następnego video."
}

# --- 7. INTERFEJS ---
with st.sidebar:
    st.write(f"Zalogowano jako: **{st.session_state.user}**")
    proj = st.text_input("Nazwa Projektu:", "Zdrada na Wilanowie")
    active_p = proj.strip()
    
    st.markdown("### STATUS DNA 🧬")
    biblia = get_system_data(f"SYS_BIBLIA_{active_p}")
    drabinka = get_system_data(f"SYS_DRABINKA_{active_p}")
    mapa = get_system_data(f"SYS_MAPA_{active_p}")
    doktryna = get_system_data(f"SYS_DOKTRYNA_{active_p}")
    
    st.markdown(f"📖 Biblia: {'✅' if biblia else '❌'}\n\n🪜 Drabinka: {'✅' if drabinka else '❌'}\n\n🗺️ Mapa: {'✅' if mapa else '❌'}\n\n⚖️ Doktryna: {'✅' if doktryna else '❌'}")
    
    agent = st.selectbox("Wybierz Agenta:", list(AGENTS.keys()))
    if st.button("Nowy czat"): st.session_state.messages = []

# Konfiguracja Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-pro-latest')

if "messages" not in st.session_state: st.session_state.messages = []

c_left, c_right = st.columns([2, 1])

with c_right:
    st.markdown("### 📍 GPS FABUŁY")
    st.text_area("Detektyw Wątków", value=get_system_data(f"SYS_WATKI_{active_p}"), height=150, disabled=True)
    st.text_area("Szafa Rekwizytów", value=get_system_data(f"SYS_SZAFA_{active_p}"), height=150, disabled=True)
    
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
    
    st.divider()
    st.markdown("### 📝 NOTATNIK AUTORA")
    saved_notes = get_system_data(f"SYS_NOTES_{active_p}")
    user_notes = st.text_area("Luźne zapiski:", value=saved_notes, height=200, key="notes")
    if st.button("💾 ZAPISZ NOTATKI", use_container_width=True):
        save_system_data(f"SYS_NOTES_{active_p}", user_notes)
        st.success("Notatki zapisane!")

with c_left:
    st.markdown(f"## {agent}")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])
        
    if prompt := st.chat_input("Napisz do agenta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        sys_prompt = f"{AGENTS[agent]}\nZASADY ŚWIATA:\nBiblia:{biblia}\nDrabinka:{drabinka}\nMapa:{mapa}\nDoktryna:{doktryna}"
        full_prompt = sys_prompt + "\n\nKonwersacja:\n" + "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-10:]])
        
        with st.chat_message("assistant"):
            with st.spinner("Agent myśli..."):
                resp = model.generate_content(full_prompt).text
                st.markdown(resp)
        st.session_state.messages.append({"role": "assistant", "content": resp})

st.divider()
st.markdown("### 💾 PANEL ZAPISU (WEHIKUŁ CZASU)")
plik = st.text_input("Nazwa pliku (np. Odcinek 1):", "Odcinek ")
stat = st.selectbox("Status:", ["Robocze", "Gotowe", "Kanon"])
txt_to_save = st.text_area("👀 PODGLĄD DO ZAPISU (Edytuj przed zapisem):", height=300)

c1, c2 = st.columns(2)
with c1:
    if st.button("💾 KROK 1: ZAPISZ TEKST W WERSJI", use_container_width=True):
        if txt_to_save.strip():
            bazowa_nazwa = f"{active_p} / {stat} - {plik}"
            istniejace = db.table("archiwum_mikro").select("projekt_nazwa").like("projekt_nazwa", f"{bazowa_nazwa}%").execute()
            licznik = len(istniejace.data) + 1
            nowa_nazwa = f"{bazowa_nazwa} (v{licznik})"
            db.table("archiwum_mikro").insert({"projekt_nazwa": nowa_nazwa, "tresc": txt_to_save.replace('\x00', ''), "agent": "System"}).execute()
            st.success(f"Zapisano bezpiecznie jako: {nowa_nazwa}!")
        else: st.warning("Pole tekstu jest puste!")
with c2:
    if st.button("🔍 KROK 2: AKTUALIZUJ PAMIĘĆ AI", use_container_width=True): st.info("Ta funkcja wymaga osobnego Agenta Ekstraktora (w przygotowaniu). Na razie użyj panelu po prawej.")

if txt_to_save.strip():
    st.divider()
    cd1, cd2 = st.columns(2)
    with cd1: st.download_button("📄 POBIERZ .TXT", data=txt_to_save, file_name=f"{active_p}_{plik}.txt", use_container_width=True)
    with cd2: st.download_button("🎬 POBIERZ FINAL DRAFT (.fdx)", data=create_fdx(txt_to_save), file_name=f"{active_p}_{plik}.fdx", mime="application/xml", use_container_width=True)
