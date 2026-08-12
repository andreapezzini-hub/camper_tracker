import json
import os
import sqlite3
from dotenv import load_dotenv

import glob
import importlib.util
from datetime import datetime
import traceback

import score_calculator
import database_setup

DB_FILE = "camper_tracker.db"
JSON_EXPORT_FILE = "dati_storici.json"
SCRAPERS_DIR = "scrapers"

def get_db_connection():
    """Restituisce la connessione al database (SQLite locale o Turso Cloud)."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        import libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        if not os.path.exists(DB_FILE):
            database_setup.setup_database()
        return sqlite3.connect(DB_FILE)

def export_to_json(db_conn):
    """
    Esporta i dati da SQLite al formato JSON originale per mantenere 
    compatibile la dashboard index.html senza doverla modificare.
    """
    try:
        # Esegue una query veloce di keep-alive per riaprire lo stream se scaduto
        db_conn.execute("SELECT 1")
    except Exception as db_err:
    
    print(f"Riconnessione al DB in corso per timeout stream: {db_err}")
    db_conn = get_db_connection()
    
    print(f"[*] Esportazione dati in {JSON_EXPORT_FILE} per il frontend...")
    cursor = db_conn.cursor()
    
    # Prende tutti gli annunci
    cursor.execute("""
        SELECT url, sito, marca, modello, allestimento, distanza_seregno, prezzo_attuale, 
               dati_tecnici, punteggio_totale, dettaglio_punteggi, status, 
               motivo_scarto, data_scoperta, data_ultimo_aggiornamento, 
               url_immagine, ai_usata, testo_originale 
        FROM annunci
    """)
    annunci = cursor.fetchall()
    
    db_json = {"annunci": {}}
    
    for row in annunci:
        url = row[0]
        
        # Prende lo storico prezzi per questo url
        cursor.execute("SELECT data, prezzo FROM storico_prezzi WHERE url_annuncio = ? ORDER BY data ASC", (url,))
        storico = [{"data": r[0], "prezzo": r[1]} for r in cursor.fetchall()]
        
        db_json["annunci"][url] = {
            "sito": row[1],
            "marca": row[2],
            "modello": row[3],
            "allestimento": row[4],
            "distanza_seregno": row[5],
            "prezzo_attuale": row[6],
            "storico_prezzi": storico,
            "dati_tecnici": json.loads(row[7]) if row[7] else {},
            "punteggio_totale": row[8],
            "dettaglio_punteggi": json.loads(row[9]) if row[9] else {},
            "status": row[10],
            "motivo_scarto": row[11],
            "data_scoperta": row[12],
            "data_ultimo_aggiornamento": row[13],
            "url_immagine": row[14],
            "ai_usata": bool(row[15]),
            "testo_originale": row[16]
        }
        
    with open(JSON_EXPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_json, f, indent=4, ensure_ascii=False)
    print(f"[+] Esportazione completata. {len(annunci)} annunci esportati.")

def load_and_run_scrapers(db_conn):
    if not os.path.exists(SCRAPERS_DIR):
        os.makedirs(SCRAPERS_DIR)
        print(f"Cartella '{SCRAPERS_DIR}' creata.")
        return

    scraper_files = [f for f in glob.glob(os.path.join(SCRAPERS_DIR, "*.py")) if not f.endswith('__init__.py')]

    if not scraper_files:
        print(f"Nessun file scraper trovato nella cartella '{SCRAPERS_DIR}'.")
        return

    try:
        config_file_path = os.path.join(os.path.dirname(__file__), "config.env")
        load_dotenv(config_file_path)
        config = score_calculator.load_config()

        ollama_config = {
            "url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2")
        }
    except Exception as e:
        print(f"  [!] ERRORE CRITICO: Impossibile caricare scoring_config.json o config.env. Dettagli: {e}")
        traceback.print_exc()
        return

    for file_path in scraper_files:
        module_name = os.path.basename(file_path)[:-3]
        print(f"\n--- Avvio scraper: {module_name} ---")
        
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                print(f"  [!] Impossibile creare il loader per {file_path}.")
                continue

            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            
            if hasattr(modulo, 'run_scraper'):
                # Passiamo la connessione db SQLite al posto del dizionario
                modulo.run_scraper(db_conn, config, ollama_config=ollama_config)
            else:
                print(f"  [!] Il file {file_path} non contiene la funzione 'run_scraper(db_conn, config)'.")
                
        except Exception as e:
            print(f"  [!] ERRORE CRITICO in {module_name}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    print(f"[*] Avvio CamperTracker AI Engine - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Inizializza e ottiene connessione SQLite
    db_conn = get_db_connection()
    
    # Esegue gli scraper passando la connessione DB
    load_and_run_scrapers(db_conn)
    
    # Salva il file JSON per la dashboard web
    export_to_json(db_conn)
    
    # Chiude la connessione
    db_conn.close()
    
    print("\n[+] Esecuzione completata.")
