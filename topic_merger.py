import json
import pandas as pd
import glob
import os
from pathlib import Path

from paths import CACHE_DIR, OUTPUT_DIR

_DATA_DIR = Path(__file__).parent / "data"


def merge_csv_files_with_dedup(
    input_folder: str = None, dedup_column: str = "title", verify_column: str = None
):
    """
    Merges CSV files and removes duplicate entries based on a column.

    Args:
        input_folder: Path to folder containing CSV files
        output_file: Name of the output merged CSV file
        dedup_column: Column name to check for duplicates
        verify_column: If given, a row is only treated as a duplicate when
            both dedup_column and verify_column match, so a repeated topic
            with different content in verify_column is kept.
    """
    if input_folder is None:
        input_folder = str(CACHE_DIR)

    file_pattern = os.path.join(input_folder, "topics_[0-9][0-9][0-9][0-9].csv")
    csv_files = glob.glob(file_pattern)

    if not csv_files:
        print(f"No files found matching 'topics_*.csv' in {input_folder}")
        return None

    # Read all files
    all_dfs = []
    for file in csv_files:
        try:
            df = pd.read_csv(file)
            all_dfs.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")
            continue

    if not all_dfs:
        return None

    # Concatenate
    merged_df = pd.concat(all_dfs, ignore_index=True)

    # Remove duplicates based on a column
    if dedup_column in merged_df.columns:
        subset = [dedup_column]
        if verify_column is not None:
            if verify_column in merged_df.columns:
                subset.append(verify_column)
            else:
                print(
                    f"Warning: Column '{verify_column}' not found. Ignoring verify_column."
                )

        original_len = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=subset, keep="first")
        removed = original_len - len(merged_df)
        print(f"Removed {removed} duplicate rows based on {subset}")
    else:
        print(
            f"Warning: Column '{dedup_column}' not found. No deduplication performed."
        )

    # Index by date
    merged_df = merged_df.sort_values(by="Datum").reset_index(drop=True)

    return merged_df


def clean_df(
    input_df: pd.DataFrame,
    column_to_check="Runde",
    standardize_rounds=True,
    standardize_motions=True,
) -> pd.DataFrame:
    """
    Removes known 'non-topic' columns from topic dataframe

    """
    if column_to_check not in input_df.columns:
        raise ValueError(f"Column '{column_to_check}' not found in DataFrame")

    with open(_DATA_DIR / "drop_round_values.json", "r", encoding="utf-8") as f:
        drop_round_vals = json.load(f)

    old_len = len(input_df)
    out_df = input_df[~input_df[column_to_check].isin(drop_round_vals)].copy()
    new_len = len(out_df)
    print(f"Removed {old_len-new_len} lines according to clean list.")

    # A handful of source rows store German umlauts in decomposed Unicode
    # form (base letter + combining diaeresis, e.g. "u" + U+0308, instead of
    # the precomposed "ü") -- invisible when printed, but it silently breaks
    # any literal-umlaut regex against those specific rows (both here in
    # standardize_df_motions/classify_motion_types and downstream). Normalize
    # to NFC once, up front, so every consumer can assume precomposed form.
    for col in ("Thema", "Factsheet"):
        if col in out_df.columns:
            out_df[col] = out_df[col].str.normalize("NFC")

    if standardize_rounds:
        with open(_DATA_DIR / "round_translations.json", "r", encoding="utf-8") as f:
            translate_dict = json.load(f)
        out_df = out_df.replace({column_to_check: translate_dict})
        print("Standardized round descriptors")
    if standardize_motions:
        out_df = standardize_df_motions(out_df)
        print("Standardized motion types")
    return out_df


def standardize_df_motions(input_df: pd.DataFrame) -> pd.DataFrame:
    """
    Uses the translations in data/motion_type_abbreviations.json to expand abbreviations denoting motion types
    """
    out_df = input_df.copy()

    with open(_DATA_DIR / "motion_type_abbreviations.json", "r", encoding="utf-8") as f:
        abbreviations_dict = json.load(f)

    for lang in ["GERMAN", "ENGLISH"]:
        mask = input_df["Sprache"] == lang
        out_df.loc[mask, "Thema"] = out_df.loc[mask, "Thema"].replace(
            abbreviations_dict[lang], regex=True
        )

    return out_df


