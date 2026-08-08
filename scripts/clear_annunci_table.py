import sqlite3

DB_FILE = "camper_tracker.db"

def get_db_connection():
    """Restituisce la connessione al database (SQLite locale o Turso Cloud)."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        print("[*] Connessione al database remoto su Turso (Cloud)...")
        import libsql_experimental as libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        if not os.path.exists(DB_FILE):
            database_setup.setup_database()
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
