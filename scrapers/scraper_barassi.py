import os
import re
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import scraper_utils

# ==========================================
# 1. LOGICA REGEX SPECIFICA (Fix Categorie & Clima)
# ==========================================

def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    # 1. Anno
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    if anno_match:
        valore_anno = int(anno_match.group(1))
        if valore_anno == 2000 and re.search(r'2000\s*(?:cm|cc|€|euro)', testo):
            anno_match = None
            
    if anno_match:
        anno = int(anno_match.group(1))
    else:
        import datetime
        anno = datetime.datetime.now().year
    
    # 2. Chilometri
    km = None
    km_match_dettaglio = re.search(r'chilometraggio\s*:\s*(\d{1,6})\s*km', testo)
    if km_match_dettaglio:
        km = int(km_match_dettaglio.group(1))
    else:
        km_match = re.search(r'(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*(?:km|chilometri)', testo)
        km = int(km_match.group(1).replace('.', '')) if km_match else None
        
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo):
        km = 0

    # 3. Tipologie: Fix Categorie (Urban Vehicle -> Van, Semi-integrati priority)
    categoria_match = re.search(r'categoria\s*:\s*([^\n]+)', testo)
    cat_str = categoria_match.group(1).strip() if categoria_match else ""

    tipo_furgonato = False
    tipo_mansardato = False
    tipo_motorhome = False
    tipo_semintegrale = False

    if 'urban-vehicle' in testo or 'urban vehicle' in testo or 'furgonato' in cat_str or 'van' in cat_str:
        tipo_furgonato = True
    elif 'semi' in cat_str or 'profilat' in cat_str or 'basculante' in cat_str or re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b|\bbasculante\b', testo):
        tipo_semintegrale = True
    elif 'motorhome' in cat_str or 'integrale' in cat_str or re.search(r'\bmotorhome\b', testo):
        tipo_motorhome = True
    elif 'mansardato' in cat_str or re.search(r'\bmansardat[oi]\b', testo):
        tipo_mansardato = True
    else:
        if re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b|\bbasculante\b', testo): tipo_semintegrale = True
        elif re.search(r'\bmotorhome\b', testo): tipo_motorhome = True
        elif re.search(r'\bmansardat[oi]\b', testo): tipo_mansardato = True
        elif re.search(r'\bvan\b|\bfurgonat[oi]\b', testo): tipo_furgonato = True

    lunghezza = None
    misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
    if misure_dec:
        floats = [float(m.replace(',', '.')) for m in misure_dec]
        lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
        if lunghezze_valide:
            lunghezza = max(lunghezze_valide)
            
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
    
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|stufa\s*diesel', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    # 4. Accessori e Fix Clima Cellula (Esclude Clima Cabina)
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pack\s*winter|pacchetto\s*invernale|predisposizione\s*invernale|serbatoi[oi]?\s*(?:coibentat[oi]|riscaldat[oi])|coibentaz|riscaldamento\s*regolabile', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria|due\s*batterie|2\s*batteri[ea]|2°?\s*batteria', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti|piedini\s*idraulici|autolivellanti', testo))
    
    testo_no_clima_cabina = re.sub(
        r'(?:clima|climatizzatore|aria\s*condizionata|a/c)\s*(?:automatico|manuale)?\s*(?:in\s*)?(?:cabina|motore)|(?:cabina|motore)\s*(?:con\s*)?(?:clima|climatizzatore|aria\s*condizionata|a/c)', 
        '', 
        testo
    )
    aria_condizionata = bool(re.search(r'clima\s*cellula|condizionatore\s*cellula|climatizzatore\s*cellula|truma\s*aventa|telair|viesa|dometic\s*freshjet', testo_no_clima_cabina))

    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|letto\s*a\s*castello|\bcastello\b', testo))
    
    peso = 3500
    match_peso = re.search(r'(\d{4})\s*kg', testo)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r'patente\s*c|oltre\s*3500|heavy|maxi', testo):
        peso = 4250
    
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
        "emissioni_euro6": bool(re.search(r'euro\s*6', testo)),
        "pannelli_solari": 'pannell' in testo and 'solar' in testo,
        "batterie_litio": batterie_litio,
        "sospensioni_aria": 'sospensioni' in testo and ('aria' in testo or 'pneumat' in testo),
        "predisposizione_invernale": predisposizione_invernale,
        "doppia_batteria": doppia_batteria,
        "aria_condizionata": aria_condizionata,
        "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio,
        "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti,
        "letto_nautico": 'letto nautico' in testo or 'letto centrale' in testo,
        "letti_gemelli": letti_gemelli,
        "letti_a_castello": letti_a_castello
    }


