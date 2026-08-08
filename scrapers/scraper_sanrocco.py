import os
import re
import time
import requests
from bs4 import BeautifulSoup
import sqlite3

# Importiamo il modulo di utilità condiviso
import scraper_utils

# ==========================================
# 1. LOGICA REGEX (Adattata per DB)
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else None
    
    km_match = re.search(r'km\s*(\d{1,3}(?:\.\d{3})+|\d{1,6})', testo)
    km = int(km_match.group(1).replace('.', '')) if km_match else None
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo):
        km = 0
        
    # LOGICA AFFINATA PER LE CATEGORIE: GERARCHIA RIGOROSA
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    
    # Protezione per evitare false assegnazioni al semintegrale
    if tipo_furgonato:
        tipo_semintegrale = False
        tipo_motorhome = False
        tipo_mansardato = False
    elif tipo_mansardato:
        tipo_semintegrale = False
        tipo_motorhome = False
    elif tipo_semintegrale:
        tipo_motorhome = False
    elif tipo_motorhome and not re.search(r'\bsemi[\s-]?integral[ei]\b', testo):
        tipo_semintegrale = False
    
    lunghezza = None
    # Catturiamo i numeri decimali nel testo (misure come 7.4, 7.35, 2.95, ecc.)
    misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
    if misure_dec:
        floats = [float(m.replace(',', '.')) for m in misure_dec]
        # REGOLA: un camper non sarà mai meno lungo di 5 metri, e non sarà mai più alto/largo di 5 metri.
        lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
        if lunghezze_valide:
            lunghezza = max(lunghezze_valide)
            
    # Fallback in caso la lunghezza sia indicata intera es. "lunghezza 7 m" 
    if lunghezza is None:
        match_lung = re.search(r'lunghezza\s*[:]?\s*(\d+[.,]?\d*)', testo)
        if match_lung:
            lunghezza = float(match_lung.group(1).replace(',', '.'))

    posti_omologati = None
    posti_letto = None
    
    match_omologati = re.search(r'(?:omologati|viaggio)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*(?:omologati|viaggio)', testo)
    if match_omologati: posti_omologati = int(match_omologati.group(1))
    
    match_letto = re.search(r'(?:letto|dormire)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*letto', testo)
    if match_letto: posti_letto = int(match_letto.group(1))
    
    if posti_omologati is None and posti_letto is None:
        match_barassi = re.search(r'\b(\d)\s+(\d)\s+(?:\d{2,3}[.,]\d{3})', testo)
        if match_barassi:
            posti_omologati = int(match_barassi.group(1))
            posti_letto = int(match_barassi.group(2))

    cv_match = re.search(r'(\d{3})\s*cv', testo)
    potenza = int(cv_match.group(1)) if cv_match else None
    
    # Regole di estrazione Riscaldamento
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|riscaldatore\s*supplementare', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pack\s*winter|pacchetto\s*invernale|predisposizione\s*invernale', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria|due\s*batterie|2\s*batterie', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti|piedini\s*idraulici|autolivellanti', testo))
    
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|letto\s*a\s*castello|\bcastello\b', testo))
    
    peso = 3500 # Default patente B comune
    match_peso = re.search(r'(\d{4})\s*kg', testo)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r'patente\s*c|oltre\s*3500|heavy|maxi', testo):
        peso = 4250
    
    # NUOVA LOGICA: Cerca prima nel DB catalogo_modelli usando utils
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    
    if match_db:
        marca = match_db["marca"]
        modello = match_db["modello"]
        allestimento = match_db["allestimento"]
    else:
        # Fallback se il DB non ha corrispondenze
        parole = str(raw_text).split()
        parole_utili = []
        stop_words = ['nuovo', 'usato', 'pronta', 'consegna', 'camper', 'occasione', '']
        
        for p in parole:
            p_clean = re.sub(r'[^\w\s]', '', p).strip()
            if p_clean.lower() not in stop_words and p_clean:
                parole_utili.append(p_clean.capitalize())
            if len(parole_utili) == 5:
                break
                
        modello_fallback = " ".join(parole_utili) if parole_utili else "Sconosciuto"
        modello_fallback = re.sub(r'^(?:Selection\s*)?\d+\s+', '', modello_fallback, flags=re.IGNORECASE)
        marca = "Sconosciuto"
        modello = modello_fallback
        allestimento = ""
    
    return {
        "marca": marca,
        "modello": modello,
        "allestimento": allestimento,
        "prezzo": current_price,
        "anno": anno,
        "chilometri": km,
        "nuovo": km == 0,
        "peso": peso,
        "tipo_furgonato": tipo_furgonato,
        "tipo_mansardato": tipo_mansardato,
        "tipo_motorhome": tipo_motorhome,
        "tipo_semintegrale": tipo_semintegrale,
        "lunghezza": lunghezza,
        "potenza": potenza,
        "posti_omologati": posti_omologati,
        "posti_letto": posti_letto,
        "telaio_alko": 'alko' in testo or 'al-ko' in testo,
        "doppio_pavimento": 'doppio pavimento' in testo,
        "cambio_automatico": 'automatico' in testo,
        "emissioni_euro6": bool(re.search(r'euro\s*6', testo)) or (anno is not None and anno >= 2017),"pannelli_solari": 'pannell' in testo and 'solar' in testo,
        "batterie_litio": batterie_litio,
        "sospensioni_aria": 'sospensioni' in testo and ('aria' in testo or 'pneumat' in testo),
        "predisposizione_invernale": predisposizione_invernale,
        "doppia_batteria": doppia_batteria,
        "aria_condizionata": 'clima' in testo or 'condizionata' in testo,
        "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio,
        "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti,
        "letto_nautico": 'letto nautico' in testo,
        "letti_gemelli": letti_gemelli,
        "letti_a_castello": letti_a_castello
    }

