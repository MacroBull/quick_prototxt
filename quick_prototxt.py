#! /usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Created on Sun Sep 15 22:09:46 2019

@author: Macrobull
"""

from __future__ import absolute_import, division, unicode_literals

import logging, re
import yaml


DELIMITER       :str = '@'
UNAME_ID_FORMAT :str = '{:09d}'


logger :logging.Logger = logging.getLogger(__name__)

if hasattr(yaml, 'cyaml'):
    loader :yaml.Loader = yaml.CSafeLoader
    dumper :yaml.Dumper = yaml.CSafeDumper
else:
    logger.warning('cYAML not enabled, using pyYAML implementation may impact performance')

    loader :yaml.Loader = yaml.SafeLoader
    dumper :yaml.Dumper = yaml.SafeDumper


def load_prototxt(
        s:str,
        **load_kwargs)->'Any':
    r"""
    direct deserialize from Protobuf text format
    load_kwargs: kwargs for 'yaml.load', leave it empty
    """

    # HINT: in fact no load_kwargs required
    load = lambda s: yaml.load(s, Loader=loader, **load_kwargs)

    if not re.search(r'^\s*\w+\s*[{:]', s): # if scalar
        return load(s)

    unames = dict()

    def replace_key(s):
        t = []
        start = 0
        idx = 0
        for m in re.finditer(r'(\n\s*)(\w+)\s*:', s):
            prefix, ok = m.groups()
            nk = ok + DELIMITER + UNAME_ID_FORMAT.format(idx)
            unames[nk] = ok
            t.extend([s[start:m.start()], prefix, nk, ':'])
            start = m.end()
            idx += 1
        t.append(s[start:])
        return ''.join(t)

    def restore_key(no):
        oo = type(no)()
        for nk, nv in no.items():
            ok = unames[nk]
            nv = restore_key(nv) if isinstance(nv, dict) else nv
            ov = oo.get(ok)
            if ov is None:
                oo[ok] = nv
            else:
                if not isinstance(ov, list):
                    oo[ok] = [ov]
                oo[ok].append(nv)
        return oo

    s = '\n' + s + '\n'
    s = re.sub(r'\s+\n', '\n', s) # rstrip each line
    s = re.sub(r'(?<=\w)\s*{\n', ': {\n', s) # add : for field
    s = replace_key(s)
    s = re.sub(r'(?<=[^{\s])\n', ',\n', s) # add, for flow mapping
    s = '{' + s + '}' # simply

    # NOTE: Python 3 built-in ordered dict makes repeated fields parsing perfect
    # see yaml/constructor.py: BaseConstructor.construct_mapping for details
    o = load(s)

    return restore_key(o)


def dump_prototxt(
        o:'Any',
        unquote_rule:'Callable[str, bool]'=str.isupper,
        quote:str='"', indent:int=2,
        **dump_kwargs)->str:
    r"""
    direct serialize to Protobuf text format
    unquote_rule:
        function judges wether a string value should not be quoted for types like enum,
        by default full-uppercased
    quote: prefered quote convension, ' or "
    indent: indent size
    dump_kwargs: kwargs for 'yaml.dump'
    """

    list_clss = (list, tuple, set)

    assert not isinstance(o, list_clss), "'o' cannot be unnamed list"

    dump_kwargs_ = dict(
            indent=indent, width=(indent * 2 + 1),
            default_flow_style=True, allow_unicode=True,
            )
    dump_kwargs_.update(dump_kwargs)
    dump = lambda o: yaml.dump(o, Dumper=dumper, **dump_kwargs_)

    def remove_document_end(s):
        t = '\n...'
        if s.endswith(t):
            s = s[:-len(t)]
        return s

    if not isinstance(o, dict): # extra scalar support
        if isinstance(o, str):
            s = quote + o + quote
        else:
            s = dump(o)
            s = s.strip()
            s = remove_document_end(s)
        return s + '\n'

    str_tag = '!str '
    str_re = re.compile(r'([\'"])' + str_tag + r'(.*)([\'"])\s*\n')

    def replace_key_value(oo):
        no = type(oo)()
        for ok, ov in oo.items():
            if isinstance(ov, dict):
                no[ok] = replace_key_value(ov)
            elif isinstance(ov, str):
                no[ok] = str_tag + ov
            elif isinstance(ov, list_clss):
                prefix = str(ok) + DELIMITER
                for idx, oi in enumerate(ov):
                    assert not isinstance(oi, list_clss), 'list item cannot be unnamed list'

                    nk = prefix + UNAME_ID_FORMAT.format(idx) # make key ordered
                    ni = replace_key_value(oi) if isinstance(oi, dict) else oi
                    no[nk] = ni
            else:
                no[ok] = ov
        return no

    def restore_key(s):
        t = []
        start = 0
        for m in re.finditer(r'(\n\s*)(\w+)' + DELIMITER + r'\d+\s*:', s):
            prefix, ok = m.groups()
            t.extend([s[start:m.start()], prefix, ok, ':'])
            start = m.end()
        t.append(s[start:])
        return ''.join(t)

    def fix_mapping_end_break(s):
        t = []
        start = 0
        current_space_size = 0
        for m in re.finditer(r'\n(\s*)(.+?)({*)(}*)(?=\n)', s):
            spaces, content, lbraces, rbraces = m.groups()

            t.append(s[start:m.start()])

            if len(spaces) > current_space_size:
                assert len(spaces) == current_space_size + indent

                spaces = spaces[:current_space_size]
                t.extend([' ', content])
            else:
                assert len(spaces) == current_space_size

                t.extend(['\n', spaces, content])

            t.append(lbraces)
            current_space_size += indent * len(lbraces)
            assert current_space_size >= len(rbraces) * indent

            for brace in rbraces:
                spaces = spaces[:-indent]
                t.extend(['\n', spaces, brace])
            current_space_size -= indent * len(rbraces)

            start = m.end()
        t.append(s[start:])
        return ''.join(t)

    def fix_value_quote(s):
        t = []
        start = 0
        for m in re.finditer(r'(?<=\n)(\s*)(\w+)(:\s*)(.+?)(\s*\n)', s):
            s0, key, s1, value, s2 = m.groups()

            values = [value]
            str_match = str_re.match(value + s2)
            if str_match:
                lquote, value, rquote = str_match.groups()
                if lquote == rquote:
                    if unquote_rule(value):
                        values = [value]
                    else:
                        if lquote != quote and quote not in value: # HINT: not forced
                            lquote = quote
                        values = [lquote, value, lquote]

            t.extend([s[start:m.start()], s0, key, s1])
            t.extend(values)
            t.append(s2)

            start = m.end()
        t.append(s[start:])
        return ''.join(t)

    o = replace_key_value(o)
    # HINT: ~ canonical=True
    s = dump(o)
    s = '\n' + s.strip()[1: -1].replace('\n  ', '\n') + '\n' # remove root flow mapping brace
    s = restore_key(s)
    s = s.replace(',\n', '\n').replace(': {', ' {') # remove , and :)
    s = fix_mapping_end_break(s)
    s = fix_value_quote(s)
    return s[1:]


if __name__ == '__main__':
    o = 'hello world'
    t = dump_prototxt(o)
    print(t)
    o = load_prototxt(t)
    print(o)
    print('-' * 8)
    o = {'hello': [{'world': 42}, {'what': False}, {'enum': 'DEBUG'}]}
    t = dump_prototxt(o)
    print(t)
    o = load_prototxt(t)
    print(o)
    print('-' * 8)
    o = {'y': [1, 2], 'x': [{'a': 3.0, 'b': {'c': 4}}, {'a': 0, 'z': '1 2 3 4'}]}
    t = dump_prototxt(o)
    print(t)
    o = load_prototxt(t)
    print(o)
    print('-' * 8)
