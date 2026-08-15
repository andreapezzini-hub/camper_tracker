import os
import re
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import scraper_utils


# ==========================================
# 1. LOGICA REGEX (Adattata per DB)
# ==========================================
def regex_extract_camper_data(raw_text, current_price, db_conn):
    testo = str(raw_text).lower()

    anno_match = re.search(r"\b(199\d|20[0-2]\d)\b", testo)
    anno = int(anno_match.group(1)) if anno_match else None

    km = None
    # 1. Prova prima il formato "80381 km" o "80.381 km"
    km_match = re.search(
        r"(\d{1,3}(?:\.\d{3})+|\d{2,6})\s*km\b", testo, re.IGNORECASE
    )
    if km_match:
        km = int(km_match.group(1).replace(".", ""))
    else:
        # 2. Se fallisce, prova il formato "km 80381" o "km 80.381"
        km_match_alt = re.search(
            r"\bkm\s*(\d{1,3}(?:\.\d{3})+|\d{2,6})", testo, re.IGNORECASE
        )
        if km_match_alt:
            km = int(km_match_alt.group(1).replace(".", ""))

    # Fallback per i mezzi nuovi/da immatricolare
    if km is None and (
        "nuovo" in testo.lower() or "da immatricolare" in testo.lower()
    ):
        km = 0

    tipo_furgonato = bool(
        re.search(r"(?:\r?\n|\r|\s)(van|furgonat[oi]|camper puro)", testo)
    )
    tipo_mansardato = bool(re.search(r"\bmansardat[oi]\b", testo))
    tipo_motorhome = bool(re.search(r"\bmotorhome\b|\bintegrale\b", testo))
    tipo_semintegrale = bool(
        re.search(r"\bsemi[\s-]?integral[ei]\b|\bprofilat[oi]\b", testo)
    )

    if tipo_furgonato:
        tipo_semintegrale = tipo_motorhome = tipo_mansardato = False
    elif tipo_mansardato:
        tipo_semintegrale = tipo_motorhome = False
    elif tipo_semintegrale:
        tipo_motorhome = False
    elif tipo_motorhome and not re.search(
        r"\bsemi[\s-]?integral[ei]\b", testo
    ):
        tipo_semintegrale = False

    lunghezza = None
    misure_dec = re.findall(r"(\d+[.,]\d{1,2})", testo)
    if misure_dec:
        floats = [float(m.replace(",", ".")) for m in misure_dec]
        lunghezze_valide = [v for v in floats if 5.0 <= v <= 12.0]
        if lunghezze_valide:
            lunghezza = max(lunghezze_valide)

    if lunghezza is None:
        match_lung = re.search(r"lunghezza\s*[:]?\s*(\d+[.,]?\d*)", testo)
        if match_lung:
            lunghezza = float(match_lung.group(1).replace(",", "."))

    posti_omologati = posti_letto = None
    match_omologati = re.search(
        r"(?:omologati|viaggio)[\s:]*(\d)", testo
    ) or re.search(r"(\d)\s*posti\s*(?:omologati|viaggio)", testo)
    if match_omologati:
        posti_omologati = int(match_omologati.group(1))

    match_letto = re.search(
        r"(?:letto|dormire)[\s:]*(\d)", testo
    ) or re.search(r"(\d)\s*posti\s*letto", testo)
    if match_letto:
        posti_letto = int(match_letto.group(1))

    cv_match = re.search(r"(\d{3})\s*cv", testo)
    potenza = int(cv_match.group(1)) if cv_match else None

    riscaldamento_gasolio = bool(
        re.search(r"webasto|eberspacher|riscaldamento\s*(?:a\s*)?gasolio", testo)
    )
    riscaldamento_alde = bool(re.search(r"\balde\b", testo))
    batterie_litio = bool(
        re.search(r"batteri[ea]\s*(?:al\s*)?litio|\blitio\b", testo)
    )
    predisposizione_invernale = bool(
        re.search(r"winter\s*pack|pacchetto\s*invernale", testo)
    )
    doppia_batteria = bool(
        re.search(r"doppi[oa]\s*batteri[ea]|seconda\s*batteria", testo)
    )
    piedini_autolivellanti = bool(
        re.search(r"piedini\s*(?:auto)?livellanti", testo)
    )
    letti_gemelli = bool(re.search(r"letti\s*gemelli|letto\s*gemello", testo))
    letti_a_castello = bool(
        re.search(r"letti\s*a\s*castello|\bcastello\b", testo)
    )

    peso = 3500
    match_peso = re.search(r"(\d{4})\s*kg", testo)
    if match_peso:
        peso = float(match_peso.group(1))
    elif re.search(r"patente\s*c|oltre\s*3500|heavy", testo):
        peso = 4250

    match_db = scraper_utils.match_marca_modello_db(raw_text, db_conn)
    if match_db:
        marca, modello, allestimento = (
            match_db["marca"],
            match_db["modello"],
            match_db["allestimento"],
        )
    else:
        parole = [
            re.sub(r"[^\w\s]", "", p).strip().capitalize()
            for p in str(raw_text).split()
            if p.strip().lower()
            not in ["nuovo", "usato", "pronta", "consegna", "camper"]
        ]
        modello_fallback = " ".join(parole[:5]) if parole else "Sconosciuto"
        marca, modello, allestimento = "Sconosciuto", modello_fallback, ""

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
        "telaio_alko": "alko" in testo,
        "doppio_pavimento": "doppio pavimento" in testo,
        "cambio_automatico": "automatico" in testo,
        "emissioni_euro6": bool(re.search(r"euro\s*6", testo)),
        "pannelli_solari": "pannell" in testo and "solar" in testo,
        "batterie_litio": batterie_litio,
        "sospensioni_aria": "sospensioni" in testo and "aria" in testo,
        "predisposizione_invernale": predisposizione_invernale,
        "doppia_batteria": doppia_batteria,
        "aria_condizionata": "clima" in testo,
        "riscaldamento_gasolio": riscaldamento_gasolio,
        "riscaldatore_gasolio": riscaldamento_gasolio,
        "riscaldamento_alde": riscaldamento_alde,
        "piedini_autolivellanti": piedini_autolivellanti,
        "letto_nautico": "letto nautico" in testo,
        "letti_gemelli": letti_gemelli,
        "letti_a_castello": letti_a_castello,
    }


