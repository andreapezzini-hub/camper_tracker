import os
import sys
import json
import argparse
import glob
import re
import importlib.util
from datetime import datetime
from dotenv import load_dotenv

import score_calculator
import scraper_utils
from main_engine import get_db_connection, export_to_json, SCRAPERS_DIR

def load_site_regex_map(target_scraper=None):
    """
    Scansiona i file scraper, estrae il SITE_NAME dichiarato all'interno 
    e lo associa alla rispettiva funzione regex_extract_camper_data.
    Gestisce in modo sicuro le librerie mancanti.
    """
    site_regex_map = {}
    pattern = os.path.join(SCRAPERS_DIR, f"{target_scraper}.py") if target_scraper else os.path.join(SCRAPERS_DIR, "*.py")
    files = [f for f in glob.glob(pattern) if not f.endswith('__init__.py')]
    
    for file_path in files:
        module_name = os.path.basename(file_path)[:-3]
        
        # Estrae dinamicamente il SITE_NAME leggendo il codice sorgente
        site_name = None
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'SITE_NAME\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                site_name = match.group(1)
        
        if not site_name:
            print(f"[-] Attenzione: Variabile SITE_NAME non trovata in {file_path}. File ignorato.")
            continue

        # Carica il modulo in memoria gestendo le eccezioni di importazione
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            
            if hasattr(modulo, 'regex_extract_camper_data'):
                site_regex_map[site_name] = modulo.regex_extract_camper_data
                print(f"[+] Collegato scraper '{module_name}' al sito DB '{site_name}'")
            else:
                print(f"[-] Nessuna funzione regex_extract_camper_data in {file_path}")
                
        except ImportError as e:
            print(f"[-] Errore dipendenze in '{module_name}': {e}. Lo scraper verrà saltato.")
        except Exception as e:
            print(f"[-] Errore critico in '{module_name}': {e}. Lo scraper verrà saltato.")
            
    return site_regex_map

def reprocess_database(use_ai=False, target_scraper=None):
    load_dotenv("config.env")
    config = score_calculator.load_config()
    db_conn = get_db_connection()
    cursor = db_conn.cursor()
    
    ollama_config = None
    if use_ai:
        ollama_config = {
            "url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2")
        }
        
    print("\n[*] Costruzione mappa dinamica Scraper <-> DB...")
    site_regex_map = load_site_regex_map(target_scraper)
    
    if not site_regex_map:
        print("Nessuna associazione valida trovata. Interruzione.")
        return

    print("\n[*] Estrazione annunci dal database...")
    cursor.execute("SELECT url, testo_originale, prezzo_attuale, sito FROM annunci WHERE testo_originale IS NOT NULL")
    annunci = cursor.fetchall()
    
    count_aggiornati = 0

    for url, testo, prezzo, sito in annunci:
        # Associazione diretta tramite il nome estratto
        regex_func = site_regex_map.get(sito)
        
        if not regex_func:
            # Utile se stiamo filtrando con --scraper o se un sito a DB non ha più il suo file
            continue
            
        dati_estratti = regex_func(testo, prezzo, db_conn)
        
        ai_used = False
        if use_ai:
            print(f"    -> Richiesta Ollama AI per {url}...")
            dati_ai = scraper_utils.extract_camper_data_ai(testo, ollama_config=ollama_config)
            if dati_ai:
                for k, v in dati_ai.items():
                    if v is not None and str(v).strip() != "" and v is not False:
                        dati_estratti[k] = v
                
                riassunto = dati_ai.get("riassunto_ia", "")
                if riassunto:
                    dati_regex_ai = regex_func(riassunto, prezzo, db_conn)
                    for k, v in dati_regex_ai.items():
                        if isinstance(v, bool) and v is True:
                            dati_estratti[k] = True
                ai_used = True
                
        dati_estratti["prezzo"] = prezzo
        risultato = score_calculator.calculate_score(dati_estratti, config)
        
        cursor.execute('''
            UPDATE annunci 
            SET dati_tecnici = ?, punteggio_totale = ?, dettaglio_punteggi = ?, 
                status = ?, motivo_scarto = ?, ai_usata = ?, data_ultimo_aggiornamento = ?
            WHERE url = ?
        ''', (
            json.dumps(dati_estratti), risultato.get("totale", 0), json.dumps(risultato.get("categorie", {})),
            risultato.get("status", "SCONOSCIUTO"), risultato.get("motivo", ""),
            1 if ai_used else 0, datetime.now().strftime("%Y-%m-%d"), url
        ))
        print(f"[OK] Aggiornato: {url} | Punteggio: {risultato.get('totale', 0)}")
        count_aggiornati += 1
        
    db_conn.commit()
    export_to_json(db_conn)
    db_conn.close()
    print(f"\n[+] Ripocessamento completato. {count_aggiornati} annunci aggiornati.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Riprocessa i testi degli annunci a DB.")
    parser.add_argument("--ai", action="store_true", help="Attiva l'elaborazione con Ollama")
    parser.add_argument("--scraper", type=str, default=None, help="Nome del file scraper (senza .py) da riprocessare")
    args = parser.parse_args()
    
    reprocess_database(use_ai=args.ai, target_scraper=args.scraper)