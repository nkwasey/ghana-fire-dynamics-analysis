"""Inspect local Markdown links using CommonMark tokens and heading identifiers.

Heading fragments follow conventional GitHub-style IDs, including duplicate
suffixes. Explicit HTML IDs and named anchors are also recognised. A renderer
without automatic heading IDs may still need fragment-free entry links; the
runbook checks that separately. Code examples do not create links or anchors.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


class _HTMLTargets(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.anchors.add(values['id'])
        if tag.lower() == 'a':
            if values.get('name'):
                self.anchors.add(values['name'])
            if values.get('href'):
                self.links.append(values['href'])
        elif tag.lower() == 'img' and values.get('src'):
            self.links.append(values['src'])

    handle_startendtag = handle_starttag


def _html(content):
    parser = _HTMLTargets()
    parser.feed(content)
    parser.close()
    return parser


def _heading_text(token):
    return ''.join(
        child.content if child.type in {'text', 'code_inline', 'image'} else
        ' ' if child.type in {'softbreak', 'hardbreak'} else ''
        for child in (token.children or [])
    ).strip()


def _heading_slug(value):
    value = ''.join(
        character for character in value.lower()
        if character in '-_' or character.isspace()
        or unicodedata.category(character)[0] in 'LNM'
    )
    return re.sub(r'\s', '-', value)


def document_targets(text):
    """Return explicit/generated anchor IDs and actual link/image targets."""
    tokens = MarkdownIt().parse(text)
    explicit, generated, links = set(), set(), []
    for index, token in enumerate(tokens):
        line = token.map[0] + 1 if token.map else 1
        if token.type == 'heading_open':
            stem = _heading_slug(_heading_text(tokens[index + 1]))
            candidate, suffix = stem, 0
            while candidate in generated:
                suffix += 1
                candidate = stem + '-' + str(suffix)
            generated.add(candidate)
        if token.type == 'html_block':
            html = _html(token.content)
            explicit.update(html.anchors)
            links.extend((target, line) for target in html.links)
        elif token.type == 'inline':
            for child in token.children or []:
                if child.type == 'link_open':
                    links.append((child.attrGet('href'), line))
                elif child.type == 'image':
                    links.append((child.attrGet('src'), line))
                elif child.type == 'html_inline':
                    html = _html(child.content)
                    explicit.update(html.anchors)
                    links.extend((target, line) for target in html.links)
    return explicit | generated, links


def local_link_issues(document):
    """Check file existence and Markdown fragments, ignoring external URLs."""
    document = Path(document)
    anchors, links = document_targets(document.read_text(encoding='utf-8'))
    issues = []
    for target, line in links:
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            continue
        filename, fragment = unquote(parts.path), unquote(parts.fragment)
        destination = document.parent / filename if filename else document
        if not destination.is_file():
            issues.append({'line': line, 'target': target, 'reason': 'missing file'})
        elif fragment and destination.suffix.lower() == '.md':
            known = anchors if destination == document else document_targets(
                destination.read_text(encoding='utf-8'))[0]
            if fragment not in known:
                issues.append({'line': line, 'target': target, 'reason': 'missing fragment'})
    return issues
