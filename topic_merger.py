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
    input_df: pd.DataFrame, column_to_check="Runde", standardize_rounds=True
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
    if standardize_rounds:
        with open(_DATA_DIR / "round_translations.json", "r", encoding="utf-8") as f:
            translate_dict = json.load(f)
        out_df = out_df.replace({column_to_check: translate_dict})
        print("Standardized round descriptors")
    return out_df


def build_topics_csv() -> pd.DataFrame:
    """
    Merges the per-year cache CSVs, cleans the result, and writes both
    `topics.csv` (the cleaned dataset the site is built from) and
    `topics_full.csv` (the merged-but-uncleaned cache) to disk.
    """
    merged_df = merge_csv_files_with_dedup(dedup_column="Thema", verify_column="Link")
    cleaned_df = clean_df(merged_df)
    print(f"Writing {len(cleaned_df)} topics to csv.")
    cleaned_df.to_csv(OUTPUT_DIR / "topics.csv", index=False)
    merged_df.to_csv(CACHE_DIR / "topics_full.csv", index=False)
    return cleaned_df


if __name__ == "__main__":
    build_topics_csv()
