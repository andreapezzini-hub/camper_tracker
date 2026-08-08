import sqlite3

DB_FILE = "camper_tracker.db"

def clear_storico_prezzi_table():
    print(f"[+] Pulizia della tabella storico_prezzi in {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM storico_prezzi")
    conn.commit()
    conn.close()
    print("[+] Tabella storico_prezzi pulita con successo.")

if __name__ == "__main__":
    clear_storico_prezzi_table()