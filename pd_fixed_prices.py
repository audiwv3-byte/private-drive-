"""Explicit owner-approved direct-route tariffs; extra stops use normal route pricing."""
import re,unicodedata

def city(address):
    value=''.join(c for c in unicodedata.normalize('NFKD',str(address).casefold()) if not unicodedata.combining(c))
    names={'vilnius':r'\b(?:vilnius|вильнюс|wilno)\b','kaunas':r'\b(?:kaunas|каунас|kowno)\b'}
    matches=[key for key,pattern in names.items() if re.search(pattern,value)]
    return matches[0] if len(matches)==1 else None

def base(data):
    if data.get('stop_address'):return None
    start,end=city(data.get('origin','')),city(data.get('destination',''))
    if start=='vilnius' and end=='kaunas':return '190.00' if data.get('roundtrip') else '130.00'
    return None
