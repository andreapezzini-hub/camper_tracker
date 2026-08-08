import sqlite3
import os
import requests
from bs4 import BeautifulSoup
import time
import re
import json
import math

DB_FILE = "camper_tracker.db"

# ==========================================
# 1. DATABASE OFFLINE (Ultimi 25 Anni)
# ==========================================
# Un catalogo massiccio precompilato per garantire 
# che lo strumento funzioni subito anche senza scraping.
CATALOGO_STORICO = [
    # --- HYMER ---
    ("Hymer", "B-Class", "MasterLine"),
    ("Hymer", "B-Class", "ModernComfort"),
    ("Hymer", "B-Class", "SupremeLine"),
    ("Hymer", "B-Class", "PremiumLine"),
    ("Hymer", "B-Class", "644"),
    ("Hymer", "B-Class", "654"),
    ("Hymer", "Exsis", "t 580"),
    ("Hymer", "Exsis", "i 580"),
    ("Hymer", "Exsis", "i 474"),
    ("Hymer", "ML-T", "580"),
    ("Hymer", "ML-T", "570"),
    ("Hymer", "Tramp", "S"),
    ("Hymer", "Grand Canyon", "S"),
    ("Hymer", "Ayers Rock", ""),
    ("Hymer", "Yosemite", ""),
    
    # --- ADRIA ---
    ("Adria", "Matrix", "Supreme"),
    ("Adria", "Matrix", "Plus"),
    ("Adria", "Matrix", "Axess"),
    ("Adria", "Matrix", "670 SL"),
    ("Adria", "Matrix", "670 SC"),
    ("Adria", "Coral", "Supreme"),
    ("Adria", "Coral", "Plus"),
    ("Adria", "Coral", "Axess"),
    ("Adria", "Coral", "XL"),
    ("Adria", "Sonic", "Supreme"),
    ("Adria", "Sonic", "Plus"),
    ("Adria", "Sonic", "Axess"),
    ("Adria", "Twin", "Supreme"),
    ("Adria", "Twin", "Plus"),
    ("Adria", "Compact", "Supreme"),
    
    # --- LAIKA ---
    ("Laika", "Ecovip", "1"),
    ("Laika", "Ecovip", "2"),
    ("Laika", "Ecovip", "309"),
    ("Laika", "Ecovip", "3009"),
    ("Laika", "Ecovip", "409"),
    ("Laika", "Kreos", "3000"),
    ("Laika", "Kreos", "4000"),
    ("Laika", "Kreos", "5000"),
    ("Laika", "Kreos", "7000"),
    ("Laika", "Kreos", "8000"),
    ("Laika", "Kosmo", "209"),
    ("Laika", "Kosmo", "509"),
    ("Laika", "Kosmo", "Urban"),
    
    # --- ROLLER TEAM ---
    ("Roller Team", "Kronos", "295 M"),
    ("Roller Team", "Kronos", "284 TL"),
    ("Roller Team", "Kronos", "265 TL"),
    ("Roller Team", "Zefiro", "295 M"),
    ("Roller Team", "Zefiro", "284 TL"),
    ("Roller Team", "Zefiro", "265 TL"),
    ("Roller Team", "Granduca", "295"),
    ("Roller Team", "Granduca", "284"),
    ("Roller Team", "Pegaso", "Mythos"),
    ("Roller Team", "Livingstone", "K2"),
    ("Roller Team", "Livingstone", "5"),
    ("Roller Team", "Livingstone", "Duo"),
    
    # --- CI (CARAVANS INTERNATIONAL) ---
    ("CI", "Magis", "95 M"),
    ("CI", "Magis", "84 XT"),
    ("CI", "Magis", "65 XT"),
    ("CI", "Horon", "95 M"),
    ("CI", "Horon", "84 XT"),
    ("CI", "Riviera", "84 XT"),
    ("CI", "Kyros", "2"),
    ("CI", "Kyros", "5"),
    ("CI", "Elliot", "5"),
    
    # --- ELNAGH ---
    ("Elnagh", "Baron", "22"),
    ("Elnagh", "Baron", "26"),
    ("Elnagh", "Baron", "531"),
    ("Elnagh", "T-Loft", "450"),
    ("Elnagh", "T-Loft", "530"),
    ("Elnagh", "Magnum", "581"),
    ("Elnagh", "Magnum", "530"),
    ("Elnagh", "E-Van", "2"),
    ("Elnagh", "E-Van", "5"),
    ("Elnagh", "Prince", "55 L"),
    ("Elnagh", "Duke", "46"),
    
    # --- MOBILVETTA ---
    ("Mobilvetta", "K-Yacht", "Tekno Line 85"),
    ("Mobilvetta", "K-Yacht", "Tekno Line 89"),
    ("Mobilvetta", "K-Yacht", "Tekno Line 90"),
    ("Mobilvetta", "Kea", "P65"),
    ("Mobilvetta", "Kea", "P67"),
    ("Mobilvetta", "Kea", "I86"),
    ("Mobilvetta", "Krosser", "P90"),
    ("Mobilvetta", "Krosser", "P86"),
    
    # --- MCLOUIS ---
    ("McLouis", "Glamys", "22"),
    ("McLouis", "Glamys", "320"),
    ("McLouis", "Mc4", "231"),
    ("McLouis", "Mc4", "281"),
    ("McLouis", "Mc4", "881"),
    ("McLouis", "Nevis", "881"),
    ("McLouis", "Nevis", "873"),
    ("McLouis", "Menfys", "S-Line"),
    ("McLouis", "Tandy", "640"),
    ("McLouis", "Steel", "462"),
    
    # --- CARTHAGO ---
    ("Carthago", "Chic C-Line", "I 4.9"),
    ("Carthago", "Chic C-Line", "I 5.0"),
    ("Carthago", "Chic E-Line", "I 50"),
    ("Carthago", "Chic E-Line", "I 51"),
    ("Carthago", "C-Tourer", "I 141"),
    ("Carthago", "C-Tourer", "T 143"),
    ("Carthago", "C-Compactline", "I 138"),
    ("Carthago", "Liner-for-two", "I 53"),
    
    # --- BURSTNER ---
    ("Burstner", "Lyseo", "Time T"),
    ("Burstner", "Lyseo", "TD Harmony Line"),
    ("Burstner", "Ixeo", "Time"),
    ("Burstner", "Ixeo", "TL"),
    ("Burstner", "Nexxo", "Van"),
    ("Burstner", "Elegance", "I 910"),
    ("Burstner", "Elegance", "I 920"),
    ("Burstner", "Campeo", "C 600"),
    ("Burstner", "Eliseo", "C 540"),
    ("Burstner", "Aviano", "I 684"),
    
    # --- DETHLEFFS ---
    ("Dethleffs", "Trend", "T 7057"),
    ("Dethleffs", "Trend", "I 7057"),
    ("Dethleffs", "Pulse", "T 7051"),
    ("Dethleffs", "Pulse", "I 7051"),
    ("Dethleffs", "Globetrotter", "XLI"),
    ("Dethleffs", "Globetrotter", "XXLA"),
    ("Dethleffs", "Just", "90"),
    ("Dethleffs", "Advantage", "T 6601"),
    
    # --- KNAUS ---
    ("Knaus", "Sky Ti", "650 MEG"),
    ("Knaus", "Sky Ti", "700 MEG"),
    ("Knaus", "Sun Ti", "650 MF"),
    ("Knaus", "Van Ti", "550 MD"),
    ("Knaus", "BoxStar", "Street 600"),
    ("Knaus", "BoxStar", "Family 600"),
    ("Knaus", "L!ve", "Wave 700"),
    ("Knaus", "L!ve", "Ti 650"),
    
    # --- CHALLENGER ---
    ("Challenger", "Genesis", "43"),
    ("Challenger", "Genesis", "288"),
    ("Challenger", "Mageo", "290"),
    ("Challenger", "Mageo", "398"),
    ("Challenger", "Graphite", "260"),
    ("Challenger", "Graphite", "380"),
    ("Challenger", "Vany", "V114"),
    
    # --- CHAUSSON ---
    ("Chausson", "Flash", "03"),
    ("Chausson", "Flash", "718"),
    ("Chausson", "Welcome", "78"),
    ("Chausson", "Welcome", "718"),
    ("Chausson", "Titanium", "640"),
    ("Chausson", "Titanium", "720"),
    ("Chausson", "Twist", "V594"),
    
    # --- RIMOR ---
    ("Rimor", "Seal", "12 P"),
    ("Rimor", "Seal", "69 Plus"),
    ("Rimor", "Seal", "9"),
    ("Rimor", "Evo", "77 Plus"),
    ("Rimor", "Evo", "5"),
    ("Rimor", "SuperBrig", "695"),
    ("Rimor", "SuperBrig", "687"),
    ("Rimor", "SuperBrig", "Suite"),
    ("Rimor", "Horus", "38"),
    ("Rimor", "Horus", "45"),
    ("Rimor", "Katamarano", "9"),
    ("Rimor", "Katamarano", "12P"),
    
    # --- BENIMAR ---
    ("Benimar", "Tessoro", "463"),
    ("Benimar", "Tessoro", "497"),
    ("Benimar", "Mileo", "263"),
    ("Benimar", "Mileo", "297"),
    ("Benimar", "Amphitryon", "997"),
    ("Benimar", "Amphitryon", "967"),
    ("Benimar", "Benivan", "116"),
    
    # --- ARCA ---
    ("Arca", "Europa", "M 745"),
    ("Arca", "Europa", "P 745"),
    ("Arca", "Europa", "H 745"),
    ("Arca", "SuperAmerica", "475"),
    ("Arca", "Freccia", "70"),
    
    # --- CARADO ---
    ("Carado", "T", "135"),
    ("Carado", "T", "338"),
    ("Carado", "T", "447"),
    ("Carado", "I", "338"),
    ("Carado", "I", "447"),
    ("Carado", "A", "461"),
    ("Carado", "V-Low", "V132"),
    
    # --- SUNLIGHT ---
    ("Sunlight", "T", "68"),
    ("Sunlight", "T", "69 L"),
    ("Sunlight", "I", "68"),
    ("Sunlight", "I", "69 L"),
    ("Sunlight", "A", "70"),
    ("Sunlight", "Cliff", "600"),
    
    # --- ETRUSCO ---
    ("Etrusco", "T", "7400"),
    ("Etrusco", "T", "6900"),
    ("Etrusco", "I", "7400"),
    ("Etrusco", "V", "5900"),
    
    # --- FRANKIA ---
    ("Frankia", "F-Line", "I 740"),
    ("Frankia", "M-Line", "I 7400"),
    ("Frankia", "Platin", "I 8400"),
    ("Frankia", "Titan", "I 890")
]

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

