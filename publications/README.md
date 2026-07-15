# Publication metadata

This directory keeps the webpage and CV publication lists synchronized.

- `manual.json` contains works in progress and explicit overrides for INSPIRE records.
- `inspire.json` is the latest cached response from the INSPIRE REST API.
- `publications.json` is the normalized, merged dataset.
- `sync.py` refreshes INSPIRE metadata and generates the webpage listing and `cv/publications.tex`.

Run a normal refresh from the repository root:

```sh
python3 publications/sync.py
```

To regenerate output without network access, use the committed cache:

```sh
python3 publications/sync.py --offline
```

Edit `manual.json`, not the generated JSON, HTML publication block, or `cv/publications.tex`. After synchronization, rebuild the CV from inside `cv/` with a LaTeX environment that includes the current directory in `TEXINPUTS`:

```sh
env TEXINPUTS=.: pdflatex -interaction=nonstopmode -halt-on-error ./main.tex
```

The stable INSPIRE query uses the BAI `Richard.M.Whitehill.1`; it does not rely on a free-form name search.
