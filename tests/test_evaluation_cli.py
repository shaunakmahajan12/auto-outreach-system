import asyncio
import json
import sys

import pytest

from evaluation import run


def test_limited_benchmark_is_explicitly_partial():
    result = asyncio.run(run.benchmark(limit=1))
    assert result['case_count'] == 1 and result['corpus_count'] == 50 and result['partial_run']
    assert len(result['cases']) == 2  # Same case evaluated with both methods.
    with pytest.raises(ValueError, match='positive'):
        asyncio.run(run.benchmark(limit=0))


@pytest.mark.parametrize(
    'failure,method,warning,expected',
    [
        (None, 'embedding cosine', None, 0),
        (None, 'pgvector cosine', None, 0),
        ('Unavailable', 'embedding cosine', None, 1),
        (None, 'lexical', 'Fictional embedding provider failure', 1),
    ],
)
def test_strict_gate_writes_results_before_reporting_failure(
    tmp_path, monkeypatch, failure, method, warning, expected
):
    async def benchmark(*args):
        return {
            'cases': [
                {
                    'method': 'upgraded',
                    'failure': failure,
                    'retrieval_method': method,
                    'retrieval_warning': warning,
                }
            ]
        }

    monkeypatch.setattr(run, 'benchmark', benchmark)
    output = tmp_path / 'results.json'
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'evaluation',
            '--real-model',
            '--embeddings',
            '--require-success',
            '--output',
            str(output),
        ],
    )
    if expected:
        with pytest.raises(SystemExit) as error:
            run.main()
        assert error.value.code == expected
    else:
        run.main()
    assert json.loads(output.read_text())['cases'][0]['failure'] == failure
