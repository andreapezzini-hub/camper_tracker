import os
import re
import time
import requests
from bs4 import BeautifulSoup

import scraper_utils

# ==========================================
# 1. LOGICA REGEX (Adattata per DB)
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    # 1. ANNO (Protezione da "Cilindrata 1996")
    anno = None
    match_anno_explicit = re.search(r'anno\s*[:]?\s*(20[0-2]\d|199\d)', testo)
    if match_anno_explicit:
        anno = int(match_anno_explicit.group(1))
    else:
        anno_match = re.search(r'(?<!cilindrata\s)(?<!cilindrata)(?<!cc\s)\b(199\d|20[0-2]\d)\b', testo)
        if anno_match:
            anno = int(anno_match.group(1))
            
    # 2. CHILOMETRI E STATO (NUOVO/USATO)
    km = None
    is_nuovo = False
    
    # 1. Controllo primario tramite Keyword dirette nel testo (molto più affidabile)
    testo_lower = testo.lower()

    if "caratteristiche del camper nuovo" in testo_lower or "camper nuovo" in testo_lower:
        is_nuovo = True
    elif "caratteristiche del camper usato" in testo_lower or "camper usato" in testo_lower:
        is_nuovo = False
    else:
        # 2. Fallback sul controllo KM se il tipo non è esplicito nel testo
        # Pulisce/ignora frasi promozionali del footer (es. "10.000 veicoli")
        testo_pulito = re.sub(r'10\.?000\s*(?:veicoli|euro|€)', '', testo, flags=re.IGNORECASE)

        # Regex rigorosa: "KM: 15.000", "KM 15000", "15.000 km", "15000 chilometri"
        # Utilizza boundary ed evita di prendere numeri isolati senza indicatore KM adiacente
        match_km = re.search(r'(?:km|chilometri|chilometraggio)\s*[:\-]?\s*(\d{1,3}(?:\.\d{3})+|\d{1,6})\b|\b(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*(?:km|chilometri)\b', testo_pulito, re.IGNORECASE)

    if match_km:
        # Estrae il gruppo valorizzato
        val = match_km.group(1) if match_km.group(1) else match_km.group(2)
        km = int(val.replace('.', ''))
        
        # Considera usato solo se i km superano la soglia (es. 1000 km)
        is_nuovo = False if km > 1000 else True
    else:
        # Se non vengono specificati i KM nel testo, di norma per i camper si tratta di un NUOVO
        is_nuovo = True
        
    # 3. TIPOLOGIA
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    
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
    
    # 4. LUNGHEZZA (Gestione cm e m)
    lunghezza = None
    match_lung_esplicita = re.search(r'lunghezza\s*[:]?\s*(\d+[.,]?\d*)\s*(cm|m)?', testo)
    if match_lung_esplicita:
        val = float(match_lung_esplicita.group(1).replace(',', '.'))
        if match_lung_esplicita.group(2) == 'cm' or val > 100:
            lunghezza = val / 100.0
        else:
            lunghezza = val
            
    if lunghezza is None:
        misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
        if misure_dec:
            floats = [float(m.replace(',', '.')) for m in misure_dec]
            lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
            if lunghezze_valide:
                lunghezza = max(lunghezze_valide)

    # 5. POSTI E LETTI
    posti_omologati = None
    posti_letto = None
    
    match_posti = re.search(r'posti\s*[:]?\s*(\d)', testo) or re.search(r'(?:omologati|viaggio)[\s:]*(\d)', testo)
    if match_posti: posti_omologati = int(match_posti.group(1))
    
    match_letti = re.search(r'letti\s*[:]?\s*(\d)', testo) or re.search(r'(?:letto|dormire)[\s:]*(\d)', testo)
    if match_letti: posti_letto = int(match_letti.group(1))

    # 6. POTENZA
    potenza = None
    cv_match = re.search(r'(?:cavalli|cv|potenza)\s*[:]?\s*(\d{2,3})', testo)
    if cv_match:
        potenza = int(cv_match.group(1))
    else:
        cv_match_2 = re.search(r'(\d{3})\s*(?:cv|cavalli)', testo)
        if cv_match_2: potenza = int(cv_match_2.group(1))
        
    # 7. PESO 
    peso = 3500 
    match_peso = re.search(r'peso\s*(?:p\.?c\.?\s*)?[:]?\s*(\d{3,4})\s*kg', testo)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r'patente\s*c|oltre\s*3500|heavy|maxi', testo):
        peso = 4250
    
    # 8. ACCESSORI E RISCALDAMENTO
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|stufa\s*diesel|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|riscaldatore\s*supplementare', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pack\s*winter|pacchetto\s*invernale|predisposizione\s*invernale', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria|due\s*batterie|2\s*batterie', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti|piedini\s*idraulici|autolivellanti', testo))
    
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|letto\s*a\s*castello|\bcastello\b', testo))
    
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    
    if match_db:
        marca = match_db["marca"]
        modello = match_db["modello"]
        allestimento = match_db["allestimento"]
    else:
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
        "nuovo": is_nuovo,
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
        "emissioni_euro6": bool(re.search(r'euro\s*6', testo)) or (anno is not None and anno >= 2017),
        "pannelli_solari": 'pannell' in testo and 'solar' in testo,
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
    
    pattern_currency = r'(?:€|euro)\s*(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?|(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?\s*(?:€|euro)'
    matches_curr = re.findall(pattern_currency, text, re.IGNORECASE)
    
    for m in matches_curr:
        val_str = m[0] if m[0] else m[1]
        if val_str:
            clean_val = re.sub(r'[.,]', '', val_str)
            if clean_val.isdigit():
                prices.append(int(clean_val))
                
    pattern_words = r'(?:prezzo|a\s+soli|tuo\s+a)\s*(?:di\s*)?(?::)?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?'
    matches_words = re.findall(pattern_words, text, re.IGNORECASE)
    for m in matches_words:
        if m:
            clean_val = re.sub(r'[.,]', '', m)
            if clean_val.isdigit():
                prices.append(int(clean_val))
                
    valid_prices = [p for p in prices if 5000 <= p <= 200000]
    
    if valid_prices:
        return max(valid_prices)
        
    return 0

