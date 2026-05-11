"""
PDF Ontology Extractor — Extracts tool/part names from Technical Manuals
========================================================================
Uses Gemini API to analyze PDF content and extract:
- Tool names (screwdrivers, wrenches, pliers, etc.)
- Part names (screws, connectors, batteries, etc.)
- Action verbs used in the manual

Output: tech_glossary.json — a structured glossary for AI annotation
Priority: 2 (below Discord Golden Rules, above Domain rules)

Usage:
  python pdf_ontology_extractor.py path/to/manual.pdf
  python pdf_ontology_extractor.py path/to/folder/  # Batch mode
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import google.generativeai as genai
except ImportError:
    print("[extractor] FATAL: pip install google-generativeai")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
GLOSSARY_FILE = PROJECT_ROOT / "prompts" / "tech_glossary.json"

# Configure Gemini
API_KEY = os.getenv("GEMINI_API_KEY", "")
if not API_KEY:
    API_KEY = os.getenv("GEMINI_API_KEY_FALLBACK", "")

genai.configure(api_key=API_KEY)

EXTRACTION_PROMPT = """You are a Technical Ontology Extractor. Your job is to read a technical manual 
or instruction document and extract ALL tool names, part names, and action verbs mentioned.

RULES:
1. Extract ONLY concrete, physical objects (not abstract concepts).
2. Normalize names: "Phillips head screwdriver" → "Phillips screwdriver"
3. Include both specific and general terms:
   - Specific: "Phillips screwdriver", "Torx T5 bit", "spudger"
   - General: "screwdriver", "bit", "tool"
4. For action verbs: extract ONLY physical manipulation verbs (not "understand", "note", etc.)
5. Group by category: tools, parts, materials, containers, surfaces.

OUTPUT FORMAT (JSON only, no markdown):
{
  "domain": "detected domain (e.g., phone repair, automotive, cooking)",
  "source": "filename",
  "tools": [
    {"name": "Phillips screwdriver", "aliases": ["crosshead screwdriver"], "category": "screwdriver"},
    {"name": "spudger", "aliases": ["pry tool"], "category": "pry tool"}
  ],
  "parts": [
    {"name": "battery", "aliases": ["cell", "rechargeable cell"], "category": "power"},
    {"name": "display assembly", "aliases": ["screen", "LCD"], "category": "display"}
  ],
  "materials": [
    {"name": "adhesive strip", "aliases": ["tape", "pull tab"], "category": "adhesive"}
  ],
  "action_verbs": [
    {"verb": "loosen", "context": "turning screws counterclockwise"},
    {"verb": "pry", "context": "separating components with spudger"}
  ]
}

Analyze the following document and extract the ontology:
"""


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using basic methods."""
    text = ""
    try:
        # Try PyPDF2 first
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    except ImportError:
        try:
            # Try pdfminer
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = pdfminer_extract(str(pdf_path))
        except ImportError:
            print("[extractor] WARNING: No PDF library found. pip install PyPDF2 or pdfminer.six")
            print("[extractor] Falling back to Gemini's native PDF reading...")
            return None
    return text


