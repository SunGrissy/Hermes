# File Cleaner Tool Walkthrough

## Overview
A modern, native desktop application for scanning and cleaning up files based on extensions and keywords.

## Setup & Run
1.  Open Terminal / Command Prompt.
2.  Navigate to the project directory:
    ```bash
    cd d:\MyAgents\FileCleanerTool
    ```
3.  Install dependencies (if not already done):
    ```bash
    pip install -r requirements.txt
    ```
4.  Run the application:
    ```bash
    python gui.py
    ```

## How to Use
1.  **Browse**: Click "Browse" to select a target directory.
2.  **Configure**:
    *   **Extensions**: Enter file extensions to find (e.g., `.txt, .log, .tmp`). Leave empty to ignore extension filtering.
    *   **Keywords**: Enter filename keywords (e.g., `copy, old`).
3.  **Scan**: Click "Scan Files" to populate the list.
4.  **Select & Delete**: Check the boxes for files you want to remove, then click "Delete Selected".
