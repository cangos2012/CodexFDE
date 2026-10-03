"""Regression fixtures for local PPT selection and OOXML/teaching boundaries."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

from tests.course_assets import (A_NS, P_NS, R_NS, REL_NS, has_lesson_marker,
                                local_slide_decks, local_slide_review_targets,
                                normalized_slide_text, presentation_slide_texts)
from tests.test_course_ppt_endings import closing_contract_issues
from tests.test_course_ppt_endings import has_operational_claim


def package_fixture(targets, texts):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as package:
        ids = ''.join(f'<p:sldId id="{256 + i}" r:id="rId{i}"/>' for i in range(len(targets)))
        package.writestr('ppt/presentation.xml',
                         f'<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        relations = ''.join(f'<Relationship Id="rId{i}" Type="{R_NS}/slide" Target="{escape(target)}"/>'
                            for i, target in enumerate(targets))
        package.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{REL_NS}">{relations}</Relationships>')
        for name, text in texts.items():
            package.writestr(name, f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}"><a:t>{escape(text)}</a:t></p:sld>')
    buffer.seek(0)
    return buffer


class CoursePptReadingTests(unittest.TestCase):
    def test_formatted_runs_merge_but_paragraphs_and_explicit_breaks_remain_separate(self):
        fixture = package_fixture(['slides/slide1.xml'], {})
        with ZipFile(fixture, 'a') as package:
            package.writestr('ppt/slides/slide1.xml',
                f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}">'
                '<a:p><a:r><a:t>用 Spec </a:t></a:r><a:r><a:t>明确任务。</a:t></a:r></a:p>'
                '<a:p><a:r><a:t>记录</a:t></a:r><a:br/><a:r><a:t>候选</a:t></a:r></a:p>'
                '<a:p><a:r><a:t>版本</a:t></a:r></a:p></p:sld>')
        fixture.seek(0)
        with ZipFile(fixture) as package:
            text = presentation_slide_texts(package)[0]
        self.assertEqual('用 Spec 明确任务。\n记录\n候选\n版本', text)
        self.assertTrue(has_operational_claim(text.splitlines()[0]))
        self.assertFalse(has_operational_claim('\n'.join(text.splitlines()[1:])))

    def test_first_and_last_follow_presentation_order_and_resolve_absolute_targets(self):
        fixture = package_fixture(['slides/slide5.xml', '/ppt/slides/slide2.xml'],
                                  {'ppt/slides/slide5.xml': '第 08 讲：真实封面',
                                   'ppt/slides/slide2.xml': '真正末页',
                                   'ppt/slides/slide1.xml': '不在展示顺序中的旧封面'})
        with ZipFile(fixture) as package:
            self.assertEqual(['第 08 讲：真实封面', '真正末页'], presentation_slide_texts(package))

    def test_missing_and_outside_package_slide_targets_are_rejected(self):
        for target in ('slides/missing.xml', '../outside.xml'):
            with self.subTest(target=target), ZipFile(package_fixture([target], {})) as package:
                with self.assertRaisesRegex(AssertionError, '不存在或越界'):
                    presentation_slide_texts(package)

    def test_lesson_marker_accepts_chinese_cover_and_rejects_wrong_or_longer_numbers(self):
        for text in ('L08', '第08讲', '第 08 讲', '01\nL08\n把同一套 Eval 接入 CI'):
            self.assertTrue(has_lesson_marker(text, 8), text)
        for text in ('L07', '第09讲', 'L080', 'AL08', '第18讲'):
            self.assertFalse(has_lesson_marker(text, 8), text)
        self.assertEqual(normalized_slide_text('把同一套 Eval 接入 CI'),
                         normalized_slide_text('把同一套\nEval，接入\nCI'))
        self.assertNotEqual(normalized_slide_text('把同一套 Eval 接入 CI'),
                            normalized_slide_text('把另一套 Eval 接入 CI'))

    def test_office_locks_are_excluded_without_opening_or_deleting_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            courses = Path(temporary)
            directory = courses / 'L06/slides'
            directory.mkdir(parents=True)
            deck = directory / 'L06-current.PPTX'
            deck.touch()
            lock = directory / '~$L06-current.pptx'
            lock.write_bytes(b'Office owner file, not a ZIP package')
            self.assertEqual([deck], local_slide_decks(6, courses))
            self.assertTrue(lock.exists())

    def test_explicit_current_material_link_selects_version_without_filename_guessing(self):
        with tempfile.TemporaryDirectory() as temporary:
            courses = Path(temporary)
            directory = courses / 'L06/slides'
            directory.mkdir(parents=True)
            old = directory / 'L06-a-old.pptx'
            selected = directory / 'L06-z adopted.pptx'
            old.touch()
            selected.touch()
            source = directory.parent / 'README.md'
            source.write_text('[本讲配套](slides/L06-z%20adopted.pptx)', encoding='utf-8')
            self.assertEqual(([selected], source), local_slide_review_targets(6, courses))

    def test_missing_or_ambiguous_selection_reviews_all_candidates_and_reports_no_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            courses = Path(temporary)
            directory = courses / 'L06/slides'
            directory.mkdir(parents=True)
            decks = [directory / 'L06-a.pptx', directory / 'L06-b.pptx']
            for deck in decks:
                deck.touch()
            source = directory.parent / 'README.md'
            for body in ('[旧链接](L06-missing.pptx)',
                         '[甲](slides/L06-a.pptx) [乙](slides/L06-b.pptx)'):
                source.write_text(body, encoding='utf-8')
                self.assertEqual((decks, None), local_slide_review_targets(6, courses))


class CoursePptClosingTests(unittest.TestCase):
    def setUp(self):
        self.recap = ('本讲总结：用 Spec 明确任务，让工作台组织受控执行，再依据实际结果验收。'
                      '指定候选目录与允许文件，记录输出并保留失败。独立验收核对同一候选，说明接受理由。')
        self.transfer = ('迁移：换个需求，导出未完成的采购申请。重新确认状态与字段，沿用已接受的 V0，'
                         '限定具体文件并记录采用版本，请同伴独立复验，再检查文件内容和只读状态。')
        self.transition = ('下一讲 L05：程序和测试都把可用量写成在库量，测试却全绿。'
                           '怎样证明检查真的发现目标错误？L05 用重复入库反例检验检查的辨别能力。')

    def test_outcomes_transfer_and_transition_can_be_separate_closing_pages(self):
        self.assertEqual([], closing_contract_issues(4, [self.recap, self.transfer, self.transition]))

    def test_ending_cannot_pass_on_summary_and_question_markers_alone(self):
        fake = ('课程总结；本讲完成了什么；个人证据；迁移；思考；Q1；Q2；Q3；下一讲 L05。'
                '这是漂亮的排版和装饰，所有关键术语都在这里。' * 2)
        self.assertEqual(3, len(closing_contract_issues(4, [fake])))
        keywords = '本讲总结 Spec 边界 验收。个人证据 迁移 候选 原始记录。下一讲 L05 失败 错误 修复。'
        self.assertEqual(3, len(closing_contract_issues(4, [keywords])))

    def test_newline_only_keyword_page_cannot_borrow_a_predicate_from_another_heading(self):
        fake = '\n'.join(['本讲总结', '本讲完成了什么', 'Spec', '边界', '验收',
                          '个人证据', '记录', '候选', '原始', '下一讲 L05', '失败', '修复'])
        self.assertEqual(3, len(closing_contract_issues(4, [fake])))

    def test_next_lesson_needs_its_own_explanation_after_the_label(self):
        fake_transition = '请核对检查结果并保存修复记录。\n下一讲 L05\n失败\n修复'
        self.assertIn('收束页缺少正确的下一讲对象及其承接关系',
                      closing_contract_issues(4, [self.recap, self.transfer, fake_transition]))

    def test_real_table_actions_and_following_paragraphs_remain_valid(self):
        table = ('本讲总结：把一个小需求交给工作台完成\n掌握的知识\n什么时候用\n具体怎样用\n'
                 'Spec 与任务绑定\n编码前，避免做错需求\n写清目标、边界和验收；保存采用的版本。\n'
                 '受控执行\n委托 Codex 修改代码时\n指定候选目录与允许文件；记录输出，失败就停。')
        self.assertEqual([], closing_contract_issues(4, [table, self.transfer, self.transition]))

    def test_missing_learner_evidence_and_wrong_next_lesson_still_fail(self):
        self.assertIn('收束页缺少个人证据或具体迁移判断',
                      closing_contract_issues(4, ['本讲总结：Spec 定义边界，工作台组织执行。' * 4, self.transition]))
        issues = closing_contract_issues(4, [self.recap, self.transfer, self.transition.replace('L05', 'L09')])
        self.assertIn('收束页缺少正确的下一讲对象及其承接关系', issues)

    def test_early_keywords_do_not_substitute_for_a_closing_section(self):
        slides = [self.recap, self.transfer, self.transition] + ['新的正文实验，没有收束。'] * 4
        self.assertEqual(3, len(closing_contract_issues(4, slides)))


if __name__ == '__main__':
    unittest.main()
