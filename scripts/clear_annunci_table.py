import os
import sqlite3

from dotenv import load_dotenv

DB_FILE = "camper_tracker.db"

def get_db_connection():
    config_file_path = os.path.join(os.path.dirname(__file__), "local.env")
    load_dotenv(config_file_path)

    """Restituisce la connessione al database (SQLite locale o Turso Cloud)."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        import libsql_experimental as libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        return sqlite3.connect(DB_FILE)

def clear_annunci_table():
    print(f"[+] Pulizia della tabella annunci ...")
    cursor = db_conn.cursor()
    cursor.execute("DELETE FROM annunci")
    db_conn.commit()
    db_conn.close()
    print("[+] Tabella annunci pulita con successo.")

if __name__ == "__main__":

    # Inizializza e ottiene connessione SQLite
    db_conn = get_db_connection()
    
    clear_annunci_table()