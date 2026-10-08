from __future__ import annotations

import re
import os
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tests.test_course_outline_alignment import schedule_titles
from tests.course_assets import (has_lesson_marker, local_slide_decks,
                                normalized_slide_text, presentation_slide_texts,
                                published_docs)


ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / "docs" / "courses"
BLUEPRINT = COURSES / "课程蓝图.md"
SLIDES = COURSES / "slides"


def pptx_name(number: int, title: str) -> str:
    stem = f"L{number:02d}-{title.replace('`', '')}"
    stem = re.sub(r'[<>:"/\\|?*]', "-", stem)
    stem = re.sub(r"\s+", "", stem)
    stem = re.sub(r"-+", "-", stem)
    return f"{stem}.pptx"


def slide_text(archive: zipfile.ZipFile, number: int) -> str:
    root = ET.fromstring(archive.read(f"ppt/slides/slide{number}.xml"))
    return "".join(root.itertext())


def normalized(text: str) -> str:
    return re.sub(r"[`\s]", "", text)


class CourseBlueprintTests(unittest.TestCase):
    def test_blueprint_connects_teacher_design_to_the_authoritative_outline(self) -> None:
        body = BLUEPRINT.read_text(encoding="utf-8")
        self.assertRegex(body, r"教师|备课")
        self.assertRegex(body, r"教学活动|学生参与的活动")
        self.assertRegex(body, r"评价证据|教师核对的直接证据")
        self.assertIn("试讲", body)
        self.assertRegex(body, r"\]\(\.\./课程大纲-Codex-FDE行动营-个人研发自动化工作台\.md(?:#[^)]*)?\)")
        self.assertRegex(body, r"\]\(\.\./README\.md(?:#[^)]*)?\)")
        for number in range(1, 7):
            with self.subTest(objective=number):
                self.assertIn(f"CLO-{number}", body)

    def test_blueprint_preserves_learning_support_and_local_slide_validation_boundary(self) -> None:
        body = BLUEPRINT.read_text(encoding="utf-8")
        for marker in (
            "不超过 30 分钟",
            "教师示范",
            "学生尝试",
            "独立检查",
            "正常路径",
            "失败路径",
            "学生是否掌握",
        ):
            self.assertIn(marker, body)
        self.assertIn("## 本地课件检查", body)
        self.assertIn("CODEXFDE_VALIDATE_LOCAL_SLIDES", body)
        self.assertIn("tests.test_course_pptx", body)
        self.assertIn("tests.test_course_ppt_endings", body)
        self.assertRegex(body, r"逐页渲染|逐页检查")

    def test_editable_course_diagrams_and_previews_exist(self) -> None:
        for stem in ("course-three-layer", "workbench-capability-growth", "fde-feedback-loop"):
            source = COURSES / "assets" / f"{stem}.drawio"
            self.assertTrue(source.is_file())
            self.assertTrue((COURSES / "assets" / f"{stem}.svg").is_file())
            ET.parse(source)

    @unittest.skipUnless(os.environ.get('CODEXFDE_VALIDATE_LOCAL_SLIDES') == '1',
                         'PPT 不随 Git 发布；显式启用本地课件检查')
    def test_each_lesson_has_valid_local_decks(self) -> None:
        expected_titles = schedule_titles()
        for number, title in expected_titles.items():
            decks = local_slide_decks(number)
            self.assertTrue(decks, f'L{number:02d} 缺少本地课件')
            for deck in decks:
                with self.subTest(deck=deck.name), zipfile.ZipFile(deck) as archive:
                    self.assertIsNone(archive.testzip())
                    names = [name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
                    self.assertTrue(names, '课件必须包含幻灯片')
                    for name in names:
                        ET.fromstring(archive.read(name))
                    cover = presentation_slide_texts(archive)[0]
                    self.assertTrue(has_lesson_marker(cover, number),
                                    f'{deck.name} 封面缺少正确讲次 L{number:02d} / 第 {number:02d} 讲')
                    self.assertIn(normalized_slide_text(title), normalized_slide_text(cover),
                                  f'{deck.name} 封面标题须与正式课表一致')

    def test_no_inspection_outputs_are_published_with_student_materials(self) -> None:
        self.assertFalse([p for p in published_docs() if p.name.endswith('.inspect.ndjson')])


if __name__ == "__main__":
    unittest.main()
