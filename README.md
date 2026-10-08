# training_app — agent-driven träningsplanering (PoC)

Claude är coachen; Python-verktygen hämtar och analyserar Garmin-data. Arbetet är spec-drivet:

- `CLAUDE.md` — regler agenten alltid följer
- `docs/DESIGN.md` — designval, begränsningar, kända buggar, nice-to-haves (levande)
- `docs/COACHING_SPEC.md` — coachingregler med ID (levande)
- `data/athlete/profile.json` / `goals.json` — utgångsläge och mål
- `plans/YYYY-Www.json|.md` — veckoplaner · `log/coach_log.md` — beslutslogg

## Kom igång (Windows, en gång)

```powershell
cd <sökväg>\training_app
py -3.12 -m venv .venv      # kräver Python >= 3.12 (garminconnect >= 0.3)
.venv\Scripts\activate
pip install -r requirements.txt
python -m trainer init      # skapar profile/goals/season_plan från *.example.* om de saknas
copy .env.example .env      # fyll i GARMIN_EMAIL / GARMIN_PASSWORD i .env
python -m trainer login     # interaktiv inloggning (MFA-kod om du har det)
python -m trainer sync --days 120   # första hämtningen: ~4 månaders historik
python -m unittest discover -s tests
```

Inloggningstokens sparas i `.garmin_tokens/`, så `sync` fungerar sedan utan lösenord tills de löper ut.

## Varje vecka

Säg till Claude: **"Gör veckoplanen"**. Agenten kör `sync` → frågar efter check-in (primär begränsning, RPE, styrka, sömn) → `context` → skriver planen → `validate`/`render` → loggar beslutet.
Om agenten inte når Garmin från sin miljö: kör `python -m trainer sync` själv först.

Övrigt:
- **"Revidera planen"** mitt i veckan — nytt revisionsnummer, utförda dagar lämnas orörda.
- **"Ändra mål …"** — uppdaterar `goals.json` med historik och kontrollerar planen.
- Ingen Garmin-åtkomst? Lägg `.fit`-filer i `data/inbox/` eller fyll i `data/inbox/manual_sessions.csv`, kör `python -m trainer import` och `normalize`.

## Kommandon
`login · fetch · import · normalize · sync · status · checkin · context · new-plan · validate · render` — se `docs/DESIGN.md` §2.2.

## Git och personlig data
Koden, scheman, tester och SDD-specarna (`CLAUDE.md`, `docs/*.md`) versioneras. All personlig data (profil, mål, säsongsplan, check-ins, planer, coach-logg, Garmin-data, hand-off, `.env`, tokens) är git-ignorerad, se `.gitignore` och `docs/DESIGN.md` D-015.
Specarna refererar till personliga värden via nyckel (t.ex. `profile.run.easy_hr_cap_bpm`). Testet `TestPrivacy` larmar om namn, PB-tider eller måltitlar hamnar i en spårad fil.