def classify_motion_types(input_df: pd.DataFrame) -> pd.DataFrame:
    bp_filtering_patterns = [
        (r"Dieses Haus glaubt.*sollte", "Dieses Haus glaubt, X sollte..."),
        (r"Dieses Haus (?:würde|verbietet)", "Dieses Haus würde..."),
        (r"Würde dieses Haus", "Dieses Haus würde..."),
        (r"Dieses Haus,? als", "Dieses Haus als..."),
        (r"Dieses Haus glaubt", "Dieses Haus glaubt..."),
        (r"Dieses Haus bereut", "Dieses Haus bereut..."),
        (r"Dieses Haus (?:bedauert|verurteilt)", "Dieses Haus bedauert..."),
        (r"Dieses Haus lehnt.*ab", "Dieses Haus bedauert..."),
        (r"Dieses Haus hält.*für falsch", "Dieses Haus bedauert..."),
        (
            r"Dieses Haus (?:begrüßt|befürwortet|unterstützt|wünscht|möchte|feiert)",
            "Dieses haus begrüßt...",
        ),
        (r"Dieses Haus (?:bevorzugt|präferiert|zieht)", "Dieses Haus bevorzugt..."),
        (r"This house believes.*should", "Dieses Haus glaubt, X sollte..."),
        (r"This house would", "Dieses Haus würde..."),
        (r"This house,? as", "Dieses Haus als..."),
        (r"This house believes", "Dieses Haus glaubt..."),
        (r"This house opposes", "Dieses Haus bedauert..."),
        (r"This house regrets", "Dieses Haus bereut..."),
        (r"This house supports", "Dieses haus begrüßt..."),
        (r"This house prefers", "Dieses Haus bevorzugt..."),
        (r"This house hopen", "Dieses Haus hofft..."),
        (r"This house predicts", "Dieses Haus sagt vorraus..."),
    ]

    opd_filtering_patterns = [
        (
            r"\bist(?:\s+es)?\b.*\bzu\s+(?:bereuen|bedauern)\b",
            "Ist x zu bereuen/bedauern?",
        ),
        (r"\bim\s+interesse\b", "Ist x im Interesse von y?"),
        (r"\bhätten?\b.*\btun\s+sollen\b", "Hätte x y tun sollen?"),
        (r"\bsoll(?:en|test|te|ten)?\b", "Sollten wir/Sollte x...?"),
        (r"\bbrauchen\s+wir\b", "Brauchen wir..?"),
        (r"\bshould\b", "Sollten wir/Sollte x...?"),
        (
            r"\bverpflichtung\b|\bmoralisch richtig\b|\bmoralische\s+pflicht\b|\bmoralisch\s+gerechtfertigt\b",
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
        (
            r"\bbevorzug\w*\b|\bvorzuzieh\w*\b|\bvorzieh\w*\b|\bpräferier\w*\b",
            "Ist x zu bevorzugen?",
        ),
        (
            r"ist es besser",
            "Ist x zu bevorzugen?",
        ),
        (r"\b(?:wäre|ist)\b.*\b(?:gut|schlecht)\b", "Ist x gut/schlecht?"),
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


def build_topics_csv() -> pd.DataFrame:
    """
    Merges the per-year cache CSVs, cleans the result, and writes both
    `topics.csv` (the cleaned dataset the site is built from) and
    `topics_full.csv` (the merged-but-uncleaned cache) to disk.
    """
    merged_df = merge_csv_files_with_dedup(dedup_column="Thema", verify_column="Link")
    cleaned_df = clean_df(merged_df)
    cleaned_df = classify_motion_types(cleaned_df)
    print(f"Writing {len(cleaned_df)} topics to csv.")
    cleaned_df.to_csv(OUTPUT_DIR / "topics.csv", index=False)
    merged_df.to_csv(CACHE_DIR / "topics_full.csv", index=False)
    return cleaned_df


if __name__ == "__main__":
    build_topics_csv()
