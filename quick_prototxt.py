#! /usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Created on Sun Sep 15 22:09:46 2019

@author: Macrobull
"""

from __future__ import absolute_import, division, unicode_literals

import logging, re
import yaml


DELIMITER :str = '@'


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
    direct deserialize from ProtoBuffer text format
    load_kwargs: kwargs for 'yaml.load', leave it empty
    """

    # HINT: in fact no load_kwargs required
    load = lambda s: yaml.load(s, Loader=loader, **load_kwargs)

    if not re.search(r'^\s*\w+\s*[{:]', s): # if scalar
        return load(s)

    unames = dict()

    def replace_key(s):
        t = ''
        start = 0
        idx = 0
        for m in re.finditer(r'(\n\s*)(\w+)\s*:', s):
            prefix, ok = m.groups()
            nk = ok + DELIMITER + f'{idx:09}'
            unames[nk] = ok
            t += s[start:m.start()]
            t += prefix + nk + ':'
            start = m.end()
            idx += 1
        return t + s[start:]

    def restore_key(no):
        oo = type(no)()
        for nk, nv in no.items():
            ok = unames[nk]
            nv = restore_key(nv) if isinstance(nv, dict) else nv
            ov = oo.get(ok, None)
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
        quote_rule:'Optional[Callable]'=None,
        quote:str='"', indent:int=2,
        **dump_kwargs)->str:
    r"""
    direct serialize to ProtoBuffer text format
    quote_rule:
        function judges wether a non-quoted and non-numeric value string should be quoted
        by default non-bool and non-uppercase
    quote: quote conversion, ' or "
    indent: indent size
    dump_kwargs: kwargs for 'yaml.dump'
    """

    list_clss = (list, tuple, set)
    dump_kwargs_ = dict(
            indent=indent, width=(indent * 2 + 1),
            default_flow_style=True, allow_unicode=True,
            )
    dump_kwargs_.update(dump_kwargs)
    dump = lambda o: yaml.dump(o, Dumper=dumper, **dump_kwargs_)
    is_quoted = lambda s: (
            s.startswith('"') and s.endswith('"') or s.startswith("'") and s.endswith("'"))

    def is_numeric(s):
        if re.match(r'-?inf(?:inity)?f?', s, re.IGNORECASE):
            return True
        if re.match(r'nanf?', s, re.IGNORECASE):
            return True
        try:
            float(s.rstrip('f'))
            return True
        except ValueError:
            return False

    if quote_rule is None:
        quote_rule = lambda s: not (
                s == 'true' or s == 'false' or s == 'True' or s == 'False' or
                s.isupper()) # or s.istitle()) # HINT: enum convensions

    assert not isinstance(o, list_clss), "'o' cannot be unnamed list"

    def remove_document_end(s):
        t = '\n...'
        if s.endswith(t):
            s = s[:-len(t)]
        return s

    if not isinstance(o, dict): # if scalar
        s = dump(o)
        s = s.strip()
        s = remove_document_end(s)
        if not is_quoted(s) and not is_numeric(s) and quote_rule(s):
            s = quote + s + quote
        return s + '\n'

    def replace_key(oo):
        no = type(oo)()
        for ok, ov in oo.items():
            if isinstance(ov, dict):
                no[ok] = replace_key(ov)
            elif isinstance(ov, list_clss):
                prefix = str(ok) + DELIMITER
                for idx, oi in enumerate(ov):
                    assert not isinstance(oi, list_clss), 'list item cannot be unnamed list'

                    nk = prefix + f'{idx:09}' # make key ordered
                    ni = replace_key(oi) if isinstance(oi, dict) else oi
                    no[nk] = ni
            else:
                no[ok] = ov
        return no

    def restore_key(s):
        t = ''
        start = 0
        for m in re.finditer(r'(\n\s*)(\w+)' + DELIMITER + r'\d+\s*:', s):
            prefix, ok = m.groups()
            t += s[start:m.start()]
            t += prefix + ok + ':'
            start = m.end()
        s = t + s[start:]
        return s

    def fix_mapping_end_break(s):
        t = ''
        start = 0
        current_space_size = 0
        for m in re.finditer(r'\n(\s*)(.+?)({*)(}*)(?=\n)', s):
            spaces, content, lbraces, rbraces = m.groups()

            t += s[start:m.start()]

            if len(spaces) > current_space_size:
                assert len(spaces) == current_space_size + indent

                spaces = spaces[:current_space_size]
                t += ' ' + content
            else:
                assert len(spaces) == current_space_size

                t += '\n' + spaces + content

            for brace in lbraces:
                t += brace
                current_space_size += indent

            assert current_space_size >= len(rbraces) * indent

            for brace in rbraces:
                spaces = spaces[:-indent]
                t += '\n' + spaces + brace
                current_space_size -= indent

            start = m.end()
        return t + s[start:]

    def fix_value_quote(s):
        t = ''
        start = 0
        for m in re.finditer(r'(?<=\n)(\s*)(\w+)(:\s*)(.+?)(\s*\n)', s):
            s0, key, s1, value, s2 = m.groups()

            if not is_quoted(value) and not is_numeric(value) and quote_rule(value):
                value = quote + value + quote

            t += s[start:m.start()]
            t += s0 + key + s1 + value + s2

            start = m.end()
        return t + s[start:]

    o = replace_key(o)
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
    t = dump_prototxt(o, quote_rule=(lambda s: ' ' in s))
    print(t)
    o = load_prototxt(t)
    print(o)
    print('-' * 8)
    o = {'hello': [{'world': 42}, {'what': False}]}
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
