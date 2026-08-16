import os
import re
import time
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

import scraper_utils

# URL o percorsi di sottocategorie da NON considerare mai come singoli annunci
KNOWN_SUBCATEGORIES = [
    '/camper-usati/semintegrali-usati',
    '/camper-usati/mansardati-usati',
    '/camper-usati/furgonati-usati',
    '/camper-usati/motorhome-usati',
    '/vendita-camper-nuovi/van-nuovi',
    '/vendita-camper-nuovi/minivan-nuovi',
    '/vendita-camper-nuovi/semintegrali-nuovi',
    '/vendita-camper-nuovi/motorhome-nuovi',
    '/van-nuovi',
    '/furgonati-usati',
    '/motorhome-usati',
    '/semintegrali-usati',
    '/camper-usati',
    '/vendita-camper-nuovi'
]

# ==========================================
# 1. LOGICA REGEX E PARSING DATI
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn, url=""):
    testo = str(raw_text).lower()
    url_lower = str(url).lower()

    # --- 1. STATO NUOVO / USATO ---
    # Controllo tassativo dall'URL
    is_nuovo_cat = any(k in url_lower for k in ['/vendita-camper-nuovi', '/van-nuovi', 'nuovi'])
    is_usato_cat = any(k in url_lower for k in ['/camper-usati', '/furgonati-usati', '/motorhome-usati', '/semintegrali-usati', 'usati'])

    is_nuovo_text = bool(re.search(r'\b(stato\s*[:]?\s*nuovo|nuovo\b|da immatricolare)\b', testo))
    is_usato_text = bool(re.search(r'\b(stato\s*[:]?\s*usato|usato\b)\b', testo))

    if is_nuovo_cat:
        nuovo = True
    elif is_usato_cat:
        nuovo = False
    elif is_nuovo_text and not is_usato_text:
        nuovo = True
    elif is_usato_text and not is_nuovo_text:
        nuovo = False
    else:
        nuovo = False

    # --- 2. ANNO ---
    anno = None
    anno_match = re.search(r'anno\s*[:]?\s*(199\d|20[0-2]\d)', testo) or re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    if anno_match:
        anno = int(anno_match.group(1))

    # --- 3. CHILOMETRI ---
    km = None
    km_match = (
        re.search(r'(?:chilometri|chilometraggio)[\s:]*(\d{1,3}(?:\.\d{3})+|\d+)', testo) or
        re.search(r'km[\s:]*(\d{1,3}(?:\.\d{3})+|\d+)', testo) or
        re.search(r'(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*km\b', testo)
    )
    if km_match:
        km = int(km_match.group(1).replace('.', ''))
    elif nuovo:
        km = 0

    # --- 4. CATEGORIZZAZIONE TIPOLOGIA ---
    tipologia_str = ""
    tipo_match = re.search(r'tipologia\s*[:]?\s*([^\n\r]+)', testo)
    if tipo_match:
        tipologia_str = tipo_match.group(1).strip()

    tipo_furgonato = bool(
        '/van-nuovi/' in url_lower or '/furgonati-usati/' in url_lower or 'furgonat' in url_lower or
        'furgonato' in tipologia_str or 'van' in tipologia_str or
        re.search(r'\b(van|furgonat[oi]|camper\s+puro|minivan)\b', testo)
    )
    
    tipo_mansardato = bool(
        'mansardato' in tipologia_str or
        re.search(r'\bmansardat[oi]\b', testo)
    )
    
    tipo_motorhome = bool(
        '/motorhome-usati/' in url_lower or 'motorhome' in tipologia_str or
        re.search(r'\bmotorhome\b|\bintegrale\b', testo)
    )
    
    tipo_semintegrale = bool(
        '/semintegrali-usati/' in url_lower or 'semintegrale' in tipologia_str or 'profilato' in tipologia_str or
        re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo)
    )

    # Gerarchia di precedenza univoca
    if tipo_furgonato:
        tipo_semintegrale = tipo_motorhome = tipo_mansardato = False
    elif tipo_mansardato:
        tipo_semintegrale = tipo_motorhome = False
    elif tipo_semintegrale:
        tipo_motorhome = False
    elif tipo_motorhome:
        tipo_semintegrale = False

    # --- 5. LUNGHEZZA ---
    lunghezza = None
    # Cerca pattern tipo: "Lunghezza 7.48", "Lunghezza: 6.72 m", "lunghezza cm 699", "lunghezza 7480 mm"
    match_lung = re.search(r'lunghezza[\s\.:]*(\d{1,4}(?:[.,]\d{1,2})?)\s*(m|mt|metri|cm|mm)?', testo)
    
    if match_lung:
        val = float(match_lung.group(1).replace(',', '.'))
        unit = match_lung.group(2)
        
        # Normalizzazione in metri
        if unit in ['cm'] or 400 <= val <= 1200:
            val = val / 100.0
        elif unit in ['mm'] or 4000 <= val <= 12000:
            val = val / 1000.0
            
        if 4.0 <= val <= 12.0:
            lunghezza = round(val, 2)

    # Fallback per varianti tipo "7.48 m"
    if lunghezza is None:
        match_m = re.search(r'\b(4|5|6|7|8|9|10|11|12)[.,](\d{1,2})\s*(?:m|mt|metri)\b', testo)
        if match_m:
            lunghezza = float(f"{match_m.group(1)}.{match_m.group(2)}")

    # --- 6. POSTI E POTENZA ---
    posti_omologati = posti_letto = None
    match_omologati = re.search(r'(?:omologati|viaggio)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*(?:omologati|viaggio)', testo)
    if match_omologati: posti_omologati = int(match_omologati.group(1))
    
    match_letto = re.search(r'(?:letto|dormire)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*letto', testo)
    if match_letto: posti_letto = int(match_letto.group(1))

    cv_match = re.search(r'(\d{3})\s*cv', testo)
    potenza = int(cv_match.group(1)) if cv_match else None

    # --- 7. ACCESSORI E DOTAZIONI ---
    cambio_automatico = bool(re.search(
        r'\bcambio\s+(?:di\s+marcia\s+)?automatico\b|\bautomatico\s+9g\b|\b9g-tronic\b|\bcomformatic\b|\bgeartronic\b|\btrasmissione\s+automatica\b',
        testo
    ))
    if not cambio_automatico:
        if re.search(r'(?<!climatizzatore\s)(?<!clima\s)\bautomatico\b', testo):
            cambio_automatico = True

    aria_condizionata = bool(re.search(
        r'clima\s*cellula|climatizzatore\s*cellula|aria\s*condizionata\s*cellula|dometic|truma\s*aventa|telair|condizionatore\s*cellula|clima\s*in\s*cellula|condizionatore',
        testo
    ))
    if not aria_condizionata and re.search(r'aria\s+condizionata(?!\s+cabina)', testo):
        aria_condizionata = True

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
    
    # --- 8. MARCA E MODELLO ---
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    if match_db:
        marca, modello, allestimento = match_db["marca"], match_db["modello"], match_db["allestimento"]
    else:
        parole = [re.sub(r'[^\w\s]', '', p).strip().capitalize() for p in str(raw_text).split() if p.strip().lower() not in ['nuovo', 'usato', 'pronta', 'consegna', 'camper']]
        modello_fallback = " ".join(parole[:5]) if parole else "Sconosciuto"
        marca, modello, allestimento = "Sconosciuto", modello_fallback, ""
    
    return {
        "marca": marca, "modello": modello, "allestimento": allestimento, "prezzo": current_price,
        "anno": anno, "chilometri": km, "nuovo": nuovo, "peso": peso,
        "tipo_furgonato": tipo_furgonato, "tipo_mansardato": tipo_mansardato, "tipo_motorhome": tipo_motorhome,
        "tipo_semintegrale": tipo_semintegrale, "lunghezza": lunghezza, "potenza": potenza,
        "posti_omologati": posti_omologati, "posti_letto": posti_letto,
        "telaio_alko": 'alko' in testo, "doppio_pavimento": 'doppio pavimento' in testo,
        "cambio_automatico": cambio_automatico, "emissioni_euro6": bool(re.search(r'euro\s*6', testo)),
        "pannelli_solari": 'pannell' in testo and 'solar' in testo, "batterie_litio": batterie_litio,
        "sospensioni_aria": 'sospensioni' in testo and 'aria' in testo,
        "predisposizione_invernale": predisposizione_invernale, "doppia_batteria": doppia_batteria,
        "aria_condizionata": aria_condizionata, "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio, "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti, "letto_nautico": 'letto nautico' in testo,
        "letti_gemelli": letti_gemelli, "letti_a_castello": letti_a_castello
    }

