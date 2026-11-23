"""Resolve explicit alphabetic Word list labels for preserved-formula views."""
from lxml import etree
from . import ns


def read_numbering(data):
    if not data:
        return {}
    root = etree.fromstring(data)
    abstracts = {item.get(ns.q('w', 'abstractNumId')): item for item in root.findall(ns.q('w', 'abstractNum'))}
    definitions = {}

    def value(parent, name, default):
        child = parent.find(ns.q('w', name))
        return child.get(ns.q('w', 'val'), default) if child is not None else default

    for number in root.findall(ns.q('w', 'num')):
        abstract = abstracts.get(value(number, 'abstractNumId', ''))
        if abstract is None:
            continue
        levels = {level.get(ns.q('w', 'ilvl'), '0'): level for level in abstract.findall(ns.q('w', 'lvl'))}
        starts = {}
        for override in number.findall(ns.q('w', 'lvlOverride')):
            index = override.get(ns.q('w', 'ilvl'), '0')
            custom = override.find(ns.q('w', 'lvl'))
            if custom is not None:
                levels[index] = custom
            starts[index] = value(override, 'startOverride', None)
        for index, level in levels.items():
            definitions[(number.get(ns.q('w', 'numId')), index)] = {
                'format': value(level, 'numFmt', ''), 'text': value(level, 'lvlText', ''),
                'start': int(starts.get(index) or value(level, 'start', '1'))}
    return definitions


def paragraph_label(paragraph, definitions, counters):
    properties = paragraph.find(ns.q('w', 'pPr'))
    number = properties.find(ns.q('w', 'numPr')) if properties is not None else None
    if number is None:
        return ''
    identifier = number.find(ns.q('w', 'numId'))
    level = number.find(ns.q('w', 'ilvl'))
    key = (identifier.get(ns.q('w', 'val')) if identifier is not None else '',
           level.get(ns.q('w', 'val'), '0') if level is not None else '0')
    definition = definitions.get(key)
    if not definition or definition['format'] not in {'upperLetter', 'lowerLetter'}:
        return ''
    marker = '%' + str(int(key[1]) + 1)
    if definition['text'] not in {marker + '.', marker + ')'}:
        return ''
    counters[key] = counters.get(key, definition['start'] - 1) + 1
    value = counters[key]
    letters = ''
    while value > 0:
        value, digit = divmod(value - 1, 26)
        letters = chr(ord('A') + digit) + letters
    if definition['format'] == 'lowerLetter':
        letters = letters.lower()
    return definition['text'].replace(marker, letters) + ' '
