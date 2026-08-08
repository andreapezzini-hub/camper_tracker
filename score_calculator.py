import json

def load_config():
    with open('scoring_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def evaluate_price_bracket(price, rules):
    if not isinstance(price, (int, float)):
        return None
        
    brackets = rules.get("brackets", [])
    for bracket in brackets:
        if "max" in bracket and "min" not in bracket:
            if price <= bracket["max"]: return bracket
        elif "min" in bracket and "max" not in bracket:
            if price >= bracket["min"]: return bracket
        elif "min" in bracket and "max" in bracket:
            if price >= bracket["min"] and price <= bracket["max"]: return bracket
    return None

def calculate_score(camper_data, config):
    if not isinstance(camper_data, dict):
        return {"totale": 0, "status": "ERRORE", "motivo": "Formato dati camper non valido."}
    if not isinstance(config, dict) or "categories" not in config:
        return {"totale": 0, "status": "ERRORE", "motivo": "Formato file config non valido."}

    total_score = 0
    category_scores = {}
    
    prezzo_camper = camper_data.get("prezzo", 0)
    
    try:
        prezzo_rules = config["categories"]["prezzo"]["attributes"]["valutazione_prezzo"]
        matched_bracket = evaluate_price_bracket(prezzo_camper, prezzo_rules)
        
        if matched_bracket and matched_bracket.get("is_veto", False):
            return {"totale": -9999, "status": "SCARTATO", "motivo": f"Prezzo ({prezzo_camper}€) in VETO."}
    except KeyError:
        matched_bracket = None
        
    for cat_name, cat_data in config["categories"].items():
        cat_weight = cat_data.get("weight", 0)
        attributes = cat_data.get("attributes", {})
        
        cat_points = 0
        total_active_weight = 0 
        
        for attr_name, rules in attributes.items():
            if "exclude_if" in rules:
                exclude_attr = rules["exclude_if"]["attribute"]
                exclude_val = rules["exclude_if"]["value"]
                if camper_data.get(exclude_attr) == exclude_val:
                    continue 
            
            rule_weight = rules.get("weight", 0)
            total_active_weight += rule_weight
            
            if rules["type"] == "boolean":
                valore_camper = camper_data.get(attr_name, False)
                punti = rules["true_score"] if valore_camper else rules["false_score"]
                cat_points += punti * rule_weight
                
            elif rules["type"] == "condition":
                base_attr = attr_name.split('_')[0] 
                if base_attr == "posti": base_attr = "posti_omologati"
                
                valore_camper = camper_data.get(base_attr)
                
                if valore_camper is not None:
                    condition_met = False
                    if rules["operator"] == "<": condition_met = valore_camper < rules["target"]
                    elif rules["operator"] == ">": condition_met = valore_camper > rules["target"]
                    elif rules["operator"] == "<=": condition_met = valore_camper <= rules["target"]
                    elif rules["operator"] == ">=": condition_met = valore_camper >= rules["target"]
                    
                    if condition_met:
                        cat_points += rules["true_score"] * rule_weight
                    else:
                        cat_points += rules["false_score"] * rule_weight
                        if rules.get("is_veto", False):
                             return {"totale": -9999, "status": "SCARTATO", "motivo": f"VETO Condizione: {attr_name}"}
                else:
                    # MODIFICA: Se il dato manca, assegniamo 0 punti per non alterare il punteggio
                    # Non sommiamo rules["false_score"] perché per le regole VETO vale -9999!
                    pass

            elif rules["type"] == "price_brackets" and matched_bracket:
                cat_points += matched_bracket["score"] * rule_weight

        if total_active_weight > 0:
            normalized_cat_score = (cat_points / total_active_weight)
        else:
            normalized_cat_score = 0
            
        category_scores[cat_name] = normalized_cat_score
        total_score += (normalized_cat_score * cat_weight)

    return {
        "totale": round(total_score, 1),
        "categorie": {k: round(v, 1) for k, v in category_scores.items()},
        "status": "VALIDO"
    }