import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Importiamo il modulo di utilità condiviso
import scraper_utils

# Il calcolatore punteggio resta esterno ma viene richiamato da qui
try:
    import score_calculator
except ImportError:
    pass # Gestito nel blocco main

# ==========================================
# 1. LOGICA REGEX SPECIFICA (Da adattare al sito)
# ==========================================

def regex_extract_camper_data(raw_text, current_price, db_conn):
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

def run_scraper(db_conn, config, ollama_config=None, skip_ai=False):
    SITE_NAME = "Transwe"
    BASE_URL = "https://www.transwe.it"
    # Struttura delle categorie per veicoli nuovi e usati su Transwe
    TARGET_URLS = [
        f"{BASE_URL}/category/camper-motorhome-van-caravan-usati/",
        f"{BASE_URL}/category/camper-van-motorhome-nuovi/"
    ]
    DISTANCE_FROM_SEREGNO = 18 # Anzano del Parco dista circa 18-20km
    
    # Header estesi per bypassare protezioni WordPress / Cloudflare
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Connection': 'keep-alive'
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        processed_urls = set()
        count_elaborati = 0
        
        for base_category_url in TARGET_URLS:
            # Iteriamo sulle prime pagine di paginazione di WordPress
            for page in range(1, 6): 
                url_page = f"{base_category_url}page/{page}/" if page > 1 else base_category_url
                print(f"    [Transwe] Scansione catalogo: {url_page}")
                
                response = session.get(url_page, timeout=15)
                # Se la pagina non esiste, significa che la paginazione è terminata
                if response.status_code == 404:
                    break 
                    
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Approccio universale per siti WP: estraiamo tutti i link
                links = soup.find_all('a', href=True)
                
                for link_tag in links:
                    url_completo = link_tag['href']
                    
                    if not url_completo.startswith('http'):
                        url_completo = f"{BASE_URL}{url_completo if url_completo.startswith('/') else '/' + url_completo}"
                        
                    if not url_completo.startswith(BASE_URL):
                        continue
                        
                    # Filtriamo pesantemente i link di utilità per evitare pagine inutili
                    percorsi_ignorati = ['/category/', '/tag/', '/page/', '/wp-content/', '/wp-json/', '/wp-admin/', 
                                         '/noleggio', '/tariffe', '/faq', '/assistenza', '/galleria', '/blog', 
                                         '/contatti', '/valuta', '/chi-siamo', '/privacy', '/cookie',
                                         '/offerte', '/promozion', '/perche', '/accessori']
                                         
                    if any(p in url_completo.lower() for p in percorsi_ignorati):
                        continue
                        
                    # Ignoriamo la homepage e ancore
                    if url_completo in [f"{BASE_URL}/", BASE_URL] or '#' in url_completo:
                        continue
                        
                    if url_completo.endswith(('.jpg', '.png', '.jpeg', '.pdf')):
                        continue
                        
                    if url_completo in processed_urls:
                        continue
                        
                    processed_urls.add(url_completo)
                    
                    # Troviamo il container della card per eventuali dati
                    container = link_tag.find_parent(['article', 'div', 'li'])
                    testo_card = ""
                    img_url = None
                    
                    if container:
                        testo_card = clean_text_preserve_lists(container.get_text(separator="\n"))
                        img_tag = container.find('img')
                        if img_tag:
                            img_url = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')

                    try:
                        time.sleep(1) 
                        det_resp = session.get(url_completo, timeout=10)
                        if det_resp.status_code != 200:
                            continue
                            
                        det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                        
                        # Recupero immagine dai dettagli qualora non trovata nella card
                        if not img_url:
                            for img in det_soup.find_all('img'):
                                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                                if src and 'uploads' in src.lower() and not 'logo' in src.lower():
                                    img_url = src
                                    break
                        
                        # Pulizia del DOM interno per evitare testo inutile (menu che contiene "motorhome")
                        for hidden in det_soup(["script", "style", "nav", "footer", "header", "aside"]):
                            hidden.decompose()
                            
                        testo_dettaglio = clean_text_preserve_lists(det_soup.get_text(separator="\n"))
                        testo_completo_check = testo_dettaglio.lower()
                        
                        # LOGICA VENDUTO CON CANCELLAZIONE
                        if re.search(r'\bvenduto\b', testo_completo_check):
                            print(f"      [-] Ignorato (VENDUTO): {url_completo}")
                            cursor = db_conn.cursor()
                            cursor.execute("SELECT 1 FROM annunci WHERE url = ?", (url_completo,))
                            if cursor.fetchone():
                                cursor.execute("DELETE FROM annunci WHERE url = ?", (url_completo,))
                                cursor.execute("DELETE FROM storico_prezzi WHERE url_annuncio = ?", (url_completo,))
                                db_conn.commit()
                                print(f"      [!] RIMOSSO DAL DB (VENDUTO): {url_completo}")
                            continue
                            
                        # FIX: Verifica robustezza per capire se è un camper VERO (evita false pagine)
                        tech_keywords = ['chilometri', 'meccanica', 'posti omologati', 'posti letto', 'lunghezza', 'larghezza', 'potenza', 'cambio', 'immatricolazione', 'cilindrata', 'telaio']
                        matches = sum(1 for kw in tech_keywords if kw in testo_completo_check)
                        
                        if matches < 2:
                            # Se non ha almeno 2 parole chiave tecniche, non è un veicolo reale in vendita
                            continue
                        
                        # Estrazione Prezzo
                        prezzo = extract_price(testo_dettaglio)
                        if prezzo == 0 and testo_card:
                            prezzo = extract_price(testo_card)

                        testo_finale = f"{testo_card}\n\n--- DETTAGLI ---\n{testo_dettaglio}"
                        
                    except Exception as inner_e:
                        print(f"      [!] Impossibile leggere dettaglio per {url_completo}: {inner_e}")
                        continue

                    if len(testo_finale) > 3000:
                        testo_finale = testo_finale[:3000]

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
                        ollama_config=ollama_config,
                        skip_ai=skip_ai
                    )
                    
                    count_elaborati += 1
                    if count_elaborati >= 500: 
                        break
                        
                if count_elaborati >= 500:
                    break
                        
    except Exception as e:
        print(f"    [!] Errore fatale nello scraper Transwe: {e}")

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import scraper_utils
    import score_calculator
