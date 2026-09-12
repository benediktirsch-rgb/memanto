# Übergabe — memanto Avatare (John = Claude, Madeleine = OpenAI)

Wechselarbeit zwischen Claude (Claude Code, Benes Rechner) und Astra (OpenAI Codex, ChatGPT Work).
Diese Datei ist die einzige Übergabestelle: Wer ein Arbeitspaket abschließt, trägt hier
Änderungen, Prüfungen, offene Punkte und den konkreten nächsten Schritt ein.
Es gibt **keinen automatischen Wechsel** — Bene reicht die Übergabe von Hand weiter.

- Fork: https://github.com/benediktirsch-rgb/memanto (Upstream: moorcheh-ai/memanto, `main` vom 12.09.2026)
- Branch: `feature/avatars`
- Draft-PR im Fork: https://github.com/benediktirsch-rgb/memanto/pull/1 (Basis `main` des Forks, nicht Upstream)

---

## Ziel

Ein **Avatar** ist das Gesicht eines Agenten: Anzeigename (*John*, *Madeleine*), der Modellanbieter
dahinter (`claude`, `openai`, `other`), optional Emoji und Farbe. Jeder Avatar sitzt auf genau einem
Agenten; **Avatar wechseln = diesen Agenten aktivieren**. Erinnerungen bleiben im Namensraum des
jeweiligen Agenten, John und Madeleine vermischen sich nie.

Gewünscht war: Feature in der Web-UI **und** Änderung am CLI.

---

## Stand — Paket 1 (Claude, 12.09.2026)

### Änderungen

| Bereich | Datei(en) | Was |
|---|---|---|
| Modell | `memanto/app/models/session.py` | `AgentProvider`, `AgentAvatar` (name, provider, emoji, color, `initials`), `AVATAR_PRESETS` (`john`, `madeleine`), `get_avatar_preset()`; `avatar` auf `AgentCreate`, `AgentInfo`, `SessionInfo` |
| Service | `memanto/app/services/agent_service.py` | `set_avatar(agent_id, avatar|None)`, `find_by_avatar_name()` (Agent-ID vor Avatar-Name, case-insensitiv); `create_agent` übernimmt den Avatar |
| REST | `memanto/app/routes/sessions.py` | `GET /api/v2/avatars/presets`, `PUT /api/v2/agents/{id}/avatar`, `DELETE /api/v2/agents/{id}/avatar`; `GET /api/v2/status` liefert `avatar` |
| Clients | `memanto/cli/client/direct_client.py`, `sdk_client.py` | `create_agent(..., avatar=)`, `set_agent_avatar()`, `find_agent_by_avatar()` |
| CLI | `memanto/cli/commands/avatar.py` (neu), `agent.py`, `_shared.py`, `__init__.py` | Gruppe `memanto avatar` mit `presets`, `list`, `current`, `switch`, `set`, `clear`; `agent create --avatar john\|madeleine`, `--avatar-name`, `--provider`, `--emoji`; `agent list` zeigt Avatar-Spalte |
| Web-UI | `memanto/app/ui/static/index.html` | Chip-Leiste über der Agententabelle (Klick = wechseln, aktiver Chip hervorgehoben), Avatar-Spalte, Knopf „Avatar“ je Zeile mit Modal (Preset-Auswahl, Name, Provider, Emoji, Farbe, Entfernen), Avatar in Sidebar-Status und Dashboard-Profil |
| Tests | `tests/test_avatars.py` (neu, 33 Tests) | Modell, Service, API, CLI-Helfer, CLI-Kommandos |
| Doku | `docs/CLI_USER_GUIDE.md`, `docs/CLI_INSTALLATION.md` | Abschnitt „Avatar Commands“, Kommandoliste |

Alte Agentendateien ohne `avatar`-Feld laden weiter (Feld optional, Test vorhanden).

### Prüfungen

- `ruff check` und `ruff format` auf allen geänderten Python-Dateien: sauber.
- `pytest tests` (ohne `test_session_config_overlay.py`): **alles grün**, 1 Skip (POSIX-Rechte).
  `test_session_config_overlay.py` schlägt auf Benes Rechner nur fehl, weil das portable Embeddable-Python
  in Kindprozessen `PYTHONPATH` ignoriert — nicht durch dieses Paket verursacht; im CI mit normalem Python läuft sie.
- Inline-JS der UI mit `node --check` syntaxgeprüft.
- Web-UI im Browser gegen einen lokalen Server mit isoliertem `USERPROFILE` und drei Agenten geprüft:
  Chips rendern, Wechsel John → Madeleine → John (Sidebar folgt), Modal speichert einen eigenen Avatar
  („Bene Digital“ → Initialen „BD“), Dashboard-Profil zeigt den Avatar.
- CLI-Kette real gegen dieselben Dateien: `avatar list` → `switch john` → `current` → `switch John`
  (schon aktiv, No-op) → `agent list` → `clear` → `set --preset madeleine --name Astra --emoji ✨`.

### Bewusst nicht gemacht

- Kein Upstream-PR an moorcheh-ai (Benes Entscheidung; die Presets tragen private Namen).
- Kein `.venv` im Repo; Abhängigkeiten liegen lokal in `.pydeps/` (in `.git/info/exclude`).
- Keine Änderung an `memanto connect` (Hooks/`MEMORY.md`) und an `memanto status`.

---

## Offene Punkte / nächster Schritt (für Astra)

1. **`memanto status` und die Session-Hooks zeigen den Avatar noch nicht.**
   `memanto/cli/commands/core.py` (`status`) sollte die Zeile „Active agent“ um `avatar_label(...)` ergänzen;
   `memanto/cli/connect/assets/hooks/session_start.py` bzw. die Vorlage für `MEMORY.md` könnte oben
   „Du sprichst als 🧭 John (Claude)“ eintragen, damit die KI-Session ihre Persona kennt.
2. **README**: kurzer Absatz „Avatars“ mit den zwei Presets und `memanto avatar switch` (Abschnitt CLI).
3. **Wechsel-Semantik prüfen**: `avatar switch` beendet die alte Session per `clear_active_session()` und
   aktiviert die neue. Wenn Astra findet, dass eine echte `end_session` (mit Session-Zusammenfassung)
   besser ist, in `memanto/cli/commands/avatar.py::avatar_switch` umbauen und `tests/test_avatars.py`
   anpassen.
4. Kleinigkeit: Das ZWJ-Emoji „👩‍💼“ von Madeleine ist in Rich-Tabellen breiter als eine Zelle
   (Spalte rutscht). Alternative: `👩` oder `💼` als Preset-Emoji.

Vorgehen für Astra: `git fetch origin && git checkout feature/avatars`, `pip install -e ".[all]"`,
`pytest tests/test_avatars.py`, dann Punkt 1 umsetzen, Tests ergänzen, committen, hier unten
„Paket 2“ eintragen.

---

## Regeln für beide

- Nur Porcelain-Git: `pull --ff-only` → `add <dateien>` → `commit` → `push`. Nie `add -A`, nie `push --force`.
- UTF-8 ohne BOM, LF. Vor jedem Commit `ruff check` + `ruff format` + `pytest tests/test_avatars.py`.
- Nach jedem Paket diese Datei fortschreiben. Kein Merge nach `main` ohne Bene.

---

## Paket 2 (Astra, 12.09.2026)

### Änderungen

- `memanto status` zeigt den Avatar mit `avatar_label()` im Bereich Active Agent,
  sowohl mit laufendem als auch ohne lokalen REST-Server. Ohne Avatar erscheint `—`.
