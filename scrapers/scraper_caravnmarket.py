import os
import re
import time
import requests
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

import scraper_utils

# ==========================================
# 1. LOGICA REGEX (Condivisa)
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else None
    
    km_match = re.search(r'km\s*(\d{1,3}(?:\.\d{3})+|\d{1,6})', testo)
    km = int(km_match.group(1).replace('.', '')) if km_match else None
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo): km = 0
        
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    
    if tipo_furgonato: tipo_semintegrale = tipo_motorhome = tipo_mansardato = False
    elif tipo_mansardato: tipo_semintegrale = tipo_motorhome = False
    elif tipo_semintegrale: tipo_motorhome = False
    elif tipo_motorhome and not re.search(r'\bsemi[\s-]?integral[ei]\b', testo): tipo_semintegrale = False
    
    lunghezza = None
    misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
    if misure_dec:
        floats = [float(m.replace(',', '.')) for m in misure_dec]
        lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
        if lunghezze_valide: lunghezza = max(lunghezze_valide)
            
    if lunghezza is None:
        match_lung = re.search(r'lunghezza\s*[:]?\s*(\d+[.,]?\d*)', testo)
        if match_lung: lunghezza = float(match_lung.group(1).replace(',', '.'))

    posti_omologati = posti_letto = None
    match_omologati = re.search(r'(?:omologati|viaggio)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*(?:omologati|viaggio)', testo)
    if match_omologati: posti_omologati = int(match_omologati.group(1))
    
    match_letto = re.search(r'(?:letto|dormire)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*letto', testo)
    if match_letto: posti_letto = int(match_letto.group(1))

    cv_match = re.search(r'(\d{3})\s*cv', testo)
    potenza = int(cv_match.group(1)) if cv_match else None
    
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|riscaldamento\s*(?:a\s*)?gasolio', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pacchetto\s*invernale', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti', testo))
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|\bcastello\b', testo))
    
    peso = 3500
    match_peso = re.search(r'(\d{4})\s*kg', testo)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r'patente\s*c|oltre\s*3500|heavy', testo): peso = 4250
    
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    if match_db:
        marca, modello, allestimento = match_db["marca"], match_db["modello"], match_db["allestimento"]
    else:
        parole = [re.sub(r'[^\w\s]', '', p).strip().capitalize() for p in str(raw_text).split() if p.strip().lower() not in ['nuovo', 'usato', 'pronta', 'consegna', 'camper']]
        modello_fallback = " ".join(parole[:5]) if parole else "Sconosciuto"
        marca, modello, allestimento = "Sconosciuto", modello_fallback, ""
    
    return {
        "marca": marca, "modello": modello, "allestimento": allestimento, "prezzo": current_price,
        "anno": anno, "chilometri": km, "nuovo": km == 0, "peso": peso,
        "tipo_furgonato": tipo_furgonato, "tipo_mansardato": tipo_mansardato, "tipo_motorhome": tipo_motorhome,
        "tipo_semintegrale": tipo_semintegrale, "lunghezza": lunghezza, "potenza": potenza,
        "posti_omologati": posti_omologati, "posti_letto": posti_letto,
        "telaio_alko": 'alko' in testo, "doppio_pavimento": 'doppio pavimento' in testo,
        "cambio_automatico": 'automatico' in testo, "emissioni_euro6": bool(re.search(r'euro\s*6', testo)),
        "pannelli_solari": 'pannell' in testo and 'solar' in testo, "batterie_litio": batterie_litio,
        "sospensioni_aria": 'sospensioni' in testo and 'aria' in testo,
        "predisposizione_invernale": predisposizione_invernale, "doppia_batteria": doppia_batteria,
        "aria_condizionata": 'clima' in testo, "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio, "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti, "letto_nautico": 'letto nautico' in testo,
        "letti_gemelli": letti_gemelli, "letti_a_castello": letti_a_castello
    }

# ==========================================
# 2. CORE SCRAPER - CARAVAN MARKET
# ==========================================
def extract_price(text):
    match = re.search(r'€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?', text)
    if match: return int(match.group(1).replace('.', '').replace(',', ''))
    return 0

