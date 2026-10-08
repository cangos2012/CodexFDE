from pathlib import Path
import re
import os
import unittest
from zipfile import ZipFile

from tests.course_assets import (has_lesson_marker, local_slide_review_targets,
                                presentation_slide_texts)


ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / "docs" / "courses"
def last_slide_text(path: Path) -> str:
    with ZipFile(path) as package:
        return presentation_slide_texts(package)[-1]


# The outline/blueprint require an explained learning outcome, learner evidence
# or transfer, and a reason for the next step. Q1/Q2/Q3 and one fixed end-page
# heading were an old layout convention, not the current teaching contract.
RECAP_MECHANISMS = {
    3: r'Spec.{0,100}(?:来源|边界|验收|解析|交接)|(?:来源|边界|验收|解析|交接).{0,100}Spec',
    4: r'Spec.{0,100}(?:边界|执行|验收)|(?:受控|工作台).{0,100}执行|独立.{0,100}(?:验收|接受)',
    5: r'Eval.{0,100}(?:业务|工程|结果|约束)|(?:业务|工程|检查).{0,100}Eval|检查.{0,100}(?:识别|发现|反例|有效)',
    6: r'Harness.{0,100}(?:组织|执行|统一)|(?:统一|组织|等级|报告).{0,100}Harness|统一执行|分项.{0,100}报告|按等级.{0,100}出口',
    7: r'Hook.{0,100}Harness|(?:Harness|漏检|检查).{0,100}(?:触发|阻断|反馈|复验)|(?:关键|修改).{0,100}(?:检查|Hook)',
    8: r'CI.{0,100}(?:同一|独立|报告)|(?:同一|独立|候选).{0,100}(?:CI|检查|复验|报告)|产品正确.{0,100}流程可信',
    9: r'分诊.{0,100}(?:任务|修复)|修复任务.{0,100}(?:范围|执行|目标)|任务组织.{0,100}(?:执行|范围)|受控任务.{0,100}修复|Codex.{0,100}Harness',
    10: r'(?:Loop|循环).{0,100}(?:轮|预算|停止|重复|检查)|(?:停止|预算|复验).{0,100}Loop',
    11: r'(?:独立|依赖|分工|协作|并行).{0,100}(?:输入|候选|复验|交付|申请)|(?:主Agent|申请).{0,100}(?:复验|分工|协作)',
    12: r'Graph.{0,100}(?:节点|状态|条件|交付)|(?:节点|状态|条件).{0,100}(?:动作|轨迹|路径|审核)',
    13: r'(?:任务|Task|API|接口).{0,100}(?:状态|编号|查询|持久|重启|原ID)|(?:状态|重启).{0,100}(?:任务|API|接口|读取|查询)',
    14: r'(?:状态|页面).{0,100}(?:后端|来源|记录|接口)|(?:报告|结果).{0,100}(?:本轮|任务|版本|追踪)',
    15: r'(?:摘要|反馈|经验|记忆|Memory).{0,100}(?:来源|记录|审核|分诊|新任务|采用|复验|查询|检索)|(?:采用|来源|新任务|检索).{0,100}(?:摘要|反馈|经验|记忆)',
    16: r'(?:工作台|新需求|干净环境|接手).{0,100}(?:启动|运行|交付|协作|开发|可用|验证)',
}
NEXT_MECHANISMS = {
    3: r'执行|委托|最小变更|工作台V0',
    4: r'失败|辨别|裁判|检查.{0,100}错误',
    5: r'Harness|统一.{0,100}(?:执行|报告|检查)',
    6: r'Hook|工作节点|本地护栏|关键.{0,100}(?:检查|调用)|生命周期',
    7: r'CI|独立环境|独立.{0,100}复验',
    8: r'修复任务|限定.{0,100}修复|失败.{0,100}(?:任务|修复|范围)|按证据.{0,100}范围',
    9: r'Loop|有界|停止|多轮|循环',
    10: r'Subagents|并行|独立任务',
    11: r'Graph|状态|审核|回退',
    12: r'API|接口|任务ID',
    13: r'Web|页面|面板',
    14: r'摘要|反馈',
    15: r'新环境|干净环境|冷启动|现场|新需求',
}


