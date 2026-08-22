import argparse
import os
import sqlite3
from dotenv import load_dotenv

DB_FILE = "camper_tracker.db"

def get_db_connection():
    config_file_path = os.path.join(os.path.dirname(__file__), "local.env")
    load_dotenv(config_file_path)

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        import libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        return sqlite3.connect(DB_FILE)

def clear_dati_sito(db_conn, sito):
    print(f"[+] Pulizia dei dati (storico prezzi e annunci) per il sito: {sito} ...")
    cursor = db_conn.cursor()
    
    cursor.execute("""
        DELETE FROM storico_prezzi 
        WHERE url_annuncio IN (
            SELECT url FROM annunci WHERE sito = ?
        )
    """, (sito,))
    
    cursor.execute("DELETE FROM annunci WHERE sito = ?", (sito,))
    
    db_conn.commit()
    db_conn.close()
    print(f"[+] Dati del sito '{sito}' puliti con successo.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pulisce i dati di uno specifico sito nel database.")
    parser.add_argument("sito", type=str, help="Nome del sito da cancellare (es. '3C Srl')")
    
    args = parser.parse_args()

    db_conn = get_db_connection()
    clear_dati_sito(db_conn, args.sito)