def clean_text(text): return re.sub(r'\n\s*\n', '\n', re.sub(r'[ \t]+', ' ', text)).strip()

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Caravan Market"
    BASE_URL = "https://www.caravanmarket.com"
    
    # Sezioni principali da esplorare
    TARGET_CATEGORIES = [
        f"{BASE_URL}/vendita-camper-nuovi",
        f"{BASE_URL}/camper-usati",
        f"{BASE_URL}/van-nuovi",
        f"{BASE_URL}/furgonati-usati",
        f"{BASE_URL}/motorhome-usati",
        f"{BASE_URL}/semintegrali-usati"
    ]
    
    DISTANCE_FROM_SEREGNO = 190  # Vicenza -> Seregno
    MAX_ANNUNCI = 500
    count_elaborati = 0
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    processed_urls = set()
    scanned_pages = set()
    urls_to_scan = list(TARGET_CATEGORIES)
    
    try:
        while urls_to_scan and count_elaborati < MAX_ANNUNCI:
            target = urls_to_scan.pop(0)
            if target in scanned_pages:
                continue
            scanned_pages.add(target)
            
            print(f"    [{SITE_NAME}] Scansione pagina: {target}...")
            
            try:
                response = session.get(target, headers=headers, timeout=20)
                if response.status_code != 200:
                    continue
            except Exception as e:
                print(f"    [{SITE_NAME}] Errore connessione a {target}: {e}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # --- 1. Rilevamento Paginazione ---
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                full_page_url = urljoin(BASE_URL, href)
                
                # Accetta solo pagine di paginazione appartenenti alle categorie target
                if ('page=' in full_page_url or 'paged=' in full_page_url) and any(cat in full_page_url for cat in TARGET_CATEGORIES):
                    if full_page_url not in scanned_pages and full_page_url not in urls_to_scan:
                        urls_to_scan.append(full_page_url)

            # --- 2. Rilevamento Annunci Veicoli ---
            for link in soup.find_all('a', href=True):
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                raw_href = link['href'].strip()
                
                # Salva solo link validi evitando '...', '#', 'javascript:', etc.
                if not raw_href or raw_href.startswith(('#', 'javascript:', 'mailto:')):
                    continue
                    
                url_completo = urljoin(BASE_URL, raw_href)
                
                # Pulisce query string se non necessaria (es. rimozione di ?limit=... o parametri di tracciamento)
                parsed_url = urlparse(url_completo)
                path = parsed_url.path
                
                # Ignora link a se stessi, paginazioni o risorse di sistema
                if path in ['/', '/index.php', ''] or 'page=' in url_completo:
                    continue
                    
                # Regola di Matching Annuncio:
                # Un annuncio valido deve iniziare con una delle categorie e avere una sottopath (il nome del veicolo)
                is_valid_listing = False
                for cat in TARGET_CATEGORIES:
                    cat_path = urlparse(cat).path
                    if path.startswith(cat_path + '/') and len(path) > len(cat_path) + 1:
                        is_valid_listing = True
                        break
                        
                if not is_valid_listing:
                    continue
                    
                # Parole chiave da ignorare (filtri di navigazione/pagine statiche)
                path_lower = path.lower()
                if any(skip in path_lower for skip in [
                    'noleggio', 'contatti', 'caravan', 'rimorchi', 'accessori', 
                    'privacy', 'condizioni', 'chi-siamo', 'marchi', 'carrello'
                ]):
                    continue
                    
                if url_completo in processed_urls:
                    continue
                processed_urls.add(url_completo)
                
                # --- 3. Elaborazione Dettaglio Annuncio ---
                try:
                    time.sleep(0.5)
                    det_resp = session.get(url_completo, headers=headers, timeout=20)
                    if det_resp.status_code != 200:
                        continue
                        
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    # Rimuovi elementi non testuali
                    for hidden in det_soup(["script", "style", "nav", "footer", "header", "form"]):
                        hidden.decompose()
                        
                    testo = clean_text(det_soup.get_text(separator="\n"))
                    if re.search(r'\b(roulotte|noleggio)\b', testo.lower()):
                        continue
                        
                    prezzo = extract_price(testo)
                    if prezzo and prezzo < 5000:
                        continue
                        
                    # Estrazione Immagine principale
                    img_url = None
                    img = det_soup.find('img', {'src': True}) or det_soup.find('img', {'data-src': True})
                    if img:
                        src = img.get('src') or img.get('data-src')
                        img_url = urljoin(BASE_URL, src)
                        
                    scraper_utils.process_listing(
                        db_conn, config, url_completo, SITE_NAME, f"--- DETTAGLI ---\n{testo}"[:3000],
                        prezzo, DISTANCE_FROM_SEREGNO, img_url, regex_extract_camper_data, ollama_config
                    )
                    count_elaborati += 1
                    
                except Exception as e:
                    print(f"    [{SITE_NAME}] Errore elaborazione {url_completo}: {e}")
                    
    except Exception as e:
        print(f"[!] Errore {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
