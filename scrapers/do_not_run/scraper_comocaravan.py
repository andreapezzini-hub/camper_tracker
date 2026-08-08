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

def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    # 6. FIX: L'anno è spesso sbagliato. Privilegiamo le chiavi esplicite, e se usiamo il fallback 
    # scartiamo cifre seguite da cm, cc, eur, €, cv, kw per evitare false corrispondenze come "2000 Cm³" o "EUR 2000"
    anno_match = re.search(r'(?:immatricolazione|anno)\s*[:\n]?\s*(?:[0-1]?\d/)?(199\d|20[0-2]\d)\b', testo)
    if anno_match:
        anno = int(anno_match.group(1))
    else:
        fallback_match = re.search(r'(?<!eur\s)(?<!€\s)\b(199\d|20[0-2]\d)\b(?!\s*(?:cm|cc|eur|€|cv|kw))', testo)
        anno = int(fallback_match.group(1)) if fallback_match else None
    
    km_match = re.search(r'(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*(?:km|chilometri)', testo)
    km = int(km_match.group(1).replace('.', '')) if km_match else None
    if km is None and ('nuovo' in testo or '0 km' in testo or 'da immatricolare' in testo):
        km = 0
        
    # LOGICA AFFINATA PER LE CATEGORIE: GERARCHIA RIGOROSA
    tipo_furgonato = bool(re.search(r'(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))
    
    # Protezione per evitare false assegnazioni al semintegrale e ad altre categorie
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
    # 4. FIX: Catturiamo lunghezze indicate in cm (es. L699, oppure numeri sciolti tra 500 e 1200)
    misure_dec = re.findall(r'(\d+[.,]\d{1,2})', testo)
    if misure_dec:
        floats = [float(m.replace(',', '.')) for m in misure_dec]
        # REGOLA: un camper non sarà mai meno lungo di 5 metri, e non sarà mai più alto/largo di 5 metri.
        lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
        if lunghezze_valide:
            lunghezza = max(lunghezze_valide)
            
    if lunghezza is None:
        # Cerchiamo format come L699, L745
        match_l_cm = re.search(r'\bl\s*(\d{3})\b', testo)
        if match_l_cm:
            val_cm = float(match_l_cm.group(1))
            if 500 <= val_cm <= 1200:
                lunghezza = val_cm / 100.0

    if lunghezza is None:
        # Fallback per valori isolati espressi in cm (da 500 a 1200)
        misure_cm = re.findall(r'(?<!\d)(5\d{2}|6\d{2}|7\d{2}|8\d{2}|9\d{2})(?!\d)', testo)
        if misure_cm:
            lunghezze_valide_cm = [float(v)/100.0 for v in misure_cm]
            lunghezza = max(lunghezze_valide_cm)
            
    if lunghezza is None:
        match_lung = re.search(r'lunghezza\s*[:]?\s*(\d+[.,]?\d*)', testo)
        if match_lung:
            lunghezza = float(match_lung.group(1).replace(',', '.'))

    # 4. FIX: Posti Omologati e Posti Letto con intercettazione della formattazione estesa
    posti_omologati = None
    posti_letto = None
    
    match_omologati = re.search(r'(?:omologati|viaggio)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*(?:omologati|viaggio)', testo) or re.search(r'\bposti\b\s*[:\n]?\s*(\d)', testo)
    if match_omologati: 
        posti_omologati = int(match_omologati.group(1))
    
    match_letto = re.search(r'(?:letto|dormire)[\s:]*(\d)', testo) or re.search(r'(\d)\s*posti\s*letto', testo) or re.search(r'numero\s*letti\s*[:\n]?\s*(\d)', testo)
    if match_letto: 
        posti_letto = int(match_letto.group(1))

    cv_match = re.search(r'(\d{3})\s*cv', testo)
    potenza = int(cv_match.group(1)) if cv_match else None
    
    # 7. FIX: Aggiunta intercettazione "Stufa Combi Diesel" al riscaldamento a gasolio
    riscaldamento_gasolio = bool(re.search(r'webasto|eberspacher|eberspächer|riscaldatore\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*(?:[a-z0-9]+\s*){0,3}(?:a\s*)?gasolio|riscaldamento\s*diesel|stufa\s*(?:a\s*)?gasolio|stufa\s*combi\s*diesel|truma\s*(?:combi\s*)?(?:d\b|a\s*gasolio)|riscaldatore\s*supplementare', testo))
    riscaldamento_alde = bool(re.search(r'\balde\b', testo))
    
    # Accessori 
    batterie_litio = bool(re.search(r'batteri[ea]\s*(?:al\s*)?litio|\blitio\b', testo))
    predisposizione_invernale = bool(re.search(r'winter\s*pack|pack\s*winter|pacchetto\s*invernale|predisposizione\s*invernale', testo))
    doppia_batteria = bool(re.search(r'doppi[oa]\s*batteri[ea]|seconda\s*batteria|due\s*batterie|2\s*batterie', testo))
    piedini_autolivellanti = bool(re.search(r'piedini\s*(?:auto)?livellanti|piedini\s*idraulici|autolivellanti', testo))
    
    letti_gemelli = bool(re.search(r'letti\s*gemelli|letto\s*gemello', testo))
    letti_a_castello = bool(re.search(r'letti\s*a\s*castello|letto\s*a\s*castello|\bcastello\b', testo))
    
    # 8. FIX: Rimozione diciture legate alla sola cabina per non falsare "Aria condizionata"
    testo_no_cabina = re.sub(r'clima\s*cabina|climatizzatore\s*cabina|climatizzatore\s*automatico|aria\s*condizionata\s*cabina|climatizzatore\s*manuale|clima\s*manuale', '', testo)
    aria_condizionata = bool(re.search(r'clima|condizionat', testo_no_cabina))
    
    # 5. FIX: Pulizia per non pescare il "peso rimorchiabile"
    peso = 3500 # Default patente B
    testo_no_rimorchiabile = re.sub(r'peso\s*rimorchiabile\s*[:]?\s*\d+\s*kg', '', testo)
    match_peso = re.search(r'(\d{4})\s*kg', testo_no_rimorchiabile)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r'patente\s*c|oltre\s*3500|heavy|maxi', testo_no_rimorchiabile):
        peso = 4250
    
    # Cerca nel DB catalogo_modelli usando utils
    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    
    if match_db:
        marca = match_db["marca"]
        modello = match_db["modello"]
        allestimento = match_db["allestimento"]
    else:
        # Fallback se il DB non ha corrispondenze
        parole = str(raw_text).split()
        parole_utili = []
        stop_words = ['nuovo', 'usato', 'pronta', 'consegna', 'camper', 'occasione', 'euro', 'iva', 'esposta', 'noleggio', '']
        
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
        "letto_nautico": 'letto nautico' in testo,
        "letti_gemelli": letti_gemelli,
        "letti_a_castello": letti_a_castello
    }