def has_operational_claim(text: str) -> bool:
    # An action must relate to a concrete object; a heading/keyword list alone
    # cannot satisfy a learning outcome, evidence request or causal transition.
    action = r'明确|组织|实现|核对|规定|确定|解析|完成|建设|建立|判断|采用|复验|检查|发现|证明|拒绝|形成|解释|定义|保存|保留|记录|恢复|选择|支持|绑定|接入|验证|限定|沿用|说明|写清|写成|转成|生成|纳入|交出|表达|提供|调用|执行'
    object_ = r'任务|需求|范围|候选|执行|状态|版本|报告|检查|经验|来源|规则|条件|反馈|结果|节点|可用量|文件|方法|交付|流程|风险|业务|原因|身份|依据|Spec|Harness|Eval|Loop|Graph|API|请求|知识|证据|字段|变更|返工|错误|修复|差异|能力|目标|移交|决定|事实|入口'
    return any(re.search(rf'(?:{action})[^。；：,:;！？!?]{{0,60}}(?:{object_})', paragraph)
               for paragraph in text.splitlines())


def closing_contract_issues(number: int, slides: list[str]) -> list[str]:
    """Check the last four teaching pages together, without a marker-only pass.

    These text checks reject missing content and stale transitions. They do not
    establish visual quality, instructional effectiveness or named acceptance.
    """
    # Keep actual paragraphs/explicit line breaks. Only layout whitespace
    # inside a statement is removed; isolated headings cannot form a claim.
    closing = ['\n'.join(re.sub(r'\s', '', paragraph) for paragraph in text.splitlines())
               for text in slides[-4:]]
    issues = []
    recap_label = rf'本讲|本课程|课程总结|总结|交付边界|课程结束|L{number - 1:02d}(?!\d)'
    if not any(re.search(recap_label, text) and has_operational_claim(text)
               and re.search(RECAP_MECHANISMS[number], text.replace('\n', '')) for text in closing):
        issues.append('收束页缺少具体的本讲收获与方法回收')
    learner = r'首次判断|个人(?:证据|交付|练习|候选|记录)|本人|同伴|迁移|换(?:个|一个|成).{0,30}(?:需求|场景|业务)|复用|新任务|采用.{0,30}版本'
    action = r'保留|记录|核对|确认|设计|重写|判断|检查|采用|复验|验证|解释|证明|留下|交付|交出|实现|回答|修订|复用'
    evidence = r'版本|源码|报告|检查|规则|证据|场景|字段|任务|范围|候选|原始|条件|原因|反馈|状态|命令|输入'
    if not any(re.search(learner, text) and has_operational_claim(text)
               and re.search(action, text) and re.search(evidence, text) for text in closing):
        issues.append('收束页缺少个人证据或具体迁移判断')
    if number == 16:
        transition = any(re.search(r'课程之后|接下来|课程结束|下一项.{0,20}需求', text)
                         and has_operational_claim(text)
                         and re.search(r'工作台.{0,100}(?:新需求|真实需求|协作|开发)', text) for text in closing)
    else:
        transition = False
        for text in closing:
            paragraphs = text.splitlines()
            for index, paragraph in enumerate(paragraphs):
                if not has_lesson_marker(paragraph, number + 1):
                    continue
                # The next lesson's explanation must follow its label. A
                # current-lesson action elsewhere on the page cannot lend it
                # a predicate. A separate heading on this page may name the
                # bridge, while the action remains after the correct label.
                context = paragraphs[index:]
                bridge = text
                if (re.search(r'下一讲|进入|衔接|成为|继续|将|接下来|起点|承接|同一个|同一套|按证据', bridge)
                        and any(has_operational_claim(explanation)
                                and re.search(NEXT_MECHANISMS[number], explanation)
                                for explanation in context)):
                    transition = True
    if not transition:
        issues.append('收束页缺少正确的下一讲对象及其承接关系' if number < 16 else '收束页缺少课程之后的真实交付引导')
    return issues


@unittest.skipUnless(os.environ.get('CODEXFDE_VALIDATE_LOCAL_SLIDES') == '1',
                     'PPT 不随 Git 发布；显式启用本地课件检查')
class CoursePptEndingTests(unittest.TestCase):
    def test_l03_to_l16_close_with_outcomes_learner_evidence_and_transition(self):
        for number in range(3, 17):
            lesson = f"L{number:02d}"
            decks, source = local_slide_review_targets(number)
            self.assertTrue(decks, f'{lesson} 缺少本地课件')
            selection = f'材料链接：{source.relative_to(ROOT)}' if source else '未指定授课版，核对全部实际候选'
            print(f'{lesson} {selection}：' + '；'.join(deck.name for deck in decks))
            for deck in decks:
                with self.subTest(lesson=lesson, deck=deck.name), ZipFile(deck) as package:
                    issues = closing_contract_issues(number, presentation_slide_texts(package))
                    self.assertFalse(issues, f'{deck.name}：' + '；'.join(issues))


if __name__ == "__main__":
    unittest.main()
