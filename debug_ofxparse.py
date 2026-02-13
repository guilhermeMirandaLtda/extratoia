
import io
from ofxparse import OfxParser
import sys

def test_parse(file_path):
    print(f"Testing {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        ofx = OfxParser.parse(io.StringIO(content))
        print("Parsed successfully.")
        if ofx.account:
            print(f"Account: {ofx.account}")
            if ofx.account.statement:
                print(f"Transactions: {len(ofx.account.statement.transactions)}")
                for t in ofx.account.statement.transactions[:5]:
                    print(t)
            else:
                print("No statement.")
        else:
            print("No account.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_parse(sys.argv[1])
    else:
        test_parse(r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-06.ofx.normalized.ofx")
