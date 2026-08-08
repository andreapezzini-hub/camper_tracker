import os
import json
import requests
import re
from datetime import datetime
from dotenv import load_dotenv

# Il calcolatore punteggio resta esterno ma viene richiamato da qui
import score_calculator

# ==========================================
# 1. LOGICA AI DEDICATA A OLLAMA (SOLO RIASSUNTO ACCESSORI)
# ==========================================

def get_extraction_prompt(testo_annuncio):
    prompt = f"""Sei un assistente esperto nell'analisi di annunci di camper.
Il tuo UNICO compito è leggere il testo dell'annuncio e fare una lista COMPLETA ed ESAUSTIVA di TUTTI gli accessori e gli optional presenti sul veicolo.
Non devi estrarre parametri tecnici base o booleani, devi concentrarti solo ed esclusivamente sugli equipaggiamenti e accessori.

REGOLE PER IL RIASSUNTO ACCESSORI:
1. CERCA IN TUTTO IL TESTO: Non fermarti ai primi risultati. Scansiona attentamente ogni riga alla ricerca di equipaggiamenti reali.
2. NESSUNA ALLUCINAZIONE (CRITICO): Estrai SOLO ed ESCLUSIVAMENTE gli accessori che sono palesemente ed esplicitamente descritti nel testo dell'annuncio fornito. NON inventare accessori, NON presumere dotazioni e se non trovi nulla, non scrivere nulla.
3. FORMATTAZIONE OBBLIGATORIA: Usa UN VERO RITORNO A CAPO (\\n) dopo ogni singolo elemento per garantire che la lista sia leggibile.
4. ELENCO PUNTATO: Usa esclusivamente il trattino "-" per ogni accessorio. Formato esatto richiesto: "- Accessorio 1\\n- Accessorio 2\\n".
5. ESCLUSIONI TASSATIVE: Ignora garanzie, finanziamenti, permute, lavaggi, passaggi di proprietà, chilometri, prezzi, misure, meccanica di base e testi promozionali del concessionario.
6. INTRODUZIONE: Scrivi una brevissima frase introduttiva (es. "Accessori presenti sul veicolo:\\n").

Template JSON esatto da restituire:
{{
    "riassunto_ia": "Accessori presenti sul veicolo:\\n- Accessorio reale 1\\n- Accessorio reale 2" 
}}

Testo annuncio:
\"\"\"{testo_annuncio}\"\"\"
"""
    return prompt

def sanitize_ai_data(dati):
    # Gestione stringa riassunto_ia 
    risultato = {}
    if "riassunto_ia" in dati and dati["riassunto_ia"]:
        testo_ia = str(dati["riassunto_ia"]).strip()
        # Forza la conversione di eventuali ritorni a capo letterali (escape testuale) in veri 'a capo'
        testo_ia = testo_ia.replace("\\n", "\n")
        risultato["riassunto_ia"] = testo_ia
    else:
        risultato["riassunto_ia"] = ""
                
    return risultato

