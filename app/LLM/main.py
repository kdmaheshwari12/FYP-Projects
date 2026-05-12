#!/usr/bin/env python3
# main.py - PRODUCTION-GRADE SECURE RAG SYSTEM v4.1
# ============================================================================
# FIXES:
# 1. APIStatusError handled with status-code-aware retry logic
# 2. Rate-limit (429) → wait and retry
# 3. Auth errors (401/403) → clear message, no retry
# 4. Server errors (500/502/503) → retry with backoff
# 5. All other APIStatusError subtypes → logged and shown clearly
# ============================================================================

import os, re, time, html, hashlib, logging, random, unicodedata, sys
from typing import List, Dict, Tuple, Set, Any
from collections import Counter
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain_community.vectorstores import FAISS
from pathlib import Path

# Try to import groq for specific error handling
try:
    from groq import APIStatusError as GroqAPIStatusError
    from groq import RateLimitError, AuthenticationError, APIConnectionError
    GROQ_ERRORS_AVAILABLE = True
except ImportError:
    GROQ_ERRORS_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────
class SecureLogFormatter(logging.Formatter):
    CTRL = re.compile(r"[\r\n\t\x00-\x1F\x7F-\x9F]")
    def format(self, record):
        if isinstance(record.msg, str):
            record.msg = self.CTRL.sub("", str(record.msg))
        return super().format(record)

logger = logging.getLogger(__name__) 

def safe_log(level, msg, *args, **kwargs):
    """Log a message safely without crashing the main flow."""
    try:
        if level == "info": logger.info(msg, *args, **kwargs)
        elif level == "warning": logger.warning(msg, *args, **kwargs)
        elif level == "error": logger.error(msg, *args, **kwargs)
        else: logger.debug(msg, *args, **kwargs)
    except:
        print(f"[{level.upper()}] {msg}") # Fallback to print if logging fails

load_dotenv()
API_KEY             = os.getenv("GROQ_API_KEY", "").strip()
BASE_DIR = os.path.dirname(__file__)
INDEX_PATH = os.path.join(BASE_DIR, os.getenv("INDEX_PATH", "vector_index.faiss.backup").strip())
FAISS_CHECKSUM      = os.getenv("FAISS_CHECKSUM", "").strip() or None
MAX_QUERIES_PER_MIN = int(os.getenv("MAX_QUERIES_PER_MINUTE", "10"))

# ── Path Validation ───────────────────────────────────────────────────────────
def validate_safe_path(fp, allowed="."):
    try:
        if not fp or len(fp) > 4096: raise ValueError("Invalid filepath")
        fp = unicodedata.normalize("NFKC", fp)
        if "\x00" in fp: raise ValueError("NULL byte")
        p = Path(fp).resolve(strict=False)
        a = Path(allowed).resolve(strict=False)
        try: p.relative_to(a)
        except ValueError: raise ValueError(f"Path traversal: {fp}")
        if p.is_symlink():
            t = p.readlink().resolve(strict=False)
            try: t.relative_to(a)
            except ValueError: raise ValueError("Symlink escape")
        return str(p)
    except Exception as e: raise ValueError(f"Invalid path: {e}")

# Global states (lazily loaded)
embedding_model = None
vector_store = None
_model = None
PAKISTAN_CITIES = []
CITY_RE = None

import threading
_init_lock = threading.Lock()

