"""eMAG return reasons (rma return_reason), official hierarchy from the eMAG Marketplace API
documentation v4.5.1 (attached "return_reason & observations" sheet). The IDs are identical on
RO/BG/HU; the labels are the Romanian ones, each one the full path ("Level1 > Level2 > Level3").
"""

EMAG_RETURN_REASONS: dict[int, str] = {
    30: "Vreau sa returnez un produs sigilat",
    31: "Vreau sa returnez un produs functional",
    32: "Vreau sa returnez un produs nefunctional",
    34: "Marimea nu corespunde",
    35: "Produsul nu corespunde asteptarilor",
    36: "Produsul nu corespunde descrierii din site",
    37: "Produsul primit prezinta un defect sau este incomplet",
    38: "Am comandat mai mult de o marime",
    39: "Am primit alt produs decat cel comandat",
    40: "Am primit coletul deteriorat",
    42: "Vreau sa returnez un produs sigilat > Am gasit produsul la un pret mai bun",
    43: "Vreau sa returnez un produs sigilat > Am primit alt produs decat cel comandat",
    44: "Vreau sa returnez un produs sigilat > Am comandat produsul gresit",
    45: "Vreau sa returnez un produs sigilat > Alt motiv",
    46: "Vreau sa returnez un produs functional > Nu sunt multumit de produs",
    47: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa",
    48: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site",
    49: "Vreau sa returnez un produs functional > Am gasit produsul la un pret mai bun",
    50: "Vreau sa returnez un produs functional > Am primit alt produs decat cel comandat",
    51: "Vreau sa returnez un produs functional > Am comandat produsul gresit",
    52: "Vreau sa returnez un produs functional > Alt motiv",
    53: "Vreau sa returnez un produs nefunctional > Produsul este lovit/spart",
    54: "Vreau sa returnez un produs nefunctional > Produsul este defect",
    55: "Vreau sa returnez un produs nefunctional > Am comandat produsul gresit",
    57: "Marimea nu corespunde > Am primit marimea comandata, dar produsul imi este mic",
    58: "Marimea nu corespunde > Am primit marimea comandata, dar produsul imi este mare",
    59: "Marimea nu corespunde > Am primit o alta marime decat cea comandata",
    60: "Produsul nu corespunde asteptarilor > Nu imi place materialul",
    61: "Produsul nu corespunde asteptarilor > Nu imi place culoarea",
    62: "Produsul nu corespunde asteptarilor > Nu imi place croiala",
    63: "Produsul nu corespunde asteptarilor > Nu imi place cum imi vine",
    64: "Produsul nu corespunde asteptarilor > Nu sunt comozi",
    65: "Produsul nu corespunde asteptarilor > Nu imi place dimensiunea",
    66: "Produsul nu corespunde asteptarilor > Nu imi place cum este compartimentat",
    67: "Produsul nu corespunde asteptarilor > Alt motiv",
    68: "Produsul nu corespunde descrierii din site > Materialul este diferit",
    69: "Produsul nu corespunde descrierii din site > Culoarea este diferita",
    70: "Produsul nu corespunde descrierii din site > Dimensiunile sunt diferite fata de specificatiile din site",
    71: "Produsul nu corespunde descrierii din site > Captuseala este diferita",
    72: "Produsul nu corespunde descrierii din site > Bareta are o alta dimensiune",
    73: "Produsul nu corespunde descrierii din site > Alt motiv",
    74: "Produsul primit prezinta un defect sau este incomplet > Materialul este patat",
    75: "Produsul primit prezinta un defect sau este incomplet > Materialul este descusut",
    76: "Produsul primit prezinta un defect sau este incomplet > Materialul este rupt",
    77: "Produsul primit prezinta un defect sau este incomplet > Materialul este zgariat",
    78: "Produsul primit prezinta un defect sau este incomplet > Inchizatoarea este defecta",
    79: "Produsul primit prezinta un defect sau este incomplet > Cadranul este zgariat",
    80: "Produsul primit prezinta un defect sau este incomplet > Cureaua este zgariata",
    81: "Produsul primit prezinta un defect sau este incomplet > Produsul prezinta urme de oxidare",
    82: "Produsul primit prezinta un defect sau este incomplet > Remontorul este rupt",
    83: "Produsul primit prezinta un defect sau este incomplet > Lipsesc nasturi",
    84: "Produsul primit prezinta un defect sau este incomplet > Talpa este dezlipita",
    85: "Produsul primit prezinta un defect sau este incomplet > Fermoarul este defect",
    86: "Produsul primit prezinta un defect sau este incomplet > Lipseste un accesoriu",
    87: "Produsul primit prezinta un defect sau este incomplet > Catarama este defecta",
    88: "Produsul primit prezinta un defect sau este incomplet > Produsul prezinta urme de exfoliere",
    89: "Produsul primit prezinta un defect sau este incomplet > Produs incomplet sau cu accesorii lipsa",
    90: "Produsul primit prezinta un defect sau este incomplet > Produsul este lovit/spart",
    91: "Produsul primit prezinta un defect sau este incomplet > Produsul nu functioneaza",
    92: "Produsul primit prezinta un defect sau este incomplet > Alt motiv",
    93: "Am comandat mai mult de o marime > Am vrut sa compar marimile",
    94: "Am comandat mai mult de o marime > Am comandat din greseala",
    95: "Am comandat mai mult de o marime > Alt motiv",
    96: "Am primit coletul deteriorat > Produsul este intact",
    97: "Am primit coletul deteriorat > Produsul a fost afectat",
    98: "Vreau sa returnez un produs sigilat > Am gasit produsul la un pret mai bun > Tot la eMAG",
    99: "Vreau sa returnez un produs sigilat > Am gasit produsul la un pret mai bun > La un alt magazin",
    100: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Bateria se descarca prea repede",
    101: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea camerei foto este sub asteptari",
    102: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Diagonala ecranului este mai mica decat ma asteptam",
    103: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea sunetului este sub asteptarile mele",
    104: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Conexiunea la internet wireless este instabila",
    105: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea imaginii este sub asteptarile mele",
    106: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu imi place platforma SmartTV/meniul TV-ului",
    111: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul nu corespunde asteptarilor mele",
    112: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc castile",
    113: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste incarcatorul",
    114: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste cablul",
    115: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste telecomanda",
    116: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste piciorul (standul) televizorului",
    117: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc suruburi",
    118: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc accesorii ale produsului",
    120: "Vreau sa returnez un produs functional > Am gasit produsul la un pret mai bun > Tot la eMAG",
    121: "Vreau sa returnez un produs functional > Am gasit produsul la un pret mai bun > La un alt magazin",
    122: "Vreau sa returnez un produs nefunctional > Produsul este lovit/spart > Ambalajul este intact",
    123: "Vreau sa returnez un produs nefunctional > Produsul este lovit/spart > Ambalajul este deteriorat",
    124: "Vreau sa returnez un produs nefunctional > Produsul este defect > Nu porneste",
    125: "Vreau sa returnez un produs nefunctional > Produsul este defect > Pixeli morti",
    126: "Vreau sa returnez un produs nefunctional > Produsul este defect > Produsul are probleme de afisaj",
    127: "Vreau sa returnez un produs nefunctional > Produsul este defect > Alt motiv",
    128: "Produsul primit prezinta un defect sau este incomplet > Produsul este lovit/spart > Am primit coletul deteriorat, dar cutia ceasului este intacta",
    129: "Produsul primit prezinta un defect sau este incomplet > Produsul este lovit/spart > Am primit coletul deteriorat si cutia ceasului este deteriorata",
    130: "Produsul primit prezinta un defect sau este incomplet > Produsul este lovit/spart > Am primit coletul in stare buna",
    131: "Produsul primit prezinta un defect sau este incomplet > Produsul nu functioneaza > Am primit coletul deteriorat, dar cutia ceasului este intacta",
    132: "Produsul primit prezinta un defect sau este incomplet > Produsul nu functioneaza > Am primit coletul deteriorat si cutia ceasului este deteriorata",
    133: "Produsul primit prezinta un defect sau este incomplet > Produsul nu functioneaza > Am primit coletul in stare buna",
    134: "Produs acordat cadou",
    135: "Nespecificat",
    136: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Culoarea chiuvetei difera de cea a bateriei",
    137: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Chiuveta nu este perforata pentru instalarea bateriei",
    138: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Chiuveta nu se potriveste cu mobilierul",
    139: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Chiuveta prezinta urme de uzura sau zgarieturi",
    140: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Culoarea bateriei difera de cea a chiuvetei",
    141: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Bateria prezinta urme de uzura sau zgarieturi",
    142: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul nu se potriveste cu mobilierul",
    143: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul prezinta urme de uzura sau zgarieturi",
    144: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste bateria",
    145: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc sifonul si preaplinul",
    146: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc racorduri",
    147: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc usi",
    148: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc manere",
    149: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc role",
    150: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Culoarea este diferita",
    151: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Produsul are alte dimensiuni",
    152: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Alt motiv",
    153: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Lungimea pipei este diferita",
    154: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Inaltimea bateriei este diferita",
    155: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Diametrul este diferit",
    157: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Dimensiunea nu este potrivita",
    158: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul nu este confortabil",
    159: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu imi place culoarea",
    160: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul este dificil de asamblat",
    161: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea materialului este una slaba",
    162: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc roti",
    163: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc picioare",
    166: "Vreau sa returnez un produs nefunctional > Produsul este defect > Pistonul este defect",
    167: "Vreau sa returnez un produs functional > Produsul este deteriorat",
    168: "Vreau sa returnez un produs functional > Produsul este deteriorat > Materialul este patat",
    169: "Vreau sa returnez un produs functional > Produsul este deteriorat > Materialul este rupt",
    170: "Vreau sa returnez un produs functional > Produsul este deteriorat > Produsul prezinta urme de uzura sau zgarieturi",
    171: "Vreau sa returnez un produs functional > Produsul este deteriorat > Altceva",
    172: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Am primit un produs cu alte specificatii",
    173: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul este prea zgomotos",
    174: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumit de calitatea materialelor",
    175: "Nu sunt multumit cum functioneaza produsul",
    176: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Diagonala ecranului este mai mare decat ma asteptam",
    177: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumit de greutatea produsului",
    178: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumim de calitatea produsului",
    179: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul se incalzeste foarte tare",
    180: "Vreau sa returnez un produs nefunctional > Produsul este defect > Produsul prezinta unul sau mai multi pixeli morti",
    181: "Vreau sa returnez un produs nefunctional > Produsul este defect > Nu functioneaza tastatura/touchpad-ul",
    182: "Vreau sa returnez un produs nefunctional > Produsul are display-ul spart",
    183: "Vreau sa returnez un produs nefunctional > Produsul are display-ul spart > Ambalajul este intact",
    184: "Vreau sa returnez un produs nefunctional > Produsul are display-ul spart > Ambalajul este deteriorat",
    185: "Vreau sa returnez un produs nefunctional > Alt motiv",
    186: "Vreau sa returnez un produs functional > Produsul este lovit/spart",
    187: "Vreau sa returnez un produs functional > Produsul este lovit/spart > Ambalajul este intact",
    188: "Vreau sa returnez un produs functional > Produsul este lovit/spart > Ambalajul este deteriorat",
    189: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc suruburile pentru montajul suportului inclus",
    190: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Produsul prezinta unul sau mai multi pixeli morti",
    191: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste acumulatorul",
    192: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc electrozi",
    193: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste masca",
    194: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste sarma de sudura",
    195: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipsesc duze",
    196: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste rezervorul pentru vopsea",
    197: "Vreau sa returnez un produs functional > Produsul este deteriorat > Produsul este zgariat",
    198: "Vreau sa returnez un produs functional > Produsul este deteriorat > Produsul este spart",
    199: "Vreau sa returnez un produs functional > Produsul este deteriorat > Accesoriile sunt deteriorate",
    200: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea produsului este sub asteptarile mele",
    201: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea accesoriilor este sub asteptarile mele",
    202: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Fotografia din site difera fata de produsul primit",
    203: "Vreau sa returnez un produs functional > Produsul nu corespunde descrierii din site > Specificatiile prezentate in site diferta fata de produsul primit",
    204: "Vreau sa returnez un produs nefunctional > Produsul este defect > Produsul nu se alimenteaza",
    205: "Vreau sa returnez un produs nefunctional > Produsul este defect > Produsul se supraincalzeste",
    206: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste sacul",
    207: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste lantul",
    208: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste sina",
    209: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste pistolul",
    210: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumit de viteza cu care televizorul raspunde la comenzile prin telecomanda",
    211: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumit de finisajul carcasei",
    212: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste obiectivul produsului",
    213: "Vreau sa returnez un produs functional > Produs incomplet sau cu accesorii lipsa > Lipseste geanta/husa produsului",
    214: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Software-ul produsului este greoi",
    215: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu ma pot obisnui cu meniul produsului",
    216: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Autonomia acumulatorului este sub asteptarile mele",
    217: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Focalizarea a produsului este sub asteptarile mele",
    218: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea pozelor este sub asteptarile mele",
    219: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Calitatea clipurilor video este sub asteptarile mele",
    220: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Nu sunt multumit de calitatea materialelor folosite la constructia produsului",
    221: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Sunt diferente intre descrierea de pe site si produsul primit",
    222: "Vreau sa returnez un produs functional > Nu sunt multumit de produs > Ma asteptam la o data de fabricatie mai recenta",
}


