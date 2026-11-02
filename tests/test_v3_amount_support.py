"""All monetary statements and source facts below are synthetic."""
import httpx

import pytest

from lexaegis import amount_support, output_checks, return_pipeline
from tests.test_output_checks import _claim, _decisions, _facts
from tests.conftest import approve, demo_task


def checked(claim, disclosed, pack=None):
    row=_claim(claim)
    counts=output_checks.apply_return_checks([row],_decisions(disclosed),_facts(),pack or {})
    return row,counts


@pytest.mark.parametrize('source,claim',[
    ('工资15000元。','工资5000元。'),  # Old substring-number check can miss this.
    ('工资5000元。','工资6000元。'),
    ('工资5000元。','工资5万元。'),
    ('工资-5000元。','工资5000元。'),
    ('工资5000美元。','工资5000元。'),
    ('工资5000元。','工资人民币5000元。'),  # Do not infer currency from bare 元.
    ('本月工资已经支付。','工资5000元。'),
    ('工资5000元。','工资5000元，奖金2000元。'),
])
def test_value_sign_scale_and_currency_invention_blocked(source,claim):
    row,counts=checked(claim,source)
    assert row['status']=='blocked' and row['blocked']
    assert counts['block']>=1
    assert row['amount_support']['status']=='unsupported_amount'
    assert row['amount_support']['unsupported_amounts']
    assert row['amount_support']['semantic_entailment_verified'] is False


@pytest.mark.parametrize('source,claim',[
    ('工资4500元。','工资4,500.00元。'),
    ('工资4500元。','工资0.45万元。'),
    ('工资4500元。','工资４，５００元。'),
    ('工资人民币4500元。','工资CNY 4,500。'),
    ('工资USD 4500。','工资4500美元。'),
    ('工资-4500元。','工资-0.45万元。'),
    ('工资￥4500。','工资¥4500。'),
    ('工资0.10元。','工资0.1元。'),
])
def test_exact_decimal_and_explicit_unit_equivalence(source,claim):
    row,counts=checked(claim,source)
    assert counts['block']==0
    assert row['amount_support']['status']=='numeric_consistency_only'
    assert row['amount_support']['semantic_entailment_verified'] is False
    assert row['amount_support']['amounts'][0]['matched_source_ids']==['f1']


def test_other_facts_cannot_launder_a_valid_source_id():
    claims=[_claim('工资6000元。',('f1',))]
    decisions=_decisions('工资5000元。')+_decisions('奖金6000元。','f2')
    facts=_facts()+[{'id':'f2','field':'amount','value':'奖金6000元'}]
    output_checks.apply_return_checks(claims,decisions,facts,{})
    assert claims[0]['status']=='blocked'
    assert claims[0]['amount_support']['unsupported_amounts'][0]['matched_source_ids']==[]


def test_deleted_fact_and_local_original_cannot_support_returned_amount():
    claims=[_claim('工资5000元。')]
    output_checks.apply_return_checks(claims,_decisions(''),_facts(value='工资5000元'),{})
    assert claims[0]['status']=='blocked'
    assert claims[0]['amount_support']['unsupported_amounts']


def test_support_hash_changes_and_matching_never_verifies_semantics():
    source=[('f1','工资5000元。')]
    a=amount_support.assess('奖金5000元。',source)
    b=amount_support.assess('奖金5000元。',[('f1','工资6000元。')])
    assert a['status']=='numeric_consistency_only'
    assert a['semantic_entailment_verified'] is False
    assert a['disclosed_support_hash']!=b['disclosed_support_hash']
    assert b['status']=='unsupported_amount'


def test_scope_limit_not_mislabeled_as_verified():
    result=amount_support.assess('工资伍仟元。',[('f1','工资伍仟元。')])
    assert result['status']=='no_amount_tokens_checked'
    assert result['semantic_entailment_verified'] is False
    assert amount_support.amounts('序号1e3元')==[]


def test_nfkc_spans_refer_to_original_text():
    text='ﬁ工资４，５００元。'
    row=amount_support.amounts(text)[0].public()
    assert text[row['start']:row['end']]=='４，５００元'
    assert row['value']=='4500' and row['unit']=='元'


