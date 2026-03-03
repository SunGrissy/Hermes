import sys
import os

print("--- DEBUG START ---")
print(f"Python Executable: {sys.executable}")
print(f"Version: {sys.version}")

try:
    print("Attempting to import tkinter...")
    import tkinter
    print("Success: tkinter imported.")
except Exception as e:
    print(f"ERROR: tkinter import failed: {e}")

try:
    print("Attempting to import customtkinter...")
    import customtkinter
    print("Success: customtkinter imported.")
except Exception as e:
    print(f"ERROR: customtkinter import failed: {e}")

input("Press Enter to exit...")
