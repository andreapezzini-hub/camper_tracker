import json
import os
import sqlite3
import sys
from dotenv import load_dotenv

# Costanti di configurazione
DB_FILE = "camper_tracker.db"
JSON_EXPORT_FILE = "dati_storici.json"

def get_db_connection():
    """
    Stabilisce la connessione al database (SQLite locale o Turso Cloud).
    A differenza del main_engine, non crea un nuovo DB se non esiste, 
    poiché lo scopo qui è solo leggere dati esistenti.
    """
    # Carica le variabili d'ambiente dal file .env se presente
    load_dotenv("config.env")
    
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        try:
            import libsql
            return libsql.connect(turso_url, auth_token=turso_token)
        except ImportError:
            print("[!] Errore: libreria 'libsql-client' non trovata.")
            print("    Installala con: pip install libsql-experimental")
            sys.exit(1)
    else:
        print(f"[*] Connessione al database locale SQLite ('{DB_FILE}')...")
        if not os.path.exists(DB_FILE):
            print(f"[!] ERRORE: Il file database '{DB_FILE}' non esiste.")
            print("    Assicurati di aver eseguito prima lo scraper (main_engine.py).")
            sys.exit(1)
        return sqlite3.connect(DB_FILE)

def export_to_json(db_conn):
    """
    Esporta i dati dal database al formato JSON richiesto dal frontend.
    Questa logica è identica a quella presente in main_engine.py.
    """
    print(f"[*] Lettura dei dati in corso...")
    cursor = db_conn.cursor()
    
    try:
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
            
        print(f"[*] Creazione del file {JSON_EXPORT_FILE} in corso...")
        with open(JSON_EXPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(db_json, f, indent=4, ensure_ascii=False)
            
        print(f"[+] SUCCESSO: Esportazione completata! {len(annunci)} annunci esportati nel file '{JSON_EXPORT_FILE}'.")
        
    except sqlite3.Error as e:
        print(f"[!] ERRORE DATABASE: Si è verificato un errore durante la lettura dei dati: {e}")
    except Exception as e:
        print(f"[!] ERRORE IMPREVISTO: {e}")

if __name__ == "__main__":
    # Assicura il corretto encoding del terminale
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
    print("--- Avvio Utility di Esportazione JSON ---")
    
    # Inizializza e ottiene connessione DB
    conn = get_db_connection()
    
    try:
        # Avvia l'esportazione
        export_to_json(conn)
    finally:
        # Chiude sempre la connessione in modo sicuro
        conn.close()
        print("--- Operazione conclusa ---")