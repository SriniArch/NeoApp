import re

def parse_symbol_parts(symbol: str):
    s = symbol.strip().upper()
    
    # Try 6-digit match first
    m = re.search(r'^([A-Z]+?)([0-9]{6})(\d+)(CE|PE)$', s)
    if m:
        base, expiry, strike, opt_type = m.groups()
        try:
            mm = int(expiry[2:4])
            dd = int(expiry[4:6])
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                return base, expiry, int(strike), opt_type
        except:
            pass

    # Try 5-character match (YYMMM)
    m = re.search(r'^([A-Z]+?)([0-9]{2}[A-Z]{3})(\d+)(CE|PE)$', s)
    if m:
        base, expiry, strike, opt_type = m.groups()
        return base, expiry, int(strike), opt_type

    # Try 5-digit match (YYMDD)
    m = re.search(r'^([A-Z]+?)([0-9]{5})(\d+)(CE|PE)$', s)
    if m:
        base, expiry, strike, opt_type = m.groups()
        return base, expiry, int(strike), opt_type
        
    return None

test_symbol = "NIFTY2630225300PE"
print(f"Testing {test_symbol}: {parse_symbol_parts(test_symbol)}")
