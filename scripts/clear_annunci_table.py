import sqlite3

DB_FILE = "camper_tracker.db"

def clear_annunci_table():
    print(f"[+] Pulizia della tabella annunci in {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM annunci")
    conn.commit()
    conn.close()
    print("[+] Tabella annunci pulita con successo.")

if __name__ == "__main__":
    clear_annunci_table()