# ==========================================
# 2. CORE SCRAPER - BARASSI CON PLAYWRIGHT
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

def run_scraper(db_conn, config, ollama_config=None, skip_ai=False):
    SITE_NAME = "Centro Caravans Barassi"
    BASE_URL = "https://www.centrocaravansbarassi.com"
    TARGET_URLS = [
        f"{BASE_URL}/camper.php",
        f"{BASE_URL}/van.php",
        f"{BASE_URL}/urban-vehicle.php",
    ]
    DISTANCE_FROM_SEREGNO = 15 
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        processed_urls = set()
        count_elaborati = 0

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=headers['User-Agent'])
            page = context.new_page()

            for target_base in TARGET_URLS:
                print(f"    [Barassi] Scansione dinamica sezione: {target_base}", flush=True)
                
                # Apertura e scroll per garantire l'iniezione JS dei nodi
                page.goto(target_base, wait_until="domcontentloaded", timeout=30000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)
                
                html_content = page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                links_veicoli = soup.find_all('a', href=re.compile(r'dettaglio|veicolo|id=\d+'))
                print(f"    [Barassi] Trovati {len(links_veicoli)} link veicolo in {target_base}", flush=True)

                for link in links_veicoli:
                    container = link.find_parent('div') 
                    while container and len(container.get_text()) < 50:
                        container = container.find_parent('div')
                        if not container: break
                    
                    if not container: continue
                    
                    url_parziale = link['href']
                    url_completo = BASE_URL + "/" + url_parziale if not url_parziale.startswith('http') else url_parziale
                    
                    if url_completo in processed_urls: 
                        continue
                    
                    processed_urls.add(url_completo)
                    
                    # Logga SEMPRE prima del filtro per tracciare tutti gli URL incontrati
                    print(f"    [Barassi] Analisi: {url_completo}", flush=True)

                    testo_card = clean_text_preserve_lists(container.get_text(separator="\n"))
                    prezzo = extract_price(testo_card)
                    
                    # Filtro: scarta se è venduto (None) o sotto i 10.000€ (None). Fa passare solo >= 10000 o 0 (Trattativa)
                    if prezzo is None:
                        print("      [!] Annuncio venduto o senza prezzo valido: saltato.", flush=True)
                        continue
                    
                    img_url = None
                    for img_tag in container.find_all('img'):
                        src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-original') or img_tag.get('data-lazy-src')
                        if src and ('immagini/' in src.lower() or 'camper/' in src.lower()):
                            if src.startswith('http'):
                                img_url = src
                            else:
                                src = src.lstrip('/') 
                                img_url = f"{BASE_URL}/{src}"
                            break
                    
                    testo_finale = testo_card
                    try:
                        time.sleep(0.3) 
                        det_resp = requests.get(url_completo, headers=headers, timeout=10)
                        det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                        
                        if not img_url:
                            for img in det_soup.find_all('img'):
                                src = img.get('src') or img.get('data-src') or img.get('data-original')
                                if src and ('immagini/' in src.lower()):
                                    if src.startswith('http'):
                                        img_url = src
                                    else:
                                        src = src.lstrip('/')
                                        img_url = f"{BASE_URL}/{src}"
                                    break
                        
                        for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                                            hidden.decompose()
                                            
                        testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                        testo_finale = f"{testo_card}\n\n--- DETTAGLI ---\n{testo_dettaglio}"
                        
                    except Exception as inner_e:
                        print(f"      [!] Impossibile leggere dettaglio: {inner_e}. Fallback su dati card.", flush=True)

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
                        ollama_config=ollama_config,
                        skip_ai=skip_ai
                    )
                    
                    count_elaborati += 1

            browser.close()

    except Exception as e:
        print(f"    [!] Errore fatale nello scraper Barassi: {e}", flush=True)

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    import scraper_utils