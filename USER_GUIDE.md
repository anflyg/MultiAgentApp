# MultiAgentApp - Enkel Anvandarguide

Kort guide for forsta anvandning och demo.

## Vad ar appen?

MultiAgentApp ar ett beslutsstod med:
- CLI-kommandon for att stalla panelfragor och visa sparad analys
- en TUI-dashboard for att se fragor, rekommendationer och beslutskontext

## Snabbstart (fran tomt lage)

1. Aktivera venv och installera beroenden:
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Skapa demo-data + forsta panelresultat:
   - `python src/main.py --db-path alpha_demo.db alpha-demo-setup`
3. Visa sparad fraga:
   - `python src/main.py --db-path alpha_demo.db show-panel-question --question-id <ID_FRAN_OUTPUT>`
4. Oppna TUI:
   - `python src/main.py --db-path alpha_demo.db tui`

## Stall en ny panelfraga

- CLI:
  - `python src/main.py --db-path alpha_demo.db ask-decision-panel --topic Expansion --question "Din fraga har"`
- TUI:
  - fyll i `Topic` och `Question` till hoger
  - klicka `Ask panel`

## Vad ska du titta efter i outputen?

I både CLI och TUI:
- `Assessment` och `Handling mode` (hur fragan klassas)
- `Combined recommendation` (panelens samlade rad)
- `Recommended next step` (vad du bor gora nu)
- `Key reasoning notes` (viktigaste resonemangssignaler)

## Vanlig demo-resa

1. `alpha-demo-setup`
2. `show-panel-question`
3. `tui`
4. stall en ny fraga och jamfor rekommendation/next step

## Kanda begransningar (i alfa)

- Heuristiska regler, ingen full AI-beslutsmotor.
- Ingen automatisk beslutsskapning (anvandaren behaller kontroll).
- Ingen webb-UI i alfa (CLI + TUI).