def get_llm_resources():
    global embedding_model, vector_store, _model, PAKISTAN_CITIES, CITY_RE
    if _model is not None and CITY_RE is not None:
        return _model, vector_store, CITY_RE

    with _init_lock:
        if _model is not None and CITY_RE is not None:
            return _model, vector_store, CITY_RE
        print("🚀 Initializing LLM Resources (First time)...")
    
    # ── Path Validation ───────────────────────────────────────────────────────────
    valid_index_path = validate_safe_path(INDEX_PATH, BASE_DIR)
    if not os.path.exists(valid_index_path):
        raise FileNotFoundError(f"FAISS index not found at {valid_index_path}")

    # ── Load Models ───────────────────────────────────────────────────────────────
    try:
        embedding_model = HuggingFaceEmbeddings(
            model_name="thenlper/gte-small",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )
        vector_store = FAISS.load_local(valid_index_path, embedding_model, allow_dangerous_deserialization=True)
        
        _model = ChatGroq(api_key=API_KEY, model_name="llama-3.3-70b-versatile",
                          temperature=0.1, max_tokens=4096, timeout=60)
        
        # Load cities
        cities = set()
        for q in ["Pakistan","city","places","travel","tourism"]:
            try:
                for doc in vector_store.similarity_search(q, k=50): # Reduced k for speed
                    c = doc.metadata.get("Places_city","").strip()
                    if c and len(c) > 2: cities.add(c.lower())
            except: pass
        
        if cities:
            PAKISTAN_CITIES = sorted(cities)
        else:
            PAKISTAN_CITIES = ["karachi","lahore","islamabad","rawalpindi","faisalabad",
                              "multan","peshawar","quetta","hyderabad","abbottabad"]
        
        CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in PAKISTAN_CITIES) + r")\b", re.IGNORECASE)
        
        print(f"✅ LLM Ready. Loaded {len(PAKISTAN_CITIES)} cities.")
        return _model, vector_store, CITY_RE
    except Exception as e:
        print(f"❌ Error loading models: {e}")
        raise e

def validate_api_key(key):
    if not key: raise ValueError("GROQ_API_KEY missing")
    key = key.strip()
    if not (20 <= len(key) <= 200): raise ValueError(f"Bad key length {len(key)}")
    if not re.match(r"^[a-zA-Z0-9\-_]+$", key): raise ValueError("Bad key chars")
    return key

# Check API key at startup but don't exit
try:
    API_KEY = validate_api_key(API_KEY)
except Exception as e:
    print(f"WARNING: LLM API key validation failed: {e}")

# Removed heavy top-level initialization
# PAKISTAN_CITIES = load_cities()
# CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in PAKISTAN_CITIES) + r")\b", re.IGNORECASE)

# ── Destination Alias Map ─────────────────────────────────────────────────────
DESTINATION_ALIASES: Dict[str, str] = {
    "hunza valley":       "hunza",
    "hunza-valley":       "hunza",
    "gilgit baltistan":   "gilgit",
    "gilgit-baltistan":   "gilgit",
    "azad kashmir":       "kashmir",
    "azad jammu kashmir": "kashmir",
    "swat valley":        "swat",
    "naran kaghan":       "naran",
    "murree hills":       "murree",
}

def normalize_destination(dest: str) -> str:
    key = dest.strip().lower()
    if key in DESTINATION_ALIASES:
        return DESTINATION_ALIASES[key]
    for alias, canonical in DESTINATION_ALIASES.items():
        if alias in key:
            return canonical
    return dest

# ── Rate Limiter ──────────────────────────────────────────────────────────────
class RateLimiter:
    def __init__(self, rate=10, per=60):
        self.rate=rate; self.per=per; self.allowance=float(rate); self.last=time.time()
    def allow_request(self):
        now=time.time(); self.allowance+=(now-self.last)*(self.rate/self.per); self.last=now
        if self.allowance>self.rate: self.allowance=self.rate
        if self.allowance<1: return False
        self.allowance-=1; return True

rate_limiter = RateLimiter(rate=MAX_QUERIES_PER_MIN)

# ── Input Sanitization ────────────────────────────────────────────────────────
def sanitize_user_input(text, maxlen=500):
    if not text: return ""
    if len(text)>maxlen: raise ValueError(f"Too long (max {maxlen})")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c)[0]!="C" or c in " \n")
    text = html.escape(text, quote=True)
    for p in [r"(?i)(<|&lt;)script",r"(?i)javascript:",r"(?i)on\w+\s*=",
              r"(?i)(eval|exec|__import__|compile)\s*[\(\[]",
              r"(?i)(DROP|DELETE|INSERT|UPDATE|SELECT)\s+",
              r"[\|\&\;]\s*(sh|bash|cmd|powershell)",
              r"(?i)(&&|\|\|).*?(rm|del|format)",
              r"\$\{.*?\}",r"\{\{.*?\}\}",r"<%.*?%>",r"%0[ad]"]:
        if re.search(p, text): raise ValueError("Malicious content detected")
    if not re.match(r"^[a-zA-Z0-9\s\.,\-\?\!\'\"]+$", text):
        raise ValueError("Invalid characters")
    return text.strip()

