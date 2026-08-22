import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup
import sqlite3
from playwright.sync_api import sync_playwright
import scraper_utils

# ==========================================
# 1. LOGICA REGEX
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    # 1. Anno: Se non disponibile, usa l'anno corrente (2026)
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else datetime.datetime.now().year
    
    # 2. Chilometri
    km_match = re.search(r'(?:Km|Chilometri|KM)\s*[:\-]?\s*([\d\.]+)', testo, re.IGNORECASE)
    km = int(km_match.group(1).replace('.', '')) if km_match else None
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo):
        km = 0
        
    # Tipologia veicolo
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

    cv_match = re.search(r'(?:Cavalli|CV|Potenza)\s*[:\-]?\s*(\d+)', testo, re.IGNORECASE)
    potenza = int(cv_match.group(1)) if cv_match else None
    
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|riscaldamento\s*(?:a\s*)?gasolio', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pacchetto\s*invernale', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti', testo))
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|\bcastello\b', testo))
    
    pannelli_solari = bool(re.search(r'pannell[oi]\s*(?:solar[ei]|fotovoltaic[oi])|solare', testo))
    sospensioni_aria = bool(re.search(r'sospension[ei]\s*(?:ad?\s*aria|pneumatic[he])', testo))
    aria_condizionata_cellula = bool(re.search(r'(?:clima|climatizzatore|aria\s*condizionata)\s*(?:cellula|abitacolo|stazionari[oa]|viti5|truma)', testo))
    
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
        "pannelli_solari": pannelli_solari, "batterie_litio": batterie_litio,
        "sospensioni_aria": sospensioni_aria,
        "predisposizione_invernale": predisposizione_invernale, "doppia_batteria": doppia_batteria,
        "aria_condizionata": aria_condizionata_cellula, "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio, "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti, "letto_nautico": 'letto nautico' in testo,
        "letti_gemelli": letti_gemelli, "letti_a_castello": letti_a_castello
    }

# ==========================================
# 2. CORE SCRAPER - CAMPERIS
# ==========================================
def extract_price(soup_or_text):
    """Estrae il prezzo più basso (prezzo in offerta/scontato) se presenti più prezzi"""
    if isinstance(soup_or_text, BeautifulSoup):
        prezzi_trovati = []
        for tag_prezzo in soup_or_text.find_all(['span', 'p', 'div'], class_=re.compile(r'price|prezzo|amount', re.I)):
            testo_p = tag_prezzo.get_text()
            matches = re.findall(r'€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?', testo_p)
            for m in matches:
                val = int(m.replace('.', '').replace(',', ''))
                if val >= 5000:
                    prezzi_trovati.append(val)
        
        if prezzi_trovati:
            return min(prezzi_trovati)
        text = soup_or_text.get_text()
    else:
        text = str(soup_or_text)

    matches = re.findall(r'€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?', text)
    prezzi = [int(m.replace('.', '').replace(',', '')) for m in matches if int(m.replace('.', '').replace(',', '')) >= 5000]
    return min(prezzi) if prezzi else 0