def inserisci_dati(db_conn, dati_catalogo):
    """
    Inserisce o aggiorna i dati nel database ignorando i duplicati perfetti.
    Gestisce tuple di lunghezze diverse (3 campi per storico, 9 per web scraping).
    """
    cursor = db_conn.cursor()
    inseriti = 0
    ignorati = 0
    
    for record in dati_catalogo:
        # Uniformazione della struttura (padding) se provengono dal catalogo storico
        if len(record) == 3:
            marca, modello, allestimento = record
            base, dimensioni, posti, disposizione, prezzo_euro, data_aggiornamento = ("", "", "", "", "", "")
        elif len(record) == 9:
            marca, modello, allestimento, base, dimensioni, posti, disposizione, prezzo_euro, data_aggiornamento = record
        else:
            print(f"[!] Record con formato inatteso ignorato: {record}")
            continue

        marca = marca.strip()
        modello = modello.strip()
        allestimento = allestimento.strip() if allestimento else ""
        
        # Verifica se la configurazione (Marca, Modello, Allestimento) esiste già per evitare doppioni logici
        cursor.execute('''
        SELECT COUNT(*) FROM catalogo_modelli 
        WHERE marca = ? COLLATE NOCASE 
        AND modello = ? COLLATE NOCASE 
        AND allestimento = ? COLLATE NOCASE
        ''', (marca, modello, allestimento))
        
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
            INSERT INTO catalogo_modelli (marca, modello, allestimento, base, dimensioni, posti, disposizione, prezzo_euro, data_aggiornamento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (marca, modello, allestimento, base, dimensioni, posti, disposizione, prezzo_euro, data_aggiornamento))
            inseriti += 1
        else:
            ignorati += 1
            
    db_conn.commit()
    print(f"[+] Dati Database -> Inseriti: {inseriti} | Ignorati (già presenti): {ignorati}")


