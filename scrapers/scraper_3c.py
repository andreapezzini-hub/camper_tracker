import os
import re
import time
import requests
from bs4 import BeautifulSoup

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
# 2. CORE SCRAPER - 3C Srl
# ==========================================
def extract_price(text):
    prices = []
    
    # 1. Trova i prezzi associati al simbolo € o alla parola euro (gestisce migliaia con punto/senza punto ed eventuali decimali)
    pattern_currency = r'(?:€|euro)\s*(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?|(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?\s*(?:€|euro)'
    matches_curr = re.findall(pattern_currency, text, re.IGNORECASE)
    
    for m in matches_curr:
        val_str = m[0] if m[0] else m[1]
        if val_str:
            # Eliminiamo punti e virgole delle migliaia
            clean_val = re.sub(r'[.,]', '', val_str)
            if clean_val.isdigit():
                prices.append(int(clean_val))
                
    # 2. Trova numeri preceduti da termini specifici
    pattern_words = r'(?:prezzo|a\s+soli|tuo\s+a)\s*(?:di\s*)?(?::)?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?'
    matches_words = re.findall(pattern_words, text, re.IGNORECASE)
    for m in matches_words:
        if m:
            clean_val = re.sub(r'[.,]', '', m)
            if clean_val.isdigit():
                prices.append(int(clean_val))
                
    # Filtriamo i prezzi considerando solo quelli validi per un camper (> 5.000€)
    valid_prices = [p for p in prices if p >= 5000]
    
    if valid_prices:
        # Prende l'importo massimo tra quelli validi (così da scartare piccoli acconti se menzionati)
        return max(valid_prices)
        
    if prices:
        return max(prices)
        
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
    SITE_NAME = "3C Srl"
    BASE_URL = "https://3csrl.com"
    # Adattamento per i probabili path di 3C Srl
    TARGET_URLS = [
        f"{BASE_URL}/categoria-prodotto/camper-usati/",
        f"{BASE_URL}/categoria-prodotto/camper-nuovi/",
        f"{BASE_URL}/veicoli-usati/",
        f"{BASE_URL}/camper/"
    ]
    DISTANCE_FROM_SEREGNO = 170 # Reggio Emilia -> Seregno
    MAX_ANNUNCI = 500
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
                break
                
            target = urls_to_scan.pop(0)
            if target in scanned_targets:
                continue
            scanned_targets.add(target)
            
            print(f"    [{SITE_NAME}] Scansione sezione: {target}...")
            try:
                response = fetch_url_with_retry(session, target, headers=headers)
                if response.status_code == 404:
                    continue # Ignora se una delle categorie base non esiste
            except Exception:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Gestione Paginazione (es. /page/2/ o ?paged=2)
            for page_link in soup.find_all('a', href=True):
                href = page_link['href']
                if ('/page/' in href or '?paged=' in href) and BASE_URL in href and href not in scanned_targets:
                    if href not in urls_to_scan:
                        urls_to_scan.append(href)

            links_veicoli = soup.find_all('a', href=True)
            
            for link in links_veicoli:
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                url_parziale = link['href']
                
                # Ignora direttamente le scorciatoie di rete per telefono e mail
                if url_parziale.lower().startswith(('tel:', 'mailto:', 'javascript:')):
                    continue
                
                url_completo = url_parziale if url_parziale.startswith('http') else f"{BASE_URL.rstrip('/')}/{url_parziale.lstrip('/')}"
                
                # Deve essere dominio corretto
                if BASE_URL not in url_completo:
                    continue
                
                path_lower = url_parziale.lower()
                skip_words = ['chi-siamo', 'contatti', 'dove', 'noleggio', 'officina', 'servizi', 'privacy', 'cookie', 'index', 'caravan', 'rimorchi', 'barca', 'carrelli', 'login', 'cart', 'checkout', 'carrello', 'my-account']
                if any(skip in path_lower for skip in skip_words) or url_completo in scanned_targets:
                    continue
                
                # Cerchiamo pattern tipici di schede prodotto / veicoli
                is_product = ('/prodotto/' in path_lower or '/veicolo/' in path_lower or '/camper/' in path_lower or '-it-' in path_lower)
                # Spesso gli URL prodotti sono lunghi
                if not is_product and len(url_completo.split('/')[-1]) < 15:
                    continue
                
                if url_completo in processed_urls: continue
                processed_urls.add(url_completo)
                
                print(f"    [{SITE_NAME}] Check URL: {url_completo}")
                
                try:
                    time.sleep(0.5) 
                    det_resp = fetch_url_with_retry(session, url_completo, headers=headers)
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                        hidden.decompose()
                        
                    for menu in det_soup.find_all(['div', 'ul'], class_=re.compile(r'menu|nav|footer|header|sidebar|widget', re.I)):
                        menu.decompose()
                    for menu in det_soup.find_all(['div', 'ul'], id=re.compile(r'menu|nav|footer|header|sidebar', re.I)):
                        menu.decompose()
                        
                    testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                    testo_dettaglio_lower = testo_dettaglio.lower()
                    
                    # Controllo parole chiave vietate solo nel titolo principale e URL per evitare falsi positivi nel footer
                    h1_testo = " ".join([h1.get_text(separator=" ") for h1 in det_soup.find_all('h1')]).lower()
                    if re.search(r'\b(roulotte|noleggio|noleggi|caravan)\b', h1_testo) or re.search(r'\b(roulotte|noleggio|noleggi|caravan)\b', url_completo.lower()):
                        print("      [!] Saltato: Trovate parole chiave vietate nell'intestazione o nell'URL.")
                        continue
                        
                    prezzo = extract_price(testo_dettaglio)
                    
                    if prezzo < 5000 and "0,00" not in testo_dettaglio_lower and "trattativa riservata" not in testo_dettaglio_lower:
                        print(f"      [!] Saltato: Prezzo non valido ({prezzo}€).")
                        continue 
                    
                    print(f"    [{SITE_NAME}] >>> Avvio estrazione dati per: {url_completo}")
                    
                    img_url = None
                    # WooCommerce spesso usa immagini di classe wp-post-image o gallerie
                    img_tags = det_soup.find_all('img', class_=re.compile(r'wp-post-image|woocommerce-main-image|attachment-shop_single'))
                    if not img_tags:
                        img_tags = det_soup.find_all('img')
                        
                    for img in img_tags:
                        src = img.get('src') or img.get('data-src') or img.get('data-large_image')
                        if src and ('upload' in src.lower() or 'camper' in src.lower() or 'prodotto' in src.lower()):
                            img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                            break
                    
                    testo_finale = f"--- DETTAGLI ---\n{testo_dettaglio}"
                    if len(testo_finale) > 3000:
                        testo_finale = testo_finale[:3000]

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
                    
                except Exception as inner_e:
                    print(f"      [!] Impossibile leggere dettaglio: {inner_e}")

    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator