# Alpha Checklist (MultiAgentApp)

Denna checklista definierar nar appen kan raknas som **forsta alfa**.

## Alfa-krav (måste vara sant)

- [ ] Appen startar lokalt utan specialsteg utover README (`venv`, `pip install -r requirements.txt`).
- [ ] `alpha-demo-setup` fungerar från tom databas:
  - `python src/main.py --db-path alpha_demo.db alpha-demo-setup`
  - kommandot skapar demo-data och ett sparat panelresultat.
- [ ] Sparad panelfraga går att visa:
  - `python src/main.py --db-path alpha_demo.db show-panel-question --question-id <ID>`
  - output visar assessment, recommendation, next step och reasoning notes.
- [ ] TUI startar och visar data:
  - `python src/main.py --db-path alpha_demo.db tui`
  - latest questions, recommendation och decision guidance syns för vald fraga.
- [ ] Ny panelfraga går att ställa och sparas:
  - via CLI `ask-decision-panel` eller via TUI Ask panel
  - frågan går att hitta med `list-panel-questions`.
- [ ] Paneloutput är begriplig nog för demo:
  - användarvänliga labels (inte råa interna tokens)
  - tydlig recommendation + rekommenderat nästa steg
  - reasoning notes syns i läsbar form.
  - aktivt valda advisor-roller och fallback-signalering syns tydligt.
- [ ] Testsviten som krävs för alfa är groen:
  - `python -m pytest`

## Kända begränsningar (acceptabla i alfa)

- Roller och panelbedömning är regel-/heuristikbaserade med valfritt LLM-stod (med robust fallback).
- En intern roll-router avgor vilka advisor-roller som aktiveras per fraga; ingen femte synlig agent finns i produkten.
- Inget automatiskt beslutsskapande: systemet föreslår nästa steg men formaliserar inte beslut.
- Ingen avancerad sök/filter i historik utover enkla listkommandon.
- Ingen webb-UI; fokus är CLI + Textual TUI.

## Inte inkluderat i alfa (senare fas)

- Fullt privat samtalsminne/long-term conversational memory.
- Konfigurerbara roller och policy-workflows per organisation.
- Avancerad automatisk kunskapsextraktion/auto-linking utover nuvarande heuristik.
