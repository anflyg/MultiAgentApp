# MultiAgentApp

Ett minimalt Pythonprojekt med virtuell miljö (`.venv`) och en enkel startpunkt.

## Kom igång

1. Aktivera venv (från projektroten):
   - macOS/Linux: `source .venv/bin/activate`
   - Windows (PowerShell): `.venv\\Scripts\\Activate.ps1`
2. Uppgradera pip (frivilligt men rekommenderas): `python -m pip install --upgrade pip`
3. Installera beroenden (om du lägger till `requirements.txt`): `pip install -r requirements.txt`
4. Kör appen: `python src/main.py`

## Struktur

- `src/main.py` – Entrypoint som just nu skriver ut ett meddelande.
- `.venv/` – Virtuell miljö skapad med `python3 -m venv .venv`.

Lägg till fler moduler under `src/` när du bygger vidare.
