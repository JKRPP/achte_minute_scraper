"""Merges, cleans and deduplicates the per-year topic csvs into topics.csv."""

import glob
import json
import os
from pathlib import Path

import pandas as pd

from motion_classifier import classify_motion_types
from paths import CACHE_DIR, OUTPUT_DIR

_DATA_DIR = Path(__file__).parent / "data"


def merge_csv_files(input_folder: str = None):
    """Merges the per-year topic csvs in a folder into one DataFrame sorted by date."""
    if input_folder is None:
        input_folder = str(CACHE_DIR)

    file_pattern = os.path.join(input_folder, "topics_[0-9][0-9][0-9][0-9].csv")
    csv_files = glob.glob(file_pattern)

    if not csv_files:
        print(f"No files found matching 'topics_*.csv' in {input_folder}")
        return None

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

    merged_df = pd.concat(all_dfs, ignore_index=True)

    return merged_df.sort_values(by="Datum").reset_index(drop=True)


def deduplicate_topics(
    input_df: pd.DataFrame, topic_column: str = "Thema", date_column: str = "Datum"
) -> pd.DataFrame:
    """Drops topics already seen in the same year; row order decides which occurrence is kept."""
    for col in (topic_column, date_column):
        if col not in input_df.columns:
            print(f"Warning: Column '{col}' not found. No deduplication performed.")
            return input_df

    years = pd.to_datetime(input_df[date_column], errors="coerce").dt.year
    is_duplicate = pd.DataFrame(
        {"topic": input_df[topic_column], "year": years}
    ).duplicated(keep="first")
    print(f"Removed {is_duplicate.sum()} duplicate topics (same topic, same year)")
    return input_df[~is_duplicate].reset_index(drop=True)


def clean_df(
    input_df: pd.DataFrame,
    column_to_check="Runde",
    standardize_rounds=True,
    standardize_motions=True,
) -> pd.DataFrame:
    """Drops non-topic rows and normalizes umlauts, round names and motion abbreviations."""
    if column_to_check not in input_df.columns:
        raise ValueError(f"Column '{column_to_check}' not found in DataFrame")

    with open(_DATA_DIR / "drop_round_values.json", "r", encoding="utf-8") as f:
        drop_round_vals = json.load(f)

    old_len = len(input_df)
    out_df = input_df[~input_df[column_to_check].isin(drop_round_vals)].copy()
    new_len = len(out_df)
    print(f"Removed {old_len-new_len} lines according to clean list.")

    # NFC so composed and decomposed umlauts compare equal
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
    """Expands motion type abbreviations (e.g. "DHW") using data/motion_type_abbreviations.json."""
    out_df = input_df.copy()

    with open(_DATA_DIR / "motion_type_abbreviations.json", "r", encoding="utf-8") as f:
        abbreviations_dict = json.load(f)

    for lang in ["GERMAN", "ENGLISH"]:
        mask = input_df["Sprache"] == lang
        out_df.loc[mask, "Thema"] = out_df.loc[mask, "Thema"].replace(
            abbreviations_dict[lang], regex=True
        )

    return out_df


def build_topics_csv(include_old_ddm=True, include_old_list=True) -> pd.DataFrame:
    """Builds topics.csv from the cached per-year csvs and the old topic lists."""
    merged_df = merge_csv_files()
    cleaned_df = clean_df(merged_df)
    cleaned_df = classify_motion_types(cleaned_df)
    if include_old_ddm:
        old_ddm_path = os.path.join(_DATA_DIR, "old_ddm_topics.json")
        old_ddm_df = pd.read_json(old_ddm_path)
        cleaned_df = pd.concat([cleaned_df, old_ddm_df], ignore_index=True)
        cleaned_df = cleaned_df.sort_values(by="Datum").reset_index(drop=True)
        print(f"Appended {len(old_ddm_df)} old DDM topics!")
    if include_old_list:
        old_topic_path = os.path.join(_DATA_DIR, "old_topics.json")
        old_df = pd.read_json(old_topic_path)
        cleaned_df = pd.concat([cleaned_df, old_df], ignore_index=True)
        cleaned_df = cleaned_df.sort_values(by="Datum").reset_index(drop=True)
        print(f"Appended {len(old_df)} topics!")
    cleaned_df = deduplicate_topics(cleaned_df)
    cleaned_df = cleaned_df.sort_values(by="Datum").reset_index(drop=True)
    print(f"Writing {len(cleaned_df)} topics to csv.")
    cleaned_df.to_csv(OUTPUT_DIR / "topics.csv", index=False)
    return cleaned_df


if __name__ == "__main__":
    build_topics_csv()
