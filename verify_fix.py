
import sys
import os
import pandas as pd
from main import extrair_ofx
import logging

# Setup logging to see errors from main.py
logging.basicConfig(level=logging.DEBUG)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

files = [
    r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-06.ofx",
    r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-08.ofx"
]

for file_path in files:
    print(f"\n--- Testing {os.path.basename(file_path)} ---")
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        df = extrair_ofx(file_bytes)
        
        if not df.empty:
            print(f"Success! Extracted {len(df)} transactions.")
            print(df.head())
            
            # Check for any remaining asterisks in amounts
            asterisk_found = False
            for val in df["Valor"]:
                if "*" in str(val):
                    asterisk_found = True
                    print(f"WARNING: Asterisk found in value: {val}")
            
            if not asterisk_found:
                print("Verification Passed: No asterisks in values.")
        else:
            print("Warning: DataFrame is empty (might be expected for files without transactions).")
            
    except Exception as e:
        print(f"FAILED with error: {e}")
        import traceback
        traceback.print_exc()