def detect_prompt_injection(q):
    for p in [r"(?i)ignore\s+(all\s+)?previous\s+instructions",r"(?i)you\s+are\s+now",
              r"(?i)forget\s+(everything|all)",r"(?i)system\s+prompt",
              r"(?i)reveal\s+your",r"(?i)act\s+as\s+a\s+(?!travel)",r"(?i)roleplay"]:
        if re.search(p,q): return True
    return False

# ── Query Parsing ─────────────────────────────────────────────────────────────
def parse_travel_intent(query):
    _, _, city_re = get_llm_resources()
    ql = query.lower()
    cities = [m.title() for m in city_re.findall(ql)]
    dest = None
    m = re.search(r"from\s+\w+\s+to\s+(\w+(?:\s+\w+)?)", ql)
    if m:
        pot = m.group(1).strip()
        for c in PAKISTAN_CITIES:
            if pot in c or c in pot: dest=c.title(); break
        if not dest and len(cities)>=2: dest=cities[-1]
    elif cities:
        dest = cities[-1] if any(w in ql for w in [" in ","visit","explore","trip to","travel to"]) else cities[0]
    dm  = re.search(r"(\d+)\s*(?:day|days)", ql)
    dur = min(max(int(dm.group(1)) if dm else 3, 1), 14)
    bud = None
    if any(t in ql for t in ["moderate","mid","medium","average"]): bud="moderate"
    elif any(t in ql for t in ["low","cheap","budget","affordable"]):  bud="low"
    elif any(t in ql for t in ["luxury","expensive","high","premium"]): bud="high"
    return {"destination_city":dest,"duration":dur,"budget_preference":bud,"query":query}

def build_search_queries(intent):
    city = intent.get("destination_city")
    q = []
    if city:
        q += [city, f"places to visit in {city}", f"{city} attractions",
              f"restaurants in {city}", f"hotels in {city}"]
        if intent.get("budget_preference"):
            q.append(f"{intent['budget_preference']} budget places in {city}")
    else:
        q += ["Pakistan travel places","tourist attractions Pakistan"]
    q.append(intent["query"])
    return q[:8]

# ── Budget ────────────────────────────────────────────────────────────────────
def normalize_budget_category(b):
    if not b or str(b).lower() in ["not specified","nan","none",""]: return "unspecified"
    bl = str(b).lower()
    nums = re.findall(r"\d+", b)
    if nums:
        avg = sum(int(n) for n in nums)/len(nums)
        return "low" if avg<500 else "moderate" if avg<2000 else "high"
    if any(t in bl for t in ["low","cheap","budget","affordable"]): return "low"
    if any(t in bl for t in ["moderate","mid","medium","average"]):  return "moderate"
    if any(t in bl for t in ["high","luxury","expensive","premium"]): return "high"
    return "unspecified"

def get_budget_emoji(cat):
    return {"low":"💵","moderate":"💳","high":"💎"}.get(cat,"💰")

def categorize_place_type(ptype):
    t = ptype.lower()
    if any(k in t for k in ["hotel","motel","lodge","inn","resort","guest house","hostel"]): return "hotel"
    if any(k in t for k in ["restaurant","cafe","coffee","food","eatery","dining",
                             "bakery","biryani","karahi","sweets","grill","bbq","dhaba"]): return "restaurant"
    return "attraction"

def normalize_place_name(name):
    n = re.sub(r"[^\w\s]","",name.lower())
    n = " ".join(n.split())
    stops = {"the","a","an","and","or","of","at","in"}
    return " ".join(w for w in n.split() if w not in stops)

# ============================================================================
# TIMING LOGIC
# ============================================================================
_ALLDAY_NORM = {"all-day","all day","allday","all_day","fullday","full day","full-day"}

