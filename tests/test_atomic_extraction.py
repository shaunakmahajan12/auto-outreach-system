import asyncio
import pytest
from backend.matching import Requirements, RequirementReferences, extract, match, source_spans
from backend.security import InvalidOutput


class CombinedModel:
    def __init__(self,text):self.text=text
    async def structured(self,*args):
        return Requirements(requirements=[{'text':self.text,'excerpt':self.text,
                                          'category':'responsibility','priority':'required'}])


def test_combined_postgres_responsibility_keeps_scope_uncertain_but_selects_explicit_skill():
    text='Design and maintain dependable customer-facing services using Postgres'
    requirements=asyncio.run(extract(CombinedModel(text),text))
    results=match(requirements.model_dump()['requirements'],[
        {'id':'fact','text':'I built a fictional PostgreSQL service.','status':'approved'}])
    assert results[0]['assessment']=='uncertain' and not results[0]['supporting_facts']
    assert results[1]['text']==results[1]['excerpt']=='Postgres'
    assert results[1]['assessment']=='supported'
    assert results[1]['supporting_facts'][0]['fact_id']=='fact'


@pytest.mark.parametrize('text',[
    'Build services without using Postgres',
    'Do not build services using Postgres',
    'Build services using Postgres or SQLite',
    'Avoid using Postgres',
    'Build services using Postgresqlish',
])
def test_ambiguous_or_negated_usage_is_not_promoted(text):
    assert len(asyncio.run(extract(CombinedModel(text),text)).requirements)==1


@pytest.mark.parametrize('technology', ['Python3','Postgres','Docker','React.js','Go','C++'])
def test_exact_usage_subrequirement_preserves_original_source(technology):
    text=f'Build dependable systems using {technology}.'
    requirements=asyncio.run(extract(CombinedModel(text),text)).requirements
    assert len(requirements)==2
    assert requirements[0].excerpt==text
    assert requirements[1].text==requirements[1].excerpt==technology


def test_indexed_extraction_uses_server_owned_exact_excerpt():
    description='Required: café systems using Postgres.\nPreferred: Docker.'
    class Indexed:
        async def structured(self,schema,instruction,data):
            assert schema is RequirementReferences
            assert data['source_spans']==['Required: café systems using Postgres.','Preferred: Docker.']
            return RequirementReferences(requirements=[{'text':'Docker','category':'skill','priority':'preferred','source_index':1}])
    result=asyncio.run(extract(Indexed(),description))
    assert result.requirements[0].excerpt=='Preferred: Docker.'


def test_invalid_source_index_is_rejected_after_bounded_retry():
    class InvalidIndex:
        calls=0
        async def structured(self,*args):
            self.calls+=1
            return RequirementReferences(requirements=[{'text':'Python','category':'skill','priority':'required','source_index':999}])
    model=InvalidIndex()
    with pytest.raises(InvalidOutput,match='source index'):asyncio.run(extract(model,'Required: Python'))
    assert model.calls==2


def test_long_source_spans_remain_exact_and_bounded():
    description='Required: '+('fictional technology '*100)+'\n'+('x'*900)
    spans=source_spans(description)
    assert all(0<len(span)<=800 and span in description for span in spans)


def test_valid_index_cannot_introduce_a_technology_absent_from_its_source():
    class InventedSkill:
        async def structured(self,*args):
            return RequirementReferences(requirements=[{'text':'Kubernetes','category':'skill','priority':'required','source_index':0}])
    with pytest.raises(InvalidOutput,match='absent'):asyncio.run(extract(InventedSkill(),'Required: Python'))
