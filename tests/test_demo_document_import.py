from pathlib import Path
import pytest

FILES = sorted((Path(__file__).resolve().parents[1] / 'data' / 'recording').glob('*.docx'))

@pytest.mark.parametrize('index,scenario', [(0,'linkage'),(1,'human_veto'),(2,'success')])
def test_import_registers_facts_without_deciding_outcome(demo_env,index,scenario):
    client=demo_env['client']
    response=client.post('/api/v1/demos/import',files={'file':('renamed.docx',FILES[index].read_bytes())})
    assert response.status_code==200,response.text
    case=response.json()
    assert case['scenario']==scenario
    detail=client.get('/api/v1/cases/'+case['id']).json()
    assert detail['facts']
    assert detail['tasks']==[]
    assert detail['ledger']==[]


def test_recording_documents_create_three_distinct_cases(demo_env):
    client = demo_env['client']
    expected = [
        ('顾舟', '晨岛示例研究所'),
        ('林澄', '星桥示例科技有限公司'),
        ('乔安', '云岑示例商贸有限公司'),
    ]
    observed = []
    for path in FILES:
        response = client.post(
            '/api/v1/demos/import',
            files={'file': (path.name, path.read_bytes())},
        )
        assert response.status_code == 200, response.text
        detail = client.get('/api/v1/cases/' + response.json()['id']).json()
        entities = [item['value'] for item in detail['facts'] if item['field'] == 'entity']
        observed.append(tuple(entities))
    assert observed == expected
    assert len({name for pair in observed for name in pair}) == 6


def test_changed_document_is_not_accepted(demo_env):
    response=demo_env['client'].post('/api/v1/demos/import',files={'file':(FILES[0].name,FILES[0].read_bytes()+b'changed')})
    assert response.status_code==400


def test_production_cannot_import_recording(env):
    response=env['client'].post('/api/v1/demos/import',files={'file':(FILES[0].name,FILES[0].read_bytes())})
    assert response.status_code==409