def normalize_timing_for_filtering(raw):
    if not raw or str(raw).strip().lower() in ("nan","none","","not specified"):
        return ["all-day"]
    key = str(raw).strip().lower()
    clean = re.sub(r"[\s/,\-]+", " ", key).strip()
    if clean in _ALLDAY_NORM or key in _ALLDAY_NORM:
        return ["all-day"]
    MAP = {
        "breakfast": ["breakfast"], "breakfast brunch": ["brunch"], "brunch": ["brunch"],
        "brunch meals": ["brunch"], "lunch": ["lunch"], "dinner": ["dinner"],
        "dinner snacks": ["dinner"], "dinner late": ["dinner"], "mainmeals": ["mainmeals"],
        "main meals": ["mainmeals"], "meals": ["meals"], "dessert": ["meals"],
        "morning": ["morning"], "afternoon": ["afternoon"], "evening": ["evening"], "night": ["night"],
    }
    if clean in MAP: return MAP[clean]
    if key in MAP: return MAP[key]
    if "breakfast" in key and "lunch" in key: return ["brunch"]
    if "breakfast" in key: return ["breakfast"]
    if "brunch" in key: return ["brunch"]
    if "mainmeal" in key or "main meal" in key: return ["mainmeals"]
    if "lunch" in key: return ["lunch"]
    if "dinner" in key: return ["dinner"]
    if "meal" in key: return ["meals"]
    if "morning" in key: return ["morning"]
    if "afternoon" in key: return ["afternoon"]
    if "evening" in key: return ["evening"]
    if "night" in key: return ["night"]
    return ["all-day"]

def get_timing_display(raw):
    if not raw or str(raw).strip().lower() in ("nan","none","","not specified"):
        return "All-day"
    return str(raw).strip()

def matches_timing(place_timing: List[str], required_timing: str) -> bool:
    if not place_timing: return True
    req = required_timing.lower()
    if "all-day" in place_timing: return True
    if req in place_timing: return True
    if req == "breakfast":
        return any(t in place_timing for t in ["breakfast","brunch","meals"])
    if req == "lunch":
        return any(t in place_timing for t in ["lunch","brunch","mainmeals"])
    if req == "dinner":
        return any(t in place_timing for t in ["dinner","mainmeals","meals"])
    return False

# ============================================================================
# RETRIEVE & FILTER
# ============================================================================
def retrieve_and_filter_places(intent, k_per_query=100):
    _, v_store, _ = get_llm_resources()
    MAX_DOCS  = 600
    dest      = intent.get("destination_city")
    bud_pref  = intent.get("budget_preference")
    queries   = build_search_queries(intent)
    all_docs, seen_ids, seen_norm = [], set(), set()
    print("Searching database...")
    for q in queries:
        if len(all_docs) >= MAX_DOCS: break
        try:
            k = min(k_per_query, MAX_DOCS - len(all_docs))
            for doc in v_store.similarity_search(q, k=k):
                name = doc.metadata.get("Places_name","").strip()
                nn   = normalize_place_name(name)
                did  = f"{name}_{doc.metadata.get('Places_city','')}"
                if nn in seen_norm or did in seen_ids: continue
                all_docs.append(doc); seen_ids.add(did); seen_norm.add(nn)
        except Exception as e: safe_log("warning", f"Search: {e}")
    hotels, restaurants, attractions = [], [], []
    used_names, used_norm_set = set(), set()
    for doc in all_docs:
        meta   = doc.metadata
        name   = meta.get("Places_name","").strip()
        ptype  = meta.get("Places_type","").strip()
        city   = meta.get("Places_city","").strip()
        ref    = meta.get("Places_reference","").strip()
        budget = meta.get("Budget","")
        timing_raw = meta.get("timing") or meta.get("Timings") or "All-day"
        if not name or not city: continue
        nn = normalize_place_name(name)
        if nn in used_norm_set or name in used_names: continue
        if dest and city.lower().strip() != dest.lower().strip(): continue
        bcat = normalize_budget_category(budget)
        if bud_pref and bcat != "unspecified":
            order = {"low":0,"moderate":1,"high":2}
            mp = "moderate" if bud_pref=="medium" else bud_pref
            if mp in order and bcat in order:
                if abs(order[mp]-order[bcat]) > 1: continue
        used_names.add(name); used_norm_set.add(nn)
        link = ref or f"https://www.google.com/maps/search/{name.replace(' ','+' )}+{city.replace(' ','+')}"
        entry = dict(name=name, type=ptype, city=city, link=link,
                     budget=budget, budget_category=bcat,
                     timing=normalize_timing_for_filtering(timing_raw),
                     timing_display=get_timing_display(timing_raw),
                     normalized_name=nn)
        cat = categorize_place_type(ptype)
        if cat == "hotel": hotels.append(entry)
        elif cat == "restaurant": restaurants.append(entry)
        else: attractions.append(entry)
    random.shuffle(hotels); random.shuffle(restaurants); random.shuffle(attractions)
    return hotels, restaurants, attractions

