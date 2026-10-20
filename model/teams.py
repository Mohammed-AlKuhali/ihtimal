"""Canonical team registry: ESPN display names are the canonical key (ESPN is consistent across its
domestic and UEFA feeds). openfootball names are mapped onto them. Arabic names + colours for the four
site leagues (+ the featured clubs)."""
import re, unicodedata

OF_TO_CANON = {
    # explicit overrides (everything else: auto-normalised in build_data.auto_map and asserted)
    "Deportivo Alavés": "Alavés", "RC Deportivo La Coruña": "Deportivo", "RCD Espanyol de Barcelona": "Espanyol",
    "Rayo Vallecano de Madrid": "Rayo Vallecano",
    "Angers SCO": "Angers", "ES Troyes AC": "Troyes", "Lille OSC": "Lille", "Montpellier HSC": "Montpellier",
    "OGC Nice": "Nice", "Olympique Lyonnais": "Lyon", "Olympique de Marseille": "Marseille",
    "RC Strasbourg Alsace": "Strasbourg", "Racing Club de Lens": "Lens", "Stade Brestois 29": "Brest",
    "1. FC Köln": "FC Cologne", "1. FSV Mainz 05": "Mainz", "FC Bayern München": "Bayern Munich", "Hamburger SV": "Hamburg SV",
    "ACF Fiorentina": "Fiorentina", "Atalanta BC": "Atalanta", "FC Internazionale Milano": "Internazionale", "Genoa CFC": "Genoa",
}

# (arabic, hex colour override or None). Colour None -> derived from ESPN colours with a contrast rule.
AR = {
    # Premier League
    "Arsenal": "أرسنال", "Coventry City": "كوفنتري سيتي", "Hull City": "هال سيتي", "Manchester United": "مانشستر يونايتد",
    "Everton": "إيفرتون", "Crystal Palace": "كريستال بالاس", "Ipswich Town": "إيبسويتش تاون", "Sunderland": "سندرلاند",
    "Nottingham Forest": "نوتنغهام فورست", "Leeds United": "ليدز يونايتد", "Brentford": "برينتفورد", "Tottenham Hotspur": "توتنهام",
    "Brighton & Hove Albion": "برايتون", "Aston Villa": "أستون فيلا", "Manchester City": "مانشستر سيتي", "AFC Bournemouth": "بورنموث",
    "Newcastle United": "نيوكاسل يونايتد", "Liverpool": "ليفربول", "Fulham": "فولهام", "Chelsea": "تشيلسي",
    # La Liga
    "Alavés": "ألافيس", "Getafe": "خيتافي", "Sevilla": "إشبيلية", "Rayo Vallecano": "رايو فايكانو", "Racing Santander": "راسينغ سانتاندير",
    "Villarreal": "فياريال", "Espanyol": "إسبانيول", "Levante": "ليفانتي", "Deportivo": "ديبورتيفو لاكورونيا", "Elche": "إلتشي",
    "Atlético Madrid": "أتلتيكو مدريد", "Málaga": "ملقا", "Real Betis": "ريال بيتيس", "Real Sociedad": "ريال سوسيداد",
    "Athletic Club": "أتلتيك بلباو", "Valencia": "فالنسيا", "Celta Vigo": "سيلتا فيغو", "Real Madrid": "ريال مدريد",
    "Barcelona": "برشلونة", "Osasuna": "أوساسونا",
    # Ligue 1
    "Marseille": "مارسيليا", "Strasbourg": "ستراسبورغ", "Lens": "لانس", "AJ Auxerre": "أوكسير", "Le Mans": "لومان", "Brest": "بريست",
    "Nice": "نيس", "Lorient": "لوريان", "Toulouse": "تولوز", "Lyon": "ليون", "Troyes": "تروا", "Paris FC": "باريس إف سي",
    "Angers": "أنجيه", "Lille": "ليل", "Le Havre AC": "لوهافر", "AS Monaco": "موناكو", "Stade Rennais": "رين", "Paris Saint-Germain": "باريس سان جيرمان",
    # Saudi Pro League
    "Abha": "أبها", "Al Ahli": "الأهلي", "Al Diriyah": "الدرعية", "Al Hazem": "الحزم", "Al Ettifaq": "الاتفاق", "Al Fateh": "الفتح",
    "Al Hilal": "الهلال", "Al Fayha": "الفيحاء", "Al Ittihad": "الاتحاد", "Al Qadsiah": "القادسية", "Al Nassr": "النصر",
    "Al Riyadh": "الرياض", "Al Shabab": "الشباب", "Al Khaleej": "الخليج", "Al Taawoun": "التعاون", "Al Kholood": "الخلود",
    "Neom SC": "نيوم", "Al Faisaly": "الفيصلي",
    # Featured / internal
    "Bayern Munich": "بايرن ميونخ",
}