# ==========================================
# 2. CORE SCRAPER - SAN ROCCO NAUTICA
# ==========================================
def extract_price(text):
    match = re.search(r'€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?', text)
    if match:
        return int(match.group(1).replace('.', '').replace(',', ''))
    return 0

def clean_text_preserve_lists(text):
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def fetch_url_with_retry(session, url, headers, max_retries=3, timeout=25):
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.RequestException, Exception) as e:
            if attempt == max_retries:
                raise e
            print(f"      [!] Rete/Timeout su {url} (tentativo {attempt}/{max_retries}), riprovo... ({e})")
            time.sleep(2 * attempt)

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "San Rocco Nautica Campeggio"
    BASE_URL = "https://www.sanrocconauticacampeggio.com"
    TARGET_URLS = [
        f"{BASE_URL}/it/Camper.htm",
        f"{BASE_URL}/it/Il-Nostro-Usato/Usato-Camper.htm",
        f"{BASE_URL}/it/Nuovo-in-promozione.htm"
    ]
    DISTANCE_FROM_SEREGNO = 40 
    MAX_ANNUNCI = 500  # Limite annunci elaborati per sessione
    count_elaborati = 0
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    session = requests.Session()
    
    try:
        processed_urls = set()
        urls_to_scan = list(TARGET_URLS)
        scanned_targets = set()
        
        while urls_to_scan:
            if count_elaborati >= MAX_ANNUNCI:
                print(f"    [{SITE_NAME}] Raggiunto limite massimo di annunci ({MAX_ANNUNCI}). Stop scansione.")
                break
                
            target = urls_to_scan.pop(0)
            if target in scanned_targets:
                continue
            scanned_targets.add(target)
            
            print(f"    [{SITE_NAME}] Scansione sezione: {target}...")
            try:
                response = fetch_url_with_retry(session, target, headers=headers, timeout=25)
            except Exception as target_e:
                print(f"      [!] Impossibile scaricare la sezione {target}: {target_e}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links_veicoli = soup.find_all('a', href=True)
            
            for link in links_veicoli:
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                url_parziale = link['href']
                
                # Identifica pagine figlie/dettaglio camper
                if not url_parziale.endswith('.htm') and not url_parziale.endswith('.html'):
                    continue
                    
                url_completo = BASE_URL + "/" + url_parziale.lstrip('/') if not url_parziale.startswith('http') else url_parziale
                
                # Se è una sottocategoria camper (es. /it/Camper/Laika.htm), aggiungila ai target da scansionare
                if url_completo.endswith('.htm') and '/it/camper/' in url_completo.lower() and url_completo not in scanned_targets:
                    if url_completo not in urls_to_scan:
                        urls_to_scan.append(url_completo)
                    continue
                
                # Esclusione stringente basata SOLO sul percorso relativo dell'URL (path) per non escludere il dominio
                path_lower = url_parziale.lower()
                skip_words = ['chi-siamo', 'contatti', 'dove', 'noleggio', 'officina', 'servizi', 'privacy', 'cookie', 'index', 'caravan', 'rimorchi', 'barca', 'barche', 'gommon', 'nautica', 'accessori', 'campeggio', 'tende', 'motori', 'fuoribordo', 'carrelli', 'login', 'password', 'registrati']
                if any(skip in path_lower for skip in skip_words) or url_completo in TARGET_URLS or url_completo in scanned_targets:
                    continue
                
                # I veri link dei veicoli sono lunghi (es. marca e modello). Le categorie sono brevi.
                # San Rocco usa spesso .html per i prodotti singoli e .htm per le categorie generiche.
                is_html = url_completo.endswith('.html')
                if len(url_completo) < 65 and not is_html:
                    continue
                
                if url_completo in processed_urls: continue
                processed_urls.add(url_completo)
                
                print(f"    [{SITE_NAME}] Check URL: {url_completo}")
                
                try:
                    time.sleep(0.5) 
                    det_resp = fetch_url_with_retry(session, url_completo, headers=headers, timeout=25)
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    # =========================================================================
                    # FONDAMENTALE: Rimuovere il menu e footer PRIMA di cercare parole vietate
                    # Altrimenti la parola "noleggio" (presente nel menu) farà scartare TUTTI i camper!
                    # =========================================================================
                    for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                        hidden.decompose()
                        
                    # Rimuoviamo specifici div e container identificabili come navigazione o menu laterali
                    for menu in det_soup.find_all(['div', 'ul'], class_=re.compile(r'menu|nav|footer|header|sidebar', re.I)):
                        menu.decompose()
                    for menu in det_soup.find_all(['div', 'ul'], id=re.compile(r'menu|nav|footer|header|sidebar', re.I)):
                        menu.decompose()
                        
                    testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                    testo_dettaglio_lower = testo_dettaglio.lower()
                    
                    # Ora il controllo testo_dettaglio_lower opererà SOLTANTO sul contenuto testuale principale
                    if re.search(r'\b(roulotte|noleggio|noleggi|barca|gommone|fuoribordo)\b', testo_dettaglio_lower) or "categoria caravan" in testo_dettaglio_lower:
                        print("      [!] Saltato: Trovate parole chiave vietate (es. barca, noleggio) nel corpo testuale.")
                        continue
                        
                    prezzo = extract_price(testo_dettaglio)
                    
                    # Salva da finti check: tolleriamo prezzi 0 per camper usati da valutare o "trattativa riservata"
                    if prezzo < 5000 and "0,00" not in testo_dettaglio_lower and "trattativa riservata" not in testo_dettaglio_lower:
                        print(f"      [!] Saltato: Prezzo non valido ({prezzo}€) e nessuna dicitura speciale trovata.")
                        continue 
                    
                    print(f"    [{SITE_NAME}] >>> Avvio estrazione dati per: {url_completo}")
                    
                    img_url = None
                    for img in det_soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if src and ('usato' in src.lower() or 'camper' in src.lower() or 'upload' in src.lower()):
                            img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                            break
                    
                    testo_finale = f"--- DETTAGLI ---\n{testo_dettaglio}"

                    if len(testo_finale) > 3000:
                        testo_finale = testo_finale[:3000]

                    # Utilizziamo la funzione modulare di utils
                    scraper_utils.process_listing(
                        db_conn=db_conn, 
                        config=config, 
                        url=url_completo, 
                        site_name=SITE_NAME, 
                        raw_text=testo_finale, 
                        current_price=prezzo, 
                        distance=DISTANCE_FROM_SEREGNO, 
                        img_url=img_url,
                        regex_extractor_func=regex_extract_camper_data,
                        ollama_config=ollama_config
                    )
                    
                    count_elaborati += 1
                    if count_elaborati >= MAX_ANNUNCI:
                        print(f"    [{SITE_NAME}] Raggiunto limite massimo di annunci ({MAX_ANNUNCI}). Stop scansione.")
                        break
                    
                except Exception as inner_e:
                    print(f"      [!] Impossibile leggere dettaglio: {inner_e}")

    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    
    # Helper finto per simulare DB durante test isolato
    def get_test_db():
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE annunci (url TEXT, prezzo_attuale REAL, url_immagine TEXT, dati_tecnici TEXT, punteggio_totale REAL, dettaglio_punteggi TEXT, status TEXT, motivo_scarto TEXT, data_scoperta TEXT, data_ultimo_aggiornamento TEXT, ai_usata INTEGER, testo_originale TEXT, sito TEXT, marca TEXT, modello TEXT, allestimento TEXT, distanza_seregno INTEGER)")
        cursor.execute("CREATE TABLE storico_prezzi (url_annuncio TEXT, data TEXT, prezzo REAL)")        
        cursor.execute("CREATE TABLE catalogo_modelli (marca TEXT, modello TEXT, allestimento TEXT)")
        cursor.execute("INSERT INTO catalogo_modelli VALUES ('Hymer', 'B-Class', '644')")
        conn.commit()
        return conn
    
    print("Avvio test isolato Scraper San Rocco (SQLite)...")
    mock_db_conn = get_test_db()
    mock_config = score_calculator.load_config() if os.path.exists('../scoring_config.json') else {"categories": {}}
    run_scraper(mock_db_conn, mock_config)
    print("\n[+] Esecuzione test DB in memoria completata.")