def test_explicit_pack_severity_is_preserved_and_report_still_visible():
    row,counts=checked('工资6000元。','工资5000元。',{'return_check_severity':{'unsupported_amount':'review'}})
    assert row['status']=='needs_review' and not row.get('blocked')
    assert counts['review']>=1 and row['amount_support']['status']=='unsupported_amount'


def test_fact_and_disclosed_output_are_paired_by_id_not_zip_position():
    facts=[{'id':'f1','field':'event','claim_stance':'deny'}, {'id':'f2','field':'event','claim_stance':'claim'}]
    claims=[_claim('法院认定已付工资。',('f1','f2'))]
    decisions=[{'fact_id':'f1','output':''}, {'fact_id':'f2','output':'劳动者主张已经支付工资。'}]
    output_checks.apply_return_checks(claims,decisions,facts,{})
    assert any('法院认定' in issue for issue in claims[0]['issues'])
    assert claims[0]['status']=='blocked'


@pytest.mark.parametrize('returned',['劳动者主张未支付工资800元。','劳动者主张未支付工资9800美元。'])
def test_return_pipeline_blocks_valid_id_wrong_amount_and_api_adoption(demo_env,returned):
    from lexaegis.worker import process_one
    env=demo_env;case,task=demo_task(env)
    task=approve(env,task)
    with env['app'].state.store.read() as repo:
        current=repo.get(task['id'],'task')
        decision=next(item for item in current['decisions'] if '9800元' in (item.get('output') or ''))
    env['client'].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    class AlteredSyntheticResult:
        def post(self,*args,**kwargs):
            return httpx.Response(200,json={'status':'complete','result':{'claims':[{'text':returned,'source_ids':[decision['fact_id']]}]}},
                                  request=httpx.Request('POST','http://synthetic.invalid/dispatch'))
    assert process_one(env['app'].state.store,env['root'],AlteredSyntheticResult())
    with env['app'].state.store.read() as repo:
        current=repo.get(task['id'],'task')
        claim=current['artifact']['claims'][0]
        assert claim['anchors'] and claim['status']=='blocked'
        assert current['artifact']['provenance']=='simulation'
        assert claim['amount_support']['status']=='unsupported_amount'
        assert '日期或金额存在未在引用事实中出现的数字' not in claim['issues']
        claim_id=claim['id']
    response=env['client'].post(f"/api/v1/tasks/{task['id']}/claims/{claim_id}/review")
    assert response.status_code in (400,409),response.text
    assert env['client'].post(f"/api/v1/tasks/{task['id']}/confirm").status_code==409
    with env['app'].state.store.read() as repo:
        current=repo.get(task['id'],'task')
        assert not current['artifact']['confirmed']
        assert repo.list('human_decision',case['id'])==[]


@pytest.mark.parametrize('source,claim',[
    ('工资USD1e3。','工资USD1。'),
    ('工资$4 500。','工资$4。'),
    ('工资人民币1,00元。','工资人民币1元。'),
    ('工资4 500元。','工资500元。'),
])
def test_unhandled_numeric_formats_never_support_a_partial_value(source,claim):
    row,counts=checked(claim,source)
    assert row['status']=='blocked'
    assert row['amount_support']['unsupported_amounts']


def test_old_reviewed_candidate_rechecked_before_final_human_decision(demo_env):
    env=demo_env;case,task=demo_task(env)
    task=approve(env,task)
    with env['app'].state.store.transaction() as repo:
        current=repo.get(task['id'],'task')
        decision=next(item for item in current['decisions'] if '9800元' in (item.get('output') or ''))
        return_pipeline.execute(repo,current,{'status':'complete','result':{'claims':[{'text':'劳动者主张未支付工资800元。','source_ids':[decision['fact_id']]}]}})
        claim=current['artifact']['claims'][0]
        # Simulate a pre-upgrade persisted result, individually reviewed but not adopted.
        claim.pop('amount_support'); claim.pop('blocked')
        claim['issues']=[item for item in claim['issues'] if '金额或币种' not in item]
        claim.update(status='confirmed',reviewed=True)
        current['artifact']['confirmed']=False
        repo.put('task',current,case['id'])
    response=env['client'].post(f"/api/v1/tasks/{task['id']}/confirm")
    assert response.status_code==409,response.text
    assert '证据校核' in response.text
    with env['app'].state.store.read() as repo:
        assert repo.list('human_decision',case['id'])==[]
        assert not repo.get(task['id'],'task')['artifact']['confirmed']