# ==========================================
# 2. ESTRAZIONE PREZZO E CLEANING DOM
# ==========================================
def extract_price(text):
    text_lower = text.lower()
    if 'trattativa riservata' in text_lower or 'trattativa in sede' in text_lower:
        return None  
    match = re.search(r'€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?', text)
    if match: 
        return int(match.group(1).replace('.', '').replace(',', ''))
    return None

def clean_text(text): 
    return re.sub(r'\n\s*\n', '\n', re.sub(r'[ \t]+', ' ', text)).strip()

def clean_and_extract_detail_text(det_soup):
    """ Rimuove navigazione, caroselli ed estrae il testo netto. """
    
    # 1. Rimuovi head, script e tag non testuali
    for hidden in det_soup(["script", "style", "nav", "footer", "header", "form", "iframe", "svg", "noscript", "meta", "link"]):
        hidden.decompose()
        
    # 2. Decompose selettivo via classi di Journal 3
    for class_regex in [r'module-products', r'module-side_products', r'related-products', r'product-related', r'carousel']:
        for el in det_soup.find_all(class_=re.compile(class_regex)):
            el.decompose()

    # 3. Pulizia aggressiva basata sui titoli (Guarda Anche, ecc.)
    for tag in det_soup.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'b', 'div']):
        # Se è un div, assicuriamoci che sia un titolo vero per evitare di distruggere il body
        if tag.name == 'div' and not any(c in tag.get('class', []) for c in ['title', 'module-title', 'box-heading']):
            continue
            
        text_content = tag.get_text().strip().lower()
        if any(keyword in text_content for keyword in ['guarda anche', 'stessa categoria', 'stessa marca', 'prodotti correlati', 'potrebbe interessarti']):
            # Trova l'intero wrapper del blocco (es. un .module o .section) e rimuovi tutto
            parent_module = tag.find_parent('div', class_=re.compile(r'module|section|panel|row'))
            if parent_module:
                parent_module.decompose()
            else:
                tag.decompose()

    # Estrazione
    content_div = det_soup.find('div', id='content') or det_soup
    return clean_text(content_div.get_text(separator="\n"))