EN_OVERRIDE = {"AFC Bournemouth": "Bournemouth", "Brighton & Hove Albion": "Brighton", "Tottenham Hotspur": "Tottenham",
               "Neom SC": "NEOM", "Paris Saint-Germain": "Paris Saint-Germain", "Stade Rennais": "Rennes", "AS Monaco": "Monaco",
               "AJ Auxerre": "Auxerre", "Le Havre AC": "Le Havre", "Al Diriyah": "Al-Diriyah"}
ID_OVERRIDE = {"Paris Saint-Germain": "psg", "Barcelona": "barcelona", "Bayern Munich": "bayern", "Arsenal": "arsenal", "Real Madrid": "real-madrid",
               "Neom SC": "neom"}
# hand-picked, visible-on-navy colours for clubs where ESPN's colour is wrong/dark/white
COLOUR_OVERRIDE = {"Paris Saint-Germain": "#3B7BFF", "Barcelona": "#D4286A", "Bayern Munich": "#E4143C", "Arsenal": "#EF2A2F",
                   "Real Madrid": "#E9E4D0", "Al Hilal": "#3D5BFF", "Al Nassr": "#F5D90A", "Al Ittihad": "#F2D21B", "Al Ahli": "#1FA463",
                   "Al Qadsiah": "#F2B705", "Tottenham Hotspur": "#9FB4E8", "Leeds United": "#FFCD00", "Newcastle United": "#8A94A6",
                   "Al Diriyah": "#6FA8DC", "Al Riyadh": "#E24B4B", "Paris FC": "#6C8BFF", "Juventus": "#D9D9D9", "Lyon": "#4A74E0",
                   "Marseille": "#59B3E8", "Chelsea": "#3D78D8", "Everton": "#4D6BFF", "Crystal Palace": "#3F5FFF", "Brighton & Hove Albion": "#3F7BFF",
                   "Aston Villa": "#B03A74", "Fulham": "#E8E8E8", "Ipswich Town": "#3F6CFF", "Hull City": "#F28800", "Getafe": "#4C6BFF",
                   "Espanyol": "#4A7BE0", "Deportivo": "#4A7BE0", "Real Sociedad": "#4A7BE0", "Sevilla": "#E8E8E8", "Valencia": "#F28C1C",
                   "Rayo Vallecano": "#E83A3A", "Racing Santander": "#3FA34D", "Elche": "#3FA34D", "Real Betis": "#3FA34D"}


def strip_accents(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def slug(s):
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast_vs_navy(hexc):
    L = _lum(hexc); Ln = _lum("#07090D")
    return (L + 0.05) / (Ln + 0.05)


def _lighten(hexc, t):
    h = hexc.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [int(c + (255 - c) * t) for c in rgb]
    return "#%02X%02X%02X" % tuple(rgb)


def pick_colour(canon, espn_main, espn_alt):
    if canon in COLOUR_OVERRIDE:
        return COLOUR_OVERRIDE[canon]
    cands = [c for c in (espn_main, espn_alt) if c]
    cands = ["#" + c.lstrip("#").upper() for c in cands if len(c.lstrip("#")) == 6]
    for c in cands:
        if _contrast_vs_navy(c) >= 4.0 and c.upper() != "#FFFFFF":
            return c
    base = cands[0] if cands else "#8899AA"
    t = 0.2
    while _contrast_vs_navy(base) < 4.0 and t < 0.95:
        base = _lighten(base, t); t += 0.1
    return base


def team_record(canon, espn_main=None, espn_alt=None):
    return {"id": ID_OVERRIDE.get(canon, slug(canon)), "ar": AR.get(canon), "en": EN_OVERRIDE.get(canon, canon),
            "colour": pick_colour(canon, espn_main, espn_alt)}
