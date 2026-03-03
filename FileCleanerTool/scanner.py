import os
import re
from typing import List, Dict, Union

def scan_directory(directory: str, extensions: Union[str, List[str]], keywords: Union[str, List[str]]) -> List[Dict]:
    """
    Scans a directory for files matching extensions and keywords.
    
    Args:
        directory: Root directory to scan.
        extensions: List or string of extensions to include.
        keywords: List or string of keywords to search for (OR relationship).
        
    Returns:
        List of dictionaries containing file details.
    """
    found_files = []
    
    # Robust parsing: handle strings with multiple separators or pre-split lists
    def parse_input(inp):
        if isinstance(inp, str):
            # Split by comma, pipe, or space
            return [x.strip() for x in re.split(r'[,|\s]+', inp) if x.strip()]
        return [str(x).strip() for x in inp if str(x).strip()]

    ext_list = parse_input(extensions)
    key_list = parse_input(keywords)

    # Normalize extensions to lowercase and ensure they start with dot
    exts = ['.' + e.lower().lstrip('.') for e in ext_list]
    keys = [k.lower() for k in key_list]
    
    if not os.path.exists(directory):
        return []


    for root, _, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            
            # Check extension
            match_ext = False
            if not exts: # If no extensions provided, assume all logic or check keywords? 
                # Usually if no filter provided, we might want to match nothing or everything.
                # Let's assume if both filters are empty, we return nothing to be safe?
                # Or if extension is empty, we don't filter by extension.
                match_ext = True
            else:
                for ext in exts:
                    if file_lower.endswith(ext):
                        match_ext = True
                        break
            
            # Check keywords
            match_key = False
            if not keys:
                match_key = True
            else:
                for key in keys:
                    if key in file_lower:
                        match_key = True
                        break
            
            # Logic: If user provides ONLY extensions, match extensions.
            # If user provides ONLY keywords, match keywords.
            # If user provides BOTH, should it be AND or OR?
            # Typically "filter by these rules" implies AND for strictness, or OR for "find garbage".
            # The prompt said "screening files... select directory, file type, keywords".
            # Let's go with AND if both are present, but if one is missing, ignore that filter.
            # Wait, if I supply ".txt" and "temp", I probably want .txt files containing "temp". AND makes sense.
            
            if not exts and not keys:
                # If no filters, assume user wants to list ALL files in the directory
                pass

            if match_ext and match_key:
                full_path = os.path.join(root, file)
                try:
                    size = os.path.getsize(full_path)
                    found_files.append({
                        "name": file,
                        "path": full_path,
                        "size": size,
                        "size_str": format_size(size)
                    })
                except OSError:
                    # Skip files we can't access
                    continue
                    
    return found_files

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def delete_file(file_path: str) -> bool:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception as e:
        print(f"Error deleting {file_path}: {e}")
    return False