# ==========================================
# 2. CORE SCRAPER E COLLEGAMENTO
# ==========================================

def extract_price(text):
    # Aggiornato per riconoscere i formati "€ 60.000" e "60.000 Euro" usati dal sito
    match = re.search(r'(?:€|euro)?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*(?:€|euro)?', text, re.IGNORECASE)
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
    SITE_NAME = "Como Caravan"
    BASE_URL = "https://www.comocaravan.it"
    TARGET_URL = f"{BASE_URL}/lista-veicoli/"
    DISTANCE_FROM_SEREGNO = 20 # Distanza Grandate(CO)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        print(f"    [{SITE_NAME}] Scansione catalogo principale...")
        response = requests.get(TARGET_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Como Caravan usa link che contengono 'scheda-' per le pagine di dettaglio
        links_veicoli = soup.find_all('a', href=re.compile(r'scheda-'))
        processed_urls = set()
        count_elaborati = 0
        
        for link in links_veicoli:
            # Ricerca del contenitore card
            container = link.find_parent('div', class_=re.compile(r'item|card|vehicle', re.I))
            if not container:
                container = link.find_parent('div') 
                while container and len(container.get_text()) < 50:
                    container = container.find_parent('div')
                    if not container: break
            
            if not container: continue
            
            url_parziale = link['href']
            url_completo = BASE_URL + url_parziale if url_parziale.startswith('/') else url_parziale
            if not url_completo.startswith('http'):
                url_completo = f"{BASE_URL}/{url_parziale.lstrip('/')}"
            
            if url_completo in processed_urls: continue
            
            testo_card = clean_text_preserve_lists(container.get_text(separator="\n"))
            
            # 9. FIX: Scartare i caravan/roulotte identificati
            if re.search(r'lunghezza\s*con\s*timone|roulotte', testo_card, re.IGNORECASE):
                print(f"      [!] Saltato: identificato come Caravan/Roulotte.")
                continue
                
            prezzo = extract_price(testo_card)
            
            # Filtro per prezzo sensato e valuta
            if prezzo > 10000 and ('€' in testo_card or 'euro' in testo_card.lower()):
                processed_urls.add(url_completo)
                
                print(f"    [{SITE_NAME}] Analisi: {url_completo}")
                
                img_url = None
                
                # Tentativo di intercettare immagine d'anteprima
                for img_tag in container.find_all('img'):
                    src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-original')
                    if src and not 'logo' in src.lower():
                        # 1. FIX: Risoluzione URL malformati con protocollo implicito //
                        if src.startswith('//'):
                            img_url = 'https:' + src
                        elif src.startswith('http'):
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
                            if src and ('veicoli' in src.lower() or 'foto' in src.lower() or 'uploads' in src.lower() or 'gestionemodelli' in src.lower()):
                                # 1. FIX: Risoluzione URL malformati con protocollo implicito // anche nel dettaglio
                                if src.startswith('//'):
                                    img_url = 'https:' + src
                                elif src.startswith('http'):
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
                    print(f"      [!] Impossibile leggere dettaglio: {inner_e}. Fallback su dati card.")
                    testo_finale = testo_card

                # 2. FIX: Rimossa la troncatura arbitraria a 3000 caratteri 
                # (if len(testo_finale) > 3000: testo_finale = testo_finale[:3000])

                # 3. FIX: Troncatura manuale successiva a "Siamo a Grandate (COMO)"
                match_grandate = re.search(r'siamo a grandate\s*\(como\)', testo_finale, re.IGNORECASE)
                if match_grandate:
                    testo_finale = testo_finale[:match_grandate.start()]

                # Invocazione della funzione standard modularizzata
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
                    
    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")

if __name__ == "__main__":
    import sys
    # Aggiunta per il testing indipendente dalla folder scrapers
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
    import scraper_utils