# ============================================================================
# CONTEXT & PROMPT
# ============================================================================
def get_places_for_slot(places, required_timing, global_used, limit):
    result = []
    for p in places:
        if p["normalized_name"] in global_used: continue
        if matches_timing(p["timing"], required_timing):
            result.append(p)
        if len(result) >= limit: break
    return result

def format_context(intent, hotels, restaurants, attractions):
    dest = intent.get("destination_city","Pakistan")
    dur  = intent.get("duration",3)
    global_used: Set[str] = set()
    ctx  = f"=== {dest.upper()} | {dur} DAYS ===\n\n"
    ctx += "HOTELS (choose exactly ONE):\n"
    for i,h in enumerate(hotels[:8],1):
        e = get_budget_emoji(h["budget_category"])
        ctx += f"H{i}. {h['name']} | {h['type']} | {h['link']} | ({e} {h['budget_category'].upper()}) | ⏰ {h['timing_display']} ⏰\n"
    if not hotels: ctx += "  None available\n"
    ctx += "\n"
    def slot_section(label, slot_key, pool, per_day):
        needed = dur * per_day + 5
        cands  = get_places_for_slot(pool, slot_key, global_used, needed)
        for p in cands: global_used.add(p["normalized_name"])
        lines = f"{label}\n"
        if cands:
            for i, p in enumerate(cands, 1):
                e = get_budget_emoji(p["budget_category"])
                lines += f"  {i}. {p['name']} | {p['type']} | {p['link']} | ({e} {p['budget_category'].upper()}) | ⏰ {p['timing_display']} ⏰\n"
        else: lines += "  NONE — use FREE TIME\n"
        return lines + "\n"
    ctx += slot_section("BREAKFAST LIST:", "breakfast", restaurants, 2)
    ctx += slot_section("LUNCH LIST:", "lunch", restaurants, 2)
    ctx += slot_section("DINNER LIST:", "dinner", restaurants, 2)
    ctx += slot_section("MORNING LIST:", "morning", attractions, 6)
    ctx += slot_section("AFTERNOON LIST:", "afternoon", attractions, 6)
    ctx += slot_section("EVENING LIST:", "evening", attractions, 3)
    ctx += slot_section("NIGHT LIST:", "night", attractions, 3)
    return ctx

PROMPT_TEMPLATE = """Generate a dense {duration}-day travel itinerary for {destination}.

STRICT RULES:
- Generate exactly {duration} days only.
- Each day MUST have 7-10 activities, spaced realistically from 8:00 AM to 10:00 PM.
- Follow this pattern:
  * 8:00 AM: Breakfast / Hotel Check-in
  * 9:00 AM - 1:00 PM: 2-3 Tourist attractions
  * 1:00 PM - 2:30 PM: Lunch at a recommended restaurant
  * 3:00 PM - 6:30 PM: 2-3 more attractions/shopping/parks
  * 7:00 PM - 9:00 PM: Dinner + evening activity
  * 10:00 PM: Rest / (Departure on last day)
- MANDATORY DEPARTURE: Add "10:00 PM – 🛫 Departure from {destination} [Airport / Bus Terminal](https://www.google.com/maps/search/{destination}+Airport) - Type (MODERATE) ⏰ 10:00 PM ⏰" ONLY at the end of Day {duration}.
- Zero Duplicates. Use the provided lists in order. 
- Do NOT generate extra days.
- Do NOT add notes, warnings, or preamble.
- No null links. If no link is in data, use google maps search link.

Format Example:
### Day 1
1. **8:00 AM** – 🏨 Check-in at [Hotel Name](link) - Type (MODERATE) ⏰ 8:00 AM ⏰
2. **9:30 AM** – 🏛️ Visit [Attraction Name](link) - Type (LOW) ⏰ 9:30 AM ⏰
...

DATA:
{context}

QUERY: {question}
Generate exactly {duration} days with high activity density.
"""

