import os
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Importiamo il modulo di utilità condiviso
import scraper_utils

# ==========================================
# 1. LOGICA REGEX SPECIFICA (Da adattare al sito)
# ==========================================

def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-3]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else None
    
    # Estrazione chilometri migliorata
    km_matches = re.findall(r'(?:km|chilometri|km percorsi)[\s\n:]*(\d{1,3}(?:\.\d{3})+|\d{1,6})|(\d{1,3}(?:\.\d{3})+|\d{1,6})[\s\n]*(?:km|chilometri)', testo)
    km_values = []
    for match in km_matches:
        for group in match:
            if group:
                km_values.append(int(group.replace('.', '')))
                
    km = None
    valid_kms = [v for v in km_values if not (1990 <= v <= 2030)] # Evita di confondere l'anno con i km
    if valid_kms:
        km = valid_kms[0]
        
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo or 'km 0' in testo):
        km = 0
        
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    
    # LOGICA AFFINATA PER LE CATEGORIE: GERARCHIA RIGOROSA
    if tipo_furgonato:
        tipo_semintegrale = False
        tipo_motorhome = False
        tipo_mansardato = False
    elif tipo_semintegrale:
        # Priorità al semintegrale per evitare false categorizzazioni in presenza di comparative (es. "non è mansardato")
        tipo_mansardato = False
        tipo_motorhome = False
    elif tipo_motorhome and not re.search(r'\bsemi[\s-]?integral[ei]\b', testo):
        tipo_mansardato = False
    elif tipo_mansardato:
        tipo_motorhome = False
    
    # Estrazione lunghezza migliorata
    lunghezza = None
    match_lung_label = re.search(r'lunghezza[\s\n:]*(\d+[.,]?\d*)[\s\n]*(mm|cm|mt|m)?', testo)
    if match_lung_label:
        val = float(match_lung_label.group(1).replace(',', '.'))
        if val > 4000:
            lunghezza = val / 1000
        elif val > 400:
            lunghezza = val / 100
        else:
            lunghezza = val

    if lunghezza is None:
        misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
        if misure_dec:
            floats = [float(m.replace(',', '.')) for m in misure_dec]
            lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
            if lunghezze_valide:
                lunghezza = max(lunghezze_valide)

    posti_omologati = None
    posti_letto = None
    
    match_omologati = re.search(r'(?:omologati|viaggio)[\s\n:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*(?:omologati|viaggio)', testo)
    if match_omologati: posti_omologati = int(match_omologati.group(1))
    
    match_letto = re.search(r'(?:letto|dormire)[\s\n:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*letto', testo)
    if match_letto: posti_letto = int(match_letto.group(1))
    
    if posti_omologati is None and posti_letto is None:
        match_generico = re.search(r'\b(\d)\s+(\d)\s+(?:\d{2,3}[.,]\d{3})', testo)
        if match_generico:
            posti_omologati = int(match_generico.group(1))
            posti_letto = int(match_generico.group(2))

    cv_match = re.search(r'(\d{3})\s*cv', testo)
    potenza = int(cv_match.group(1)) if cv_match else None
    
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|riscaldatore\s*supplementare', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    
    # Predisposizione invernale migliorata
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pack\s*winter|pacchetto\s*invernale|predisposizione\s*invernale|serbatoi[oaie]?\s+(?:\w+\s+){0,3}(?:isolat[oi]|coibentat[oi]|riscaldat[oi])', testo))
    
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria|due\s*batterie|2\s*batterie', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti|piedini\s*idraulici|autolivellanti', testo))
    
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|letto\s*a\s*castello|\bcastello\b', testo))
    
    # Estrazione peso migliorata
    peso = 3500 # Default patente B comune
    peso_match = re.search(r'peso\s*(?:compl\.|complessivo|omologato|totale|massimo)?[\s\n:]*(\d{3,4})[\s\n]*kg', testo)
    if peso_match:
        peso = float(peso_match.group(1))
    else:
        # Fallback scartando valori che potrebbero essere pesi rimorchiabili
        for m in re.finditer(r'(\d{3,4})[\s\n]*kg', testo):
            start = max(0, m.start() - 30)
            contesto = testo[start:m.start()]
            if 'rimorch' not in contesto and 'trainab' not in contesto:
                peso = float(m.group(1))
                break
    
    if re.search(r'patente\s*c|oltre\s*3500|heavy|maxi', testo) and peso <= 3500:
        peso = 4250
    
    # Cerca prima nel DB catalogo_modelli usando utils
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    
    if match_db:
        marca = match_db["marca"]
        modello = match_db["modello"]
        allestimento = match_db["allestimento"]
    else:
        # Fallback originale se il DB non ha corrispondenze
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
    """
    Pulisce il testo ma cerca di mantenere i ritorni a capo utili
    per non perdere le liste puntate degli accessori mostrate sul sito.
    """
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Caravan Schiavolin"
    BASE_URL = "https://www.caravanschiavolin.it"
    TARGET_URLS = [
        f"{BASE_URL}/veicolo-ricerca-list.php?cat=nuovo",
        f"{BASE_URL}/veicolo-ricerca-list.php?cat=usato"
    ]
    DISTANCE_FROM_SEREGNO = 60 
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # Configurazione Session con Retry automatici per tollerare rallentamenti/timeout del server
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504, 408])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.headers.update(headers)
    
    try:
        processed_urls = set()
        count_elaborati = 0
        
        for target in TARGET_URLS:
            print(f"    [{SITE_NAME}] Scansione catalogo: {target}...")
            try:
                # Timeout alzato a 30 secondi
                response = session.get(target, timeout=30)
                response.raise_for_status()
            except Exception as e:
                print(f"    [!] Errore durante il caricamento del catalogo {target}: {e}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Supporto per URL legacy (id=) e nuovi permalink SEO-friendly (veicolo/)
            links_veicoli = soup.find_all('a', href=re.compile(r'veicolo-dettaglio\.php\?id=\d+|veicolo/\d+'))
            
            for link in links_veicoli:
                url_parziale = link['href']
                url_completo = BASE_URL + "/" + url_parziale if not url_parziale.startswith('http') else url_parziale
                
                if url_completo in processed_urls: continue
                
                container = link.find_parent('div', class_=re.compile(r'item|col-|card')) or link.find_parent('div')
                if not container: continue
                
                testo_card = clean_text_preserve_lists(container.get_text(separator="\n"))
                
                # Esclusione caravan/roulotte/noleggio in modo sicuro
                testo_lower = testo_card.lower()
                if re.search(r'\b(roulotte|noleggio|noleggi)\b', testo_lower) or "categoria caravan" in testo_lower or "tipo: caravan" in testo_lower:
                    continue
                
                prezzo = extract_price(testo_card)
                processed_urls.add(url_completo)
                
                print(f"    [{SITE_NAME}] Analisi: {url_completo}")
                
                img_url = None
                for img_tag in container.find_all('img'):
                    src = img_tag.get('src') or img_tag.get('data-src')
                    if src:
                        img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                        break
                
                try:
                    time.sleep(1) 
                    # Timeout alzato a 20 secondi anche sui dettagli
                    det_resp = session.get(url_completo, timeout=20)
                    det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                    
                    if not img_url:
                        for img in det_soup.find_all('img'):
                            src = img.get('src')
                            if src and 'veicoli' in src.lower():
                                img_url = src if src.startswith('http') else f"{BASE_URL}/{src.lstrip('/')}"
                                break
                    
                    for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                        hidden.decompose()
                        
                    testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                    testo_dettaglio_lower = testo_dettaglio.lower()
                    
                    # Doppio check di sicurezza 
                    if re.search(r'\b(roulotte|noleggio|noleggi)\b', testo_dettaglio_lower) or "categoria caravan" in testo_dettaglio_lower or "tipo: caravan" in testo_dettaglio_lower:
                        continue
                        
                    if prezzo == 0:
                        prezzo = extract_price(testo_dettaglio)
                        
                    if prezzo < 5000:
                        continue
                        
                    testo_finale = f"{testo_card}\n\n--- DETTAGLI ---\n{testo_dettaglio}"
                    
                except Exception as inner_e:
                    print(f"      [!] Impossibile leggere dettaglio: {inner_e}. Fallback su dati card.")
                    testo_finale = testo_card

                # Utilizziamo la funzione modulare passando la NOSTRA funzione RegEx
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
                if count_elaborati >= 500: # Modifica qui per testare più o meno annunci
                    break
                    
    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    # Aggiungiamo la directory superiore per poter importare scraper_utils e score_calculator se eseguiamo da /scrapers
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    import scraper_utils