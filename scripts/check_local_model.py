"""Check real Ollama ranking and drafting using fictional inputs, without database writes."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.demo import FixtureSearch
from backend.research import Ollama


async def main():
    model = Ollama()
    health = await model.health()
    if not health['available']:
        raise SystemExit(health['message'])
    sources = await FixtureSearch().search('Fictional Cedar Labs', 'Software Engineer')
    ranked = await model.rank('Fictional Cedar Labs', 'Software Engineer', sources)
    if not ranked:
        raise SystemExit('Model returned no valid candidate for the fictional test source.')
    pick, source = ranked[0]
    assert source.id == 'fictional-source'
    facts = [{'id': 'fictional-python', 'text': 'I built a fictional Python project.'}]
    draft = await model.draft(
        {'company': 'Fictional Cedar Labs', 'role': 'Software Engineer'},
        pick, facts, {'note_limit': 200, 'dm_limit': 1200},
    )
    assert len(draft['note']) <= 200 and len(draft['dm']) <= 1200
    assert set(draft['grounding']['fact_ids']) <= {'fictional-python'}
    print(f"PASS: {model.model} ranked fictional evidence and generated a validated draft.")
    print('No real contacts, approved facts, external search requests, or database writes were used.')


if __name__ == '__main__':
    asyncio.run(main())
