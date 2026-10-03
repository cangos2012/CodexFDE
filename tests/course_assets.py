"""Publication boundaries shared by course checks; local decks are opt-in QA."""
from pathlib import Path
import posixpath
import re
import subprocess
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / 'docs' / 'courses'
P_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def local_slide_decks(number: int, courses: Path = COURSES) -> list[Path]:
    """Inventory current packages in the lesson root and direct slides folder."""
    lesson = courses / f'L{number:02d}'
    return sorted(path for directory in (lesson, lesson / 'slides')
                  if directory.is_dir() for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() == '.pptx'
                  and not path.name.startswith('~$'))


def local_slide_review_targets(number: int, courses: Path = COURSES) -> tuple[list[Path], Path | None]:
    """Use a current material's explicit link; otherwise review every candidate.

    A filename or modification date does not establish an adopted teaching
    version. A missing/ambiguous link leaves the selection unconfirmed.
    """
    decks = local_slide_decks(number, courses)
    available = {path.resolve(): path for path in decks}
    lesson = courses / f'L{number:02d}'
    for source in (lesson / 'README.md', lesson / '辅导资料.md',
                   lesson / '实践操作手册.md', lesson / '参考详解.md',
                   courses / '课程蓝图.md'):
        if not source.is_file():
            continue
        references = set()
        for link in re.findall(r'\]\(([^\n)]+)\)', source.read_text(encoding='utf-8')):
            target = urlsplit(link.strip().strip('<>'))
            if target.scheme or target.netloc:
                continue
            path = (source.parent / unquote(target.path)).resolve()
            if path in available:
                references.add(path)
        if len(references) == 1:
            return [available[references.pop()]], source
        if references:
            return decks, None
    return decks, None


def presentation_slide_parts(package: ZipFile) -> list[str]:
    """Follow presentation order, which need not match slide XML numbering."""
    presentation = ET.fromstring(package.read('ppt/presentation.xml'))
    relationships = ET.fromstring(package.read('ppt/_rels/presentation.xml.rels'))
    targets = {item.attrib['Id']: item for item in relationships.findall(f'{{{REL_NS}}}Relationship')}
    parts = []
    for slide in presentation.findall(f'./{{{P_NS}}}sldIdLst/{{{P_NS}}}sldId'):
        relationship_id = slide.attrib[f'{{{R_NS}}}id']
        relationship = targets.get(relationship_id)
        if relationship is None or relationship.get('TargetMode') == 'External':
            raise AssertionError(f'幻灯片关系缺失或指向外部：{relationship_id}')
        if relationship.get('Type') != f'{R_NS}/slide':
            raise AssertionError(f'不是幻灯片关系：{relationship_id}')
        target = relationship.attrib['Target'].replace('\\', '/')
        part = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                                 else posixpath.join('ppt', target))
        if not part.startswith('ppt/slides/') or part not in package.namelist():
            raise AssertionError(f'幻灯片部件不存在或越界：{target}')
        parts.append(part)
    if not parts:
        raise AssertionError('课件没有幻灯片')
    if len(parts) != len(set(parts)):
        raise AssertionError('课件重复引用同一幻灯片')
    return parts


def presentation_slide_texts(package: ZipFile) -> list[str]:
    slides = []
    for part in presentation_slide_parts(package):
        root = ET.fromstring(package.read(part))
        paragraphs = []
        for paragraph in root.findall(f'.//{{{A_NS}}}p'):
            # A font/style change starts a new run, not a new statement.
            # Paragraphs and explicit line breaks retain their boundaries.
            text = ''.join('\n' if node.tag == f'{{{A_NS}}}br' else node.text or ''
                           for node in paragraph.iter()
                           if node.tag in {f'{{{A_NS}}}t', f'{{{A_NS}}}br'})
            if text.strip():
                paragraphs.append(text)
        if not paragraphs:
            paragraphs = [node.text or '' for node in root.findall(f'.//{{{A_NS}}}t')]
        slides.append('\n'.join(paragraphs))
    return slides


def has_lesson_marker(text: str, number: int) -> bool:
    return bool(re.search(rf'(?<![A-Za-z0-9])L\s*0*{number}(?!\d)', text)
                or re.search(rf'第\s*0*{number}\s*讲', text))


def normalized_slide_text(text: str) -> str:
    # Layout can split runs or punctuation without changing the Chinese title.
    return re.sub(r'[\W_]+', '', text)


def local_only(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(ROOT)
    except ValueError:
        return False
    return relative.parts[0] == 'docs' and (
        'slides' in relative.parts or '教师资料' in relative.parts or path.suffix.lower() == '.pptx')


def published_docs() -> list[Path]:
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'docs'],
        cwd=ROOT, capture_output=True, check=True)
    return sorted({ROOT / name for name in result.stdout.decode('utf-8').split('\0')
                   if name and (ROOT / name).is_file() and not local_only(ROOT / name)})
