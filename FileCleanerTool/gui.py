import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from scanner import scan_directory, delete_file
import threading

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class FileCleanerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("File Cleaner Tool")
        self.geometry("900x700")
        
        # Grid layout configuration
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.create_widgets()
        self.found_files = [] # Stores file data
        self.checkboxes = [] # Stores checkbox widgets

    def create_widgets(self):
        # --- Header ---
        self.header_label = ctk.CTkLabel(self, text="File Cleaner Pro", font=ctk.CTkFont(size=24, weight="bold"))
        self.header_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="w")

        # --- Configuration Area (Frame) ---
        self.config_frame = ctk.CTkFrame(self)
        self.config_frame.grid(row=1, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.config_frame.grid_columnconfigure(1, weight=1)

        # Directory Selection
        self.dir_label = ctk.CTkLabel(self.config_frame, text="Directory:")
        self.dir_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.dir_entry = ctk.CTkEntry(self.config_frame, placeholder_text="Path to scan...")
        self.dir_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        self.browse_btn = ctk.CTkButton(self.config_frame, text="Browse", width=100, command=self.browse_directory)
        self.browse_btn.grid(row=0, column=2, padx=10, pady=10)

        # Extensions
        self.ext_label = ctk.CTkLabel(self.config_frame, text="Extensions:")
        self.ext_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        
        self.ext_entry = ctk.CTkEntry(self.config_frame, placeholder_text="e.g. .txt .log .tmp (space, comma, or | separated)")
        self.ext_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        # Keywords
        self.key_label = ctk.CTkLabel(self.config_frame, text="Keywords:")
        self.key_label.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        
        self.key_entry = ctk.CTkEntry(self.config_frame, placeholder_text="e.g. backup copy temp (space, comma, or | separated)")
        self.key_entry.grid(row=2, column=1, padx=10, pady=10, sticky="ew")

        # Scan Button
        self.scan_btn = ctk.CTkButton(self.config_frame, text="Scan Files", command=self.start_scan, fg_color="#2CC985", hover_color="#229965")
        self.scan_btn.grid(row=2, column=2, padx=10, pady=10)

        # --- Results Area ---
        self.results_frame = ctk.CTkScrollableFrame(self, label_text="Scan Results")
        self.results_frame.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="nsew")

        # --- Action Footer ---
        self.footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.footer_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=20, sticky="ew")

        self.status_label = ctk.CTkLabel(self.footer_frame, text="Ready", text_color="gray")
        self.status_label.pack(side="left")

        self.delete_btn = ctk.CTkButton(self.footer_frame, text="Delete Selected", state="disabled", fg_color="#FF4747", hover_color="#BB3333", command=self.confirm_delete)
        self.delete_btn.pack(side="right")
        
        self.select_all_btn = ctk.CTkButton(self.footer_frame, text="Select All", width=100, command=self.select_all)
        self.select_all_btn.pack(side="right", padx=10)

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, directory)

    def start_scan(self):
        directory = self.dir_entry.get()
        extensions_str = self.ext_entry.get()
        keywords_str = self.key_entry.get()

        if not directory:
            messagebox.showerror("Error", "Please select a directory first.")
            return

        # Pass raw strings to scanner, it handles robust parsing (comma, space, pipe)
        extensions = extensions_str
        keywords = keywords_str

        self.status_label.configure(text="Scanning...", text_color="yellow")
        self.scan_btn.configure(state="disabled")
        
        # Run scan in thread to keep GUI responsive
        threading.Thread(target=self.run_scan_thread, args=(directory, extensions, keywords)).start()

    def run_scan_thread(self, directory, extensions, keywords):
        results = scan_directory(directory, extensions, keywords)
        self.after(0, self.display_results, results)

    def display_results(self, results):
        self.found_files = results
        
        # Clear previous results
        for item in self.checkboxes:
            item["widget"].destroy()
        self.checkboxes = []

        if not results:
            self.status_label.configure(text="No files found matching criteria.", text_color="white")
            self.delete_btn.configure(state="disabled")
            self.scan_btn.configure(state="normal")
            return

        for idx, file_data in enumerate(results):
            var = ctk.IntVar(value=0)
            text = f"{file_data['name']}  ({file_data['size_str']}) - {file_data['path']}"
            cb = ctk.CTkCheckBox(self.results_frame, text=text, variable=var, command=self.update_select_all_btn)
            cb.grid(row=idx, column=0, sticky="w", padx=10, pady=2)
            self.checkboxes.append({"widget": cb, "var": var, "path": file_data['path']})

        self.status_label.configure(text=f"Found {len(results)} files.", text_color="white")
        self.delete_btn.configure(state="normal")
        self.scan_btn.configure(state="normal")
        self.select_all_btn.configure(text="Select All")


    def select_all(self):
        if not self.checkboxes:
            return
            
        current_text = self.select_all_btn.cget("text")
        target_val = 1 if current_text == "Select All" else 0
        
        for item in self.checkboxes:
            item["var"].set(target_val)
            
        self.update_select_all_btn()

    def update_select_all_btn(self):
        if not self.checkboxes:
            self.select_all_btn.configure(text="Select All")
            return
            
        all_selected = all(item["var"].get() == 1 for item in self.checkboxes)
        new_text = "Unselect All" if all_selected else "Select All"
        self.select_all_btn.configure(text=new_text)


    def confirm_delete(self):
        to_delete = [item["path"] for item in self.checkboxes if item["var"].get() == 1]
        
        if not to_delete:
            messagebox.showinfo("Info", "No files selected.")
            return

        confirm = messagebox.askyesno("Confirm Delete", f"Are you sure you want to PERMANENTLY delete {len(to_delete)} files?")
        
        if confirm:
            deleted_count = 0
            for file_path in to_delete:
                if delete_file(file_path):
                    deleted_count += 1
            
            messagebox.showinfo("Success", f"Deleted {deleted_count} files.")
            # Refresh scan
            self.start_scan()

if __name__ == "__main__":
    try:
        app = FileCleanerApp()
        app.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

