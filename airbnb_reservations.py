#!/usr/bin/env python3
"""
Extracteur de réservations Airbnb
==================================
Ouvre Chrome visible, vous laisse vous connecter, puis extrait
toutes vos réservations entre deux dates.

Résultats :
  - reservations_airbnb.json
  - mise à jour de voyage.html si présent dans le même dossier

Usage :
    python3 airbnb_reservations.py
    python3 airbnb_reservations.py --start 2026-07-30 --end 2026-08-21

Prérequis (une seule fois) :
    pip install playwright
    playwright install chromium
"""

import asyncio
import json
import re
import sys
import argparse
from datetime import datetime, date
from pathlib import Path

DEFAULT_START = "2026-07-30"
DEFAULT_END   = "2026-08-21"
OUTPUT_FILE   = Path(__file__).parent / "reservations_airbnb.json"
VOYAGE_HTML   = Path(__file__).parent / "voyage.html"

MONTHS_FR = {
    "janv": 1, "jan": 1, "janvier": 1,
    "fevr": 2, "fev": 2, "fevrier": 2,
    "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7, "juillet": 7,
    "aout": 8, "out": 8,
    "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "decembre": 12,
}


def parse_args():
    p = argparse.ArgumentParser(description="Extrait les reservations Airbnb")
    p.add_argument("--start", default=DEFAULT_START)
    p.add_argument("--end",   default=DEFAULT_END)
    return p.parse_args()


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def extract_dates(text):
    t = text.lower()
    t = t.replace("fevrier","fev").replace("decembre","dec").replace("septembre","sept")
    t = t.replace("octobre","oct").replace("novembre","nov").replace("janvier","jan")
    t = t.replace("juillet","juil").replace("juin","juin").replace("aout","aout")
    t = t.replace("\u00e9","e").replace("\u00e8","e").replace("\u00ea","e")
    pattern = r'(\d{1,2})\s+(' + '|'.join(MONTHS_FR.keys()) + r')\.?\s*(\d{4})?'
    found = re.findall(pattern, t)
    parsed = []
    for day, month, year in found:
        m = MONTHS_FR.get(month.rstrip('.'))
        y = int(year) if year else 2026
        if m:
            try:
                parsed.append(date(y, m, int(day)))
            except ValueError:
                pass
    return parsed


def extract_price(text):
    m = re.search(r'([\d\s]+[,.]?\d*)\s*EUR|€', text)
    if m:
        return m.group(1).strip().replace('\u202f', '').replace(' ', '') + ' EUR'
    return ""


def find_in_json(data, start_dt, end_dt, results=None, seen=None):
    if results is None:
        results = []
    if seen is None:
        seen = set()
    if isinstance(data, dict):
        ci_val = (data.get("checkIn") or data.get("check_in") or
                  data.get("startDate") or data.get("checkinDate") or
                  data.get("start_date") or "")
        co_val = (data.get("checkOut") or data.get("check_out") or
                  data.get("endDate") or data.get("checkoutDate") or
                  data.get("end_date") or "")
        if ci_val:
            ci = parse_iso(ci_val)
            co = parse_iso(co_val)
            if ci and (start_dt <= ci <= end_dt or (co and start_dt <= co <= end_dt)):
                name = (data.get("listingName") or data.get("name") or
                        data.get("title") or data.get("listing_name") or "Reservation")
                price = str(data.get("totalPrice") or data.get("price") or "")
                url   = (data.get("reservationUrl") or data.get("url") or
                         data.get("detailsUrl") or "")
                if not url:
                    code = (data.get("reservationCode") or data.get("confirmationCode") or "")
                    if code:
                        url = f"https://www.airbnb.fr/trips/v1/reservation-details/{code}"
                key = f"{ci}:{co}:{str(name)[:40]}"
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "nom":       str(name)[:80],
                        "check_in":  ci.isoformat(),
                        "check_out": co.isoformat() if co else None,
                        "prix":      str(price),
                        "url":       str(url),
                    })
                    print(f"   + [API] {str(name)[:40]} -- {ci} -> {co}")
        for v in data.values():
            find_in_json(v, start_dt, end_dt, results, seen)
    elif isinstance(data, list):
        for item in data:
            find_in_json(item, start_dt, end_dt, results, seen)
    return results


