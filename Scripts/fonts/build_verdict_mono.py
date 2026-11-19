#!/usr/bin/env python3
"""Build Verdict Mono, the UI font, from DejaVu Sans Mono 2.37: four woff2 weights (see README.md)."""

import argparse
import os
import sys

import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import ttProgram

FAMILY = 'Verdict Mono'
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'OpenBench', 'static', 'fonts')

WEIGHTS = [
    ('Regular',  'book', 400,  0),
    ('Medium',   'book', 500, 10),
    ('SemiBold', 'book', 600, 20),
    ('Bold',     'bold', 700,  0),
]

HINTING_TABLES = ('fpgm', 'prep', 'cvt ', 'hdmx', 'LTSH', 'VDMX')
FONT_NAME_IDS = (1, 2, 3, 4, 6, 16, 17)


def grow_outline(glyph_set, name, delta):
    bounds = BoundsPen(glyph_set)
    glyph_set[name].draw(bounds)
    if not bounds.bounds:
        return None
    _, y0, _, y1 = bounds.bounds

    path = pathops.Path()
    glyph_set[name].draw(path.getPen())
    stroke = pathops.Path(path)
    stroke.stroke(2 * delta, pathops.LineCap.BUTT_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    stroke.convertConicsToQuads()
    try:
        grown = pathops.op(path, stroke, pathops.PathOp.UNION, fix_winding=True)
    except pathops.PathOpsError:
        try:
            path.simplify(fix_winding=True)
            stroke.simplify(fix_winding=True)
            grown = pathops.op(path, stroke, pathops.PathOp.UNION, fix_winding=True)
        except pathops.PathOpsError:
            return None
    grown.convertConicsToQuads()

    height = y1 - y0
    sy = height / (height + 2 * delta) if height > 0 else 1.0
    ty = y0 - (y0 - delta) * sy
    pen = TTGlyphPen(None)
    grown.draw(Cu2QuPen(TransformPen(pen, (1, 0, 0, sy, 0, ty)), max_err=1.0, reverse_direction=False))
    return pen.glyph()


def embolden(font, delta):
    glyf, glyph_set = font['glyf'], font.getGlyphSet()
    kept = []
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.isComposite() or glyph.numberOfContours <= 0:
            continue
        grown = grow_outline(glyph_set, name, delta)
        if grown is None:
            kept.append(name)
        else:
            glyf[name] = grown

    for tag in HINTING_TABLES:
        if tag in font:
            del font[tag]
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if hasattr(glyph, 'program') or glyph.isComposite():
            glyph.program = ttProgram.Program()
            glyph.program.fromBytecode(b'')
    font['maxp'].maxSizeOfInstructions = 0
    gasp = newTable('gasp')
    gasp.version, gasp.gaspRange = 1, {0xFFFF: 0x000A}
    font['gasp'] = gasp

    hmtx = font['hmtx']
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.isComposite() or glyph.numberOfContours > 0:
            glyph.recalcBounds(glyf)
            hmtx[name] = (hmtx[name][0], glyph.xMin)
    return kept


def rename(font, style, weight):
    ribbi = style in ('Regular', 'Bold')
    legacy_family = FAMILY if ribbi else '%s %s' % (FAMILY, style)
    legacy_style = style if ribbi else 'Regular'
    version = font['name'].getDebugName(5) or 'Version 2.37'
    number = version.replace('Version ', '')
    postscript = 'VerdictMono-' + style
    records = {
        1: legacy_family,
        2: legacy_style,
        3: '%s;%s' % (postscript, number),
        4: FAMILY if style == 'Regular' else '%s %s' % (FAMILY, style),
        5: version,
        6: postscript,
        10: ('%s, from DejaVu Sans Mono %s%s, for Verdict. Renamed as its licence requires.'
             % (style, number, '' if ribbi else ' Book with outlines offset outward')),
    }
    if not ribbi:
        records[16], records[17] = FAMILY, style

    name = font['name']
    keep = {0, 8, 11, 13, 14}
    name.names = [r for r in name.names if r.nameID in keep]
    for name_id, text in sorted(records.items()):
        name.setName(text, name_id, 1, 0, 0)
        name.setName(text, name_id, 3, 1, 0x409)

    os2 = font['OS/2']
    os2.usWeightClass = weight
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (1 << 5 if style == 'Bold' else 1 << 6)
    font['head'].macStyle = 1 if style == 'Bold' else 0
    font['post'].isFixedPitch = 1

    leaked = [(r.nameID, r.toUnicode()) for r in name.names if r.nameID in FONT_NAME_IDS
              and any(word in r.toUnicode() for word in ('Bitstream', 'Vera'))]
    if leaked:
        sys.exit('a font name still mentions "Bitstream" or "Vera": %r' % leaked)


def check_source(font, path, weight):
    family = font['name'].getDebugName(1)
    if family != 'DejaVu Sans Mono' or font['OS/2'].usWeightClass != weight:
        sys.exit('%s: expected DejaVu Sans Mono at weight %d, found %r at %d'
                 % (path, weight, family, font['OS/2'].usWeightClass))
    version = font['name'].getDebugName(5)
    if version != 'Version 2.37':
        print('warning: %s is %s; Verdict Mono was built from 2.37' % (path, version), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('book', help='DejaVuSansMono.ttf (Book)')
    parser.add_argument('bold', help='DejaVuSansMono-Bold.ttf')
    parser.add_argument('--out', default=DEFAULT_OUT, help='output directory (default: OpenBench/static/fonts)')
    args = parser.parse_args()
    sources = {'book': (args.book, 400), 'bold': (args.bold, 700)}
    os.makedirs(args.out, exist_ok=True)

    for style, source, weight, delta in WEIGHTS:
        path, source_weight = sources[source]
        font = TTFont(path, recalcTimestamp=False)
        check_source(font, path, source_weight)
        if 'FFTM' in font:
            del font['FFTM']
        kept = embolden(font, delta) if delta else []
        rename(font, style, weight)
        font.flavor = 'woff2'
        out = os.path.join(args.out, 'VerdictMono-%s.woff2' % style)
        font.save(out)
        print('%-28s %d  %7d bytes%s' % (os.path.basename(out), weight, os.path.getsize(out),
                                          '  (kept Book outlines: %s)' % ' '.join(kept) if kept else ''))


if __name__ == '__main__':
    main()
