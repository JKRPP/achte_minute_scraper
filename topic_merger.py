import pandas as pd
import glob
import os


def merge_csv_files_with_dedup(
    input_folder: str = ".", dedup_column: str = "title", verify_column: str = None
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
    file_pattern = os.path.join(input_folder, "topics_*.csv")
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


def clean_df(input_df: pd.DataFrame, column_to_check="Runde") -> pd.DataFrame:
    """
    Removes known 'non-topic' columns from topic dataframe

    """
    if column_to_check not in input_df.columns:
        raise ValueError(f"Column '{column_to_check}' not found in DataFrame")

    drop_round_vals = [
        "ER",
        "EO",
        "SR",
        "SO",
        "OG",
        "OO",
        "CG",
        "CO",
        "AfD",
        "Berlin",
        "Chair",
        "Chefjuroren",
        "Dessi",
        "AF",
        "B",
        "C",
        "D",
        "Datum",
        "Dresden",
        "Erstens",
        "Factsheet",
        "Fazit",
        "FFR",
        "Format",
        "Foto",
        "Gewinner",
        "Göttingen",
        "Hamburg",
        "https",
        "Indes",
        "IO",
        "Iserlohn",
        "Jena",
        "Juoren",
        "Juroren",
        "Jurorenbreak",
        "Jury",
        "Karlsruhe",
        "Linke",
        "Magdeburg",
        "Mainz",
        "Mannheim",
        "Marburg",
        "Münster",
        "Nachher",
        "Nachteil",
        "Nachteile",
        "OPP",
        "Opp",
        "Opposition",
        "Oppostion",
        "P-D-OF",
        "Panel",
        "PDOF",
        "PDVF",
        "Potsdam",
        "Priester",
        "Präsident",
        "REG",
        "Reg",
        "Regierung",
        "Schulz",
        "SPD",
        "Taschenbuchausgabe",
        "Teambreak",
        "Teams",
        "Tübingen",
        "Vorher",
        "Vorteil",
        "Vorteile",
        "Wichtig",
        "Wien",
        "Zweitens",
        "A",
    ]

    old_len = len(input_df)
    out_df = input_df[~input_df[column_to_check].isin(drop_round_vals)].copy()
    new_len = len(out_df)
    print(f"Removed {old_len-new_len} lines according to clean list.")
    return out_df


if __name__ == "__main__":
    merged_df = merge_csv_files_with_dedup(dedup_column="Thema", verify_column="Link")
    cleaned_df = clean_df(merged_df)
    print(f"Writing {len(cleaned_df)} topics to csv.")
    cleaned_df.to_csv("topics.csv")
    merged_df.to_csv("topics_full.csv")