# ==========================================
# 3. CORE SCRAPER - CARAVAN MARKET
# ==========================================
def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Caravan Market"
    BASE_URL = "https://www.caravanmarket.com"
    
    TARGET_CATEGORIES = [
        f"{BASE_URL}/vendita-camper-nuovi",
        f"{BASE_URL}/camper-usati",
        f"{BASE_URL}/van-nuovi",
        f"{BASE_URL}/furgonati-usati",
        f"{BASE_URL}/motorhome-usati",
        f"{BASE_URL}/semintegrali-usati"
    ]
    
    DISTANCE_FROM_SEREGNO = 190
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
            
            # --- 1. Paginazione ---
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                full_page_url = urljoin(BASE_URL, href)
                
                if ('page=' in full_page_url or 'paged=' in full_page_url) and any(cat in full_page_url for cat in TARGET_CATEGORIES):
                    if full_page_url not in scanned_pages and full_page_url not in urls_to_scan:
                        urls_to_scan.append(full_page_url)

            # --- 2. Rilevamento Annunci ---
            for link in soup.find_all('a', href=True):
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                raw_href = link['href'].strip()
                if not raw_href or raw_href.startswith(('#', 'javascript:', 'mailto:')):
                    continue
                    
                url_completo = urljoin(BASE_URL, raw_href)
                parsed_url = urlparse(url_completo)
                path = parsed_url.path.rstrip('/')
                
                if path in ['', '/', '/index.php'] or 'page=' in url_completo:
                    continue
                
                # Ignora categorie generiche / sottocategorie
                if any(path.endswith(sub.rstrip('/')) for sub in KNOWN_SUBCATEGORIES):
                    continue
                
                # Matching URL annuncio
                is_valid_listing = False
                for cat in TARGET_CATEGORIES:
                    cat_path = urlparse(cat).path.rstrip('/')
                    if path.startswith(cat_path + '/') and len(path) > len(cat_path) + 1:
                        is_valid_listing = True
                        break
                        
                if not is_valid_listing:
                    continue
                    
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
                    time.sleep(0.4)
                    det_resp = session.get(url_completo, headers=headers, timeout=20)
                    if det_resp.status_code != 200:
                        continue
                        
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    # 1. Recupero Immagine tramite tag Og:Image (il più pulito)
                    img_url = None
                    og_image = det_soup.find('meta', property='og:image')
                    if og_image and og_image.get('content'):
                        img_url = og_image['content']
                        # Sovrascrive risoluzioni basse (-600x315w o -200x200h) con alta risoluzione
                        if '/cache/' in img_url:
                            img_url = re.sub(r'-\d+x\d+[wh]\.', '-1200x1000w.', img_url)
                    
                    # Fallback ricerca immagine nel DOM
                    if not img_url:
                        content_div = det_soup.find('div', id='content') or det_soup
                        main_img_box = content_div.find(class_='main-image') or content_div.find(class_='product-image') or content_div.find('a', class_='thumbnail') or content_div
                        for img in main_img_box.find_all('img'):
                            src = img.get('data-src') or img.get('src') or ''
                            if not src: continue
                            src_lower = src.lower()
                            if any(skip in src_lower for skip in ['logo', 'icon', 'banner', 'payment', 'paypal', 'visa', 'mastercard', 'whatsapp', 'star', 'no_image']): continue
                            if 'catalog' in src_lower or 'cache' in src_lower:
                                img_url = urljoin(BASE_URL, src)
                                break

                    # 2. Estrai testo pulito senza caroselli
                    testo = clean_and_extract_detail_text(det_soup)
                    testo_lower = testo.lower()
                    
                    # Verifica che sia effettivamente una pagina prodotto
                    is_product_page = (
                        det_soup.find('button', id='button-cart') is not None or
                        'codice prodotto' in testo_lower or
                        'scheda tecnica' in testo_lower or
                        'disponibilità' in testo_lower
                    )
                    if not is_product_page:
                        continue

                    if re.search(r'\b(roulotte|noleggio)\b', testo_lower):
                        continue
                        
                    prezzo = extract_price(testo)
                    
                    if prezzo is not None and prezzo < 5000:
                        continue
                        
                    def custom_extractor(raw_txt, prz, db):
                        return regex_extract_camper_data(raw_txt, prz, db, url=url_completo)

                    # Passa il testo esteso con limite incrementato a 50.000 caratteri
                    scraper_utils.process_listing(
                        db_conn, config, url_completo, SITE_NAME, f"--- DETTAGLI ---\n{testo}"[:50000],
                        prezzo, DISTANCE_FROM_SEREGNO, img_url, custom_extractor, ollama_config
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