def separa_marca_modello(titolo_completo):
    """
    Riconosce le marche composite per dividere correttamente la stringa.
    """
    marche_composite = {
        "roller team", "clever vans", "eura mobil", "font vendome", 
        "karmann mobil", "le voyageur", "sun living", "niesmann+bischoff",
        "caravans international"
    }
    
    titolo_lower = titolo_completo.lower()
    
    for mc in marche_composite:
        if titolo_lower.startswith(mc):
            marca = titolo_completo[:len(mc)].strip()
            modello = titolo_completo[len(mc):].strip()
            return marca, modello
            
    parti = titolo_completo.split(maxsplit=1)
    if len(parti) == 2:
        return parti[0], parti[1]
    
    return titolo_completo, "Serie Sconosciuta"

def usa_fallback_ollama(html_snippet):
    """
    Fallback RegEx -> AI Ollama.
    Restituisce un array JSON di oggetti con tutti i campi del database.
    """
    print("    [~] Attivazione fallback Ollama per l'estrazione...")
    try:
        prompt = f"""Analizza questo blocco HTML e restituisci SOLO un array JSON di oggetti.
        Ogni oggetto deve avere le chiavi: "marca", "modello", "allestimento", "base", "dimensioni", "posti", "disposizione", "prezzo_euro", "data_aggiornamento". 
        Estrai tutti gli allestimenti elencati nella tabella e separa marca dal modello, e scrivi la stringa 'allestimento' omettendo i nomi se ridondanti. 
        HTML:\n{html_snippet[:2500]}"""
        
        payload = {
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        # In ambiente reale de-commentare per fare la call a ollama:
        # response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=25)
        # dati_json = json.loads(response.json()['response'])
        # return [(d['marca'], d['modello'], d.get('allestimento', ''), d.get('base',''), d.get('dimensioni',''), d.get('posti',''), d.get('disposizione',''), d.get('prezzo_euro',''), d.get('data_aggiornamento','')) for d in dati_json]
        
        print("    [!] API Ollama non connessa. (Placeholder pronto)")
        return []
    except Exception as e:
        print(f"    [!] Fallback Ollama fallito: {e}")
        return []

# ==========================================
# 2. WEB SCRAPER AVANZATO
# ==========================================
def scrape_camper_catalog_web():
    """
    Modulo di scraping aggiornato per estrarre Marca, Modello, Allestimento e Dati Tabellari,
    implementando un sistema di paginazione automatizzato (HTTP POST).
    """
    URL_TARGET = "https://www.camperonline.it/listino/2026" 
    print(f"\n[*] Avvio Scraping Web su {URL_TARGET}...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Content-Type': 'application/x-www-form-urlencoded'  # Serve per le form POST
    }
    
    dati_estratti = []
    
    max_pages = 1
    current_page = 1
    
    while current_page <= max_pages:
        try:
            print(f"    -> Scansione Pagina {current_page}/{max_pages if max_pages > 1 else '?'}...")
            
            # Paginazione tramite payload POST ('page' viene iniettato nel form dal js originale)
            payload = {'page': str(current_page)}
            response = requests.post(URL_TARGET, headers=headers, data=payload, timeout=15)
            
            if response.status_code != 200:
                print(f"    [!] Accesso fallito (Status: {response.status_code}) alla pagina {current_page}.")
                break
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if current_page == 1:
                # Cerca i totali dal div o dagli span nascosti
                num_records = soup.find('span', id='numRecords')
                limit = soup.find('span', id='limit')
                
                if num_records and limit:
                    # Calcola il numero massimo di pagine dinamicamente (es. 1360 records / 60 per pagina)
                    max_pages = math.ceil(int(num_records.text) / int(limit.text))
                    print(f"    [i] Individuate dinamicamente {max_pages} pagine di catalogo da analizzare.")
                else:
                    print("    [!] Struttura paginazione non trovata. Verrà scansionata solo la prima pagina.")
            
            blocchi_modelli = soup.find_all('div', class_=lambda c: c and 'well' in c and 'well-sm' in c)
            
            if not blocchi_modelli:
                print(f"    [!] Nessun blocco trovato a pagina {current_page}.")
                # Se è la prima pagina, potremmo tentare il fallback
                if current_page == 1: usa_fallback_ollama(soup.body.prettify()[:5000])
                break

            for blocco in blocchi_modelli:
                blocco_html = str(blocco)
                
                # 1. Estrazione del titolo principale (Marca + Serie Modello)
                titolo_tag = blocco.find('h2')
                if not titolo_tag: continue
                b_tag = titolo_tag.find('b')
                if not b_tag: continue
                titolo_completo = b_tag.text.strip()
                marca, serie_modello = separa_marca_modello(titolo_completo)
                
                # 2. Estrazione "Data aggiornamento" dalla parte alta del blocco 
                # (Pattern flessibile RegEx per intercettare testo all'interno dei tag <p>)
                data_match = re.search(r'Data aggiornamento:\s*<b[^>]*>(.*?)</b>', blocco_html, re.IGNORECASE)
                data_aggiornamento = data_match.group(1).strip() if data_match else ""
                
                # 3. Estrazione righe (Modello-Allestimento, Base, Dimensioni, Posti, Peso, Disposizione, Euro) 
                # RegEx usata con DOTALL e ignorecase per superare spaziature variabili nel HTML
                pattern_riga = r'<tr[^>]*>.*?<td[^>]*>.*?<a[^>]*>(.*?)</a>.*?</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>.*?</tr>'
                
                righe_tabella = re.findall(pattern_riga, blocco_html, re.IGNORECASE | re.DOTALL)
                
                if righe_tabella:
                    for row_data in righe_tabella:
                        # Parsing grezzo da RegEx
                        raw_allestimento = row_data[0].strip()
                        base = row_data[1].strip()
                        dimensioni = row_data[2].strip()
                        posti = row_data[3].strip()
                        # peso = row_data[4].strip() # Sebbene estratto, omettiamo il peso da output come da richiesta 
                        disposizione = row_data[5].strip()
                        prezzo_euro = row_data[6].strip()
                        
                        # 4. Clean-Up del nome "Allestimento" 
                        # Per evitare ripetizioni tipo "Adria Matrix Supreme Matrix Supreme 670 DC", 
                        # rimuoviamo 'Marca' e/o 'Serie Modello' dall'inizio della stringa in modo dinamico.
                        allest_pulito = raw_allestimento
                        if allest_pulito.lower().startswith(marca.lower()):
                            allest_pulito = allest_pulito[len(marca):].strip()
                            
                        # Spesso il modello (es. "Matrix Supreme") è ripetuto
                        if allest_pulito.lower().startswith(serie_modello.lower()):
                            allest_pulito = allest_pulito[len(serie_modello):].strip()
                        
                        # Aggiunta del record normalizzato (9 campi)
                        dati_estratti.append((marca, serie_modello, allest_pulito, base, dimensioni, posti, disposizione, prezzo_euro, data_aggiornamento))
                else:
                    # RegEx failed for this table -> Fallback logico AI solo per il blocco
                    dati_ai = usa_fallback_ollama(blocco_html)
                    if dati_ai:
                        dati_estratti.extend(dati_ai)
                    else:
                        dati_estratti.append((marca, serie_modello, "", "", "", "", "", "", data_aggiornamento))
                        
        except Exception as e:
            print(f"    [!] Errore critico durante lo scraping pagina {current_page}: {e}")
            break
            
        # Paginazione avanzamento
        current_page += 1
        time.sleep(1.5) # Ritardo di cortesia verso il server target
        
    if dati_estratti:
        print(f"    [+] Scraping multi-pagina completato! Trovate {len(dati_estratti)} associazioni complete.")
    else:
        print("    [!] Nessun dato utile estratto dal parser HTML/RegEx.")
        
    return dati_estratti


def main():
    print("======================================================")
    print("      POPOLAMENTO CATALOGO MARCHE E MODELLI DB")
    print("======================================================")
    print("Questo script inietta nel database un catalogo storico,")
    print("poi esegue uno scraping profondo paginato per estrarre")
    print("Dati estesi, tabelle e prezzi, pulendo le stringhe duplicate.\n")
    
    conn = get_db_connection()
    
    # 1. Popolamento DB Base Offline
    print("[*] Fase 1: Iniezione Database Offline (Dati base)...")
    inserisci_dati(conn, CATALOGO_STORICO)
    
    # 2. Scraping Paginato Avanzato
    print("\n[*] Fase 2: Scraping Paginato del Listino Web...")
    dati_web = scrape_camper_catalog_web()
    
    if dati_web:
        inserisci_dati(conn, dati_web)
        
    conn.close()
    print("\n[+] Operazione completata! Il database camper_tracker.db è aggiornato con i nuovi campi estesi.")

if __name__ == "__main__":
    main()  