# ==========================================
# 2. CORE SCRAPER - CAMPER NOVARA
# ==========================================
def extract_price(text):
    match = re.search(r"€?\s*(\d{2,3}[\.,]\d{3})(?:[\.,]\d{2})?\s*€?", text)
    if match:
        return int(match.group(1).replace(".", "").replace(",", ""))
    return 0


def clean_text(text):
    return re.sub(r"\n\s*\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()

def get_all_active_listing_urls():
    """
    Usa Playwright per simulare lo scroll e caricare tutti gli annunci attivi
    realmente presenti a schermo nelle pagine 'camper-usati' e 'camper-nuovi'.
    """
    target_pages = [
        "https://www.campernovara.it/camper-usati/",
        "https://www.campernovara.it/camper-nuovi/"
    ]
    
    collected_urls = set()

    with sync_playwright() as p:
        # Avviamo il browser headless
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for target_url in target_pages:
            print(f"[*] Caricamento e scroll automatico su: {target_url}")
            try:
                page.goto(target_url, wait_until="networkidle", timeout=30000)
                
                # Simuliamo lo scroll progressivo verso il basso per attivare l'infinite scroll/AJAX
                last_height = page.evaluate("document.body.scrollHeight")
                for _ in range(10): # Tenta fino a 10 scroll
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.5)  # Attende il caricamento AJAX dei nuovi annunci
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        break  # Nessun nuovo contenuto caricato, siamo in fondo
                    last_height = new_height

                # Estraiamo tutti i link '<a>' presenti nella pagina completamente caricata
                links = page.eval_on_selector_all("a[href]", "elements => elements.map(e => e.href)")
                
                for href in links:
                    path_lower = href.lower()
                    # Riconosciamo i link singoli alle schede camper (struttura /camper/nome-modello/)
                    if "/camper/" in path_lower:
                        # Escludiamo link di sistema o di navigazione
                        if not any(skip in path_lower for skip in [
                            "camper_categoria", "camper-usati", "camper-nuovi", 
                            "vendi-il-tuo-camper", "marchi-camper", "cart", "checkout"
                        ]):
                            collected_urls.add(href.split('?')[0].rstrip('/') + '/')

            except Exception as e:
                print(f"[!] Errore durante lo scroll di {target_url}: {e}")

        browser.close()

    return list(collected_urls)


