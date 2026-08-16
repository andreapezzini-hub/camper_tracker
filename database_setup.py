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
        db_exists = os.path.exists(DB_FILE)
        conn = sqlite3.connect(DB_FILE)
        
        # Se il file .db non esisteva, inizializziamo le tabelle
        if not db_exists:
            setup_database(conn)
            
        return conn

def setup_database(db_conn):
    print(f"[*] Inizializzazione database...")
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

    # Tabella Catalogo Modelli
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
    
    # Tabella Proposte Catalogo
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

    # Aggiornamento schema per tabelle preesistenti
    colonne_da_aggiungere = [
        "base TEXT",
        "dimensioni TEXT",
        "posti TEXT",
        "disposizione TEXT",
        "prezzo_euro TEXT",
        "data_aggiornamento TEXT"
    ]
    
    for col in colonne_da_aggiungere:
        try:
            cursor.execute(f"ALTER TABLE catalogo_modelli ADD COLUMN {col}")
        except Exception as e:
            if "duplicate column name" not in str(e):
                raise e

    # Popolamento iniziale catalogo
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
        
    print("[+] Setup del database completato con successo.")

if __name__ == "__main__":
    # Inizializza e ottiene connessione
    db_conn = get_db_connection()
    
    # Assicura che le tabelle siano create anche se il file .db esisteva già
    setup_database(db_conn)
    
    # Chiude la connessione alla fine dello script
    db_conn.close()