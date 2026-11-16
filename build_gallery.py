import base64, json, mimetypes, os, secrets, sqlite3
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE_SHARE_URL = "https://github.io"
DB_PATH = os.path.abspath("../GreetingCardApp02/creative_hub.db")
TEMPLATE_PATH = "src/gallery_template.html"
OUT_DIR = "docs/exhibitions"

def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exhibitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            notes TEXT,
            slug TEXT UNIQUE NOT NULL,
            enc_key TEXT NOT NULL,
            share_url TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(artworks)")}
    for col, col_type in [("medium", "TEXT"), ("dimensions", "TEXT"), ("year", "TEXT"), ("exhibition_slug", "TEXT")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE artworks ADD COLUMN {col} {col_type}")
    conn.commit()

def img_to_data_uri(path):
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def build_wrapper(title, iv_b64, ct_b64):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#121413; color:#c7cfc9; font-family:system-ui,sans-serif; text-align:center; padding:24px; }}
  </style>
</head>
<body>
  <p id="msg">Unlocking exhibition...</p>
  <script>
    (async () => {{
      const msg = document.getElementById('msg');
      try {{
        const raw = location.hash.slice(1).trim();
        if (!raw) {{ msg.textContent = 'Please use your personal invitation link.'; return; }}
        const b64 = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
        const key = await crypto.subtle.importKey('raw', b64(raw), 'AES-GCM', false, ['decrypt']);
        const plain = await crypto.subtle.decrypt({{ name: 'AES-GCM', iv: b64('{iv_b64}') }}, key, b64('{ct_b64}'));
        const html = new TextDecoder().decode(plain);
        document.open(); document.write(html); document.close();
      }} catch (e) {{
        msg.textContent = 'Unable to unlock exhibition. Please check your link.';
      }}
    }})();
  </script>
</body>
</html>"""

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    ex_title = input("Exhibition title: ").strip() or "Private Exhibition"
    ex_notes = input("Exhibition intro / statement (optional): ").strip()
    slug = secrets.token_hex(6)
    now = datetime.now(timezone.utc).isoformat()

    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    found = sorted(
        os.path.join(r, f)
        for r, _, fs in os.walk("src/images")
        for f in fs
        if os.path.splitext(f)[1].lower() in exts
    )

    items = []
    print(f"\nFound {len(found)} image(s) inside src/images/.")
    for img_path in found:
        print(f"\nImage: {img_path}")
        if input("  Include in this exhibition? (Y/n): ").strip().lower() == "n":
            continue

        default_title = os.path.splitext(os.path.basename(img_path))[0].replace("_", " ").replace("-", " ")
        title = input(f"  Artwork title [{default_title}]: ").strip() or default_title
        medium = input("  Medium (e.g. Oil on canvas): ").strip()
        dimensions = input("  Dimensions (e.g. 60 x 80 cm): ").strip()
        year = input("  Year: ").strip()
        notes = input("  Learn more / artist notes: ").strip()

        items.append({
            "title": title,
            "medium": medium,
            "dimensions": dimensions,
            "year": year,
            "notes": notes,
            "image": img_to_data_uri(img_path)
        })

        conn.execute("""
            INSERT INTO artworks (title, file_path, notes, created_at, medium, dimensions, year, exhibition_slug)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, os.path.abspath(img_path), notes, now, medium, dimensions, year, slug))

    if not items:
        print("No artworks added. Exiting.")
        return

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    html = (html
        .replace("{{EXHIBITION_TITLE}}", ex_title)
        .replace("{{EXHIBITION_NOTES}}", ex_notes)
        .replace("{{ARTWORKS_JSON}}", json.dumps(items)))

    key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)

    key_b64 = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
    iv_b64 = base64.urlsafe_b64encode(iv).decode("ascii")
    ct_b64 = base64.urlsafe_b64encode(ct).decode("ascii")

    out_path = os.path.join(OUT_DIR, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_wrapper(ex_title, iv_b64, ct_b64))

    share_url = f"{BASE_SHARE_URL.rstrip('/')}/exhibitions/{slug}.html#{key_b64}"
    conn.execute("""
        INSERT INTO exhibitions (title, notes, slug, enc_key, share_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ex_title, ex_notes, slug, key_b64, share_url, now))
    conn.commit()
    conn.close()

    print(f"\nSaved encrypted exhibition: {out_path}")
    print(f"Shareable one-click link:\n{share_url}\n")

if __name__ == "__main__":
    main()