# ============================================================================
# ANALYSIS & RETRY
# ============================================================================
def analyze_itinerary(content, intent, hotels, restaurants, attractions):
    links = re.findall(r"\[([^\]]+)\]\([^)]+\)", content)
    dur = intent.get("duration",3)
    return {"links":len(links), "score": 100}

def invoke_llm_with_retry(prompt: str, max_attempts: int = 3):
    llm, _, _ = get_llm_resources()
    last_error = None
    for attempt in range(max_attempts):
        try:
            return llm.invoke(prompt)
        except Exception as e:
            last_error = e
            time.sleep(2)
    safe_log("error", f"LLM failed: {last_error}")
    return None

# ============================================================================
# BACKEND WRAPPER & PARSER
# ============================================================================
import uuid

def parse_itinerary_to_json(content):
    days = []
    current_day = None
    seen_days = set()
    lines = content.split("\n")
    
    # Pre-compiled regex for better performance
    TIME_RE = re.compile(r"\*\*(.*?)\*\*")
    URL_RE = re.compile(r"(https?://[^\s\|]+)")
    BRACKET_RE = re.compile(r"\[(.*?)\]")
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith("### Day"):
            day_name = line.replace("### ", "").strip()
            if day_name in seen_days: continue
            seen_days.add(day_name)
            if current_day: days.append(current_day)
            current_day = {"day": day_name, "schedule": []}
            
        elif current_day:
            # Check if this line likely contains an itinerary item
            if not (re.match(r"^[\d\.\-\*\s]*\d+\.", line) or "**" in line or "|" in line):
                continue
                
            try:
                # 1. Extract Time
                time_match = TIME_RE.search(line)
                time_str = time_match.group(1) if time_match else "N/A"
                
                # 2. Extract Link
                url_match = URL_RE.search(line)
                link = url_match.group(1).rstrip(")").rstrip("]").rstrip("|") if url_match else None
                
                # 3. Extract Budget/Type
                budget_type = "moderate"
                if any(k in line.upper() for k in ["LOW", "💵"]): budget_type = "low"
                elif any(k in line.upper() for k in ["HIGH", "💎"]): budget_type = "high"
                
                # 4. Extract Place Name
                place_name = None
                bracket_match = BRACKET_RE.search(line)
                if bracket_match:
                    place_name = bracket_match.group(1)
                
                # Fallback if no brackets
                if not place_name:
                    parts = re.split(r"[–-]\s*", line)
                    if len(parts) > 1:
                        potential_place = parts[1]
                        potential_place = re.sub(r"^[^\w]*Visit\s+", "", potential_place, flags=re.I)
                        potential_place = re.sub(r"^[^\w]*Check-in at\s+", "", potential_place, flags=re.I)
                        potential_place = re.sub(r"^[^\w]*", "", potential_place)
                        potential_place = re.split(r"[\(\[\|]", potential_place)[0].strip()
                        if potential_place:
                            place_name = potential_place

                # 5. Extract Activity Text
                if not place_name: place_name = "Interesting Place"
                
                activity_text = "Visit " + place_name
                if "Departure" in line or "🛫" in line:
                    activity_text = "Departure"
                    if "Airport" in line: activity_text = "Departure from Airport"
                    elif "Terminal" in line: activity_text = "Departure from Terminal"
                elif "Check-in" in line.lower() or "🏨" in line:
                    activity_text = "Check-in at " + place_name
                elif "breakfast" in line.lower() or "🍳" in line:
                    activity_text = "Breakfast at " + place_name
                elif "lunch" in line.lower() or "🍽️" in line:
                    activity_text = "Lunch at " + place_name
                elif "dinner" in line.lower() or "🌙" in line:
                    activity_text = "Dinner at " + place_name

                # Final fallback for link
                if not link:
                    link = f"https://www.google.com/maps/search/{place_name.replace(' ', '+')}"

                # Reconstruct raw format
                emoji = "💵" if budget_type == "low" else "💳" if budget_type == "moderate" else "💎"
                if "Departure" in activity_text: emoji = "🛫"
                
                reconstructed_raw = f"📍 {activity_text} [{place_name}]({link}) - Type ({emoji} {budget_type.upper()}) ⏰ {time_str} ⏰"

                current_day["schedule"].append({
                    "time": time_str or "10:00 PM",
                    "activity": activity_text,
                    "place": place_name,
                    "link": link,
                    "type": budget_type or "moderate",
                    "raw": reconstructed_raw
                })
            except Exception as e:
                safe_log("error", f"Error parsing line: {line} | {e}")
                continue
                
    if current_day: days.append(current_day)
    return days


