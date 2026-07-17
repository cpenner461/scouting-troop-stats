# Scouting Troop Stats

A tool for Scout leaders to download Scout advancement data from the Scouting America API into a local SQLite database, then explore it through an interactive dashboard. Figure out which merit badges and rank requirements the most Scouts still need so you can plan troop meetings that benefit everyone.

> This is not an officially sanctioned Scouting America tool. Use at your own risk.

## Getting the App

### Web App (recommended)

Run a local web server that handles everything -- sign in, sync your troop's data, and explore the dashboard -- all in one browser tab. Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone <this-repo>
cd scouting-troop-stats
uv sync
uv run scouting serve
```

This opens your browser to `http://127.0.0.1:8765/`. Visit `/sync` to sign in and sync your troop's data (with an optional roster CSV upload); the dashboard at `/` reads directly from the resulting `scouting_troop.db`.

### Browser Dashboard

If you already have a database file (`.db`), you can open the dashboard directly in any modern browser:

1. Open `dashboard.html` in your browser
2. Click **Open Database** and select your `.db` file
3. Browse your troop's data

If someone has shared a `.db` file with you, that's all you need. No installation required.

## Try It Out

The repo includes `sample_troop.db` -- a fully populated database for a fictional "Sample Troop 999" with 50 made-up Scouts across 5 patrols and a realistic spread of ranks from New Scout through Eagle. It lets you explore every feature without authenticating or syncing any real data.

Open `dashboard.html` in your browser, click **Open Database**, and select `sample_troop.db`.

## Dashboard Features

### Troop tab

Summary stats and troop-wide analytics:

- **Summary cards** -- total Scouts, merit badges earned, biggest Eagle MB gap, and how many Scouts are close to ranking up
- **Rank distribution** -- bar chart of how many Scouts are at each rank
- **Eagle MB gaps** -- every Eagle-required badge ranked by how many Scouts still need it, with in-progress counts
- **Closest to next rank** -- who needs the fewest requirements to advance, sorted by completion percentage
- **Activity planner** -- merit badges where a large portion of the troop would benefit, flagged by Eagle status
- **Eagle pipeline summary** -- troop-wide view of Eagle MB slot completion across all Scouts

### Roster tab

Full troop roster in a sortable table:

- Every Scout listed with current rank, patrol, total MBs earned, Eagle MB slot progress (with a mini progress bar), in-progress MB count, and approved leadership positions
- Scouts grouped by patrol when patrol data is available
- Click any Scout's name to jump directly to their Scout tab record

### Scout tab

Select any Scout by name to see their full record:

- **Overview** -- current rank, total merit badges earned (with Eagle count), in-progress MBs, leadership days, and birthday with current age
- **Rank progress** -- which requirements for their next rank are complete, in progress, or still needed
- **Merit badges** -- completed and in-progress badges; click any in-progress badge to see a per-requirement breakdown
- **Eagle pipeline** -- a visual tracker showing exactly which of the 14 Eagle-required MBs they've earned, are working on, or still need (with "choose one" group slots)
- **Leadership history** -- all positions held with dates and approval status

### Tents tab

A planning tool for assigning Scouts to tent crews for campouts and verifying BSA tenting rule compliance.

- **Crews** -- create as many named crews as you need; each is displayed as its own card
- **Assigning Scouts** -- a scrollable list inside each crew card shows all Scouts; click a name to add them, or click the X next to a member to remove them
- **Analyze** -- checks whether the crew can be validly tented under BSA rules: Scouts cannot tent alone, tentmates must be within 2 years of age, and tents hold 2 or 3 Scouts
- **Results** -- valid crews show a proposed tent assignment; invalid crews call out which Scouts can't be accommodated
- **Analyze All** -- runs the check on every crew at once
- Crew assignments are saved in browser `localStorage` and restored automatically

> Birthdates must be synced for tent analysis to work. The `sample_troop.db` ships with birthdates for all 50 Scouts.

### Settings tab

Database management. Load a `.db` file via the file picker. Once a database is loaded, the tab shows a summary of what's in it (Scout count, rank data, etc.).

## How It Works

The dashboard uses [sql.js](https://sql.js.org) (SQLite compiled to WebAssembly) to read the `.db` file entirely in the browser. **Your data never leaves your machine.**

The Scouting America API is used only to authenticate and download advancement data. Passwords are used to obtain a session token and are never stored. All synced data is saved to a local SQLite database on your computer.

## Background

While there is a "real" API that powers Scoutbook and other Scouting sites, it isn't meant for external application development. This tool takes the approach of having you authenticate manually, then pulling down all relevant info for your roster into a local database you can query as much as you want.

Claude Code was used extensively to build this. The [scouting-api](https://github.com/mmarseglia/scouting-api) repo was used as input to figure out the API endpoints.

## For Developers

If you want to run the Python CLI tools or contribute to the project, see the [Development Guide](DEVELOPMENT.md).