async def run(start_str, end_str):
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    start_dt = date.fromisoformat(start_str)
    end_dt   = date.fromisoformat(end_str)
    reservations = []
    api_payloads  = []
    seen_keys = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--window-size=1280,900"]
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        async def capture(response):
            try:
                if response.status == 200 and any(
                    k in response.url for k in ["api/v3", "/trips", "/reservations", "pdp_listing"]
                ):
                    body = await response.json()
                    api_payloads.append(body)
            except Exception:
                pass

        page.on("response", capture)

        # -- Etape 1 : connexion
        print("\n1. Ouverture d'Airbnb...")
        try:
            await page.goto("https://www.airbnb.fr/login",
                            wait_until="domcontentloaded", timeout=60_000)
        except PWTimeout:
            pass
        await page.wait_for_timeout(1500)

        print("\n  Connectez-vous a votre compte Airbnb dans la fenetre Chrome.")
        print("  Appuyez sur ENTREE une fois connecte.")
        input()

        # -- Etape 2 : page voyages
        print("\n2. Chargement des voyages...")
        for url in ["https://www.airbnb.fr/trips", "https://www.airbnb.fr/trips/v1"]:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                break
            except PWTimeout:
                print(f"   Timeout sur {url}, tentative suivante...")
                continue

        # Attendre et scroller
        await page.wait_for_timeout(3000)
        print("   Defilement pour charger toutes les reservations...")
        for i in range(8):
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(600)
        await page.wait_for_timeout(2000)

        # -- Etape 3 : extraction DOM
        print("\n3. Extraction DOM...")
        seen_hrefs = set()

        selectors = [
            "a[href*='reservation-details']",
            "a[href*='trips/v1']",
            "a[href*='manage-your-reservation']",
            "a[href*='/rooms/']",
        ]
        for sel in selectors:
            links = await page.query_selector_all(sel)
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href or href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)

                    # Remonter dans le DOM pour avoir le contexte complet
                    card = link
                    for _ in range(5):
                        p = await card.query_selector("xpath=..")
                        if p:
                            card = p
                        else:
                            break
                    card_text = await card.inner_text()

                    dates = extract_dates(card_text)
                    if not dates:
                        continue

                    ci = dates[0]
                    co = dates[1] if len(dates) > 1 else None

                    if not (start_dt <= ci <= end_dt or
                            (co and start_dt <= co <= end_dt)):
                        continue

                    full_url = ("https://www.airbnb.fr" + href
                                if href.startswith("/") else href)
                    price = extract_price(card_text)
                    lines = [l.strip() for l in card_text.split("\n")
                             if l.strip() and len(l.strip()) > 3
                             and not re.match(r'^[\d€EUR\s,./\-]+$', l.strip())]
                    name = lines[0][:80] if lines else "Reservation"

                    key = f"{ci}:{co}:{name[:30]}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        reservations.append({
                            "nom":       name,
                            "check_in":  ci.isoformat(),
                            "check_out": co.isoformat() if co else None,
                            "prix":      price,
                            "url":       full_url,
                        })
                        print(f"   + [DOM] {name[:50]} -- {ci} -> {co}")
                except Exception:
                    continue

        # -- Etape 4 : donnees API interceptees
        if api_payloads:
            print(f"\n4. Analyse de {len(api_payloads)} reponses API...")
            api_res = find_in_json(api_payloads, start_dt, end_dt)
            for r in api_res:
                key = f"{r['check_in']}:{r.get('check_out','')}:{r['nom'][:30]}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    reservations.append(r)

        await browser.close()

    return reservations


def update_voyage_html(reservations):
    if not VOYAGE_HTML.exists():
        print(f"\n   voyage.html introuvable dans {VOYAGE_HTML.parent}")
        return

    html = VOYAGE_HTML.read_text(encoding="utf-8")
    trip_start = date(2026, 7, 30)
    updates = 0

    for res in sorted(reservations, key=lambda r: r.get("check_in", "")):
        if not res.get("url") or not res.get("check_in"):
            continue
        ci = parse_iso(res["check_in"])
        if not ci:
            continue
        day_num = (ci - trip_start).days + 1
        if day_num < 1 or day_num > 24:
            continue

        pat = re.compile(
            r"(d:" + str(day_num) + r"[^}]{0,900}?night:\{[^}]{0,500}?url:')[^']*(')",
            re.DOTALL
        )
        new_html, n = pat.subn(
            lambda m: m.group(1) + res["url"] + m.group(2), html
        )
        if n > 0:
            html = new_html
            updates += 1
            print(f"   + Jour {day_num}: {res['url'][:65]}...")

    if updates > 0:
        VOYAGE_HTML.write_text(html, encoding="utf-8")
        print(f"   => {updates} entree(s) mise(s) a jour dans voyage.html")
    else:
        print("   => Aucune correspondance (URLs peut-etre deja a jour)")


def main():
    try:
        from playwright.async_api import async_playwright  # noqa
    except ImportError:
        print("Playwright manquant. Lancez :")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    args = parse_args()

    print("\n" + "="*52)
    print("   Extracteur de reservations Airbnb")
    print("="*52)
    print(f"\nPeriode : {args.start}  ->  {args.end}")
    print(f"Dossier : {Path(__file__).parent}")
    print("\nAppuyez sur ENTREE pour lancer, Ctrl+C pour annuler.")
    input()

    try:
        reservations = asyncio.run(run(args.start, args.end))
    except KeyboardInterrupt:
        print("\nAnnule.")
        return

    if not reservations:
        print("\nAucune reservation trouvee pour cette periode.")
        print("\nSi la page s'est bien chargee mais sans resultats :")
        print("  - Airbnb affiche peut-etre vos reservations futures differemment")
        print("  - Essayez F12 -> Reseau dans Chrome, filtrez 'trips' ou 'reservation'")
        print("  - Copiez les URLs manuellement dans le tableau Excel")
        return

    # Sauvegarder
    out = {
        "extraction_date": datetime.now().isoformat(),
        "periode": {"debut": args.start, "fin": args.end},
        "nb_reservations": len(reservations),
        "reservations": sorted(reservations, key=lambda r: r.get("check_in", ""))
    }
    OUTPUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Affichage
    print(f"\n{'='*52}")
    print(f"  {len(reservations)} reservation(s) extraite(s)")
    print(f"{'='*52}")
    for i, r in enumerate(sorted(reservations, key=lambda r: r.get("check_in","")), 1):
        print(f"\n[{i}] {r.get('nom','?')}")
        print(f"    {r.get('check_in','?')}  ->  {r.get('check_out','?')}")
        if r.get("prix"):
            print(f"    {r['prix']}")
        url = r.get("url","")
        print(f"    {url[:72]}{'...' if len(url)>72 else ''}")

    print(f"\nSauvegarde -> {OUTPUT_FILE.name}")

    print("\n5. Mise a jour voyage.html...")
    update_voyage_html(reservations)
    print("\nTermine !")


if __name__ == "__main__":
    main()
