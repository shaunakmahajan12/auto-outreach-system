"""Serper transport checks using fictional responses; no external requests."""
import asyncio
import json

import httpx
import pytest

from backend.demo import MemorySecrets
from backend.research import Serper
from backend.security import Retryable, Unavailable


def provider(monkeypatch, response):
    vault = MemorySecrets()
    vault.put('serper', 'fictional-test-key')
    original = httpx.AsyncClient

    def handle(request):
        assert str(request.url) == 'https://google.serper.dev/search'
        assert request.headers['X-API-KEY'] == 'fictional-test-key'
        payload = json.loads(request.content)
        assert set(payload) == {'q', 'num'}
        assert 'Fictional Company' in payload['q']
        return response

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handle), **kwargs))
    return Serper(vault)


def test_profiles_filtered_deduplicated_and_bounded(monkeypatch):
    search = provider(monkeypatch, httpx.Response(200, json={'organic': [
        {'link': 'https://linkedin.com/in/fictional-person/', 'title': 'Fictional Person', 'snippet': 'Evidence'},
        {'link': 'https://www.linkedin.com/in/fictional-person', 'snippet': 'Duplicate'},
        {'link': 'https://www.linkedin.com/jobs/123', 'snippet': 'Not a profile'},
        {'link': 'https://example.com/in/name', 'snippet': 'Wrong site'},
        {'link': 'https://linkedin.com/in/no-evidence', 'snippet': None},
        None,
    ]}))
    results = asyncio.run(search.search('Fictional Company', 'Engineer'))
    assert len(results) == 1
    assert results[0].url == 'https://www.linkedin.com/in/fictional-person'
    assert results[0].excerpt == 'Evidence'


@pytest.mark.parametrize('status,error', [(401, Unavailable), (402, Unavailable), (403, Unavailable), (429, Retryable), (503, Retryable)])
def test_provider_errors(monkeypatch, status, error):
    search = provider(monkeypatch, httpx.Response(status))
    with pytest.raises(error):
        asyncio.run(search.search('Fictional Company', 'Engineer'))


def test_invalid_response_is_retryable(monkeypatch):
    search = provider(monkeypatch, httpx.Response(200, json={'organic': None}))
    with pytest.raises(Retryable):
        asyncio.run(search.search('Fictional Company', 'Engineer'))


def test_missing_key_blocks_without_request():
    with pytest.raises(Unavailable, match='configure a Serper key'):
        asyncio.run(Serper(MemorySecrets()).search('Fictional Company', 'Engineer'))
