from __future__ import annotations

import re
import unittest
import tempfile
from pathlib import Path
from urllib.parse import unquote

from workbench.course_mainline import LESSONS
from tests.course_assets import local_only, published_docs


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
COURSES = DOCS / "courses"
SCHEDULE = DOCS / "课表｜Codex AI 工程交付行动营.md"
OUTLINE = DOCS / "课程大纲-Codex-FDE行动营-个人研发自动化工作台.md"


def schedule_titles() -> dict[int, str]:
    body = SCHEDULE.read_text(encoding="utf-8")
    return {
        int(number): title.strip()
        for number, title in re.findall(r"^\|\s*(\d{2})\s*\|([^|]+)\|", body, re.MULTILINE)
    }


def lesson_files(directory: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for number in range(1, 17):
        canonical = directory / f"L{number:02d}" / "辅导资料.md"
        if directory.name == "tasks":
            canonical = directory.parent / f"L{number:02d}" / "行动卡.md"
        if canonical.is_file():
            result[number] = canonical
    for path in sorted(directory.glob("L??-*.md")):
        if path.name.endswith("-教师备课说明.md"):
            continue
        number = int(path.name[1:3])
        if 1 <= number <= 16:
            if number in result:
                # Small migration pointers are aliases, not a second handout.
                body = path.read_text(encoding="utf-8")
                targets = re.findall(r"<!-- course-alias: (.+?) -->", body)
                if len(targets) == 1 and (path.parent / targets[0]).resolve() == result[number].resolve():
                    continue
                raise AssertionError(f"L{number:02d} 有重复课程文件：{result[number].name}、{path.name}")
            result[number] = path
    return result


def outline_contracts() -> dict[int, tuple[str, tuple[str, ...]]]:
    body = OUTLINE.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^#### 第 (\d+) 讲｜(.+)$", body, re.MULTILINE))
    contracts: dict[int, tuple[str, tuple[str, ...]]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[match.end():end]
        lines = tuple(
            line.strip()
            for line in section.splitlines()
            if re.match(r"^- \*\*(核心内容|演示结果|课内增量|通过标准)\*\*：", line)
        )
        contracts[number] = (match.group(2).strip(), lines)
    return contracts


def markdown_anchors(body: str) -> set[str]:
    anchors = set(re.findall(r'<[^>]+\bid=["\']([^"\']+)["\']', body))
    occurrences: dict[str, int] = {}
    in_fence = False
    for line in body.splitlines():
        if re.match(r"^\s*(?:```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if not heading:
            continue
        label = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading.group(1))
        slug = re.sub(r"[^\w\s-]", "", label.lower())
        slug = re.sub(r"\s", "-", slug)
        suffix = occurrences.get(slug, 0)
        occurrences[slug] = suffix + 1
        anchors.add(f"{slug}-{suffix}" if suffix else slug)
    return anchors


class CourseOutlineAlignmentTests(unittest.TestCase):
    def test_discovery_excludes_teacher_notes_and_rejects_duplicate_student_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            handout = root / "L01-学生讲义.md"
            handout.touch()
            (root / "L01-教师备课说明.md").touch()
            self.assertEqual({1: handout}, lesson_files(root))
            (root / "L01-另一份讲义.md").touch()
            with self.assertRaisesRegex(AssertionError, "重复课程文件"):
                lesson_files(root)

    def test_migration_alias_must_point_to_the_canonical_handout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / 'L03/辅导资料.md'
            canonical.parent.mkdir()
            canonical.write_text('# Current chapter', encoding='utf-8')
            alias = root / 'L03-旧入口.md'
            alias.write_text('<!-- course-alias: L03/辅导资料.md -->', encoding='utf-8')
            self.assertEqual({3: canonical}, lesson_files(root))
            alias.write_text('<!-- course-alias: missing.md -->', encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, '重复课程文件'):
                lesson_files(root)

    def test_student_entry_and_new_directory_contract_exist(self) -> None:
        for path in (
            DOCS / "README.md",
            COURSES / "课程蓝图.md",
            COURSES / "FlowERP-AI研发工作台.code-workspace",
            COURSES / "行动卡索引.md",
            COURSES / "labs",
            DOCS / "reference" / "个人AI研发工作台.md",
            DOCS / "reference" / "FlowERP领域模型与业务不变量.md",
            DOCS / "reference" / "FlowERP接口与运行边界.md",
        ):
            self.assertTrue(path.exists(), path)
        self.assertFalse((ROOT / "course").exists())
        self.assertEqual(
            {f"L{number:02d}" for number in range(0, 17) if number != 1},
            {path.name for path in (COURSES / "labs").glob("L??") if path.is_dir()},
        )

    def test_repository_has_no_legacy_course_material_paths(self) -> None:
        stale: list[str] = []
        suffixes = {".md", ".py", ".json", ".yml", ".yaml", ".js", ".html", ".toml", ".code-workspace"}
        legacy_paths = (
            "course/tasks/",
            "course/labs/",
            "course/FlowERP-AI研发工作台.code-workspace",
            "course/repair-output.schema.json",
            "course/baselines/PROGRESSION.json",
        )
        source_roots = [ROOT / name for name in ("docs", "scripts", "tests", "eval", "workbench")]
        paths = [ROOT / name for name in ("README.md", "AGENTS.md", ".gitignore")]
        for source_root in source_roots:
            paths.extend(path for path in source_root.rglob("*") if path.is_file())
        for path in paths:
            if path.suffix not in suffixes and path.name != ".gitignore":
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            body = body.replace("/api/v1/course/tasks/", "")
            for legacy in legacy_paths:
                # These occurrences describe migration of historical Git tags,
                # not a live student entry. Other obsolete paths remain errors.
                if legacy == "course/baselines/PROGRESSION.json" and path.relative_to(ROOT).as_posix() in {
                    "workbench/lesson_constructibility.py", "tests/test_lesson_constructibility.py",
                    "docs/courses/逐讲实现与教学审计.md",
                }:
                    continue
                if legacy in body:
                    stale.append(f"{path.relative_to(ROOT)} -> {legacy}")
        self.assertFalse(stale, "\n".join(stale))

    def test_schedule_outline_machine_handouts_and_tasks_share_titles(self) -> None:
        expected = schedule_titles()
        contracts = outline_contracts()
        handouts = lesson_files(COURSES)
        tasks = lesson_files(COURSES / "tasks")
        self.assertEqual(set(range(1, 17)), set(expected))
        self.assertEqual(set(expected), set(contracts))
        self.assertEqual(set(expected), set(handouts))
        self.assertEqual(set(expected), set(tasks))
        self.assertEqual(expected, {item.number: item.title for item in LESSONS})
        for number, title in expected.items():
            with self.subTest(lesson=number):
                self.assertEqual(title, contracts[number][0])
                self.assertEqual(f"# L{number:02d}｜{title}", handouts[number].read_text(encoding="utf-8").splitlines()[0])
                heading = tasks[number].read_text(encoding="utf-8").splitlines()[0]
                self.assertIn(heading, (f"# L{number:02d}｜{title}", f"# L{number:02d} 行动卡｜{title}"))

    def test_handout_and_task_copy_the_four_outline_contract_lines(self) -> None:
        contracts = outline_contracts()
        handouts = lesson_files(COURSES)
        tasks = lesson_files(COURSES / "tasks")
        for number, (_title, lines) in contracts.items():
            self.assertEqual(4, len(lines), f"L{number:02d} 大纲四项合同不完整")
            for path in (handouts[number], tasks[number]):
                body = path.read_text(encoding="utf-8")
                for line in lines:
                    with self.subTest(lesson=number, file=path.name, contract=line[:20]):
                        self.assertIn(line, body)

    def test_each_handout_is_a_self_contained_student_chapter(self) -> None:
        for number, path in lesson_files(COURSES).items():
            body = path.read_text(encoding="utf-8")
            with self.subTest(lesson=number):
                for marker in (
                    "FlowERP",
                    "工作台",
                    "Codex",
                    "失败",
                    "验收",
                    "迁移",
                ):
                    self.assertIn(marker, body)
                self.assertRegex(body, r"正常|成功")
                self.assertRegex(body, r"!\[[^\]]+\]\([^)]+\)")
                self.assertRegex(body, r"\]\((?:\./)?实践操作手册\.md(?:#[^)]*)?\)")
                if path.parent.name == f"L{number:02d}":
                    # The practice manual owns the actionable submission handoff.
                    manual = (path.parent / "实践操作手册.md").read_text(encoding="utf-8")
                    self.assertIn("提交", manual)
                else:
                    self.assertIn(f"./slides/L{number:02d}-", body)
                    self.assertIn(f"./tasks/L{number:02d}-", body)
                    self.assertIn(f"./labs/L{number:02d}/", body)
                self.assertRegex(body, r"课程大纲|课程合同")
                self.assertNotIn("教师备课区", body)

    def test_student_entry_owns_all_sixteen_lesson_resources_and_titles(self) -> None:
        entry = (DOCS / "README.md").read_text(encoding="utf-8")
        rows = [line for line in entry.splitlines() if re.match(r"^\|\s*L\d{2}\s*\|", line)]
        expected = schedule_titles()
        self.assertEqual(16, len(rows), "学生总入口须直接收录 16 讲，不再分散维护索引")
        self.assertEqual(
            [f"L{number:02d}" for number in range(1, 17)],
            [row.split("|")[1].strip() for row in rows],
        )
        for number, row in enumerate(rows, start=1):
            with self.subTest(lesson=number):
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                self.assertEqual(5, len(cells), "课程资源主表应保留五个明确维度")
                title_link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", cells[1])
                self.assertIsNotNone(title_link, "主题须以本讲 README 为入口")
                self.assertEqual(expected[number], title_link.group(1))
                title_target = unquote(title_link.group(2).strip().strip("<>").split("#", 1)[0])
                self.assertEqual((COURSES / f"L{number:02d}" / "README.md").resolve(),
                                 (DOCS / title_target).resolve())
                targets = {
                    (DOCS / unquote(target.strip().strip("<>").split("#", 1)[0])).resolve()
                    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", row)
                }
                for name in ("README.md", "辅导资料.md", "实践操作手册.md", "行动卡.md"):
                    resource = (COURSES / f"L{number:02d}" / name).resolve()
                    self.assertIn(resource, targets, f"主表缺少 L{number:02d}/{name}")
                    self.assertTrue(resource.is_file(), resource)

    def test_old_indexes_are_short_compatibility_links_to_the_student_entry(self) -> None:
        for name in ("讲义阅读导航.md", "行动卡索引.md", "课件获取与本地检查.md"):
            with self.subTest(index=name):
                body = (COURSES / name).read_text(encoding="utf-8")
                targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", body)
                self.assertTrue(any(target.split("#", 1)[0] == "../README.md" for target in targets))
                self.assertLessEqual(len([line for line in body.splitlines() if line.strip()]), 12,
                                     "兼容页不能继续维护第二份课程总览")
                self.assertNotRegex(body, r"(?m)^\|[^\n]*L\d{2}[^\n]*\|")
                self.assertNotRegex(body, r"(?m)^\s*(?:\d+\.|-)\s*\[L\d{2}")
                self.assertNotIn("CODEXFDE_VALIDATE_LOCAL_SLIDES", body)
                if name == "课件获取与本地检查.md":
                    self.assertTrue(any(target in ("课程蓝图.md#本地课件检查",
                                                   "./课程蓝图.md#本地课件检查") for target in targets))

    def test_student_entry_explains_first_delivery_and_slide_access(self) -> None:
        entry = (DOCS / "README.md").read_text(encoding="utf-8")
        self.assertRegex(entry, r"L04[^。\n]*首次")
        compact = re.sub(r"\s", "", entry)
        self.assertRegex(compact, r"(?:PPT|课件|\.pptx)[^。\n]{0,40}不随Git")
        self.assertIn("课程提供方", entry)
        self.assertRegex(entry, r"获取|取得|领取|索取")
        self.assertRegex(entry, r"匹配[^。\n]*版本|版本[^。\n]*匹配")
        self.assertIn("slides/", entry)
        self.assertNotIn("CODEXFDE_VALIDATE_LOCAL_SLIDES", entry)

    def test_schedule_only_lists_lesson_numbers_and_formal_titles(self) -> None:
        body = SCHEDULE.read_text(encoding="utf-8")
        headers = [line for line in body.splitlines()
                   if line.startswith("|") and "讲次" in line and "主题" in line]
        self.assertTrue(headers, "课表必须保留讲次与主题入口")
        for header in headers:
            self.assertEqual(["讲次", "主题"], [cell.strip() for cell in header.strip("|").split("|")])
        rows = re.findall(r"^\|\s*\d{2}\s*\|([^\n]+)$", body, re.MULTILINE)
        self.assertEqual(16, len(rows))
        for row in rows:
            self.assertEqual(1, row.count("|"), "核心内容与通过标准由课程大纲维护，不复制到课表")

    def test_merged_navigation_local_links_and_heading_anchors_resolve(self) -> None:
        sources = [DOCS / "README.md"] + [COURSES / name for name in (
            "讲义阅读导航.md", "行动卡索引.md", "课件获取与本地检查.md", "课程蓝图.md",
        )]
        cached_anchors: dict[Path, set[str]] = {}
        broken: list[str] = []
        for source in sources:
            body = source.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
                target = raw_target.strip().strip("<>")
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                local, _separator, fragment = target.partition("#")
                destination = (source.parent / unquote(local)).resolve() if local else source.resolve()
                if not destination.exists():
                    broken.append(f"{source.relative_to(ROOT)} -> {target} (文件不存在)")
                    continue
                if not fragment:
                    continue
                if destination.suffix != ".md":
                    broken.append(f"{source.relative_to(ROOT)} -> {target} (不是 Markdown 锚点)")
                    continue
                if destination not in cached_anchors:
                    cached_anchors[destination] = markdown_anchors(destination.read_text(encoding="utf-8"))
                if unquote(fragment) not in cached_anchors[destination]:
                    broken.append(f"{source.relative_to(ROOT)} -> {target} (章节锚点不存在)")
        self.assertFalse(broken, "\n".join(broken))

    def test_student_entry_is_in_baseline_scaffolding_and_course_assets(self) -> None:
        from eval.cases import course_assets_present
        from scripts.build_course_baselines import scaffold_paths

        self.assertIn(DOCS / "README.md", scaffold_paths())
        self.assertEqual("关键课程资产齐备", course_assets_present())

    def test_l04_bootstrap_shift_and_l16_live_delivery_are_explicit(self) -> None:
        l04 = lesson_files(COURSES)[4].read_text(encoding="utf-8")
        l16 = lesson_files(COURSES)[16].read_text(encoding="utf-8")
        self.assertIn("自举换挡", l04)
        self.assertIn("Ticket A", l04)
        self.assertIn("Ticket B", l04)
        self.assertIn("此前未实现", l16)
        self.assertIn("动态 Eval", l16)
        self.assertIn("具名人审", l16)

    def test_student_navigation_excludes_internal_governance_documents(self) -> None:
        student_nav = (DOCS / "README.md").read_text(encoding="utf-8")
        for name in ("国家级一流本科课程建设方案", "国家级一流本科课程申报级质量门"):
            self.assertNotIn(name, student_nav)
        for required in ("国家级一流本科课程建设方案.md", "国家级一流本科课程申报级质量门.md"):
            document = COURSES / required
            self.assertTrue(document.is_file())
            body = document.read_text(encoding="utf-8")
            self.assertIn("待校方确认", body)
            self.assertIn("待真实教学采集", body)
            self.assertRegex(body, r"不代表申报资格[^。\n]*课程认定")
        plan = (COURSES / "国家级一流本科课程建设方案.md").read_text(encoding="utf-8")
        for number in range(1, 7):
            self.assertIn(f"CLO-{number}", plan)
        self.assertIn("持续改进", plan)
        blueprint = (COURSES / "课程蓝图.md").read_text(encoding="utf-8")
        self.assertNotIn("当前仓库尚缺此文件", blueprint)

    def test_workspace_points_back_to_repository_root(self) -> None:
        workspace = (COURSES / "FlowERP-AI研发工作台.code-workspace").read_text(encoding="utf-8")
        self.assertIn('"path": "../.."', workspace)
        self.assertIn('"workbench.cli", "course-status"', workspace)

    def test_all_local_markdown_links_resolve(self) -> None:
        broken: list[str] = []
        for path in (p for p in published_docs() if p.suffix == '.md'):
            body = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
                target = target.strip().strip("<>")
                if not target or target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                local = unquote(target.split("#", 1)[0])
                destination = (path.parent / local).resolve()
                if not local_only(destination) and not destination.exists():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertFalse(broken, "\n".join(broken))

    def test_course_assets_are_all_referenced(self) -> None:
        published = published_docs()
        markdown = "\n".join(path.read_text(encoding="utf-8") for path in published if path.suffix == '.md')
        orphaned = [
            str(path.relative_to(ROOT))
            for path in published
            if path.is_relative_to(COURSES / "assets") and path.suffix != '.md' and path.name not in markdown
        ]
        self.assertFalse(orphaned, "\n".join(orphaned))


if __name__ == "__main__":
    unittest.main()
