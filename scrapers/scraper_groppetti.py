import os
import re
import time
import requests
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
        
    # Risoluzione BUG: Impedisce a "semi integrale" di triggerare "integrale" (motorhome)
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b', testo)) or (bool(re.search(r'\bintegrale\b', testo)) and not tipo_semintegrale)
    
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    
    # Gerarchia rigorosa: Motorhome -> Mansardato -> Furgonato -> Semintegrale
    if tipo_motorhome:
        tipo_mansardato = tipo_furgonato = tipo_semintegrale = False
    elif tipo_mansardato:
        tipo_furgonato = tipo_semintegrale = False
    elif tipo_furgonato:
        tipo_semintegrale = False
    
    lunghezza = None
    # 1. Cerca esplicitamente la parola lunghezza e il valore, gestendo anche i cm (es. 699)
    match_lung = re.search(r'lunghezza[\s\w]*?[:]?\s*(\d+[.,]\d{1,3})', testo)
    if match_lung:
        lung_val = float(match_lung.group(1).replace(',', '.'))
        if lung_val > 100: 
            lung_val = lung_val / 100 # Converte cm in metri
        if 5.0 <= lung_val <= 12.0:
            lunghezza = lung_val
            
    # 2. Fallback: cerca un numero seguito da m o mt (es. 6,99 m)
    if lunghezza is None:
        match_lung_m = re.findall(r'(\d+[.,]\d{1,2})\s*(?:m|mt)\b', testo)
        if match_lung_m:
            floats = [float(m.replace(',', '.')) for m in match_lung_m]
            lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
            if lunghezze_valide: 
                lunghezza = max(lunghezze_valide)

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
# 2. CORE SCRAPER - GROPPETTI
# ==========================================
def extract_price(text):
    prices = []
    
    # Formato: "€ 105.900", "€105900"
    for m in re.finditer(r'€\s*(\d{1,3}(?:[.,]\d{3})*|\d{4,6})(?:[.,]\d{2})?', text):
        val = int(m.group(1).replace('.', '').replace(',', ''))
        if val >= 5000: prices.append(val)
        
    # Formato: "105.900 €", "105900€"
    for m in re.finditer(r'(\d{1,3}(?:[.,]\d{3})*|\d{4,6})(?:[.,]\d{2})?\s*€', text):
        val = int(m.group(1).replace('.', '').replace(',', ''))
        if val >= 5000: prices.append(val)
        
    # Fallback su keyword
    for m in re.finditer(r'prezzo[\s:]*(?:€\s*)?(\d{1,3}(?:[.,]\d{3})*|\d{4,6})', text, re.IGNORECASE):
        val = int(m.group(1).replace('.', '').replace(',', ''))
        if val >= 5000: prices.append(val)
        
    if not prices:
        return 0
        
    max_p = max(prices)
    # Filtro: scarta il solo importo dello "sconto", valutando valido solo un prezzo che sia almeno il 30% del massimo trovato
    valid_prices = [p for p in prices if p > (max_p * 0.3)]
    
    if valid_prices:
        return min(valid_prices) # Tra i prezzi reali validi, prendo il più basso
    return max_p