def emag_return_reason_label(code) -> str:
    """Romanian label for an eMAG return_reason id; "Motiv <id>" when unknown, "" when empty."""
    if code in (None, ""):
        return ""
    try:
        return EMAG_RETURN_REASONS.get(int(code)) or f"Motiv {code}"
    except (TypeError, ValueError):
        return f"Motiv {code}"


# ── unified reason ──────────────────────────────────────────────────────────
# Rules are checked on each level of the path, from the most specific one upwards; the first
# level that matches decides ("Alt motiv" matches nothing, so it inherits its parent's reason).
# Order matters inside a level: "nefunctional" must win over "functional", "lovit/spart" over "defect".
_REASON_RULES: list[tuple[str, tuple[str, ...]]] = [
    # level-1 "Produsul primit prezinta un defect sau este incomplet": generic = defect; its
    # specific children (Lipseste un accesoriu...) are classified on their own level first
    ("defective", ("defect sau este incomplet",)),
    ("wrong_item", ("alt produs decat", "alta marime decat")),
    ("ordered_by_mistake", ("comandat produsul gresit", "comandat din greseala")),
    ("damaged", ("lovit/spart", "deteriorat", "display-ul spart", "produsul a fost afectat")),
    ("missing_parts", ("incomplet", "lipsesc", "lipseste")),
    ("defective", ("nefunctional", "defect", "nu functioneaza", "cum functioneaza", "zgariat", "rupt",
                   "patat", "descusut", "exfoliere", "oxidare", "dezlipit")),
    ("not_as_described", ("nu corespunde descrierii", "diferit")),
    ("size_fit", ("marime", "imi este mare", "imi este mic", "dimensiunea", "cum imi vine", "comozi", "croiala")),
    ("changed_mind", ("pret mai bun", "nu sunt multumit de produs", "asteptarilor", "nu imi place", "cadou")),
]


def _classify_segment(segment: str) -> str | None:
    text = segment.lower()
    for reason, needles in _REASON_RULES:
        if any(needle in text for needle in needles):
            return reason
    return None


def emag_return_reason(code) -> str:
    """Unified ReturnReason value for an eMAG return_reason id ("other" when unknown)."""
    from bapp_connectors.core.dto import ReturnReason

    try:
        label = EMAG_RETURN_REASONS.get(int(code))
    except (TypeError, ValueError):
        label = None
    if not label:
        return ReturnReason.OTHER
    for segment in reversed(label.split(" > ")):
        reason = _classify_segment(segment)
        if reason:
            return ReturnReason(reason)
    return ReturnReason.OTHER
