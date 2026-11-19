# Verdict Mono

`build_verdict_mono.py` builds the UI font, Verdict Mono, into `OpenBench/static/fonts/`:

| file                         | weight | made from                                         |
|------------------------------|--------|---------------------------------------------------|
| `VerdictMono-Regular.woff2`  | 400    | DejaVu Sans Mono Book, renamed                    |
| `VerdictMono-Medium.woff2`   | 500    | Book, outlines offset outward by 10 font units    |
| `VerdictMono-SemiBold.woff2` | 600    | Book, outlines offset outward by 20 font units    |
| `VerdictMono-Bold.woff2`     | 700    | DejaVu Sans Mono Bold, renamed                    |

The derived weights keep Book's heights (each glyph is scaled back vertically to its own bounds) and advance widths;
their hinting is dropped. All four are named "Verdict Mono", because the Bitstream Vera licence allows modified fonts
only under names without "Bitstream" or "Vera" (the font names; the licence text, name IDs 13 and 14, stays in each
font as DejaVu ships it). The licence also ships as `OpenBench/static/fonts/VerdictMono-LICENSE.txt`; keep it next to
the fonts.

## Inputs

DejaVu Sans Mono 2.37, the two TTFs from Debian/Ubuntu's `fonts-dejavu-mono` package
(`/usr/share/fonts/truetype/dejavu/`) or from the upstream release (https://dejavu-fonts.github.io/):

```
c805f9436dbc268644c1d9584f01a601a653e028e08fd74b9b949f6cf8304d88  DejaVuSansMono.ttf
3a3c502eeff669a231549e80df9f7c49de109bafe303170409e905d0b31a38fe  DejaVuSansMono-Bold.ttf
```

## Dependencies

Python 3 with `fonttools`, `skia-pathops` and `brotli` (for woff2). They are not needed to run Verdict.

```
python3 -m venv /tmp/fontvenv
/tmp/fontvenv/bin/pip install fonttools skia-pathops brotli
```

## Command

From the repository root:

```
/tmp/fontvenv/bin/python Scripts/fonts/build_verdict_mono.py \
    /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf \
    /usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf
```

`--out DIR` writes elsewhere. The same inputs build byte-identical files (built with fontTools 4.68.0,
skia-pathops 0.9.2, brotli 1.2.1).

## After rebuilding

`OPENBENCH_STATIC_VERSION` does not reach the fonts: `verdict.css` is a static file and cannot read it, so the four
`@font-face` URLs at its top carry their own version, `?v=` and the first 8 hex digits of each file's SHA-256. When a
file changes, set its `?v=` to the new value:

```
sha256sum OpenBench/static/fonts/VerdictMono-*.woff2 | cut -c1-8
```

value to use.