def extract_camper_data_ai(raw_text, ollama_config=None):
    ollama_url = (ollama_config.get("url") if ollama_config and ollama_config.get("url") else os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip('/')
    if not ollama_url.endswith("/api/generate"):
        ollama_url += "/api/generate"
    ollama_model = ollama_config.get("model") if ollama_config and ollama_config.get("model") else os.environ.get("OLLAMA_MODEL", "llama3.2")
    
    prompt = get_extraction_prompt(raw_text)
    
    payload = {
        "model": ollama_model,
        "prompt": prompt,
        "format": "json", 
        "stream": False,
        "options": {
            "temperature": 0.0
        }
    }
    
    try:
        response = requests.post(ollama_url, json=payload, timeout=180)
        response.raise_for_status()
        data_json = response.json()
        raw_response = data_json.get("response", "").strip()
        
        # Pulizia backticks corretta, su singola linea per evitare SyntaxError
        if raw_response.startswith('```json'):
            raw_response = raw_response.replace('```json', '', 1)
            if raw_response.endswith('```'):
                raw_response = raw_response[:-3]
        elif raw_response.startswith('```'):
            raw_response = raw_response.replace('```', '', 1)
            if raw_response.endswith('```'):
                raw_response = raw_response[:-3]
                
        raw_response = raw_response.strip()
            
        data = json.loads(raw_response)
        
        if isinstance(data, dict):
            return sanitize_ai_data(data)
        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return sanitize_ai_data(data[0])
        else:
            raise ValueError(f"Struttura JSON inattesa: {type(data).__name__}")
            
    except Exception as e:
        print(f"      [!] Errore Ollama API: {e}")
        return None

# ==========================================
# 2. LOGICA DB MATCH CONDIVISA (Aggiornata con RegEx flessibile)
# ==========================================

def _genera_regex_flessibile(testo):
    """
    Genera un pattern regex che ignora spaziature, trattini e punteggiatura extra.
    Es. 'B-Class' -> r'b[\W_]*class'
    """
    if not testo:
        return ""
    parti = re.findall(r'[a-zA-Z0-9]+', str(testo).lower())
    regex_pattern = r'[\W_]*'.join(parti)
    return regex_pattern

def match_marca_modello_db(testo, db_conn, fallback_marca="", fallback_modello="", fallback_allestimento=""):
    """
    Cerca nel database SQLite il miglior match usando le espressioni regolari per tollerare sfumature e refusi.
    Se non trova un match eccellente, utilizza i parametri di fallback (che possono provenire dall'AI o dallo scraper base).
    """
    cursor = db_conn.cursor()
    try:
        cursor.execute("SELECT marca, modello, allestimento FROM catalogo_modelli")
        catalogo = cursor.fetchall()
    except sqlite3.OperationalError:
        return {
            "marca": fallback_marca if fallback_marca else "Sconosciuto", 
            "modello": fallback_modello, 
            "allestimento": fallback_allestimento
        }

    testo_lower = str(testo).lower()

    for marca, modello, allestimento in catalogo:
        cat_marca = str(marca).lower() if marca else ""
        cat_modello = str(modello).lower() if modello else ""
        cat_allestimento = str(allestimento).lower() if allestimento else ""

        # La marca generalmente non ha molti refusi, controllo base stringa
        if cat_marca and cat_marca not in testo_lower:
            continue

        regex_modello = _genera_regex_flessibile(cat_modello)
        regex_allestimento = _genera_regex_flessibile(cat_allestimento)

        match_modello = True
        if regex_modello:
            if not re.search(regex_modello, testo_lower):
                match_modello = False
                
        match_allest = True
        if regex_allestimento:
            if not re.search(regex_allestimento, testo_lower):
                match_allest = False

        # Se entrambe le regex (modello e allestimento) matchano le varianti scritte nel testo, usiamo la versione formattata ufficiale del DB
        if match_modello and match_allest:
            return {
                "marca": marca,
                "modello": modello if modello else "",
                "allestimento": allestimento if allestimento else ""
            }

    # Se usciamo dal ciclo senza match perfetti tramite Regex, ritorniamo il Fallback (I dati originali estratti/supposti)
    return {
        "marca": fallback_marca if fallback_marca else "Sconosciuto",
        "modello": fallback_modello,
        "allestimento": fallback_allestimento
    }

# ==========================================
# 3. LOGICA DI PROCESSO E SALVATAGGIO (SQLITE)
# ==========================================

def process_listing(db_conn, config, url, site_name, raw_text, current_price, distance, img_url, regex_extractor_func, ollama_config=None):
    """
    Processa un annuncio: controlla le variazioni, estrae i dati con la funzione 
    RegEx iniettata dallo scraper, consulta l'IA, calcola lo score e salva su DB.
    """
    oggi = datetime.now().strftime("%Y-%m-%d")
    cursor = db_conn.cursor()
    
    # Controlla se l'annuncio esiste già in SQLite
    cursor.execute("SELECT prezzo_attuale, url_immagine FROM annunci WHERE url = ?", (url,))
    row = cursor.fetchone()
    
    if row:
        ultimo_prezzo = row[0]
        url_immagine_salvato = row[1]
        
        # Aggiornamento prezzo se variato
        if current_price != ultimo_prezzo:
            print(f"      [!] VARIAZIONE PREZZO: {ultimo_prezzo}€ -> {current_price}€")
            cursor.execute("UPDATE annunci SET prezzo_attuale = ?, data_ultimo_aggiornamento = ? WHERE url = ?", 
                           (current_price, oggi, url))
            
            # Controllo storico prezzi per evitare duplicati consecutivi identici
            cursor.execute("SELECT prezzo FROM storico_prezzi WHERE url_annuncio = ? ORDER BY data DESC LIMIT 1", (url,))
            ultimo_storico = cursor.fetchone()
            
            if not ultimo_storico or ultimo_storico[0] != current_price:
                cursor.execute("INSERT INTO storico_prezzi (url_annuncio, data, prezzo) VALUES (?, ?, ?)", 
                               (url, oggi, current_price))
            
        # Aggiornamento immagine se mancante in DB ma trovata ora
        if not url_immagine_salvato and img_url:
            cursor.execute("UPDATE annunci SET url_immagine = ? WHERE url = ?", (img_url, url))
            
        db_conn.commit()
    else:
        print(f"      [*] NUOVO ANNUNCIO: {url}")
        
        # Richiama la funzione RegEx fornita dallo scraper specifico
        dati_estratti = regex_extractor_func(raw_text, current_price, db_conn)
        ai_used = False
        
        print("        -> Richiesta Ollama AI in corso per Riassunto Accessori...")
        dati_ai = extract_camper_data_ai(raw_text, ollama_config=ollama_config)
        
        if dati_ai:
            for k, v in dati_ai.items():
                if v is not None and str(v).strip() != "" and v != False:
                    dati_estratti[k] = v
            
            # SECONDO PASSAGGIO REGEX: usiamo il riassunto IA per irrobustire i flag booleani
            riassunto_testo = dati_ai.get("riassunto_ia", "")
            if riassunto_testo:
                print("        -> Esecuzione secondo passaggio Regex su riassunto IA per confermare accessori...")
                dati_regex_ai = regex_extractor_func(riassunto_testo, current_price, db_conn)
                
                # Uniamo solo i valori booleani (accessori) se sono True, non sovrascriviamo gli altri dati
                for k, v in dati_regex_ai.items():
                    if isinstance(v, bool) and v is True:
                        dati_estratti[k] = True
                    
            dati_estratti["prezzo"] = current_price 
            ai_used = True
            print("        -> AI Extraction completata con successo.")
        else:
            print("        -> Errore o Timeout AI: Mantenuti dati di base Regex.")
            
        risultato = score_calculator.calculate_score(dati_estratti, config) 
        
        # Inserimento nuovo annuncio su SQLite
        marca = dati_estratti.get("marca", "Sconosciuto")
        modello = dati_estratti.get("modello", "")
        allestimento = dati_estratti.get("allestimento", "")
        dati_tecnici_json = json.dumps(dati_estratti)
        dettaglio_punteggi_json = json.dumps(risultato.get("categorie", {}))
        
        cursor.execute('''
        INSERT INTO annunci (
            url, sito, marca, modello, allestimento, distanza_seregno, prezzo_attuale, 
            dati_tecnici, punteggio_totale, dettaglio_punteggi, status, 
            motivo_scarto, data_scoperta, data_ultimo_aggiornamento, 
            url_immagine, ai_usata, testo_originale
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            url, site_name, marca, modello, allestimento, distance, current_price,
            dati_tecnici_json, risultato.get("totale", 0), dettaglio_punteggi_json,
            risultato.get("status", "SCONOSCIUTO"), risultato.get("motivo", ""),
            oggi, oggi, img_url, 1 if ai_used else 0, raw_text
        ))
        
        # Inserimento storico prezzo iniziale con controllo
        cursor.execute("SELECT prezzo FROM storico_prezzi WHERE url_annuncio = ? ORDER BY data DESC LIMIT 1", (url,))
        ultimo_storico = cursor.fetchone()
        
        if not ultimo_storico or ultimo_storico[0] != current_price:
            cursor.execute("INSERT INTO storico_prezzi (url_annuncio, data, prezzo) VALUES (?, ?, ?)", 
                           (url, oggi, current_price))
        
        db_conn.commit()
        
        print(f"        -> Punteggio Finale: {risultato.get('totale', 0)}/100 [{risultato.get('status', 'SCONOSCIUTO')}] (AI Usata: {ai_used})")
