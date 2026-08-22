import os
import re
import time
import requests
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import datetime

# Importiamo il modulo di utilità condiviso
import scraper_utils

# ==========================================
# 1. LOGICA REGEX SPECIFICA (Da adattare al sito)
# ==========================================

def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()
    
    anno_match = re.search(r'\b(199\d|20[0-3]\d)\b', testo)
    anno = int(anno_match.group(1)) if anno_match else datetime.datetime.now().year
    
    # Estrazione chilometri migliorata (gestisce 'Km percorsi\n39798' e formati con separatore)
    km = None
    # Cerca prima l'etichetta esplicita 'km percorsi' seguita da numero (anche a capo)
    km_label_match = re.search(r'km\s+percorsi[:\s\n]*([\d\.]+)', testo)
    if km_label_match:
        val_str = km_label_match.group(1).replace('.', '')
        if val_str.isdigit():
            km = int(val_str)

    if km is None:
        km_matches = re.findall(r'(?:km|chilometri|km\.)[\s\n:]*(\d{1,3}(?:\.\d{3})+|\d{1,6})|(\d{1,3}(?:\.\d{3})+|\d{1,6})[\s\n]*(?:km|chilometri)', testo)
        km_values = []
        for match in km_matches:
            for group in match:
                if group:
                    km_values.append(int(group.replace('.', '')))
        valid_kms = [v for v in km_values if not (1990 <= v <= 2030)]
        if valid_kms:
            km = valid_kms[0]
        
    if km is None and ('nuovo' in testo or 'da immatricolare' in testo or 'km 0' in testo):
        km = 0
        
    tipo_furgonato = bool(re.search(r'\b(van|furgonat[oi]|camper puri)\b', testo))
    tipo_mansardato = bool(re.search(r'\bmansardat[oi]\b', testo))
    tipo_motorhome = bool(re.search(r'\bmotorhome\b|\bintegrale\b', testo)) and not bool(re.search(r'\bsemi[\s-]?integral[ei]\b', testo))
    tipo_semintegrale = bool(re.search(r'\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b', testo))

    # Esclusività delle categorie
    if tipo_furgonato:
        tipo_semintegrale = tipo_motorhome = tipo_mansardato = False
    elif tipo_motorhome:
        tipo_semintegrale = tipo_mansardato = False
    elif tipo_mansardato:
        tipo_semintegrale = False
    
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

    # URL di partenza inclusa la lista generale senza filtro cat per catturare tutto
    START_URLS = [f"{BASE_URL}/veicolo-ricerca-list.php?page={i}" for i in range(1, 20)]
    
    DISTANCE_FROM_SEREGNO = 60

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    session = requests.Session()

    retries = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[403, 429, 500, 502, 503, 504, 408],
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers)

    proxy_url = config.get("PROXY_URL") if isinstance(config, dict) else None
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    try:
        processed_detail_urls = set()
        pages_to_visit = list(START_URLS)
        visited_pages = set()
        count_elaborati = 0

        while pages_to_visit:
            target = pages_to_visit.pop(0)
            if target in visited_pages:
                continue

            visited_pages.add(target)
            print(f"    [{SITE_NAME}] Scansione pagina catalogo: {target}...")

            try:
                response = session.get(target, timeout=(5, 20))
                if response.status_code == 404:
                    continue
                response.raise_for_status()
            except requests.exceptions.ConnectTimeout:
                print(f"    [!] Timeout Connessione su {target}.")
                continue
            except Exception as e:
                print(f"    [!] Errore durante il caricamento della pagina {target}: {e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            # 1.1 Estrazione link PAGINAZIONE e OFFERTE
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href")
                if "veicolo-ricerca-list.php" in href or "offerte-del-mese.php" in href:
                    clean_href = href.split('#')[0]
                    if not clean_href:
                        continue
                    full_p_url = urljoin(BASE_URL, clean_href)
                    if (
                        full_p_url not in visited_pages
                        and full_p_url not in pages_to_visit
                    ):
                        pages_to_visit.append(full_p_url)

            # 1.2 Estrazione link di DETTAGLIO VEICOLI
            candidate_links = soup.find_all(
                "a",
                href=re.compile(
                    r"veicolo/\d+|veicolo-dettaglio", re.IGNORECASE
                ),
            )
                        
            for a_tag in soup.find_all("a", href=True):
                txt = a_tag.get_text(strip=True).lower()
                href = a_tag.get("href")
                if ("dettagli" in txt or "vedi" in txt) and "/veicolo/" in href:
                    if a_tag not in candidate_links:
                        candidate_links.append(a_tag)
                    
            if not candidate_links:
                continue

            # ----------------------------------------------------
            # FASE 2: Analisi dei singoli veicoli trovati
            # ----------------------------------------------------
            for link in candidate_links:
                url_parziale = link.get("href")
                if not url_parziale or url_parziale.startswith("#"):
                    continue

                url_completo = urljoin(BASE_URL, url_parziale)

                if url_completo in processed_detail_urls:
                    continue

                container = (
                    link.find_parent("div", class_=re.compile(r"col|item|card|box"))
                    or link.find_parent("div")
                )
                testo_card = ""
                prezzo = 0
                img_url = None

                if container:
                    testo_card = clean_text_preserve_lists(
                        container.get_text(separator="\n")
                    )
                    testo_lower = testo_card.lower()

                    if (
                        re.search(r"\b(roulotte|noleggio|noleggi)\b", testo_lower)
                        or "tipo: caravan" in testo_lower
                        or "tipologia: caravan" in testo_lower
                    ):
                        processed_detail_urls.add(url_completo)
                        continue

                    prezzo = extract_price(testo_card)

                    for img_tag in container.find_all("img"):
                        src = img_tag.get("src") or img_tag.get("data-src")
                        if src and not src.endswith(".svg"):
                            img_url = urljoin(BASE_URL, src)
                            break

                processed_detail_urls.add(url_completo)
                print(f"    [{SITE_NAME}] Analisi scheda: {url_completo}")

                try:
                    time.sleep(1.5)
                    det_resp = session.get(url_completo, timeout=(5, 15))
                    det_soup = BeautifulSoup(det_resp.text, "html.parser")

                    if not img_url:
                        for img in det_soup.find_all("img"):
                            src = img.get("src") or img.get("data-src")
                            if src and "veicol" in src.lower() and not src.endswith(".svg"):
                                img_url = urljoin(BASE_URL, src)
                                break

                    for hidden in det_soup(
                        ["script", "style", "nav", "footer", "header"]
                    ):
                        hidden.decompose()

                    testo_dettaglio = clean_text_preserve_lists(
                        det_soup.get_text(separator="\n")
                    )
                    
                    # TRONCAMENTO TESTO DIRETTAMENTE nello scraper prima del salvataggio nel DB
                    testo_dettaglio_lower = testo_dettaglio.lower()
                    for marker in ["ti potrebbe interessare anche", "ti potrebbe interressare anche", "veicoli correlati"]:
                        if marker in testo_dettaglio_lower:
                            idx = testo_dettaglio_lower.find(marker)
                            testo_dettaglio = testo_dettaglio[:idx]
                            testo_dettaglio_lower = testo_dettaglio_lower[:idx]
                            break

                    if (
                        re.search(r"\b(roulotte|noleggio|noleggi)\b", testo_dettaglio_lower)
                        or "categoria caravan" in testo_dettaglio_lower
                        or "tipo: caravan" in testo_dettaglio_lower
                    ):
                        continue

                    if prezzo == 0:
                        prezzo = extract_price(testo_dettaglio)

                    # Se ha un prezzo valido ed è inferiore a 20.000€, oppure è venduto a sotto i 20k, scarta
                    if 0 < prezzo < 20000:
                        print(f"      [-] Scartato: prezzo sotto 20.000€ ({prezzo}€)")
                        continue

                    testo_finale = (
                        f"{testo_card}\n\n--- DETTAGLI ---\n{testo_dettaglio}"
                    )

                except Exception as inner_e:
                    print(
                        f"      [!] Impossibile leggere dettaglio: {inner_e}. Fallback su dati card."
                    )
                    testo_finale = testo_card

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
                )

                count_elaborati += 1
                if count_elaborati >= 200:
                    break

            if count_elaborati >= 200:
                break

    except Exception as e:
        print(f"    [!] Errore fatale nello scraper {SITE_NAME}: {e}")
    
if __name__ == "__main__":
    import sys
    # Aggiungiamo la directory superiore per poter importare scraper_utils e score_calculator se eseguiamo da /scrapers
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import score_calculator
