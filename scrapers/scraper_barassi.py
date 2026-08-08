import os
import re
import time
import requests
from bs4 import BeautifulSoup

# Importiamo il modulo di utilità condiviso
import scraper_utils

# ==========================================
# 1. LOGICA REGEX SPECIFICA (Da adattare al sito)
# ==========================================

def regex_extract_camper_data(raw_text, current_price):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-2]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else None
    
    km_match = re.search(r'(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*(?:km|chilometri)', testo)
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
    elif tipo_motorhome and not re.search(r'\bsemi[\s-]?integral[ei]\b', testo):
        tipo_semintegrale = False
    elif tipo_semintegrale:
        tipo_motorhome = False
    
    lunghezza = None
    # Catturiamo i numeri decimali nel testo (misure come 7.4, 7.35, 2.95, ecc.)
    misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
    if misure_dec:
        floats = [float(m.replace(',', '.')) for m in misure_dec]
        # REGOLA: un camper non sarà mai meno lungo di 5 metri, e non sarà mai più alto/largo di 5 metri.
        # Quindi limitiamo la ricerca ai valori decimali tra 5.0 e 12.0 (filtro matematico sicuro).
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
    
    # Regole di estrazione Riscaldamento (Migliorato per matchare "riscaldamento truma combi a gasolio")
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|riscaldatore\s*supplementare', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    # Aggiunta estrazione per gli accessori mancanti dai dati tecnici
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
    match_db = scraper_utils.match_marca_modello_db(raw_text)
    
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
        # Rimuove l'eventuale numero iniziale (es. "24 Adria", "18 Laika") o "Selection [numero]"
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
    # Sostituisce i multipli ritorni a capo con uno singolo
    text = re.sub(r'\n\s*\n', '\n', text)
    # Rimuove tabulazioni e spazi multipli ma lascia i \n
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def run_scraper(config, ollama_config=None):
    SITE_NAME = "Centro Caravans Barassi"
    BASE_URL = "https://www.centrocaravansbarassi.com"
    TARGET_URL = f"{BASE_URL}/camper.php"
    DISTANCE_FROM_SEREGNO = 15 
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        print(f"    [Barassi] Scansione catalogo principale...")
        response = requests.get(TARGET_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links_veicoli = soup.find_all('a', href=re.compile(r'dettaglio|veicolo|id=\d+'))
        processed_urls = set()
        count_elaborati = 0
        
        for link in links_veicoli:
            container = link.find_parent('div') 
            while container and len(container.get_text()) < 50:
                container = container.find_parent('div')
                if not container: break
            
            if not container: continue
            
            url_parziale = link['href']
            url_completo = BASE_URL + "/" + url_parziale if not url_parziale.startswith('http') else url_parziale
            
            if url_completo in processed_urls: continue
            
            testo_card = clean_text_preserve_lists(container.get_text(separator="\n"))
            prezzo = extract_price(testo_card)
            
            if prezzo > 10000 and '€' in testo_card:
                processed_urls.add(url_completo)
                
                print(f"    [Barassi] Analisi: {url_completo}")
                
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
                
                try:
                    time.sleep(1) 
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
                        
                    # Usiamo \n come separatore per mantenere l'elenco degli accessori leggibile
                    testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                    testo_finale = f"{testo_card}\n\n--- DETTAGLI ---\n{testo_dettaglio}"
                    
                except Exception as inner_e:
                    print(f"      [!] Impossibile leggere dettaglio: {inner_e}. Fallback su dati card.")
                    testo_finale = testo_card

                if len(testo_finale) > 3000:
                    testo_finale = testo_finale[:3000]

                # Utilizziamo la funzione modulare passando la NOSTRA funzione RegEx
                scraper_utils.process_listing(
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
                if count_elaborati >= 2000: # Modifica qui per testare più o meno annunci
                    break
                    
    except Exception as e:
        print(f"    [!] Errore fatale nello scraper Barassi: {e}")

if __name__ == "__main__":
    import sys
    # Aggiungiamo la directory superiore per poter importare scraper_utils e score_calculator se eseguiamo da /scrapers
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    import scraper_utils
