import pandas as pd


def classify_motion_types(input_df: pd.DataFrame) -> pd.DataFrame:
    bp_filtering_patterns = [
        (r"Dieses Haus glaubt.*sollte", "Dieses Haus glaubt, X sollte..."),
        (
            r"Dieses Haus (?:würde|verbietet|hätte|fordert|verpflichtet|führt)",
            "Dieses Haus würde...",
        ),
        (r"(?:Würde|Erlaubt) dieses Haus", "Dieses Haus würde..."),
        (
            r"Dieses Haus,?\s*[-–—]?\s*\(?\s*(?:als|welches.*ist)\s*\)?",
            "Dieses Haus als...",
        ),
        (r"Dieses Haus (?:glaubt|hält|ist)", "Dieses Haus glaubt..."),
        (r"Dieses Haus bereut", "Dieses Haus bereut..."),
        (r"Dieses Haus (?:bedauert|verurteilt|hasst)", "Dieses Haus bedauert..."),
        (r"Dieses Haus lehnt.*ab", "Dieses Haus bedauert..."),
        (r"Dieses Haus hält.*für falsch", "Dieses Haus bedauert..."),
        (
            r"Dieses Haus (?:begrüßt|befürwortet|unterstützt|wünscht|möchte|feiert)",
            "Dieses haus begrüßt...",
        ),
        (
            r"Dieses Haus (?:bevorzugt|präferiert|zieht|entscheidet sich)",
            "Dieses Haus bevorzugt...",
        ),
        (r"(?:This house believes|THBT).*should", "Dieses Haus glaubt, X sollte..."),
        (r"This house (?:will|would)", "Dieses Haus würde..."),
        (r"This house,?\s*[-–—]?\s*\(?\s*as", "Dieses Haus als..."),
        (r"(?:This house believes|THBT)", "Dieses Haus glaubt..."),
        (r"This house opposes", "Dieses Haus bedauert..."),
        (r"This house regrets", "Dieses Haus bereut..."),
        (r"This house supports", "Dieses haus begrüßt..."),
        (r"This house prefers", "Dieses Haus bevorzugt..."),
        (r"This house hopes", "Dieses Haus hofft..."),
        (r"This house predicts", "Dieses Haus sagt vorraus..."),
        (r"THPAW", "Dieses Haus bevorzugt..."),
    ]

    opd_filtering_patterns = [
        (
            r"\bist(?:\s+es)?\b.*\bzu\s+(?:bereuen|bedauern)\b",
            "Ist x zu bereuen/bedauern?",
        ),
        (r"\bWäre eine Welt\b", "Wäre eine Welt...?"),
        (r"\b(?:im\s+interesse|im Sinne des)\b", "Ist x im Interesse von y?"),
        (r"\bin the interest\b", "Ist x in Interesse von y?"),
        (r"\bhätten?\b.*\btun\s+sollen\b", "Hätte x y tun sollen?"),
        (r"\bsoll(?:en|test|te|ten)?\b", "Sollten wir/Sollte x...?"),
        (r"\bbrauchen\s+wir\b", "Brauchen wir..?"),
        (r"\bbraucht\s", "Brauchen wir..?"),
        (r"\bshould\b", "Sollten wir/Sollte x...?"),
        (
            r"\bverpflichtung\b|\bmoralisch richtig\b|\blegitimes mittel\b|\bmoralische\s+pflicht\b|\bmoralisch\s+gerechtfertigt\b",
            "Ist x (un-) moralisch?",
        ),
        (
            r"\bzu\s+begrüßen\b|\bbegrüßenswert\b|\bwünschenswert\w*\b",
            "Ist x zu begrüßen?",
        ),
        (
            r"\bschad(?:et|en)\b.*\bn(?:ü|u)tz(?:t|en)\b",
            "Schadet x mehr als es nutzt?",
        ),
        (r"\bdo more harm than good\b", "Schadet x mehr als es nutzt?"),
        (
            r"\bbevorzug\w*\b|\bvorzuzieh\w*\b|\bpreferable\b|\bvorzieh\w*\b|\bpräferier\w*\b|\bwichtiger,? als\b",
            "Ist x zu bevorzugen?",
        ),
        (
            r"(?:ist|wäre) es.* besser",
            "Ist x zu bevorzugen?",
        ),
        (r"\bsollte man.*\banstelle\b", "Ist x zu bevorzugen?"),
        (
            r"\b(?:wäre|ist|sind)\b.*\b(?:gut|schlechte?|gescheitert|schädigend|sinnvoller Beitrag|hilfreich)\b",
            "Ist x gut/schlecht?",
        ),
        (r"\bunmoralisch\b|\bmoralisch\s+falsch\b", "Ist x (un-) moralisch?"),
        (
            r"\b(?:bedauern|bedauert|bereuen|bereut|bedauernswert|begrüßenswert|bedauerlich|begrüßenswerte)\b",
            "Ist x zu bereuen/bedauern?",
        ),
        (r"\b(?:verboten|abgeschaff?t|eingeführt)\b", "Sollten wir...?"),
        (r"\bdoes\b.*\b(?:have|be)\b", "Ist x (un-) moralisch?"),
        (r"mehr geschadet,? als", "Schadet x mehr als es nutzt?"),
        (r"schadet.*mehr als", "Schadet x mehr als es nutzt?"),
        (
            r"(?:nützt|nutzt|nutzen).*mehr.*als.*(?:schadet|schaden)",
            "Schadet x mehr als es nutzt?",
        ),
    ]

    out_df = input_df.copy()
    out_df["Motion-Typ"] = None

    for mask, patterns, default in [
        (out_df["Format"] == "BP", bp_filtering_patterns, "Sonstige"),
        (out_df["Format"] == "OPD", opd_filtering_patterns, "Sonstige"),
    ]:
        result = pd.Series(None, index=out_df.index, dtype=object)
        for pattern, category_name in patterns:
            pattern_mask = out_df["Thema"].str.contains(
                pattern, case=False, na=False, regex=True
            )
            result.loc[pattern_mask & result.isna()] = category_name
        result = result.fillna(default)
        out_df.loc[mask, "Motion-Typ"] = result.loc[mask]

    return out_df
