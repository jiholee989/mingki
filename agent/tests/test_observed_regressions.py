from app.nodes.impact import make_product_impact_agent
from app.schemas import ProductAssessment, ProductRevision
from test_graph import DsrReasoner, ThreeProductTools, decision, start


def test_missing_rules_must_not_be_confirmed_as_no_change():
    class Missing(ThreeProductTools):
        def get_products(self):
            return super().get_products()[:1]
        def get_product_rules(self, **kwargs):
            return [r for r in super().get_product_rules(**kwargs) if r['productId']=='P001' and r['ruleId']!='R001']
    class Uncertain(DsrReasoner):
        def product_impacts(self, *args):
            return [ProductAssessment(requirement_id='REQ-8', product_id='P001', impact='no_change',
                    applicability='unknown', reason='DSR 규칙이 없어 판단 불가', scope='추가 확인 필요',
                    basis_refs=['reg://credit-loan-ops/v4/8'])]
    tools=Missing()
    req=DsrReasoner().requirements(tools.diff_versions('credit-loan-ops','v3','v4'))[0]
    state={'requirements':[req],'snapshot_date':'2026-11-30',
           'regulation_context':tools.get_regulation_context('credit-loan-ops','v4')['articles']}
    impact=make_product_impact_agent(tools,Uncertain())(state)['product_impacts'][0]
    assert impact.impact=='needs_review'


def test_revision_connection_error_returns_to_review():
    class Offline(DsrReasoner):
        def draft_product(self, context):
            if context.get('comment'):
                raise ConnectionError('model unavailable')
            return super().draft_product(context)
    runner,out,_,_=start(Offline())
    before=out['proposals'][0]
    out=runner.resume('T1',{'decisions':[decision(before,'request_changes',comment='고객 안내 문구 추가')]})
    assert out['__interrupt__']
    assert out['proposals'][0].recommendation==before.recommendation
    assert out['proposals'][0].verification=='failed'


def test_impossible_request_returns_original_without_retry():
    class Cannot(DsrReasoner):
        def draft_product(self, context):
            if context.get('comment'):
                self.contexts.append(context)
                old=context['previous_proposal']
                return ProductRevision(**{k:old[k] for k in ('recommendation','actions','optional_actions','precautions','changes')},
                      revision_response='필수 DSR 35%를 40%로 완화할 수 없습니다.',revision_outcome='cannot_apply')
            return super().draft_product(context)
    runner,out,reasoner,_=start(Cannot())
    before=out['proposals'][0]
    out=runner.resume('T1',{'decisions':[decision(before,'request_changes',comment='DSR 40%로 유지해줘')]})
    assert len(reasoner.contexts)==3
    assert out['proposals'][0].verification=='passed'
    assert out['proposals'][0].recommendation==before.recommendation


def test_openai_connection_error_is_returned_without_provider_payload():
    import httpx
    import pytest
    from openai import APIConnectionError
    from app.llm import LlmReasoner

    class Offline:
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, messages):
            raise APIConnectionError(message='private provider diagnostic', request=httpx.Request('POST', 'https://example.test'))

    with pytest.raises(ValueError, match='모델 요청 실패') as error:
        LlmReasoner(Offline()).draft_product({'mandatory_changes': []})
    assert 'private provider diagnostic' not in str(error.value)


def test_clarification_does_not_make_failed_original_approvable():
    from app.runner import DecisionError
    from app.schemas import ProductDraft
    import pytest

    class Clarify(DsrReasoner):
        def draft_product(self, context):
            if context.get('comment'):
                old = context['previous_proposal']
                return ProductRevision(**{k:old[k] for k in ('recommendation','actions','optional_actions','precautions','changes')},
                                       revision_outcome='needs_clarification',revision_response='원하는 문구를 구체적으로 알려주세요')
            return ProductDraft(recommendation='확인 필요',actions=[],precautions=[])

    runner,out,_,_=start(Clarify())
    assert out['proposals'][0].verification=='failed'
    out=runner.resume('T1',{'decisions':[decision(out['proposals'][0],'request_changes',comment='안내 내용 보완')]})
    assert out['__interrupt__']
    assert out['proposals'][0].verification=='failed'
    assert out['proposals'][0].revision_outcome=='needs_clarification'
    with pytest.raises(DecisionError):
        runner.resume('T1',{'decisions':[decision(out['proposals'][0])]})