def clean_text(text): 
    return re.sub(r'\n\s*\n', '\n', re.sub(r'[ \t]+', ' ', text)).strip()

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Camperis"
    BASE_URL = "https://www.camperis.com"
    
    TARGET_CONFIGS = [
        {"url": f"{BASE_URL}/usato/", "condizione": "Usato"},
        {"url": f"{BASE_URL}/nuovo/", "condizione": "Nuovo"}
    ]
    
    DISTANCE_FROM_SEREGNO = 200
    MAX_ANNUNCI = 500
    count_elaborati = 0
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    EXCLUDED_SLUGS = {
        'usato', 'nuovo', 'noleggio', 'contatti', 'blog', 'news', 'guida-usato-camperis',
        'chi-siamo', 'officina', 'privacy-policy', 'cookie-policy', 'vendita-camper'
    }
    
    try:
        processed_urls = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=headers['User-Agent'])
            page = context.new_page()

            for target in TARGET_CONFIGS:
                if count_elaborati >= MAX_ANNUNCI:
                    break
                    
                base_target_url = target["url"]
                condizione_veicolo = target["condizione"]
                
                print(f"[*] Apertura sezione: {base_target_url}")
                page.goto(base_target_url, wait_until="domcontentloaded", timeout=40000)
                
                # Attende che almeno un risultato sia visibile in pagina
                try:
                    page.wait_for_selector(".fwpl-result.r1", timeout=15000)
                except Exception:
                    print(f"   [!] Nessun annuncio iniziale trovato per {condizione_veicolo}")
                    continue

                # Clicca "Carica altri risultati" finché il pulsante è visibile e non ha classe .d-none
                click_count = 0
                while count_elaborati < MAX_ANNUNCI:
                    # Cerca il pulsante "Carica altri risultati" specifico di FacetWP
                    load_more_btn = page.query_selector('.facetwp-load-more')
                    load_more_wrapper = page.query_selector('.facetwp-facet-load_more')
                    
                    # Controlla se il wrapper possiede la classe d-none o se il bottone non è più disponibile
                    if not load_more_btn or not load_more_btn.is_visible():
                        break
                        
                    if load_more_wrapper:
                        wrapper_class = load_more_wrapper.get_attribute('class') or ''
                        if 'd-none' in wrapper_class:
                            break

                    try:
                        click_count += 1
                        print(f"   [+] Clic su 'Carica altri risultati' (#{click_count})...")
                        load_more_btn.scroll_into_view_if_needed()
                        load_more_btn.click()
                        
                        # Pausa tattica e attesa del termine caricamento AJAX
                        time.sleep(1.5)
                        page.wait_for_selector(".facetwp-loading, #ajax-loader", state="detached", timeout=10000)
                    except Exception as p_err:
                        print(f"   [*] Fine espansione risultati o nessun altro elemento disponibile: {p_err}")
                        break

                print(f"   [*] Caricamento DOM completato per {condizione_veicolo}. Inizio estrazione link...")

                # Estrazione di tutti i link accumulati nella pagina completa
                html_content = page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                links_pagina = []
                for link in soup.find_all('a', href=True):
                    href_val = link['href']
                    url_completo = href_val if href_val.startswith('http') else f"{BASE_URL}/{href_val.lstrip('/')}"
                    
                    match = re.search(r'/camper/([^/]+)', url_completo.lower())
                    if not match:
                        continue
                        
                    slug = match.group(1)
                    if slug in EXCLUDED_SLUGS or slug.startswith('javascript:'):
                        continue
                        
                    if url_completo not in processed_urls:
                        processed_urls.add(url_completo)
                        links_pagina.append(url_completo)

                print(f"   [->] Trovati {len(links_pagina)} annunci totali per {condizione_veicolo}. Elaborazione in corso...")
                
                # Processing di ciascun annuncio estratto
                for url_completo in links_pagina:
                    if count_elaborati >= MAX_ANNUNCI:
                        break
                    try:
                        time.sleep(0.3)
                        det_resp = session.get(url_completo, headers=headers, timeout=20)
                        if det_resp.status_code != 200:
                            continue
                            
                        det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                        
                        for hidden in det_soup(["script", "style", "nav", "footer", "header"]): 
                            hidden.decompose()
                        
                        testo = clean_text(det_soup.get_text(separator="\n"))
                        
                        # Filtro Roulotte/Caravan e Noleggio
                        if re.search(r'\b(roulotte|caravan|noleggio)\b', testo.lower()): 
                            continue
                            
                        prezzo = extract_price(det_soup)
                        if prezzo < 5000: 
                            continue
                        
                        img_url = None
                        og_img = det_soup.find('meta', property='og:image') or det_soup.find('meta', attrs={'name': 'og:image'})
                        if og_img and og_img.get('content'):
                            img_url = og_img['content']
                        
                        if not img_url:
                            for img_tag in det_soup.find_all('img'):
                                src = img_tag.get('data-src') or img_tag.get('data-lazy-src') or img_tag.get('src', '')
                                if ('/media/' in src or '/uploads/' in src) and not any(k in src for k in ['logo', 'flag', 'icon']):
                                    img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                                    break
                        
                        if "ti potrebbe interessare anche" in testo.lower():
                            testo = re.split(r'ti potrebbe interessare anche', testo, flags=re.IGNORECASE)[0]
                            
                        if "la nostra società ha installato un impianto fotovoltaico" in testo.lower():
                            testo = re.split(r'la nostra società ha installato un impianto fotovoltaico', testo, flags=re.IGNORECASE)[0]
                        
                        testo_estratto_finale = f"Condizione: {condizione_veicolo}\n--- DETTAGLI ---\n{testo.strip()}"[:3000]
                        
                        scraper_utils.process_listing(
                            db_conn, 
                            config, 
                            url_completo, 
                            SITE_NAME, 
                            testo_estratto_finale, 
                            prezzo, 
                            DISTANCE_FROM_SEREGNO, 
                            img_url, 
                            regex_extract_camper_data, 
                            ollama_config
                        )
                        count_elaborati += 1
                        
                    except Exception as e:
                        print(f"Errore dettaglio {url_completo}: {e}")

            browser.close()

    except Exception as e: 
        print(f"[!] Errore {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator