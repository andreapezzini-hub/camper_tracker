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
        import libsql
        return libsql.connect(turso_url, auth_token=turso_token)
    else:
        print("[*] Connessione al database locale SQLite...")
        return sqlite3.connect(DB_FILE)

def clear_dati_sito(sito):
    print(f"[+] Pulizia dei dati (storico prezzi e annunci) per il sito: {sito} ...")
    cursor = db_conn.cursor()
    
    # Elimina prima lo storico prezzi collegato agli annunci di questo sito per evitare errori di Foreign Key.
    # N.B. Assumo che la foreign key in storico_prezzi sia 'id_annuncio' e la primary key in annunci sia 'id'.
    # Se utilizzi l'URL come chiave o nomi diversi per le colonne, modificali di conseguenza qui sotto.
    cursor.execute("""
        DELETE FROM storico_prezzi 
        WHERE id_annuncio IN (
            SELECT id FROM annunci WHERE sito = ?
        )
    """, (sito,))
    
    # Ora elimina gli annunci specifici del sito
    cursor.execute("DELETE FROM annunci WHERE sito = ?", (sito,))
    
    db_conn.commit()
    db_conn.close()
    print(f"[+] Dati del sito '{sito}' puliti con successo.")

if __name__ == "__main__":

    # Variabile per il sito specifico da cancellare (es. 'subito.it', 'bakeca.it', ecc.)
    SITO_DA_CANCELLARE = "Groppetti"

    # Inizializza e ottiene connessione SQLite
    db_conn = get_db_connection()
    
    clear_dati_sito(SITO_DA_CANCELLARE)