def clean_text_preserve_lists(text):
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def fetch_url_with_retry(session, url, headers, max_retries=3, timeout=25):
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            if response.status_code == 404:
                return response
            response.raise_for_status()
            return response
        except (requests.RequestException, Exception) as e:
            if attempt == max_retries:
                raise e
            print(f"      [!] Timeout o Disconnessione, riprovo...")
            time.sleep(2 * attempt)

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "3C Srl"
    BASE_URL = "https://3csrl.com"
    TARGET_URLS = [
        f"{BASE_URL}/camper-nuovi-pronta-consegna/",
        f"{BASE_URL}/camper-usati/",
        f"{BASE_URL}/camper-nuovi/"
    ]
    DISTANCE_FROM_SEREGNO = 170 
    MAX_ANNUNCI = 500
    count_elaborati = 0
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'close' 
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
            
            print(f"    [{SITE_NAME}] Scansione: {target}...")
            try:
                response = fetch_url_with_retry(session, target, headers=headers)
                if response.status_code == 404:
                    continue 
            except Exception:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for page_link in soup.find_all('a', href=True):
                href = page_link['href'].split('#')[0] 
                if ('/page/' in href or '?paged=' in href) and BASE_URL in href and href not in scanned_targets:
                    if href not in urls_to_scan:
                        urls_to_scan.append(href)

            links_veicoli = soup.find_all('a', href=True)
            for link in links_veicoli:
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                url_parziale = link['href'].split('#')[0] 
                
                if re.search(r'\.(webp|jpg|jpeg|png|gif|pdf|zip|rar)$', url_parziale, re.IGNORECASE):
                    continue
                    
                if url_parziale.lower().startswith(('tel:', 'mailto:', 'javascript:')):
                    continue
                
                url_completo = url_parziale if url_parziale.startswith('http') else f"{BASE_URL.rstrip('/')}/{url_parziale.lstrip('/')}"
                
                if BASE_URL not in url_completo:
                    continue
                
                path_lower = url_completo.lower()
                skip_words = ['chi-siamo', 'contatti', 'dove', 'noleggio', 'officina', 'servizi', 'privacy', 'cookie', 'index', 'caravan', 'rimorchi', 'barca', 'carrelli', 'login', 'cart', 'checkout', 'carrello', 'my-account', 'feed']
                if any(skip in path_lower for skip in skip_words):
                    continue
                
                # Normalizza l'URL aggiungendo lo slash finale se manca
                url_completo = url_completo.split('?')[0]
                if not url_completo.endswith('/'):
                    url_completo += '/'
                path_lower = url_completo.lower()

                # Verifica se è una pagina prodotto
                is_product = any(x in path_lower for x in ['/prodotto/', '/veicolo/', '/camper/', '-it-'])
                
                # Se NON è riconosciuto direttamente come prodotto, applica il filtro sulla lunghezza dello slug
                if not is_product:
                    slug = url_completo.strip('/').split('/')[-1]
                    if len(slug) < 15:
                        continue
                
                if url_completo in processed_urls or url_completo in scanned_targets:
                    continue
                processed_urls.add(url_completo)
                
                print(f"    [{SITE_NAME}] Check URL: {url_completo}")
                
                try:
                    time.sleep(1.0) 
                    det_resp = fetch_url_with_retry(session, url_completo, headers=headers)
                    if det_resp.status_code == 404:
                        continue
                    
                    # STRATEGIA ANTI-SPIDER TRAP: Troncare l'HTML alla dicitura "Sede centrale" 
                    # per evitare link a veicoli correlati o ai footer pur estraendo eventuali sottomodelli
                    html_content = det_resp.text
                    match_sede = re.search(r'sede centrale', html_content, re.IGNORECASE)
                    if match_sede:
                        html_content = html_content[:match_sede.start()]
                        
                    det_soup = BeautifulSoup(html_content, 'html.parser')
                    
                    for inner_link in det_soup.find_all('a', href=True):
                        inner_href = inner_link['href'].split('?')[0].split('#')[0]
                        if inner_href.startswith('/'):
                            inner_href = f"{BASE_URL.rstrip('/')}{inner_href}"
                            
                        if BASE_URL in inner_href and ('/camper/' in inner_href or '/prodotto/' in inner_href):
                            if inner_href.endswith('/') and not re.search(r'\.(webp|jpg|jpeg|png|pdf)$', inner_href, re.IGNORECASE):
                                if inner_href not in processed_urls and inner_href not in urls_to_scan and inner_href not in scanned_targets:
                                    urls_to_scan.append(inner_href)
                    
                    for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                        hidden.decompose()
                    for menu in det_soup.find_all(['div', 'ul'], class_=re.compile(r'menu|nav|footer|header|sidebar|widget', re.I)):
                        menu.decompose()
                    for menu in det_soup.find_all(['div', 'ul'], id=re.compile(r'menu|nav|footer|header|sidebar', re.I)):
                        menu.decompose()
                        
                    testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                    testo_dettaglio_lower = testo_dettaglio.lower()
                    
                    if 'dotazioni' not in testo_dettaglio_lower:
                        print("      [!] Saltato: Non contiene la parola chiave 'dotazioni'. Pagina non di dettaglio.")
                        continue
                    
                    h1_testo = " ".join([h1.get_text(separator=" ") for h1 in det_soup.find_all('h1')]).lower()
                    if re.search(r'\b(roulotte|noleggio|noleggi|caravan)\b', h1_testo) or re.search(r'\b(roulotte|noleggio|noleggi|caravan)\b', url_completo.lower()):
                        print("      [!] Saltato: Trovate parole chiave vietate nell'intestazione o nell'URL.")
                        continue
                        
                    prezzo = extract_price(testo_dettaglio)
                    
                    if prezzo < 5000 and "0,00" not in testo_dettaglio_lower and "trattativa riservata" not in testo_dettaglio_lower:
                        print(f"      [!] Saltato: Prezzo non valido ({prezzo}€).")
                        continue 
                    
                    print(f"    [{SITE_NAME}] >>> Avvio estrazione dati per: {url_completo}")
                    
                    # LOGICA IMMAGINI (Totalmente rivista e potenziata)
                    img_url = None
                    
                    # 1. Cerca Meta tag di condivisione (estremamente affidabili se presenti)
                    for meta in det_soup.find_all(['meta', 'link']):
                        if meta.get('property') in ['og:image', 'og:image:url'] or meta.get('name') == 'twitter:image':
                            img_url = meta.get('content')
                            break
                        if meta.get('rel') == ['image_src']:
                            img_url = meta.get('href')
                            break
                    
                    # 2. Fallback su tag img generici scandagliando attributi "lazy" (risolve il problema delle immagini mancanti)
                    if not img_url:
                        img_tags = det_soup.find_all('img', class_=re.compile(r'wp-post-image|woocommerce-main-image|attachment-shop_single|gallery|slider|main|product', re.I))
                        if not img_tags:
                            img_tags = det_soup.find_all('img')
                            
                        for img in img_tags:
                            # Controlla attributi tipici di lazy loading o slider
                            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-large_image')
                            if not src and img.get('srcset'):
                                src = img.get('srcset').split(',')[0].split(' ')[0]
                                
                            if src:
                                src_lower = src.lower()
                                # Filtro anti-rumore: evita loghi, icone, sfondi o placeholder
                                selettori_esclusi = ['logo', 'icon', 'spinner', 'avatar', 'blank', 'placeholder', 'svg']
                                if not any(x in src_lower for x in selettori_esclusi):
                                    if '.jpg' in src_lower or '.webp' in src_lower or '.jpeg' in src_lower or '.png' in src_lower:
                                        img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                                        break
                    
                    testo_finale = f"--- DETTAGLI ---\n{testo_dettaglio}"
                    if len(testo_finale) > 8000:
                        testo_finale = testo_finale[:8000]

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