def extract_hd_image_from_detail(det_soup, base_url):
    """
    Estrae l'immagine ad alta risoluzione direttamente dalla pagina del singolo annuncio.
    """
    # 1. Tenta prima dal Meta Tag OpenGraph (og:image) che ha quasi sempre l'immagine HD
    og_img = det_soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        return og_img["content"]

    # 2. Cerca nel blocco galleria/dettaglio un link <a> verso un'immagine in wp-content/uploads
    for a in det_soup.find_all("a", href=True):
        href = a["href"]
        if "/wp-content/uploads/" in href and any(ext in href.lower() for ext in [".jpg", ".jpeg", ".png"]):
            if not any(k in href.lower() for k in ["logo", "icon", "banner", "avatar", "favicon"]):
                return href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"

    # 3. Fallback sui tag <img>
    for img in det_soup.find_all("img"):
        candidate = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        if candidate and "/wp-content/uploads/" in candidate and not candidate.startswith("data:"):
            if not any(k in candidate.lower() for k in ["logo", "icon", "banner", "avatar", "favicon"]):
                return candidate if candidate.startswith("http") else f"{base_url}/{candidate.lstrip('/')}"

    return None


def run_scraper(db_conn, config, ollama_config=None):
    SITE_NAME = "Camper Novara"
    BASE_URL = "https://www.campernovara.it"
    DISTANCE_FROM_SEREGNO = 70
    MAX_ANNUNCI = 500
    count_elaborati = 0

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # FASE 1: Ottenimento degli URL REALI e ATTIVI tramite Playwright
    annunci_urls = get_all_active_listing_urls()
    print(f"[*] Trovati {len(annunci_urls)} annunci attivi a schermo!")

    processed_urls = set()

    # FASE 2: Parsing veloce dettagli con Requests & BeautifulSoup
    for url_completo in annunci_urls:
        if count_elaborati >= MAX_ANNUNCI:
            break

        if url_completo in processed_urls:
            continue
        processed_urls.add(url_completo)

        try:
            time.sleep(0.5)
            det_resp = session.get(url_completo, headers=headers, timeout=20)
            if det_resp.status_code != 200:
                continue

            det_soup = BeautifulSoup(det_resp.text, "html.parser")

            # Estrazione immagine HD dalla scheda del singolo annuncio
            img_url = extract_hd_image_from_detail(det_soup, BASE_URL)

            # Pulizia DOM
            for hidden in det_soup(["script", "style", "nav", "footer", "header"]):
                hidden.decompose()

            testo = clean_text(det_soup.get_text(separator="\n"))

            if re.search(r"\b(roulotte|noleggio)\b", testo.lower()):
                continue

            prezzo = extract_price(testo)
            if prezzo and prezzo < 5000:
                continue

            # Salvataggio
            scraper_utils.process_listing(
                db_conn,
                config,
                url_completo,
                SITE_NAME,
                f"--- DETTAGLI ---\n{testo}"[:3000],
                prezzo,
                DISTANCE_FROM_SEREGNO,
                img_url,
                regex_extract_camper_data,
                ollama_config,
            )
            count_elaborati += 1
            print(f"[+] [{count_elaborati}] Processato: {url_completo}")
            print(f"    -> Immagine HD: {img_url}")

        except Exception as e:
            print(f"[!] Errore su {url_completo}: {e}")


if __name__ == "__main__":
    import sqlite3
    import sys

    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    import score_calculator