def clean_text(text): 
    return re.sub(r'\n\s*\n', '\n', re.sub(r'[ \t]+', ' ', text)).strip()

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Groppetti"
    BASE_URL = "https://www.groppetti.net"
    TARGET_URLS = [
        f"{BASE_URL}/camper/2/camper-usati-in-vendita/",
        f"{BASE_URL}/camper/1/camper-nuovi-in-vendita/",
        f"{BASE_URL}/camper/2/listings/",
        f"{BASE_URL}/camper/1/listings/",
        f"{BASE_URL}/camper/2/",
        f"{BASE_URL}/camper/1/"
    ]
    DISTANCE_FROM_SEREGNO = 50 
    MAX_ANNUNCI = 500
    count_elaborati = 0
    
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        processed_urls = set()
        urls_to_scan = list(TARGET_URLS)
        scanned_targets = set()
        
        # Aggiungo preventivamente pagine di paginazione per bypassare eventuali bottoni JS
        for base_t in TARGET_URLS[:4]:
            for p in range(2, 6):
                urls_to_scan.append(f"{base_t}page/{p}/")
        
        while urls_to_scan and count_elaborati < MAX_ANNUNCI:
            target = urls_to_scan.pop(0)
            if target in scanned_targets: continue
            scanned_targets.add(target)
            
            print(f"    [{SITE_NAME}] Scansione sezione: {target}...")
            try: 
                response = session.get(target, headers=headers, timeout=20)
            except Exception: 
                continue
            
            if response.status_code != 200: continue
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Recupero di eventuali link di paginazione
            for a in soup.find_all('a', href=True):
                href_raw = a['href']
                if not href_raw or href_raw.startswith('javascript'): continue
                
                url_completo = href_raw if href_raw.startswith('http') else f"{BASE_URL}/{href_raw.lstrip('/')}"
                if BASE_URL not in url_completo: continue
                
                url_no_query = url_completo.split('#')[0].split('?')[0]
                
                if '/page/' in url_no_query:
                    if url_completo not in scanned_targets and url_completo not in urls_to_scan:
                        urls_to_scan.append(url_completo)
            
            # Ricerca dei veri listing all'interno della pagina corrente
            for link in soup.find_all('a', href=True):
                if count_elaborati >= MAX_ANNUNCI: break
                
                href_raw = link['href']
                if not href_raw or href_raw.startswith('javascript'): continue
                
                url_completo = href_raw if href_raw.startswith('http') else f"{BASE_URL}/{href_raw.lstrip('/')}"
                if BASE_URL not in url_completo: continue
                
                url_no_query = url_completo.split('#')[0].split('?')[0]
                path_lower = url_no_query.lower()
                
                if any(skip in path_lower for skip in ['noleggio', 'contatti', 'officina', 'accessori', 'privacy', 'cookie', 'chi-siamo', 'news']): 
                    continue
                if url_no_query.endswith(('.jpg', '.png', '.pdf')):
                    continue
                
                parts = [p for p in url_no_query.split('/') if p]
                if not parts: continue
                last_part = parts[-1].lower()
                
                # Ignoro root pages e liste paginazioni
                if last_part in ['listings', 'camper-usati-in-vendita', 'camper-nuovi-in-vendita', 'camper', '1', '2'] or last_part.startswith('page'):
                    continue
                
                is_listing = False
                
                if '/listings/' in path_lower and last_part != 'listings':
                    is_listing = True
                elif '-' in last_part and len(last_part) > 12:
                    is_listing = True
                
                if not is_listing: 
                    continue
                
                if url_no_query in processed_urls: continue
                processed_urls.add(url_no_query)
                
                try:
                    time.sleep(0.5)
                    det_resp = session.get(url_no_query, headers=headers, timeout=20)
                    if det_resp.status_code != 200: continue
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    # Elimina container laterali e correlati per non prelevare testi e prezzi di altri veicoli
                    for hidden in det_soup(["script", "style", "nav", "footer", "header", "form", "aside"]): 
                        hidden.decompose()
                    for elem in det_soup.find_all(class_=re.compile(r'(sidebar|related|suggested|widget|stm-more-cars|similar|stm-car-carousels)', re.I)):
                        elem.decompose()
                    for elem in det_soup.find_all(id=re.compile(r'(sidebar|related|suggested)', re.I)):
                        elem.decompose()
                    
                    testo = clean_text(det_soup.get_text(separator="\n"))
                    
                    # Rimuovo la sezione "Altre proposte" per evitare che avveleni l'estrazione dati
                    idx_altre = testo.lower().find("altre proposte")
                    if idx_altre != -1:
                        testo = testo[:idx_altre].strip()
                        
                    prezzo = extract_price(testo)
                    
                    if 0 < prezzo < 5000: 
                        continue
                    
                    img_url = None
                    # 1. Tenta prima di trovare l'immagine includendo anche i formati di lazy-loading tipici dei temi
                    for img in det_soup.select('.stm-gallery img, .wp-post-image, .single-listing-gallery img, .gallery img, .owl-item img, .owl-stage img, .fotorama__img'):
                        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-opt-src')
                        if src and not any(x in src.lower() for x in ['logo', 'icon', 'banner', 'avatar']):
                            img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                            break
                            
                    # 2. Fallback generale per la prima immagine utile con un severo controllo anti-icone
                    if not img_url:
                        for img in det_soup.find_all('img'):
                            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-opt-src')
                            if not src: continue
                            
                            w = img.get('width', '0')
                            # Ignora immagini dichiaratamente piccole (icone, thumb minuscole)
                            if str(w).isdigit() and int(w) > 0 and int(w) < 250: continue
                            
                            if not any(x in src.lower() for x in ['logo', 'icon', 'banner', 'avatar', 'thumb']):
                                img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                                break
                    
                    # Rimosso il limite aggressivo dei 3000 caratteri, espanso a 10000 per evitare troncamenti
                    scraper_utils.process_listing(
                        db_conn, config, url_no_query, SITE_NAME, f"--- DETTAGLI ---\n{testo}"[:10000], 
                        prezzo, DISTANCE_FROM_SEREGNO, img_url, regex_extract_camper_data, ollama_config
                    )
                    count_elaborati += 1
                except Exception as e: 
                    pass
    except Exception as e: 
        print(f"[!] Errore {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator