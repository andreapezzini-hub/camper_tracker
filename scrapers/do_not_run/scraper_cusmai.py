import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Importiamo il modulo di utilità condiviso
import scraper_utils

# ==========================================
# 1. LOGICA REGEX SPECIFICA
# ==========================================

def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else None
    
    # FIX 1: Intercetta correttamente "chilometri" oltre a "km", includendo spazi e due punti
    km_match = re.search(r'(?:chilometri|km)[\s:]*(\d{1,3}(?:\.\d{3})+|\d{1,6})', testo)
    km = int(km_match.group(1).replace('.', '')) if km_match else None
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo):
        km = 0
        
    # LOGICA AFFINATA PER LE CATEGORIE: GERARCHIA RIGOROSA
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    
    # Protezione per evitare false assegnazioni, dando forte priorità al semintegrale
    if tipo_furgonato:
        tipo_semintegrale = False
        tipo_motorhome = False
        tipo_mansardato = False
    elif tipo_semintegrale:
        tipo_motorhome = False
        tipo_mansardato = False
    elif tipo_motorhome:
        tipo_mansardato = False
    
    lunghezza = None
    
    # FIX 2: Priorità alla dicitura esplicita "lunghezza" e gestione conversione cm -> m
    match_lung = re.search(r'lunghezza[\s:]*(\d+[.,]?\d*)\s*(cm|m|mt|metri)?', testo)
    if match_lung:
        val = float(match_lung.group(1).replace(',', '.'))
        # Se il valore è > 100 o è esplicitamente indicato 'cm', convertiamo in metri
        if val > 100 or match_lung.group(2) == 'cm':
            val = val / 100.0
        # Validazione range realistico
        if 4.0 <= val <= 12.0:
            lunghezza = round(val, 2)
            
    # Fallback in caso la lunghezza sia indicata tra i decimali generici e senza etichetta
    if lunghezza is None:
        misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
        if misure_dec:
            floats = [float(m.replace(',', '.')) for m in misure_dec]
            # REGOLA: un camper non sarà mai meno lungo di 5 metri, e non sarà mai più alto/largo di 5 metri.
            lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
            if lunghezze_valide:
                lunghezza = max(lunghezze_valide)

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
# 2. CORE SCRAPER E COLLEGAMENTO
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

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Cusmai"
    BASE_URL = "https://www.cusmai.com"
    DISTANCE_FROM_SEREGNO = 15 
    
    urls_to_scrape = [
        "https://www.cusmai.com/index.php?route=camper/veicoli/camper_usati",
        "https://www.cusmai.com/index.php?route=camper/veicoli/camper_nuovi"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        processed_urls = set()
        count_elaborati = 0

        for target_url in urls_to_scrape:
            print(f"    [{SITE_NAME}] Scansione catalogo: {target_url}")
            response = requests.get(target_url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Cusmai utilizza Opencart, cerchiamo route=camper/veicoli nei link
            links_veicoli = soup.find_all('a', href=True)
            
            for link in links_veicoli:
                href = link['href']
                
                if 'route=camper/veicoli' in href and 'veicolo_id=' in href:
                    url_completo = href if href.startswith('http') else urljoin(BASE_URL, href)
                    
                    if url_completo in processed_urls: continue
                    
                    print(f"    [{SITE_NAME}] Analisi: {url_completo}")
                    
                    try:
                        time.sleep(1) 
                        det_resp = requests.get(url_completo, headers=headers, timeout=10)
                        det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                        
                        # Container principale Opencart
                        main_content = det_soup.find(id='content') or det_soup.find(class_='product-info') or det_soup
                        
                        for hidden in main_content(["script", "style", "nav", "footer", "header"]):
                            hidden.decompose()
                            
                        testo_dettaglio = clean_text_preserve_lists(main_content.get_text(separator="\n"))
                        testo_lower = testo_dettaglio.lower()
                        
                        # Esclusione sicura roulotte/caravan
                        if re.search(r'\b(roulotte|caravan|rimorchio|noleggio|affitto)\b', testo_lower):
                            print(f"      [SKIP] Rilevata parola esclusa in {url_completo}")
                            continue
                            
                        prezzo = extract_price(testo_dettaglio)
                        
                        img_url = None
                        img_tag = main_content.find('img', class_=re.compile(r'img-responsive|product-image', re.I))
                        if not img_tag:
                            img_tag = main_content.find('img')
                        
                        if img_tag and img_tag.get('src'):
                            src = img_tag['src']
                            img_url = src if src.startswith('http') else urljoin(BASE_URL, src)
                        
                        testo_finale = testo_dettaglio[:3000]
                        processed_urls.add(url_completo)
                        
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
                        if count_elaborati >= 500:
                            break
                        
                    except Exception as inner_e:
                        print(f"      [!] Impossibile leggere dettaglio: {inner_e}")

    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    import scraper_utils