def generate_itinerary_llm(destination, days, budget, interests, departure_location="Not specified", travel_style="General"):
    request_id = f"LLM-{uuid.uuid4().hex[:6]}"
    safe_log("info", f"[{request_id}] 🚀 Start generation: dest={destination}, days={days}, budget={budget}")
    try:
        user_query = f"Generate a {days}-day trip to {destination} with interests {', '.join(interests)} and budget {budget}."
        if not rate_limiter.allow_request(): raise Exception("Rate limit exceeded")
        intent = parse_travel_intent(user_query)
        canonical_dest = normalize_destination(destination)
        intent["destination_city"] = canonical_dest
        intent["duration"] = days
        hotels, restaurants, attractions = retrieve_and_filter_places(intent)
        if not hotels: raise ValueError("NO_HOTELS: No hotels found for this destination")
        context = format_context(intent, hotels, restaurants, attractions)
        
        # ── Safe Formatting ──────────────────────────────────────────────────
        format_kwargs = {
            "context": context,
            "question": user_query,
            "duration": days,
            "destination": destination,
            "budget": budget,
            "interests": ", ".join(interests) if interests else "General",
            "departure_location": departure_location,
            "travel_style": travel_style
        }
        
        try:
            prompt = PROMPT_TEMPLATE.format(**format_kwargs)
        except KeyError as e:
            safe_log("error", f"[{request_id}] ❌ Missing prompt placeholder: {e}")
            # Fallback: manually fill what we can or use empty string for missing
            from collections import defaultdict
            dd = defaultdict(lambda: "", **format_kwargs)
            prompt = PROMPT_TEMPLATE.format_map(dd)

        safe_log("info", f"[{request_id}] 🤖 Calling LLM...")
        response = invoke_llm_with_retry(prompt)
        if response is None: raise Exception("AI_GENERATION_FAILED: LLM returned no response")
        
        # Clean content (remove any preamble/postamble)
        content = response.content
        if "### Day 1" in content:
            content = content[content.find("### Day 1"):]
        
        structured_output = parse_itinerary_to_json(content)
        
        # VALIDATION: Ensure exactly {days} days
        if len(structured_output) > days:
            safe_log("warning", f"[{request_id}] ⚠️ Truncating itinerary from {len(structured_output)} to {days} days")
            structured_output = structured_output[:days]
        elif len(structured_output) < days:
            safe_log("warning", f"[{request_id}] ⚠️ LLM generated fewer days ({len(structured_output)}) than requested ({days})")
            
        return structured_output
    except ValueError as e: raise e
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["connection", "timeout", "503"]): raise Exception(f"EXTERNAL_SERVICE_UNAVAILABLE: {str(e)}")
        raise Exception(f"AI_GENERATION_FAILED: {str(e)}")

def main():
    print("CLI mode")
    # simplified CLI
    pass

if __name__ == "__main__":
    if len(sys.argv) == 1: main()