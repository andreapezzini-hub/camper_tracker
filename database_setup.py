import sqlite3
import os

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

def setup_database():
    print(f"[*] Inizializzazione database SQLite...")
    cursor = db_conn.cursor()

    # Tabella Annunci
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS annunci (
        url TEXT PRIMARY KEY,
        sito TEXT,
        marca TEXT,
        modello TEXT,
        allestimento TEXT,
        distanza_seregno INTEGER,
        prezzo_attuale REAL,
        dati_tecnici TEXT,
        punteggio_totale REAL,
        dettaglio_punteggi TEXT,
        status TEXT,
        motivo_scarto TEXT,
        data_scoperta TEXT,
        data_ultimo_aggiornamento TEXT,
        url_immagine TEXT,
        ai_usata INTEGER,
        testo_originale TEXT
    )
    ''')

    # Tabella Storico Prezzi
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS storico_prezzi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url_annuncio TEXT,
        data TEXT,
        prezzo REAL,
        FOREIGN KEY(url_annuncio) REFERENCES annunci(url)
    )
    ''')

    # Nuova Tabella Catalogo (Aggiornata con i campi estesi dello scraper)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS catalogo_modelli (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        marca TEXT NOT NULL,
        modello TEXT NOT NULL,
        allestimento TEXT,
        base TEXT,
        dimensioni TEXT,
        posti TEXT,
        disposizione TEXT,
        prezzo_euro TEXT,
        data_aggiornamento TEXT
    )
    ''')
    
    # NUOVA TABELLA: Proposte Catalogo (Con campi estesi richiesti)
    # Serve come "area di parcheggio" per i nuovi modelli trovati dall'AI
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS proposte_catalogo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url_annuncio TEXT,
        marca_proposta TEXT,
        modello_proposto TEXT,
        allestimento_proposto TEXT,
        base_proposta TEXT,
        dimensioni_proposta TEXT,
        posti_proposta TEXT,
        disposizione_proposta TEXT,
        motivazione_ai TEXT,
        stato TEXT DEFAULT 'DA_APPROVARE',
        data_proposta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(url_annuncio) REFERENCES annunci(url)
    )
    ''')

    # Tentativo di aggiornamento schema se la tabella esisteva già con la vecchia struttura
    try:
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN base TEXT")
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN dimensioni TEXT")
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN posti TEXT")
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN disposizione TEXT")
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN prezzo_euro TEXT")
        cursor.execute("ALTER TABLE catalogo_modelli ADD COLUMN data_aggiornamento TEXT")
    except sqlite3.OperationalError:
        pass  # Le colonne esistono già, procediamo oltre

    # Popolamento iniziale di esempio del catalogo modelli
    dati_iniziali = [
        ("Hymer", "B-Class", "644"),
        ("Hymer", "Exsis", "i 580"),
        ("Adria", "Matrix", "Plus 670"),
        ("Adria", "Coral", "XL"),
        ("Laika", "Kreos", "5009"),
        ("Laika", "Ecovip", "3009"),
        ("Roller Team", "Kronos", "295 M"),
        ("Roller Team", "Zefiro", "265 TL"),
        ("Carthago", "Chic C-Line", "I 4.9"),
        ("Mobilvetta", "K-Yacht", "Tekno Line"),
        ("Elnagh", "Magnum", "581")
    ]

    print("[*] Popolamento catalogo modelli...")
    cursor.execute("SELECT COUNT(*) FROM catalogo_modelli")
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.executemany('''
        INSERT INTO catalogo_modelli (marca, modello, allestimento)
        VALUES (?, ?, ?)
        ''', dati_iniziali)
        db_conn.commit()
        print(f"[+] Inseriti {len(dati_iniziali)} modelli nel catalogo.")
    else:
        print("[+] Il catalogo modelli contiene già dati.")

    db_conn.close()
    print("[+] Setup del database completato con successo.")

if __name__ == "__main__":
    
    # Inizializza e ottiene connessione SQLite
    db_conn = get_db_connection()
    
    setup_database()