- Die MEMORY.md-Vorlage liegt in `MemoryExportService`: Frische Exporte beginnen
  mit `Du sprichst als 🧭 John (Claude)` bzw. `Du sprichst als 👩 Madeleine (OpenAI)`.
  Beide Clients übergeben die Metadaten des **exportierten** Agenten, auch wenn ein
  anderer Agent aktiv ist. Fehlende lokale Avatar-Metadaten bleiben optional;
  Session-Validierung und agentenspezifische Speicherzugriffe bleiben bestehen.
- Der Claude-Code-SessionStart-Hook gibt diese erste Zeile vor seinem bisherigen
  Hinweis aus, ausschließlich nach erfolgreichem Sync. Bei fehlgeschlagenem Sync
  wird keine Persona aus einer eventuell noch vorhandenen MEMORY.md übernommen.
- README: Abschnitt Avatars, Presets, Erstellen/Wechseln, Trennung der Namensräume
  und manueller Handoff. Der Wechsel startet keinen anderen Modellanbieter.
- Madeleine-Preset nutzt `👩` ohne ZWJ; CLI-Handbuch angepasst. Bestehende gespeicherte
  Avatare werden nicht migriert; bei Bedarf `memanto avatar set <id> --emoji "👩"`.
- Alle Änderungen UTF-8 ohne BOM / LF; auch neu erzeugte MEMORY.md verwendet LF.

### Prüfungen

- Isolierte Python-3.12-venv außerhalb des Repositories, Installation mit
  `pip install -e ".[all]"`. Test-USERPROFILE und TEMP ebenfalls isoliert.
- `ruff check .`: grün; `ruff format --check` auf allen geänderten Python-Dateien: grün.
- `tests/test_avatars.py`: 55 Tests, davon 22 neu. Zusammen mit
  `tests/test_export_resilience.py`: **66 bestanden**.
- Gesamtsuite `pytest tests -o addopts='' -q --tb=short`: **1023 bestanden,
  26 übersprungen, 1 Warnung**. 24 Live-Moorcheh-Tests ohne echten API-Key und
  2 POSIX-Rechtetests unter Windows übersprungen. Warnung: Starlette/httpx-Deprecation.
  `test_session_config_overlay.py` besteht mit dieser normalen venv ebenfalls.
- Neue Integrationstests prüfen für beide Clients John → Madeleine im selben
  Projektordner: Persona und Erinnerungsinhalt werden ersetzt, nicht vermischt;
  der echte Hook-Sync-Lesepfad gibt jeweils die passende Persona aus.
  Backend und Subprozess sind dabei gemockt; keine Live-Provider-Sitzung gestartet.
- Keine UI-Änderung und kein erneuter Browserlauf in diesem Paket.

### Offene Punkte / konkreter nächster Schritt für Claude

1. `git pull --ff-only`, Installation aktualisieren und `memanto connect claude-code`
   im gewünschten Projekt erneut ausführen: Die Integration kopiert Hook-Dateien,
   bereits installierte Hooks aktualisieren sich nicht durch einen Git-Pull allein.
   Eine echte neue Claude-Code-Sitzung mit John prüfen, danach manuell Madeleine
   aktivieren und MEMORY.md kontrollieren. Keine automatische Übergabe behaupten.
2. Bestehende Cache-Semantik bleibt bestehen: Bei Backend-Ausfall wird der letzte
   Export desselben Agenten verwendet. Nach Avatar-Umbenennung/-Entfernung kann
   darin die alte Persona stehen, bis ein frischer Export gelingt. Eine separate
   Aktualisierung der Persona bei Cache-Fallback wäre ein mögliches Folgepaket.
3. `avatar switch` bleibt unverändert bei `clear_active_session()` plus Aktivierung.
   Die Entscheidung über echte Session-Beendigung mit Zusammenfassung ist weiterhin
   offen; nicht stillschweigend zusätzliche Modellaufrufe einführen.

Änderungen gehören ausschließlich auf `feature/avatars` im Fork und in Draft-PR #1.
Kein Upstream-PR, kein Merge, kein automatischer Wechsel. Bene reicht diese Datei
von Hand an Claude weiter.
