import sys
print("Starting verification script...")

try:
    import os
    print("Imported os")
    from scanner import scan_directory, delete_file
    print("Imported scanner")

    # Setup test environment
    test_dir = "test_scan_area"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
        print(f"Created {test_dir}")

    # Create dummy files
    files_to_create = [
        "file1.txt",
        "file2.log",
        "file3.tmp",
        "important_doc.pdf",
        "backup_data.zip",
        "temp_image.png"
    ]

    for f in files_to_create:
        with open(os.path.join(test_dir, f), "w") as file:
            file.write("dummy content")
    
    print("Created test files.")

    # Test 1: Scan for .txt
    print("Running Test 1...")
    results = scan_directory(test_dir, ["txt"], [])
    print(f"Test 1 (.txt): Found {len(results)} files. Expected 1.")
    if len(results) == 1 and results[0]['name'] == 'file1.txt':
        print("PASS")
    else:
        print("FAIL")

    # Test 2: Scan for .log and .tmp
    print("Running Test 2...")
    results = scan_directory(test_dir, [".log", "tmp"], [])
    print(f"Test 2 (.log, .tmp): Found {len(results)} files. Expected 2.")
    names = sorted([r['name'] for r in results])
    if len(results) == 2 and names == ['file2.log', 'file3.tmp']:
        print("PASS")
    else:
        print("FAIL")

    # Test 3: Scan for keyword "backup"
    print("Running Test 3...")
    results = scan_directory(test_dir, [], ["backup"])
    print(f"Test 3 (keyword 'backup'): Found {len(results)} files. Expected 1.")
    if len(results) == 1 and results[0]['name'] == 'backup_data.zip':
        print("PASS")
    else:
        print("FAIL")

    # Test 4: Scan for .png AND keyword "temp"
    print("Running Test 4...")
    results = scan_directory(test_dir, ["png"], ["temp"])
    print(f"Test 4 (.png + 'temp'): Found {len(results)} files. Expected 1.")
    if len(results) == 1 and results[0]['name'] == 'temp_image.png':
        print("PASS")
    else:
        print("FAIL")

    # Cleanup
    print("Cleaning up...")
    for f in files_to_create:
        try:
            os.remove(os.path.join(test_dir, f))
        except:
            pass
    try:
        os.rmdir(test_dir)
    except:
        pass
    print("Cleanup complete.")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
