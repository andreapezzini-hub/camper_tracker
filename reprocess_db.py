import os
import json
import sqlite3
import glob
import importlib.util
import traceback
from datetime import datetime
from dotenv import load_dotenv

# Importiamo le utility di progetto
import score_calculator
import scraper_utils
import database_setup

# ==============================================================================
# CONFIGURAZIONE SCRIPT ONE-SHOT
# ==============================================================================
# Imposta TARGET_SITE con il nome esatto del sito salvato a DB (es. "Centro Caravans Barassi")
# Oppure imposta su "ALL" per elaborare l'intero DB riapplicando tutti gli scraper disponibili.
TARGET_SITE = "ALL"

# Mappa necessaria per associare il nome del sito nel DB al relativo file dello scraper.
# La chiave è il 'sito' nel DB, il valore è il nome del file Python (senza estensione .py).
SITE_TO_SCRAPER_MAP = {
    "Centro Caravans Barassi": "barassi_scraper",  # Adatta al nome reale del tuo file
    # Aggiungi qui gli altri siti man mano che crei gli scraper
    # "Nome Sito 2": "nome_file_scraper_2",
}

JSON_EXPORT_FILE = "dati_storici.json"
SCRAPERS_DIR = "scrapers"
# ==============================================================================

def get_db_connection():
    """Restituisce la connessione al database (SQLite o Turso) mantenendo coerenza con il main."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        import libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        DB_FILE = "camper_tracker.db"
        if not os.path.exists(DB_FILE):
            database_setup.setup_database()
        return sqlite3.connect(DB_FILE)

def load_regex_functions():
    """
    Scansiona la cartella degli scraper e carica in memoria tutte 
    le funzioni `regex_extract_camper_data` trovate.
    """
    regex_funcs = {}
    if not os.path.exists(SCRAPERS_DIR):
        print(f"[!] Cartella '{SCRAPERS_DIR}' non trovata.")
        return regex_funcs

    scraper_files = [f for f in glob.glob(os.path.join(SCRAPERS_DIR, "*.py")) if not f.endswith('__init__.py')]
    
    for file_path in scraper_files:
        module_name = os.path.basename(file_path)[:-3]
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                modulo = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modulo)
                
                if hasattr(modulo, 'regex_extract_camper_data'):
                    regex_funcs[module_name] = modulo.regex_extract_camper_data
                    print(f"  [+] Funzione Regex caricata da: {module_name}.py")
        except Exception as e:
            print(f"  [!] Errore nel caricamento del modulo {module_name}: {e}")
            
    return regex_funcs

def export_to_json(db_conn):
    """Riesporta i dati nel JSON in modo che la dashboard rifletta i nuovi score."""
    print(f"\n[*] Esportazione dati aggiornati in {JSON_EXPORT_FILE} per il frontend...")
    cursor = db_conn.cursor()
    
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
        cursor.execute("SELECT data, prezzo FROM storico_prezzi WHERE url_annuncio = ? ORDER BY data ASC", (url,))
        storico = [{"data": r[0], "prezzo": r[1]} for r in cursor.fetchall()]
        
        db_json["annunci"][url] = {
            "sito": row[1], "marca": row[2], "modello": row[3], "allestimento": row[4],
            "distanza_seregno": row[5], "prezzo_attuale": row[6], "storico_prezzi": storico,
            "dati_tecnici": json.loads(row[7]) if row[7] else {},
            "punteggio_totale": row[8], "dettaglio_punteggi": json.loads(row[9]) if row[9] else {},
            "status": row[10], "motivo_scarto": row[11], "data_scoperta": row[12],
            "data_ultimo_aggiornamento": row[13], "url_immagine": row[14],
            "ai_usata": bool(row[15]), "testo_originale": row[16]
        }
        
    with open(JSON_EXPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_json, f, indent=4, ensure_ascii=False)
    print(f"[+] Esportazione completata. Dati pronti per la dashboard.")

def reprocess_database():
    try:
        config_file_path = os.path.join(os.path.dirname(__file__), "config.env")
        load_dotenv(config_file_path)
        config = score_calculator.load_config()

        ollama_config = {
            "url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2")
        }
    except Exception as e:
        print(f"[!] ERRORE CRITICO: Impossibile caricare le configurazioni. Dettagli: {e}")
        return

    db_conn = get_db_connection()
    cursor = db_conn.cursor()
    
    print("\n[*] Caricamento funzioni di estrazione dagli scraper...")
    regex_funcs = load_regex_functions()
    
    if not regex_funcs:
        print("[!] Nessuna funzione di estrazione trovata. Interruzione.")
        db_conn.close()
        return

    print(f"\n[*] Avvio Rielaborazione DB. Target: {TARGET_SITE}")
    
    if TARGET_SITE == "ALL":
        cursor.execute("SELECT url, sito, testo_originale, prezzo_attuale FROM annunci")
    else:
        cursor.execute("SELECT url, sito, testo_originale, prezzo_attuale FROM annunci WHERE sito = ?", (TARGET_SITE,))
        
    annunci = cursor.fetchall()
    print(f"[*] Trovati {len(annunci)} annunci da processare.")
    
    oggi = datetime.now().strftime("%Y-%m-%d")
    elaborati_con_successo = 0

    for row in annunci:
        url = row[0]
        sito = row[1]
        testo_originale = row[2]
        prezzo_attuale = row[3]
        
        if not testo_originale:
            print(f"  [-] Testo originale mancante per {url}. Salto.")
            continue
            
        scraper_module = SITE_TO_SCRAPER_MAP.get(sito)
        if not scraper_module or scraper_module not in regex_funcs:
            print(f"  [-] Funzione regex non associata/trovata per il sito '{sito}'. Salto.")
            continue
            
        regex_extractor_func = regex_funcs[scraper_module]
        
        print(f"\n  [>] Rielaborazione Annuncio: {url}")
        
        try:
            # 1. Primo passaggio: Regex Base nativa dello scraper
            dati_estratti = regex_extractor_func(testo_originale, prezzo_attuale, db_conn)
            ai_used = False
            
            # 2. Scansione AI: Richiamiamo scraper_utils
            print("      -> Richiesta Ollama AI in corso per Riassunto Accessori...")
            dati_ai = scraper_utils.extract_camper_data_ai(testo_originale, ollama_config=ollama_config)
            
            if dati_ai:
                for k, v in dati_ai.items():
                    if v is not None and str(v).strip() != "" and v != False:
                        dati_estratti[k] = v
                
                # 3. Secondo Passaggio Regex: Analisi incrociata sul testo generato dall'IA
                riassunto_testo = dati_ai.get("riassunto_ia", "")
                if riassunto_testo:
                    print("      -> Esecuzione secondo passaggio Regex su riassunto IA per confermare accessori...")
                    dati_regex_ai = regex_extractor_func(riassunto_testo, prezzo_attuale, db_conn)
                    
                    for k, v in dati_regex_ai.items():
                        if isinstance(v, bool) and v is True:
                            dati_estratti[k] = True
                        
                dati_estratti["prezzo"] = prezzo_attuale 
                ai_used = True
                print("      -> Estrazione AI e merge completati.")
            else:
                print("      -> Errore o Timeout AI: Mantenuti dati di base Regex.")
                
            # 4. Ricalcolo punteggio
            risultato = score_calculator.calculate_score(dati_estratti, config)
            
            marca = dati_estratti.get("marca", "Sconosciuto")
            modello = dati_estratti.get("modello", "")
            allestimento = dati_estratti.get("allestimento", "")
            dati_tecnici_json = json.dumps(dati_estratti)
            dettaglio_punteggi_json = json.dumps(risultato.get("categorie", {}))
            
            # 5. Aggiornamento in SQLite
            cursor.execute('''
                UPDATE annunci 
                SET marca = ?, modello = ?, allestimento = ?, 
                    dati_tecnici = ?, punteggio_totale = ?, dettaglio_punteggi = ?, 
                    status = ?, motivo_scarto = ?, ai_usata = ?, 
                    data_ultimo_aggiornamento = ?
                WHERE url = ?
            ''', (
                marca, modello, allestimento,
                dati_tecnici_json, risultato.get("totale", 0), dettaglio_punteggi_json,
                risultato.get("status", "SCONOSCIUTO"), risultato.get("motivo", ""),
                1 if ai_used else 0, oggi, url
            ))
            
            db_conn.commit()
            print(f"      -> Punteggio Ricalcolato: {risultato.get('totale', 0)}/100 [{risultato.get('status', 'SCONOSCIUTO')}]")
            elaborati_con_successo += 1
            
        except Exception as e:
            print(f"      [!] Errore durante la rielaborazione di {url}: {e}")
            traceback.print_exc()
            db_conn.rollback()

    print(f"\n[*] Rielaborazione completata. {elaborati_con_successo}/{len(annunci)} aggiornati con successo.")
    
    export_to_json(db_conn)
    db_conn.close()

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    print(f"[*] Avvio CamperTracker RE-EVALUATOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    reprocess_database()
    print("\n[+] Script terminato.")