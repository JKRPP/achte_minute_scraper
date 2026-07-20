import pandas as pd
import glob
import os

def merge_csv_files_with_dedup(input_folder: str = ".", 
                              dedup_column: str = "title"):
    """
    Merges CSV files and removes duplicate entries based on a column.
    
    Args:
        input_folder: Path to folder containing CSV files
        output_file: Name of the output merged CSV file
        dedup_column: Column name to check for duplicates
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
        original_len = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=[dedup_column], keep='first')
        removed = original_len - len(merged_df)
        print(f"Removed {removed} duplicate rows based on '{dedup_column}'")
    else:
        print(f"Warning: Column '{dedup_column}' not found. No deduplication performed.")
    
    # Index by date
    merged_df = merged_df.sort_values(by="Datum").reset_index(drop=True)

    return merged_df

if __name__ == "__main__":
    merged_df = merge_csv_files_with_dedup(dedup_column="Thema")
    merged_df.to_csv("topics.csv")