def extract_ontology_from_text(text: str, filename: str, max_retries: int = 3) -> dict:
    """Use Gemini to extract ontology from text with rate-limit retry."""
    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = EXTRACTION_PROMPT + f"\n\nDocument: {filename}\n\n{text[:30000]}"

    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[extractor] JSON parse error: {e}")
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait = 35 * (attempt + 1)
                print(f"[extractor]   Rate limited — waiting {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"[extractor] Gemini error: {e}")
                return None
    return None


def extract_ontology_from_pdf(pdf_path: Path, max_retries: int = 3) -> dict:
    """Use Gemini to extract ontology directly from PDF file with rate-limit retry."""
    model = genai.GenerativeModel('gemini-2.0-flash')
    uploaded = genai.upload_file(str(pdf_path))
    prompt = EXTRACTION_PROMPT + f"\n\nDocument: {pdf_path.name}"

    for attempt in range(max_retries):
        try:
            response = model.generate_content([prompt, uploaded])
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[extractor] JSON parse error: {e}")
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait = 35 * (attempt + 1)
                print(f"[extractor]   Rate limited — waiting {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"[extractor] Gemini error: {e}")
                return None
    return None


def merge_glossaries(existing: dict, new_entry: dict) -> dict:
    """Merge new ontology entry into existing glossary."""
    if not existing:
        existing = {"sources": [], "tools": [], "parts": [], "materials": [], "action_verbs": []}

    # Track sources
    source = new_entry.get("source", "unknown")
    if source not in existing.get("sources", []):
        existing.setdefault("sources", []).append(source)

    # Merge each category
    for category in ["tools", "parts", "materials", "action_verbs"]:
        existing_items = existing.get(category, [])
        new_items = new_entry.get(category, [])

        # Track existing names to avoid duplicates
        existing_names = set()
        for item in existing_items:
            if isinstance(item, dict):
                existing_names.add(item.get("name", "").lower())
                existing_names.add(item.get("verb", "").lower())

        for item in new_items:
            if isinstance(item, dict):
                name = item.get("name", item.get("verb", "")).lower()
                if name and name not in existing_names:
                    existing_items.append(item)
                    existing_names.add(name)

        existing[category] = existing_items

    return existing


def main():
    parser = argparse.ArgumentParser(description="PDF Ontology Extractor for Atlas")
    parser.add_argument("path", help="Path to PDF file or directory of PDFs")
    parser.add_argument("--output", default=str(GLOSSARY_FILE),
                        help="Output glossary file (default: prompts/tech_glossary.json)")
    args = parser.parse_args()

    input_path = Path(args.path)
    output_path = Path(args.output)

    # Collect PDF files
    if input_path.is_dir():
        pdfs = list(input_path.glob("**/*.pdf"))
        print(f"[extractor] Found {len(pdfs)} PDFs in {input_path}")
    elif input_path.is_file() and input_path.suffix.lower() == '.pdf':
        pdfs = [input_path]
    else:
        print(f"[extractor] ERROR: {input_path} is not a PDF file or directory")
        sys.exit(1)

    # Load existing glossary
    glossary = {}
    if output_path.exists():
        try:
            glossary = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"[extractor] Loaded existing glossary with {len(glossary.get('tools', []))} tools, "
                  f"{len(glossary.get('parts', []))} parts")
        except Exception:
            pass

    # Process each PDF
    for pdf in pdfs:
        print(f"\n[extractor] Processing: {pdf.name}...")

        # Try text extraction first, fall back to Gemini native PDF
        text = extract_text_from_pdf(pdf)
        if text and len(text.strip()) > 100:
            print(f"[extractor]   Text extracted: {len(text)} chars")
            result = extract_ontology_from_text(text, pdf.name)
        else:
            print(f"[extractor]   Using Gemini native PDF reading...")
            result = extract_ontology_from_pdf(pdf)

        if result:
            result["source"] = pdf.name
            glossary = merge_glossaries(glossary, result)
            tools = len(result.get("tools", []))
            parts = len(result.get("parts", []))
            verbs = len(result.get("action_verbs", []))
            print(f"[extractor]   Extracted: {tools} tools, {parts} parts, {verbs} verbs")
        else:
            print(f"[extractor]   FAILED to extract from {pdf.name}")
        
        # Rate limit: wait between files to avoid quota exhaustion
        print(f"[extractor]   Waiting 10s before next file (rate limit)...")
        time.sleep(10)

    # Save glossary
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")

    total_tools = len(glossary.get("tools", []))
    total_parts = len(glossary.get("parts", []))
    total_verbs = len(glossary.get("action_verbs", []))
    print(f"\n{'='*60}")
    print(f"[extractor] GLOSSARY SAVED: {output_path}")
    print(f"  Total tools: {total_tools}")
    print(f"  Total parts: {total_parts}")
    print(f"  Total verbs: {total_verbs}")
    print(f"  Sources: {len(glossary.get('sources', []))}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
